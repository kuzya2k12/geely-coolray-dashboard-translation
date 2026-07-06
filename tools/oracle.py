#!/usr/bin/env python3
"""
Oracle-харнесс для реверса формата RLAD.

Использует референс-энкодер Infineon (rlad-encoder.exe) как оракул:
кодирует контролируемые изображения и парсит выходные .h, чтобы
восстановить точную битовую раскладку RLAD/RLA/RL потоков.

Требует: PIL, rlad-encoder.exe в ../rlad-ex/utility/
"""
import sys, os, re, subprocess, struct
sys.stdout.reconfigure(encoding="utf-8")
from PIL import Image

ENC = os.path.abspath("../rlad-ex/utility/rlad-encoder.exe")
WORK = os.path.abspath("output/oracle")
os.makedirs(WORK, exist_ok=True)


def encode(img: Image.Image, mode: str, name: str):
    """Кодирует PIL-изображение энкодером, возвращает (bytes, meta-dict)."""
    png = os.path.join(WORK, name + ".png")
    hdr = os.path.join(WORK, name + ".h")
    img.convert("RGBA").save(png)
    r = subprocess.run([ENC, png, hdr, mode], capture_output=True, text=True,
                       cwd=os.path.dirname(ENC))
    meta = {}
    for ln in r.stdout.splitlines():
        m = re.search(r"# (\w[\w ]*\w)\s*=\s*(.+)", ln)
        if m:
            meta[m.group(1).strip()] = m.group(2).strip()
    if not os.path.exists(hdr):
        return None, meta, r.stdout
    txt = open(hdr).read()
    # извлечь массив байт
    m = re.search(r"\[(\d+)\]\s*=\s*\{(.+?)\}", txt, re.S)
    data = b""
    if m:
        vals = re.findall(r"0x([0-9a-fA-F]{2})", m.group(2))
        data = bytes(int(v, 16) for v in vals)
    fmt = {}
    for k in ("IMG_PTR_WIDTH", "IMG_PTR_HEIGHT", "MODE", "BPS_FORMAT", "SIZE_IN_WORDS"):
        mm = re.search(k + r"\s+(\w+)", txt)
        if mm:
            fmt[k] = mm.group(1)
    return data, {**meta, **fmt}, r.stdout


def hexdump(b, cols=16):
    out = []
    for i in range(0, len(b), cols):
        row = b[i:i + cols]
        out.append("  %04X  %s" % (i, " ".join("%02X" % x for x in row)))
    return "\n".join(out)


def bits_lsb_first(b):
    """Строка бит в порядке чтения RLAD BitStream (32-битные слова, lsb->msb)."""
    out = []
    for wi in range(0, len(b) - 3, 4):
        word = struct.unpack_from("<I", b, wi)[0]
        for bit in range(32):
            out.append((word >> bit) & 1)
    return out


def probe(name, img, mode="RLAD"):
    data, meta, log = encode(img, mode, name)
    print("=== %s (%s) %dx%d ===" % (name, mode, img.width, img.height))
    if data is None:
        print("  ОШИБКА энкодера:\n", log)
        return None
    print("  size=%d bytes  meta: %s" % (len(data), {k: meta.get(k) for k in ("final_size", "SIZE_IN_WORDS", "bpc")}))
    print(hexdump(data))
    print()
    return data


if __name__ == "__main__":
    # набор диагностических входов для реверса формата
    probe("solid_red_8", Image.new("RGBA", (8, 8), (255, 0, 0, 255)))
    probe("solid_gray_8", Image.new("RGBA", (8, 8), (0x40, 0x40, 0x40, 255)))
    probe("black_8", Image.new("RGBA", (8, 8), (0, 0, 0, 255)))
    # один белый пиксель на чёрном
    im = Image.new("RGBA", (8, 8), (0, 0, 0, 255)); im.putpixel((0, 0), (255, 255, 255, 255))
    probe("one_white_8", im)
    # горизонтальный градиент по X (проверка run vs literal)
    im = Image.new("RGBA", (16, 1), (0, 0, 0, 255))
    for x in range(16): im.putpixel((x, 0), (x * 16, 0, 0, 255))
    probe("gradx_16", im)
