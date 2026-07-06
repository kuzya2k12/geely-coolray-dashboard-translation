#!/usr/bin/env python3
"""
Ищет surface-изображения в дампе приборки, используя:
  1) 20-байтовый дескриптор Infineon (из utSurfLoadBitmapEx),
  2) проверку RLAD-декодом (валидный дескриптор + чистый декод = настоящий surface).

Извлекает найденное в PNG (output/surfaces/).
"""
import sys, os, struct
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "geely_cluster"))
from rlad_decoder import BitStream, decode_packet, NUM_C, CNT_RLAD
from PIL import Image

DUMP = sys.argv[1] if len(sys.argv) > 1 else "../Coolray_25_Dash_U17.bin"
OUT = "output/surfaces"
os.makedirs(OUT, exist_ok=True)

# CYGFX_SM_COMP
COMP = {0: "RLAD", 1: "RLAD_U", 2: "RLA", 3: "RLC", 4: "NONE"}


def parse_desc(buf, off):
    """20-байтовый заголовок ResGen: size,w,h,stride,bpp,flags,colorbits,colorshift."""
    if off + 0x14 > len(buf):
        return None
    size = struct.unpack_from("<I", buf, off)[0]
    w = struct.unpack_from("<H", buf, off + 4)[0]
    h = struct.unpack_from("<H", buf, off + 6)[0]
    stride = struct.unpack_from("<H", buf, off + 8)[0]
    bpp = buf[off + 0x0A]
    flags = buf[off + 0x0B]
    colorbits = struct.unpack_from("<I", buf, off + 0x0C)[0]
    colorshift = struct.unpack_from("<I", buf, off + 0x10)[0]
    return dict(off=off, size=size, w=w, h=h, stride=stride, bpp=bpp,
                flags=flags, colorbits=colorbits, colorshift=colorshift)


def plausible(d, filesize):
    if d is None:
        return False
    if not (4 <= d["w"] <= 2048 and 4 <= d["h"] <= 1024):
        return False
    if d["bpp"] not in (8, 16, 24, 32):
        return False
    if not (0x14 <= d["size"] <= min(filesize, 4_000_000)):
        return False
    # colorbits: ненулевой, ниблы каналов <=8
    cb = d["colorbits"]
    if cb == 0:
        return False
    for k in range(8):
        if ((cb >> (k * 4)) & 0xF) > 8:
            return False
    # размер данных должен примерно соответствовать w*h (сжато меньше, несжато ~w*h*bpp/8)
    raw = d["w"] * d["h"] * d["bpp"] // 8
    datasz = d["size"] - 0x14
    if not (raw // 20 <= datasz <= raw + 64):  # сжатие до ~20x или несжато
        return False
    return True


def try_decode_rlad(buf, data_off, w, h):
    """Пробует RLAD-декод; возвращает (pixels, quality) или (None,0)."""
    try:
        bs = BitStream(buf[data_off:data_off + max(4096, w * h)])
        pixels = []
        total = w * h
        guard = 0
        while len(pixels) < total and bs.pos + 48 <= bs.nbits and guard < total:
            pk, cbpc, bias = decode_packet(bs, CNT_RLAD)
            # признак мусора: cbpc>8 быть не может (ниббл), но проверим осмысленность
            if any(c > 8 for c in cbpc):
                return None, 0
            pixels.extend(pk[:min(CNT_RLAD, total - len(pixels))])
            guard += CNT_RLAD
        if len(pixels) < total:
            return None, 0
        # качество: доля повторяющихся соседних строк (гладкость картинки)
        alpha = [p[3] for p in pixels]
        gray = [(p[0] + p[1] + p[2]) // 3 for p in pixels]
        chan = alpha if len(set(alpha)) > 1 else gray
        smooth = 0
        for r in range(min(h - 1, 100)):
            a = chan[r * w:(r + 1) * w]; b = chan[(r + 1) * w:(r + 2) * w]
            if len(b) < w:
                break
            if sum(1 for k in range(w) if abs(a[k] - b[k]) < 40) > w * 0.6:
                smooth += 1
        q = smooth / max(1, min(h - 1, 100))
        return pixels, q
    except Exception:
        return None, 0


def main():
    buf = open(DUMP, "rb").read()
    print("scan %s (%d MB)" % (DUMP, len(buf) // 1048576))
    found = 0
    i = 0x180000
    step = 4
    hits = []
    while i < len(buf) - 0x14:
        d = parse_desc(buf, i)
        if plausible(d, len(buf)):
            comp = d["flags"] & 5
            data_off = i + 0x14
            if comp in (0, 1):  # RLAD
                px, q = try_decode_rlad(buf, data_off, d["w"], d["h"])
                if px and q > 0.5:
                    hits.append((q, d, px))
                    i += max(step, d["size"])
                    continue
        i += step
    hits.sort(key=lambda x: -x[0])
    print("found RLAD surfaces:", len(hits))
    for q, d, px in hits[:40]:
        img = Image.new("RGBA", (d["w"], d["h"]))
        img.putdata(px)
        fn = "%s/surf_%08X_%dx%d_q%.2f.png" % (OUT, d["off"], d["w"], d["h"], q)
        img.save(fn)
        found += 1
        print("  0x%08X %dx%d bpp=%d q=%.2f -> %s" % (d["off"], d["w"], d["h"], d["bpp"], q, fn))
    print("saved", found, "PNG in", OUT)


if __name__ == "__main__":
    main()
