#!/usr/bin/env python3
"""
Автономный брутфорс-поиск НЕсжатых глифов/иконок/картинок в дампах приборки Geely Coolray.

ЗАЧЕМ. RLAD-сжатые зоны вслепую не разбираются (бит-чувствительны, нет скоринга — проверено).
НО несжатые зоны (raw A1/A2/A4/A8) читаются напрямую: байт=пиксель, старты на 16-байт границах.
Так уже нашлись иконки. Этот скрипт систематически перебирает ВСЕ несжатые зоны × форматы ×
ширины × бит-порядки, скорит по «глифо-подобности» и сохраняет РАНЖИРОВАННУЮ галерею PNG +
CSV-каталог с адресами. Рассчитан на автономный прогон в несколько часов без надзора.

ЧЕГО НЕ ДЕЛАЕТ. Не трогает RLAD-сжатые зоны (distinct≈256) — там брутфорс бесполезен by design.

ЗАПУСК (одна команда, оба дампа, автономно):
    python tools/brute_raw_glyphs.py

    # или указать дампы/каталог явно:
    python tools/brute_raw_glyphs.py --dumps Coolray_25_Dash_U17.bin Coolray_25_Dash_U18.bin --out review/brute

ВЫХОД:
    review/brute/<dump>/gallery/<rank>_s<score>_<off>_<fmt>_w<width>_<order>.png   — картинки, лучшие первыми
    review/brute/<dump>/catalog.csv   — все находки: score, offset, format, width, bitorder, размеры
    review/brute/progress_<dump>.txt  — лог прогресса (для наблюдения/резюма)

Прерывание Ctrl+C безопасно: уже сохранённое остаётся, при повторном запуске зоны с готовым
catalog.csv пропускаются (resume).
"""
import argparse
import collections
import csv
import math
import os
import sys
import time

try:
    from PIL import Image
except ImportError:
    sys.exit("Требуется Pillow: pip install pillow")

# ---------------------------------------------------------------------------
# Параметры (все настраиваемы через CLI)
# ---------------------------------------------------------------------------
DATA_START = 0x180000          # начало активной зоны данных
DATA_END = 0x3460000           # конец
ZONE_STEP = 0x1000             # шаг сканирования зон (4 КБ = сектор)
ZONE_WINDOW = 0x4000           # окно оценки «несжатости» (16 КБ)
MAX_DISTINCT = 64              # distinct bytes < этого = несжато (RLAD ~256). Строго = меньше зон.
FORMATS = ("A8", "A4", "A2", "A1")   # bits per pixel: 8/4/2/1
# Ширины: приоритет типичным размерам глифов/иконок + плотная сетка вокруг них.
# (перебирать все 8..130 избыточно и медленно; реальные ассеты кратны 4/8)
WIDTHS = sorted(set(list(range(12, 66, 2)) + [72, 80, 88, 96, 104, 112, 120, 128]))
MIN_SCORE = 0.55               # порог сохранения (ниже = мусор, не пишем)
HARD_CAP = 400000              # предел кандидатов в памяти (backstop против взрыва на заливках)
MIN_GLYPH_ROWS = 8             # минимум непустых строк, чтобы вообще считать
RENDER_SCALE = 4               # увеличение PNG для просмотра


# ---------------------------------------------------------------------------
# Утилиты чтения пикселей из разных A-форматов
# ---------------------------------------------------------------------------
def unpack_pixels(buffer, bits_per_pixel, msb_first):
    """Разворачивает байты в список альфа-значений 0..255 для формата A1/A2/A4/A8."""
    if bits_per_pixel == 8:
        return list(buffer)
    pixels = []
    if bits_per_pixel == 4:
        for byte in buffer:
            hi, lo = byte >> 4, byte & 0x0F
            first, second = (hi, lo) if msb_first else (lo, hi)
            pixels.append(first * 17)   # 0..15 -> 0..255
            pixels.append(second * 17)
    elif bits_per_pixel == 2:
        for byte in buffer:
            vals = [(byte >> 6) & 3, (byte >> 4) & 3, (byte >> 2) & 3, byte & 3]
            if not msb_first:
                vals = [byte & 3, (byte >> 2) & 3, (byte >> 4) & 3, (byte >> 6) & 3]
            pixels.extend(v * 85 for v in vals)      # 0..3 -> 0..255
    elif bits_per_pixel == 1:
        for byte in buffer:
            rng = range(7, -1, -1) if msb_first else range(8)
            for k in rng:
                pixels.append(255 if (byte >> k) & 1 else 0)
    return pixels


def bytes_per_row(width_px, bits_per_pixel):
    return (width_px * bits_per_pixel + 7) // 8


# ---------------------------------------------------------------------------
# Скоринг «глифо-подобности» — НЕ по одной плотности (она обманывает на RLAD),
# а по совокупности признаков реальной растровой графики.
# ---------------------------------------------------------------------------
def score_from_inkmap(ink, width, height):
    """Быстрый скоринг по ГОТОВОЙ ink-карте (список 0/1 длиной >= width*height).
    ink[i] = 1 если пиксель «чернильный». Все дорогие пороги вынесены в предвычисление.
    Возвращает (score 0..1, ink_fraction)."""
    total = width * height
    ink_total = 0
    row_density = [0.0] * height
    for y in range(height):
        base = y * width
        # sum среза быстрее ручного цикла в CPython
        row_ink = 0
        for x in range(base, base + width):
            row_ink += ink[x]
        row_density[y] = row_ink / width
        ink_total += row_ink
    ink_fraction = ink_total / total
    if not (0.05 < ink_fraction < 0.75):
        return 0.0, ink_fraction

    inked_rows = 0
    empty_rows = 0
    for d in row_density:
        if d > 0.03:
            inked_rows += 1
        if d < 0.02:
            empty_rows += 1
    if inked_rows < MIN_GLYPH_ROWS:
        return 0.0, ink_fraction
    empty_bonus = min(empty_rows / height / 0.15, 1.0)

    # Вертикальная непрерывность ЧЕРНИЛ (не фона!). Считаем только пиксели, где ink=1,
    # и смотрим, продолжается ли штрих на соседней строке. Иначе пустые зоны давали бы
    # ложный vcoh≈1.0 (0==0), задирая score разреженного шума — критичный баг.
    vmatch = 0
    vtotal = 0
    for y in range(height - 1):
        b0 = y * width
        b1 = b0 + width
        for x in range(width):
            if ink[b0 + x]:            # только по чернильным пикселям
                vtotal += 1
                if ink[b1 + x]:        # штрих продолжается вниз
                    vmatch += 1
    vcoh = vmatch / vtotal if vtotal else 0

    # горизонтальные раны
    run_ok = 0
    run_cnt = 0
    max_run = max(3, width * 0.6)
    for y in range(height):
        base = y * width
        runs_sum = 0
        runs_n = 0
        cur = 0
        for x in range(base, base + width):
            if ink[x]:
                cur += 1
            elif cur:
                runs_sum += cur
                runs_n += 1
                cur = 0
        if cur:
            runs_sum += cur
            runs_n += 1
        if runs_n:
            avg_run = runs_sum / runs_n
            run_cnt += 1
            if 2 <= avg_run <= max_run:
                run_ok += 1
    stroke = (run_ok / run_cnt) if run_cnt else 0

    mean_d = sum(row_density) / height
    var = sum((d - mean_d) ** 2 for d in row_density) / height

    # --- АНТИ-ЗАЛИВКА гейт №1: строки-близнецы ---
    # Ровная заливка/градиент/вертикальные полосы = все строки почти ОДИНАКОВЫ (плотность
    # не меняется). Настоящий глиф = строки РАЗНЫЕ (верх/середина/низ буквы отличаются).
    # Считаем долю пар соседних строк, которые почти идентичны по чернилам.
    twin_rows = 0
    for y in range(height - 1):
        b0 = y * width
        b1 = b0 + width
        diff = 0
        for x in range(width):
            if ink[b0 + x] != ink[b1 + x]:
                diff += 1
        if diff <= max(1, width // 16):   # <6% пикселей отличается = строки-близнецы
            twin_rows += 1
    twin_frac = twin_rows / (height - 1) if height > 1 else 1.0
    if twin_frac > 0.55:   # больше половины строк — близнецы => заливка/полосы, НЕ глиф
        return 0.0, ink_fraction

    # --- АНТИ-ЗАЛИВКА гейт №2: вариативность плотности строк должна быть заметной ---
    if var < 0.004:        # почти постоянная плотность = заливка
        return 0.0, ink_fraction

    var_bonus = min(var / 0.02, 1.0)
    # непохожесть строк как позитивный сигнал (глиф структурен по вертикали)
    row_variety = 1.0 - twin_frac

    score = 0.30 * vcoh + 0.24 * stroke + 0.16 * var_bonus + 0.14 * empty_bonus + 0.16 * row_variety
    return score, ink_fraction


def stability_penalty(data, offset, width, bits_per_pixel, msb_first, height):
    """Тест стабильности: настоящий несжатый глиф при сдвиге старта на 1 ПИКСЕЛЬ смещается
    предсказуемо (строки сдвигаются), а RLAD-артефакт — рассыпается. Возвращает 0..1, где
    1 = стабильно (хорошо). Дешёвая версия: сравнить со сдвигом на 1 строку — должно совпасть."""
    stride = bytes_per_row(width, bits_per_pixel)
    n = stride * height
    base_buf = data[offset:offset + n]
    shift_buf = data[offset + stride:offset + stride + n]   # сдвиг ровно на строку
    if len(base_buf) < n or len(shift_buf) < n:
        return 0.5
    # строка y базового должна совпасть со строкой y-1 сдвинутого (это тот же контент)
    match = sum(1 for i in range(stride, n) if base_buf[i] == shift_buf[i - stride])
    return match / max(1, n - stride)


# ---------------------------------------------------------------------------
# Поиск несжатых зон
# ---------------------------------------------------------------------------
def find_uncompressed_zones(data):
    """Возвращает список (start, end) зон, где данные НЕ сжаты (distinct bytes < MAX_DISTINCT)."""
    hits = []
    for base in range(DATA_START, min(DATA_END, len(data)), ZONE_STEP):
        block = data[base:base + ZONE_WINDOW]
        if not block:
            continue
        zeros = block.count(0)
        if zeros > 0.97 * len(block):        # пустая зона
            continue
        if block.count(0xFF) > 0.6 * len(block):
            continue
        if len(collections.Counter(block)) >= MAX_DISTINCT:   # сжато
            continue
        hits.append(base)
    # склеить соседние в непрерывные зоны
    zones = []
    for base in hits:
        if zones and base - zones[-1][1] <= ZONE_STEP * 2:
            zones[-1][1] = base + ZONE_WINDOW
        else:
            zones.append([base, base + ZONE_WINDOW])
    return [(a, min(b, len(data))) for a, b in zones]


# ---------------------------------------------------------------------------
# Обработка одного дампа
# ---------------------------------------------------------------------------
def process_dump(dump_path, out_root, render_height, max_saved, log):
    data = open(dump_path, "rb").read()
    tag = os.path.splitext(os.path.basename(dump_path))[0]
    out_dir = os.path.join(out_root, tag)
    gallery_dir = os.path.join(out_dir, "gallery")
    os.makedirs(gallery_dir, exist_ok=True)
    catalog_path = os.path.join(out_dir, "catalog.csv")

    if os.path.exists(catalog_path):
        log("[%s] catalog.csv уже есть — пропускаю (resume). Удали его для пересчёта." % tag)
        return

    zones = find_uncompressed_zones(data)
    total_kb = sum(b - a for a, b in zones) // 1024
    log("[%s] несжатых зон: %d, суммарно %d КБ" % (tag, len(zones), total_kb))

    findings = []
    t0 = time.time()
    zone_i = 0
    fmt_bpp = {"A8": 8, "A4": 4, "A2": 2, "A1": 1}
    max_width = max(WIDTHS)
    for (zone_start, zone_end) in zones:
        zone_i += 1
        # старты только на 16-байтных границах (доказанное правило раскладки)
        for offset in range(zone_start, zone_end, 16):
            for fmt in FORMATS:
                bpp = fmt_bpp[fmt]
                orders = (True,) if bpp == 8 else (True, False)  # для A8 бит-порядок неважен
                for msb in orders:
                    # Развернуть ЛИНЕЙНЫЙ поток пикселей ОДИН раз (максимум нужного), затем для
                    # каждой ширины резать поток на строки по W (unpack не зависит от ширины —
                    # ширина лишь задаёт, где переносить строку). Это убирает повторный unpack.
                    need_px = max_width * render_height
                    need_bytes = (need_px * bpp + 7) // 8
                    if offset + need_bytes > len(data):
                        continue
                    pixels = unpack_pixels(data[offset:offset + need_bytes], bpp, msb)
                    if len(pixels) < need_px:
                        continue
                    ink_stream = [1 if v > 0x40 else 0 for v in pixels[:need_px]]

                    # Дешёвый gate: общая доля чернил в окне. Пусто/залито — пропускаем весь offset+fmt.
                    frac = sum(ink_stream) / need_px
                    if not (0.04 < frac < 0.8):
                        continue

                    for width in WIDTHS:
                        # линейный поток режем на строки шириной width (берём первые width*height пикселей)
                        ink = ink_stream[:width * render_height]
                        score, ink_frac = score_from_inkmap(ink, width, render_height)
                        if score < MIN_SCORE:
                            continue
                        # stability считаем ПОЗЖE (только для прошедших первичный скоринг),
                        # чтобы не тратить лишний проход в горячем цикле
                        findings.append((score, offset, fmt, width, msb, ink_frac, render_height))
        # backstop против взрыва памяти (напр. на регулярной заливке, проскочившей гейты):
        # держим не более HARD_CAP лучших по первичному score.
        if len(findings) > HARD_CAP:
            findings.sort(reverse=True, key=lambda t: t[0])
            del findings[HARD_CAP:]
            log("[%s] ⚠ достигнут HARD_CAP, обрезано до %d лучших" % (tag, HARD_CAP))

        elapsed = time.time() - t0
        log("[%s] зона %d/%d (0x%08X) | найдено пока: %d | %.0f сек"
            % (tag, zone_i, len(zones), zone_start, len(findings), elapsed))

    # Применить тест стабильности к прошедшим первичный скоринг (нестабильные = RLAD-артефакт → штраф).
    # Делаем это ПОСЛЕ горячего цикла, чтобы не платить за него на каждой ширине.
    log("[%s] первичных кандидатов: %d, применяю тест стабильности..." % (tag, len(findings)))
    fmt_bpp2 = {"A8": 8, "A4": 4, "A2": 2, "A1": 1}
    rescored = []
    for (score, offset, fmt, width, msb, ink_frac, height) in findings:
        stab = stability_penalty(data, offset, width, fmt_bpp2[fmt], msb, height)
        final = score * (0.5 + 0.5 * stab)
        if final >= MIN_SCORE:
            rescored.append((final, offset, fmt, width, msb, ink_frac, height))
    findings = rescored

    # ранжировать по убыванию score, дедуп близких (тот же offset±, похожая ширина)
    findings.sort(reverse=True, key=lambda t: t[0])
    findings = dedupe(findings)
    if len(findings) > max_saved:
        log("[%s] найдено %d, сохраняю топ %d (лимит --max-saved)" % (tag, len(findings), max_saved))
        findings = findings[:max_saved]

    # записать каталог + галерею
    with open(catalog_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["rank", "score", "offset_hex", "format", "width_px", "bitorder", "ink_frac", "height_px", "png"])
        for rank, (score, offset, fmt, width, msb, ink, height) in enumerate(findings, 1):
            order = "msb" if msb else "lsb"
            name = "%04d_s%.3f_%08X_%s_w%d_%s.png" % (rank, score, offset, fmt, width, order)
            _render(data, offset, fmt, width, msb, height, os.path.join(gallery_dir, name))
            writer.writerow([rank, "%.3f" % score, "0x%08X" % offset, fmt, width, order, "%.3f" % ink, height, name])
    log("[%s] ГОТОВО: %d картинок в %s, каталог %s" % (tag, len(findings), gallery_dir, catalog_path))


def dedupe(findings, cluster_bytes=1024):
    """Схлопывает кластеры почти-дубликатов. Соседние 16-байтные старты внутри ОДНОГО ресурса
    дают десятки почти одинаковых картинок — оставляем только ЛУЧШУЮ на кластер.
    findings уже отсортированы по score убыв., поэтому первый в области = лучший.
    Кластер = старт в пределах cluster_bytes от уже принятого (независимо от ширины/формата)."""
    kept = []
    accepted_offsets = []
    for item in findings:
        score, offset, fmt, width, msb, ink, height = item
        near = False
        for o2 in accepted_offsets:
            if abs(offset - o2) < cluster_bytes:
                near = True
                break
        if not near:
            kept.append(item)
            accepted_offsets.append(offset)
    return kept


def _render(data, offset, fmt, width, msb, height, path):
    bpp = {"A8": 8, "A4": 4, "A2": 2, "A1": 1}[fmt]
    stride = bytes_per_row(width, bpp)
    raw = data[offset:offset + stride * height]
    pixels = unpack_pixels(raw, bpp, msb)[: width * height]
    image = Image.new("L", (width, height))
    image.putdata(pixels)
    scale = RENDER_SCALE
    if width * scale > 1400:
        scale = max(1, 1400 // width)
    image = image.resize((width * scale, height * scale), Image.NEAREST)
    image.save(path)


# ---------------------------------------------------------------------------
def main():
    # На Windows консоль по умолчанию cp1252 — принудительно utf-8, чтобы кириллица в логах
    # не роняла прогон (важно для автономного запуска одной командой без PYTHONIOENCODING).
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

    parser = argparse.ArgumentParser(description="Автономный брутфорс несжатых глифов в дампах Geely Coolray")
    parser.add_argument("--dumps", nargs="+",
                        default=["Coolray_25_Dash_U17.bin", "Coolray_25_Dash_U18.bin"],
                        help="файлы дампов (по умолчанию оба чипа)")
    parser.add_argument("--out", default="review/brute", help="каталог вывода")
    parser.add_argument("--height", type=int, default=32,
                        help="высота окна рендера в пикселях (32 = глифы/иконки; больше = крупная графика)")
    parser.add_argument("--max-saved", type=int, default=100000,
                        help="макс. картинок на дамп (по умолчанию фактически без лимита — сохраняет ВСЁ)")
    parser.add_argument("--min-score", type=float, default=0.55, help="порог сохранения 0..1")
    args = parser.parse_args()

    global MIN_SCORE
    MIN_SCORE = args.min_score
    os.makedirs(args.out, exist_ok=True)

    for dump in args.dumps:
        if not os.path.exists(dump):
            print("ПРОПУСК: нет файла", dump)
            continue
        log_path = os.path.join(args.out, "progress_%s.txt" % os.path.splitext(os.path.basename(dump))[0])
        log_file = open(log_path, "a", buffering=1, encoding="utf-8")

        def log(msg, _lf=log_file):
            line = time.strftime("%H:%M:%S ") + msg
            print(line)
            _lf.write(line + "\n")

        log("=== START %s ===" % dump)
        try:
            process_dump(dump, args.out, args.height, args.max_saved, log)
        except KeyboardInterrupt:
            log("!!! прервано пользователем (уже сохранённое цело)")
            break
        except Exception as exc:   # не роняем весь прогон из-за одного дампа
            log("!!! ОШИБКА на %s: %r" % (dump, exc))
        log("=== DONE %s ===" % dump)

    print("\nВсё. Открой галереи в", args.out, "— картинки отсортированы, лучшие с rank 0001.")


if __name__ == "__main__":
    main()
