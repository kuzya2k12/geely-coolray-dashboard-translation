#!/usr/bin/env python3
"""
Извлечение НЕсжатых (raw A8) глифов/иконок из дампа приборки Geely Coolray.

КЛЮЧЕВОЕ ОТКРЫТИЕ (см. docs/SUCCESSFUL_FINDINGS.md):
Часть графики приборки хранится в NOR НЕ в RLAD, а СЫРЫМ A8 — 1 байт = 1 пиксель alpha.
Именно поэтому весь прежний RLAD-подход давал шум на этой зоне: пытались декодировать то,
что вообще не сжато. Достаточно интерпретировать байты напрямую как grayscale при верной
ширине строки (stride).

Подтверждённая зона иконок: 0x28F4000..0x2928000 (~208 КБ), stride = 48 px, формат raw A8.
Воспроизводится на обоих чипах (U17/U18). Извлекается ~64-67 иконок телльтейлов приборки
(ноты, авто, спидометры, замки, предупреждения, кофе, парковка, масло, ремень и т.д.).

Только чтение дампа. Пишет PNG в output/found_glyphs/.

Запуск:
  python tools/extract_raw_a8.py Coolray_25_Dash_U17.bin
  python tools/extract_raw_a8.py Coolray_25_Dash_U17.bin --zone 0x28F4000 0x2928000 --width 48
  python tools/extract_raw_a8.py Coolray_25_Dash_U17.bin --scan   # искать raw-A8 зоны по всему чипу
"""
import argparse
import collections
import math
import os
import sys

try:
    from PIL import Image
except ImportError:
    sys.exit("Требуется Pillow: pip install pillow")

# Подтверждённые параметры зоны иконок (raw A8)
DEFAULT_ZONE_START = 0x28F4000
DEFAULT_ZONE_END = 0x2928000
DEFAULT_WIDTH = 48
OUT_DIR = os.path.join("output", "found_glyphs")


def entropy(block: bytes) -> float:
    """Энтропия Шеннона блока байт (0..8 бит)."""
    if not block:
        return 0.0
    counts = collections.Counter(block)
    length = len(block)
    result = 0.0
    for count in counts.values():
        p = count / length
        result -= p * math.log2(p)
    return result


def is_raw_a8_window(block: bytes) -> bool:
    """Признак СЫРОГО A8 (не сжатого RLAD): мало уникальных значений и бимодальность.

    Сжатый RLAD-поток использует все 256 значений байта; сырой A8-глиф — лишь несколько
    уровней alpha (фон + чернила), сильно смещённых к 0x00 и к высоким значениям.
    """
    if not block:
        return False
    if block.count(0xFF) > 0.6 * len(block) or block.count(0x00) > 0.95 * len(block):
        return False
    distinct_values = len(collections.Counter(block))
    if distinct_values >= 90:  # сжатое = почти все 256 значений
        return False
    low = sum(1 for byte_value in block if byte_value < 32)
    high = sum(1 for byte_value in block if byte_value >= 200)
    return (low + high) > 0.80 * len(block) and low > 0.3 * len(block) and high > 0.02 * len(block)


def find_best_width(region: bytes, min_width: int = 16, max_width: int = 130) -> tuple[int, float]:
    """Находит истинный stride через вертикальную когерентность соседних строк.

    У настоящего битмапа глифа штрихи вертикально непрерывны, поэтому при верной ширине
    соседние строки максимально похожи. У неверной ширины картинка «съезжает» → низкая
    когерентность.
    """
    best_width = min_width
    best_score = -1.0
    for candidate_width in range(min_width, max_width):
        height = len(region) // candidate_width
        if height < 8:
            continue
        matches = 0
        total = 0
        rows_to_check = min(height, 200) - 1
        for row_y in range(rows_to_check):
            base = row_y * candidate_width
            below = base + candidate_width
            for column_x in range(candidate_width):
                if abs(region[base + column_x] - region[below + column_x]) < 24:
                    matches += 1
                total += 1
        score = matches / total if total else 0.0
        if score > best_score:
            best_score = score
            best_width = candidate_width
    return best_width, best_score


def slice_icons(region: bytes, width: int, min_height: int = 6) -> list[tuple[int, int]]:
    """Режет зону на отдельные иконки по пустым (все-нулевым) строкам-разделителям.

    Возвращает список (row_start, row_end) в единицах строк.
    """
    row_count = len(region) // width
    rows = [region[i * width:(i + 1) * width] for i in range(row_count)]

    def is_empty(row: bytes) -> bool:
        return row.count(0) >= width - 1

    icons = []
    current_start = None
    for row_y, row in enumerate(rows):
        if not is_empty(row):
            if current_start is None:
                current_start = row_y
        else:
            if current_start is not None and row_y - current_start >= min_height:
                icons.append((current_start, row_y))
            current_start = None
    if current_start is not None and row_count - current_start >= min_height:
        icons.append((current_start, row_count))
    return icons


def render_panorama(region: bytes, width: int, out_path: str, scale: int = 5, panel_rows: int = 460):
    """Складывает высокую raw-A8 полосу в широкое многоколоночное полотно (видно всё разом)."""
    height = len(region) // width
    panels = []
    y = 0
    while y < height:
        panels.append((y, min(y + panel_rows, height)))
        y += panel_rows
    gap = 10
    column_width = width * scale + gap
    sheet = Image.new("L", (column_width * len(panels), panel_rows * scale), 50)
    for column_index, (row_start, row_end) in enumerate(panels):
        buffer = region[row_start * width:row_end * width]
        panel = Image.new("L", (width, row_end - row_start))
        panel.putdata(buffer)
        panel = panel.resize((width * scale, (row_end - row_start) * scale), Image.NEAREST)
        sheet.paste(panel, (column_index * column_width, 0))
    sheet.save(out_path)
    return sheet.width, sheet.height, len(panels)


def scan_chip(data: bytes, region_start: int = 0x180000, region_end: int = 0x3450000):
    """Ищет по всему чипу окна с подписью сырого A8 (кандидаты в новые зоны иконок/глифов)."""
    hits = []
    for base in range(region_start, region_end, 0x4000):
        if is_raw_a8_window(data[base:base + 0x4000]):
            hits.append(base)
    groups = []
    for base in hits:
        if groups and base - groups[-1][1] <= 0x8000:
            groups[-1][1] = base
        else:
            groups.append([base, base])
    return groups


def main():
    parser = argparse.ArgumentParser(description="Извлечь raw-A8 иконки/глифы из дампа приборки Geely Coolray")
    parser.add_argument("dump", help="файл дампа (.bin)")
    parser.add_argument("--zone", nargs=2, metavar=("START", "END"),
                        help="границы зоны в hex, напр. 0x28F4000 0x2928000")
    parser.add_argument("--width", type=int, default=None, help="stride в пикселях (по умолчанию автоопределение)")
    parser.add_argument("--scan", action="store_true", help="просканировать весь чип на raw-A8 зоны и выйти")
    args = parser.parse_args()

    data = open(args.dump, "rb").read()
    os.makedirs(OUT_DIR, exist_ok=True)
    dump_tag = os.path.splitext(os.path.basename(args.dump))[0]

    if args.scan:
        print("Поиск raw-A8 зон по всему чипу (кандидаты в иконки/глифы):")
        for group_start, group_end in scan_chip(data):
            size_kb = (group_end + 0x4000 - group_start) // 1024
            print("  0x%08X .. 0x%08X  (%d KB)" % (group_start, group_end + 0x4000, size_kb))
        print("ПРИМЕЧАНИЕ: детектор груб — не каждая зона окажется глифовой при рендере "
              "(сжатые зоны с узким алфавитом дают ложные срабатывания). Проверяй визуально.")
        return

    zone_start = int(args.zone[0], 16) if args.zone else DEFAULT_ZONE_START
    zone_end = int(args.zone[1], 16) if args.zone else DEFAULT_ZONE_END
    region = data[zone_start:zone_end]

    if args.width:
        width = args.width
        _, coherence = find_best_width(region, width, width + 1)
    elif args.zone is None:
        # Для подтверждённой зоны иконок stride точно известен = 48. Автоподбор на
        # зашумлённом лид-ине зоны может ложно выбрать 40 — не доверяем ему здесь.
        width = DEFAULT_WIDTH
        _, coherence = find_best_width(region, width, width + 1)
    else:
        width, coherence = find_best_width(region)
    print("Зона 0x%08X..0x%08X (%d KB), stride=%d px, вертикальная когерентность=%.3f"
          % (zone_start, zone_end, len(region) // 1024, width, coherence))
    if coherence < 0.6:
        print("  ⚠️ Низкая когерентность (<0.6) — зона может быть НЕ сырым A8 (вероятно сжата RLAD).")

    # Панорама всей зоны
    panorama_path = os.path.join(OUT_DIR, "%s_panorama_w%d.png" % (dump_tag, width))
    pano_w, pano_h, columns = render_panorama(region, width, panorama_path)
    print("Панорама: %s (%dx%d, %d колонок)" % (panorama_path, pano_w, pano_h, columns))

    # Нарезка отдельных иконок
    icons_dir = os.path.join(OUT_DIR, "icons_%s" % dump_tag)
    os.makedirs(icons_dir, exist_ok=True)
    icons = slice_icons(region, width)
    saved = 0
    for index, (row_start, row_end) in enumerate(icons):
        buffer = region[row_start * width:row_end * width]
        image = Image.new("L", (width, row_end - row_start))
        image.putdata(buffer)
        bounding_box = image.getbbox()
        if not bounding_box:
            continue
        cropped = image.crop(bounding_box)
        offset = zone_start + row_start * width
        file_name = "ic_%03d_off%08X_%dx%d.png" % (index, offset, cropped.width, cropped.height)
        cropped.resize((cropped.width * 3, cropped.height * 3), Image.NEAREST).save(
            os.path.join(icons_dir, file_name))
        saved += 1
    print("Иконок нарезано: %d -> %s" % (saved, icons_dir))


if __name__ == "__main__":
    main()
