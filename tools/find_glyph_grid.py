#!/usr/bin/env python3
"""
Детектор СЕТКИ ГЛИФОВ (шрифта) в дампах — автокорреляцией, тем же методом, что дал stride=48
для иконок. Ищет НЕсжатые зоны с регулярной квадратной решёткой символов (кандидаты в шрифт:
латиница 8/12/16, CJK-иероглифы 16×16 / 24×24 / 32×32 — стандарты HZK16/24/32).

Отдельный инструмент, НИЧЕГО не меняет в других скриптах. Только чтение дампов, вывод — отчёт
в консоль + review/glyph_grid/report.txt со списком адресов-кандидатов (потом посмотришь их
в dump_to_images.py на найденной ширине).

ИДЕЯ. У растрового шрифта фиксированного размера:
  - по ГОРИЗОНТАЛИ бит-паттерн повторяется каждые W пикселей (ширина ячейки),
  - по ВЕРТИКАЛИ — каждые H пикселей (высота ячейки),
  - для CJK обычно W == H (квадрат).
Считаем автокорреляцию отдельно по обеим осям, ищем совпадающий период = размер ячейки.
Работает ТОЛЬКО на несжатом растре (RLAD-сжатое даёт ложный период упаковки — отсекаем по
distinct-bytes, как в других инструментах).

ЗАПУСК:
    python tools/find_glyph_grid.py
    python tools/find_glyph_grid.py --dumps Coolray_25_Dash_U17.bin --formats a1 a8
    python tools/find_glyph_grid.py --cells 16 24 32   # какие размеры ячеек проверять
"""
import argparse
import collections
import os
import sys

DATA_START = 0x180000
DATA_END = 0x3460000
ZONE_STEP = 0x2000            # шаг сканирования
ZONE_WINDOW = 0x2000          # окно анализа (8 КБ)
MAX_DISTINCT = 64             # <этого = несжато (RLAD ~256)
DEFAULT_CELLS = [8, 12, 16, 20, 24, 28, 32, 40, 48]   # размеры ячеек-кандидатов (px)


def unpack_bits(buffer, msb_first=True):
    """A1: 1 бит = 1 пиксель. Возвращает список 0/1."""
    out = bytearray()
    for byte in buffer:
        if msb_first:
            out.append((byte >> 7) & 1)
            out.append((byte >> 6) & 1)
            out.append((byte >> 5) & 1)
            out.append((byte >> 4) & 1)
            out.append((byte >> 3) & 1)
            out.append((byte >> 2) & 1)
            out.append((byte >> 1) & 1)
            out.append(byte & 1)
        else:
            out.append(byte & 1)
            out.append((byte >> 1) & 1)
            out.append((byte >> 2) & 1)
            out.append((byte >> 3) & 1)
            out.append((byte >> 4) & 1)
            out.append((byte >> 5) & 1)
            out.append((byte >> 6) & 1)
            out.append((byte >> 7) & 1)
    return out


def unpack_a8(buffer):
    """A8: 1 байт = 1 пиксель. Порог в ink 0/1 для структурного анализа."""
    return [1 if b > 0x40 else 0 for b in buffer]


def is_uncompressed(block):
    """Несжатый растр = мало уникальных байт (RLAD использует все 256)."""
    if block.count(0) > 0.97 * len(block) or block.count(0xFF) > 0.6 * len(block):
        return False
    return len(collections.Counter(block)) < MAX_DISTINCT


def h_autocorr(ink, width_px, rows, lag):
    """Горизонтальная автокорреляция: похожесть пикселя на пиксель через `lag` в той же строке.
    Высокая на lag = ширина ячейки (соседние глифы структурно похожи по колонкам-разделителям)."""
    match = 0
    total = 0
    for y in range(rows):
        base = y * width_px
        for x in range(width_px - lag):
            if ink[base + x] == ink[base + x + lag]:
                match += 1
            total += 1
    return match / total if total else 0


def v_autocorr(ink, width_px, rows, lag):
    """Вертикальная автокорреляция: похожесть строки на строку через `lag`."""
    match = 0
    total = 0
    for y in range(rows - lag):
        b0 = y * width_px
        b1 = (y + lag) * width_px
        for x in range(width_px):
            if ink[b0 + x] == ink[b1 + x]:
                match += 1
            total += 1
    return match / total if total else 0


def analyze_zone(data, base, fmt, cells, msb=True):
    """Возвращает лучший (score, cell) для зоны, если похоже на сетку глифов, иначе None."""
    block = data[base:base + ZONE_WINDOW]
    if not is_uncompressed(block):
        return None

    # разложить в ink с фиксированной шириной для анализа
    # для решётки берём render-ширину = крупная (несколько ячеек в ряд), напр. 128 px
    render_w = 128
    if fmt == "a1":
        need_bytes = (render_w // 8) * (ZONE_WINDOW // (render_w // 8))
        ink = unpack_bits(block, msb)
    else:  # a8
        ink = unpack_a8(block)
    rows = len(ink) // render_w
    if rows < 32:
        return None

    # доля чернил должна быть «текстовой» (не пусто, не залито)
    frac = sum(ink[:render_w * rows]) / (render_w * rows)
    if not (0.05 < frac < 0.6):
        return None

    best = None
    for cell in cells:
        if cell >= render_w or cell >= rows:
            continue
        h = h_autocorr(ink, render_w, rows, cell)
        v = v_autocorr(ink, render_w, rows, cell)
        # сетка глифов: сильная периодичность И по горизонтали, И по вертикали на одном шаге
        score = min(h, v)          # обе оси должны совпасть → берём минимум
        # бонус если h и v близки (квадратная ячейка = CJK)
        if abs(h - v) < 0.05:
            score += 0.03
        if best is None or score > best[0]:
            best = (score, cell, h, v)
    return best


def process(dump, out_dir, fmts, cells, log):
    data = open(dump, "rb").read()
    tag = os.path.splitext(os.path.basename(dump))[0]
    hits = []
    end = min(DATA_END, len(data))
    scanned = 0
    for base in range(DATA_START, end, ZONE_STEP):
        block = data[base:base + ZONE_WINDOW]
        if not is_uncompressed(block):
            continue
        scanned += 1
        for fmt in fmts:
            orders = (True, False) if fmt == "a1" else (True,)
            for msb in orders:
                res = analyze_zone(data, base, fmt, cells, msb)
                if res and res[0] > 0.72:      # порог «похоже на сетку»
                    score, cell, h, v = res
                    hits.append((score, base, fmt, cell, h, v, "msb" if msb else "lsb"))
    hits.sort(reverse=True)
    log("[%s] несжатых окон просмотрено: %d, кандидатов-сеток: %d" % (tag, scanned, len(hits)))
    # дедуп по адресу (±16КБ) — одна зона не должна плодить десятки
    kept = []
    seen = []
    for hitem in hits:
        score, base, fmt, cell, h, v, order = hitem
        if any(abs(base - o) < 0x4000 for o in seen):
            continue
        seen.append(base)
        kept.append(hitem)

    report = os.path.join(out_dir, "report_%s.txt" % tag)
    with open(report, "w", encoding="utf-8") as f:
        f.write("# Кандидаты сетки глифов (шрифт) в %s\n" % dump)
        f.write("# score  offset      format  cell  h_corr  v_corr  bitorder\n")
        f.write("# Смотри в dump_to_images.py на ширине, КРАТНОЙ cell (напр. cell*4).\n\n")
        for score, base, fmt, cell, h, v, order in kept:
            line = "%.3f  0x%08X  %-3s  cell=%-3d  h=%.2f v=%.2f  %s" % (
                score, base, fmt, cell, h, v, order)
            f.write(line + "\n")
            log("  " + line)
    log("[%s] отчёт: %s (%d уникальных зон)" % (tag, report, len(kept)))


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    parser = argparse.ArgumentParser(description="Детектор сетки глифов (шрифта) автокорреляцией")
    parser.add_argument("--dumps", nargs="+",
                        default=["Coolray_25_Dash_U17.bin", "Coolray_25_Dash_U18.bin"])
    parser.add_argument("--out", default="review/glyph_grid")
    parser.add_argument("--formats", nargs="+", default=["a1", "a8"], choices=["a1", "a8"])
    parser.add_argument("--cells", type=int, nargs="+", default=DEFAULT_CELLS)
    args = parser.parse_args()
    os.makedirs(args.out, exist_ok=True)

    def log(m):
        print(m)

    for dump in args.dumps:
        if not os.path.exists(dump):
            print("ПРОПУСК: нет файла", dump)
            continue
        log("=== %s ===" % dump)
        process(dump, args.out, args.formats, args.cells, log)

    print("\nГотово. Кандидаты в review/glyph_grid/report_*.txt.")
    print("Для каждого: смотри его адрес в dump_to_images.py на ширине, кратной cell.")
    print("Пусто/мало? Значит несжатого шрифта с регулярной сеткой нет (текст, вероятно, RLAD-сжат).")


if __name__ == "__main__":
    main()
