#!/usr/bin/env python3
"""
Визуализатор регионов дампа приборки как raw-bitmap (PPM, открывается любым просмотрщиком).
Перебирает форматы пикселей и ширину — чтобы найти атлас глифов / графику.

Использование:
  python render_region.py <файл.bin> <offset_hex> <size_kb> [width] [format]
  format: gray4 gray8 rgb565 argb8888 idx8

Примеры:
  python render_region.py Coolray_25_Dash_U17.bin 0x180000 256          # авто-перебор
  python render_region.py Coolray_25_Dash_U17.bin 0x180000 256 128 gray4
Результат: PPM-файлы region_<offset>_<fmt>_w<width>.ppm рядом.
"""
import sys, struct

def read_region(path, off, size):
    with open(path, "rb") as f:
        f.seek(off)
        return f.read(size)

def to_rgb(data, fmt):
    """Вернуть (пиксели RGB как bytes, байт-на-пиксель, пикселей всего)."""
    out = bytearray()
    if fmt == "gray4":          # 4 бита/пиксель, 2 пикселя в байте
        for b in data:
            for nib in ((b >> 4) & 0xF, b & 0xF):
                v = nib * 17
                out += bytes((v, v, v))
        return bytes(out), 0.5, len(data) * 2
    if fmt == "gray8":
        for b in data:
            out += bytes((b, b, b))
        return bytes(out), 1, len(data)
    if fmt == "rgb565":
        for i in range(0, len(data) - 1, 2):
            v = data[i] | (data[i + 1] << 8)
            r = ((v >> 11) & 0x1F) << 3
            g = ((v >> 5) & 0x3F) << 2
            b = (v & 0x1F) << 3
            out += bytes((r, g, b))
        return bytes(out), 2, len(data) // 2
    if fmt == "argb8888":
        for i in range(0, len(data) - 3, 4):
            out += bytes((data[i + 2], data[i + 1], data[i]))  # BGRA->RGB
        return bytes(out), 4, len(data) // 4
    if fmt == "idx8":            # индекс без палитры — как gray8
        return to_rgb(data, "gray8")
    raise ValueError("формат: gray4 gray8 rgb565 argb8888 idx8")

def write_ppm(path, rgb, width, npix):
    height = npix // width
    with open(path, "wb") as f:
        f.write(b"P6\n%d %d\n255\n" % (width, height))
        f.write(rgb[: width * height * 3])

def main():
    if len(sys.argv) < 4:
        print(__doc__)
        return
    path, off, size = sys.argv[1], int(sys.argv[2], 16), int(sys.argv[3]) * 1024
    data = read_region(path, off, size)
    if len(sys.argv) >= 6:
        widths = [int(sys.argv[4])]
        fmts = [sys.argv[5]]
    else:
        widths = [64, 96, 128, 160, 200, 240, 256, 320, 480, 640, 800]
        fmts = ["gray4", "gray8", "rgb565", "argb8888"]
    for fmt in fmts:
        rgb, bpp, npix = to_rgb(data, fmt)
        for w in widths:
            if npix // w < 8:
                continue
            name = "region_%X_%s_w%d.ppm" % (off, fmt, w)
            write_ppm(name, rgb, w, npix)
            print("  %s  (%dx%d)" % (name, w, npix // w))
    print("Открой PPM в GIMP/IrfanView/просмотрщике. Настоящая картинка при верной "
          "ширине/формате станет узнаваемой; глифы = регулярная сетка.")

if __name__ == "__main__":
    main()
