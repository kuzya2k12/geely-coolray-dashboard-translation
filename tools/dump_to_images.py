#!/usr/bin/env python3
"""
Тупая честная визуализация: весь дамп → большие непрерывные ч/б полосы для просмотра глазами.

Никакого скоринга/эвристик (они обманывают — награждают заливки, режут символы). Просто
раскладываем байты в пиксели при заданной ширине и режем на ВЫСОКИЕ непрерывные куски,
чтобы символ/иконка были видны целиком, а не обрезаны окном. Смотришь сам, находишь —
называешь адрес из имени файла.

ДВА РЕЖИМА:
  A8  — 1 байт = 1 пиксель (grayscale 0..255). Для иконок/картинок/цвета. Ширина W = W байт/строку.
  A1  — 1 бит  = 1 пиксель (чёрное/белое). Для текста/шрифта (он плотнее в 8×). Ширина W = W/8 байт/строку.

Быстрый: только чтение + putdata, без перебора. Оба дампа одной командой.

ЗАПУСК (одна команда, оба дампа, дефолтные ширины):
    python tools/dump_to_images.py

    # выбрать режим/ширины/масштаб/высоту куска:
    python tools/dump_to_images.py --mode a8 --widths 256 512 --scale 2 --chunk 2048
    python tools/dump_to_images.py --mode a1 --widths 256 512 1024
    python tools/dump_to_images.py --mode both        # и A8, и A1 (по умолчанию)

ВЫХОД:
    review/scan/<dump>/<mode>_w<width>/  chunk_<hexaddr>.png ...
Имя каждого файла = HEX-адрес НАЧАЛА этого куска в дампе (для точной привязки находок).
"""
import argparse
import io
import os
import sys

try:
    from PIL import Image
except ImportError:
    sys.exit("Требуется Pillow: pip install pillow")


def save_png(img, path):
    """Надёжное сохранение PNG в обход бага Pillow 12.3 ('_idat has no attribute fileno'):
    кодируем в буфер памяти, затем пишем байты в файл обычным open()."""
    try:
        img.save(path)
    except AttributeError:
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        with open(path, "wb") as f:
            f.write(buf.getvalue())

DATA_START = 0x0          # полный скан чипа (0..64МБ). Начало 0..0x180000 = нули, но сканируем всё.
DATA_END = 0x4000000      # конец чипа 64МБ (после ~0x3450000 = стёрто 0xFF, но сканируем всё)


SEP = 6            # базовая ширина разделителя (для крупных ширин); мелкие — тоньше, см. sep_for_width
SEP_COLOR = 96     # цвет разделителя (серый, чтобы граница кусков была видна)


def sep_for_width(width):
    """Толщина разделителя пропорциональна ширине колонки: на узких (16px) тонкая (2px),
    на широких — до 6px. Иначе фиксированные 6px «съедают» треть узкой колонки."""
    return min(6, max(1, width // 8))


def _chunk_image_a8(data, base, width, chunk_rows):
    buf = data[base:base + width * chunk_rows]
    rows = len(buf) // width
    if rows < 4:
        return None
    img = Image.new("L", (width, rows))
    img.putdata(buf[: width * rows])
    return img


def _chunk_image_a1(data, base, width_px, chunk_rows):
    stride = width_px // 8
    buf = data[base:base + stride * chunk_rows]
    rows = len(buf) // stride
    if rows < 4:
        return None
    pixels = bytearray(width_px * rows)
    idx = 0
    for byte in buf[: stride * rows]:
        pixels[idx] = 255 if byte & 0x80 else 0
        pixels[idx + 1] = 255 if byte & 0x40 else 0
        pixels[idx + 2] = 255 if byte & 0x20 else 0
        pixels[idx + 3] = 255 if byte & 0x10 else 0
        pixels[idx + 4] = 255 if byte & 0x08 else 0
        pixels[idx + 5] = 255 if byte & 0x04 else 0
        pixels[idx + 6] = 255 if byte & 0x02 else 0
        pixels[idx + 7] = 255 if byte & 0x01 else 0
        idx += 8
    img = Image.new("L", (width_px, rows))
    img.putdata(pixels)
    return img


def _chunk_image_rgb565(data, base, width, chunk_rows):
    """2 байта = 1 пиксель, RGB565 little-endian."""
    bpp = 2
    buf = data[base:base + width * chunk_rows * bpp]
    rows = len(buf) // (width * bpp)
    if rows < 4:
        return None
    px = []
    for i in range(0, width * rows * bpp, bpp):
        v = buf[i] | (buf[i + 1] << 8)
        r = (v >> 11) & 0x1F
        g = (v >> 5) & 0x3F
        b = v & 0x1F
        px.append(((r << 3) | (r >> 2), (g << 2) | (g >> 4), (b << 3) | (b >> 2)))
    img = Image.new("RGB", (width, rows))
    img.putdata(px[: width * rows])
    return img


def _chunk_image_rgb888(data, base, width, chunk_rows):
    """3 байта = 1 пиксель, R G B."""
    bpp = 3
    buf = data[base:base + width * chunk_rows * bpp]
    rows = len(buf) // (width * bpp)
    if rows < 4:
        return None
    px = [(buf[i], buf[i + 1], buf[i + 2]) for i in range(0, width * rows * bpp, bpp)]
    img = Image.new("RGB", (width, rows))
    img.putdata(px[: width * rows])
    return img


def _chunk_image_rgba(data, base, width, chunk_rows):
    """4 байта = 1 пиксель, RGBA8888. Alpha композитится на серый фон (чтобы видеть прозрачность)."""
    bpp = 4
    buf = data[base:base + width * chunk_rows * bpp]
    rows = len(buf) // (width * bpp)
    if rows < 4:
        return None
    img = Image.new("RGBA", (width, rows))
    img.putdata([tuple(buf[i:i + 4]) for i in range(0, width * rows * bpp, bpp)][: width * rows])
    bg = Image.new("RGBA", (width, rows), (128, 128, 128, 255))
    return Image.alpha_composite(bg, img).convert("RGB")


def is_colorful(sheet, min_colored_frac=0.005, sat_threshold=24):
    """True, если в RGB-полотне есть заметная доля ЦВЕТНЫХ пикселей (R,G,B различаются).
    Монохром (серое/ч-б) → False → файл можно не сохранять. Дёшево: сэмплируем пиксели."""
    data = sheet.getdata()
    n = len(data)
    step = max(1, n // 20000)   # ~20k выборок хватает для вердикта
    colored = 0
    checked = 0
    for i in range(0, n, step):
        r, g, b = data[i]
        if max(r, g, b) - min(r, g, b) > sat_threshold:
            colored += 1
        checked += 1
    return checked > 0 and (colored / checked) >= min_colored_frac


def _emit(columns, width, scale, out_dir, first_base, color=False, skip_monochrome=False):
    """Склеивает список вертикальных кусков бок о бок в одно широкое полотно.
    Одна папка на режим; ширина и адрес — в ИМЕНИ файла (w<width>_<hexaddr>.png), чтобы при
    сортировке файлы группировались по ширине. Если color+skip_monochrome и полотно фактически
    серое — НЕ сохраняет (возвращает False)."""
    if not columns:
        return False
    mode_img = "RGB" if color else "L"
    sep_fill = (SEP_COLOR, SEP_COLOR, SEP_COLOR) if color else SEP_COLOR
    bg_fill = (0, 0, 0) if color else 0
    sep = sep_for_width(width)
    height = max(c.height for c in columns)
    total_w = len(columns) * width + (len(columns) - 1) * sep
    sheet = Image.new(mode_img, (total_w, height), bg_fill)
    x = 0
    for c in columns:
        sheet.paste(c, (x, 0))
        x += width
        if x < total_w:
            sheet.paste(Image.new(mode_img, (sep, height), sep_fill), (x, 0))
            x += sep
    if color and skip_monochrome and not is_colorful(sheet):
        return False   # чисто серое/ч-б полотно — цвета нет, файл не создаём
    if scale != 1:
        sheet = sheet.resize((sheet.width * scale, sheet.height * scale), Image.NEAREST)
    # имя: ширина (zero-padded для сортировки) + hex-адрес первой колонки
    save_png(sheet, os.path.join(out_dir, "w%04d_%08X.png" % (width, first_base)))
    return True


def tile_for_aspect(width, chunk_rows, target_aspect=16 / 9):
    """Сколько колонок склеить, чтобы полотно было ~16:9. Узкая ширина → больше колонок."""
    # итоговая высота = chunk_rows; ширина ≈ ncols*(width+sep); хотим width/height ≈ 16/9
    target_w = chunk_rows * target_aspect
    ncols = round(target_w / (width + sep_for_width(width)))
    return max(1, ncols)


def render_bytes(data, start, end, width, chunk_rows, scale, out_dir, mode, tile, skip_monochrome=False):
    """Режет регион на вертикальные куски и склеивает по `tile` штук бок о бок в широкие полотна.
    mode: a8/a1/rgb565/rgb888/rgba. tile=0 → авто под 16:9 (число колонок из ширины).
    skip_monochrome (только для цвета): не сохранять полотна без реального цвета."""
    os.makedirs(out_dir, exist_ok=True)
    color = mode in ("rgb565", "rgb888", "rgba")
    if tile <= 0:
        tile = tile_for_aspect(width, chunk_rows)
    if mode == "a8":
        chunk_bytes = width * chunk_rows
        make = lambda base: _chunk_image_a8(data, base, width, chunk_rows)
    elif mode == "a1":
        chunk_bytes = (width // 8) * chunk_rows
        make = lambda base: _chunk_image_a1(data, base, width, chunk_rows)
    elif mode == "rgb565":
        chunk_bytes = width * chunk_rows * 2
        make = lambda base: _chunk_image_rgb565(data, base, width, chunk_rows)
    elif mode == "rgb888":
        chunk_bytes = width * chunk_rows * 3
        make = lambda base: _chunk_image_rgb888(data, base, width, chunk_rows)
    elif mode == "rgba":
        chunk_bytes = width * chunk_rows * 4
        make = lambda base: _chunk_image_rgba(data, base, width, chunk_rows)
    else:
        raise ValueError("unknown mode " + mode)

    columns = []
    first_base = start
    files = 0
    for base in range(start, end, chunk_bytes):
        img = make(base)
        if img is None:
            continue
        if not columns:
            first_base = base
        columns.append(img)
        if len(columns) >= tile:
            if _emit(columns, width, scale, out_dir, first_base, color, skip_monochrome):
                files += 1
            columns = []
    if columns:
        if _emit(columns, width, scale, out_dir, first_base, color, skip_monochrome):
            files += 1
    return files


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

    parser = argparse.ArgumentParser(description="Весь дамп → большие ч/б полосы для просмотра глазами")
    parser.add_argument("--dumps", nargs="+",
                        default=["Coolray_25_Dash_U17.bin", "Coolray_25_Dash_U18.bin"])
    parser.add_argument("--out", default="review/scan")
    parser.add_argument("--mode",
                        choices=["a8", "a1", "rgb565", "rgb888", "rgba", "both", "all"],
                        default="all",
                        help="a8=grayscale, a1=ч/б, rgb565/rgb888/rgba=цвет, both=a8+a1, all=всё")
    parser.add_argument("--widths", type=int, nargs="+", default=None,
                        help="ширины в пикселях (по умолчанию: A8=128,256,512 ; A1=256,512,1024)")
    parser.add_argument("--scale", type=int, default=2, help="увеличение (1=компактно, 2-3=крупнее)")
    parser.add_argument("--chunk", type=int, default=2048, help="высота куска в строках пикселей")
    parser.add_argument("--tile", type=int, default=0,
                        help="сколько кусков склеивать бок о бок (0=авто под 16:9 из ширины; N=фиксировано)")
    parser.add_argument("--keep-mono-color", action="store_true",
                        help="сохранять и монохромные цветные полотна (по умолчанию цветные ч/б пропускаются)")
    parser.add_argument("--start", type=lambda x: int(x, 0), default=DATA_START)
    parser.add_argument("--end", type=lambda x: int(x, 0), default=DATA_END)
    args = parser.parse_args()

    # Ширина = stride ресурса. Без верной ширины растр «съезжает» в кашу (проверено: иконки
    # читаются ТОЛЬКО на родных 48, на 128/256 — нечитаемо). Поэтому набор ПЛОТНЫЙ — чтобы для
    # любого ресурса нашлась близкая ширина. Цвет чувствительнее (2/3/4 байта на пиксель).
    #
    # A8 (1 байт/пиксель): мелкие глифы/иконки 16..64 плотно + крупные картинки.
    a8_widths = args.widths or (
        list(range(16, 129, 4)) + [160, 192, 240, 256, 320, 384, 480, 512, 640])
    # A1 (1 бит/пиксель, текст плотный): ОБЯЗАТЕЛЬНО кратные 8 (байт=8 пикселей).
    # Мелкие ширины 8..64 плотно — для мелкого текста/цифр/символов (могут быть 12-32px!),
    # плюс крупные для широких атласов/строк. Без мелких — мелкий шрифт «съедет» как иконки на 128.
    a1_widths = args.widths or (
        list(range(8, 129, 8)) + [160, 192, 224, 256, 320, 384, 448, 512, 640, 768, 1024])
    # Цвет: те же «пиксельные» ширины (в байтах умножатся на bpp внутри). Плотно в области спрайтов/дисплея.
    color_widths = args.widths or [
        16, 24, 32, 48, 64, 80, 96, 112, 128, 160, 192, 240, 256, 320, 384, 480, 640]

    for dump in args.dumps:
        if not os.path.exists(dump):
            print("ПРОПУСК: нет файла", dump)
            continue
        data = open(dump, "rb").read()
        end = min(args.end, len(data))
        tag = os.path.splitext(os.path.basename(dump))[0]
        print("=== %s (0x%08X..0x%08X, %d КБ) ===" % (dump, args.start, end, (end - args.start) // 1024))

        # Одна папка на режим; ширины различаются префиксом имени файла (w0128_..., w0256_...).
        if args.mode in ("a8", "both", "all"):
            out = os.path.join(args.out, tag, "a8")
            total = sum(render_bytes(data, args.start, end, w, args.chunk, args.scale, out, "a8", args.tile)
                        for w in a8_widths)
            print("  A8      widths %s -> %d полотен в %s/" % (a8_widths, total, out))
        if args.mode in ("a1", "both", "all"):
            out = os.path.join(args.out, tag, "a1")
            total = sum(render_bytes(data, args.start, end, w, args.chunk, args.scale, out, "a1", args.tile)
                        for w in a1_widths)
            print("  A1      widths %s -> %d полотен в %s/" % (a1_widths, total, out))
        skip_mono = not args.keep_mono_color
        if args.mode in ("rgb565", "all"):
            out = os.path.join(args.out, tag, "rgb565")
            total = sum(render_bytes(data, args.start, end, w, args.chunk, args.scale, out, "rgb565", args.tile, skip_mono)
                        for w in color_widths)
            print("  RGB565  widths %s -> %d ЦВЕТНЫХ полотен (монохром пропущен)" % (color_widths, total))
        if args.mode in ("rgb888", "all"):
            out = os.path.join(args.out, tag, "rgb888")
            total = sum(render_bytes(data, args.start, end, w, args.chunk, args.scale, out, "rgb888", args.tile, skip_mono)
                        for w in color_widths)
            print("  RGB888  widths %s -> %d ЦВЕТНЫХ полотен" % (color_widths, total))
        if args.mode in ("rgba", "all"):
            out = os.path.join(args.out, tag, "rgba")
            total = sum(render_bytes(data, args.start, end, w, args.chunk, args.scale, out, "rgba", args.tile, skip_mono)
                        for w in color_widths)
            print("  RGBA    widths %s -> %d ЦВЕТНЫХ полотен" % (color_widths, total))

    print("\nГотово. Смотри %s — по одной папке на режим (a8/a1/rgb565/rgb888/rgba)." % args.out)
    print("Имя файла: w<ШИРИНА>_<HEX-АДРЕС первой колонки>.png (сортировка группирует по ширине).")
    print("Колонки в полотне читаются СЛЕВА-НАПРАВО, каждая = следующий кусок дампа (разделены серой линией).")
    print("Нашёл что-то? Назови имя файла + примерную колонку — вытащим прицельно.")


if __name__ == "__main__":
    main()
