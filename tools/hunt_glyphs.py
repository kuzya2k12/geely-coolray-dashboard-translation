#!/usr/bin/env python3
"""
Финальный детектор атласа глифов в дампе приборки.

Основан на отпечатке РЕАЛЬНОГО глифа (получен через oracle):
глифы = A8 alpha-битмапы, поэтому RLAD-пакеты имеют cbpc вида (0,0,0,N) —
RGB-каналы нулевые (bias=0, cbpc=0), значим только alpha. Случайные данные
такого паттерна не дают.

Плюс жёсткая 2D-проверка: декодированная картинка должна быть связной
и по горизонтали, и по вертикали (шум это подделать не может).

Запуск: python hunt_glyphs.py <dump.bin> [start_hex] [end_hex]
"""
import sys, os
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "geely_cluster"))
from rlad_decoder import BitStream, decode_packet, CNT_RLAD


def scan_stream(data, off, max_packets=256):
    """Декодирует поток пакетов с off. Возвращает (pixels, cbpc_list) или (None,None)."""
    bs = BitStream(data[off:off + max_packets * 40 + 64])
    pixels = []
    cbpc_list = []
    for _ in range(max_packets):
        if bs.pos + 48 > bs.nbits:
            break
        try:
            pk, cb, bi = decode_packet(bs, CNT_RLAD)
        except Exception:
            break
        if any(c > 8 for c in cb):
            break
        cbpc_list.append(tuple(cb))
        pixels.extend(pk)
    return pixels, cbpc_list


def glyph_fingerprint(cbpc_list):
    """Доля пакетов с alpha-only паттерном (0,0,0,*) — признак A8-глифов."""
    if len(cbpc_list) < 8:
        return 0.0
    a_only = sum(1 for c in cbpc_list if c[0] == 0 and c[1] == 0 and c[2] == 0)
    return a_only / len(cbpc_list)


def twod_coherence(pixels, w):
    """Жёсткая 2D-проверка: связность по горизонтали И вертикали.
    Возвращает 0..1. Использует alpha-канал."""
    if len(pixels) < w * 8:
        return 0.0
    alpha = [p[3] for p in pixels]
    h = len(alpha) // w
    if h < 4:
        return 0.0
    # горизонтальная гладкость: соседи в строке похожи
    hs = 0; hn = 0
    for r in range(min(h, 200)):
        row = alpha[r * w:(r + 1) * w]
        for k in range(len(row) - 1):
            if abs(row[k] - row[k + 1]) < 40:
                hs += 1
            hn += 1
    # вертикальная гладкость: соседи в столбце похожи
    vs = 0; vn = 0
    for r in range(min(h - 1, 200)):
        a = alpha[r * w:(r + 1) * w]; b = alpha[(r + 1) * w:(r + 2) * w]
        for k in range(min(len(a), len(b))):
            if abs(a[k] - b[k]) < 40:
                vs += 1
            vn += 1
    hcoh = hs / hn if hn else 0
    vcoh = vs / vn if vn else 0
    # не должно быть полностью константным (иначе это заливка/мусор)
    var = len(set(alpha[:min(len(alpha), 2000)]))
    if var < 3:
        return 0.0
    # требуем И горизонтальную И вертикальную связность
    return min(hcoh, vcoh)


def best_width(pixels, wrange=range(8, 128)):
    """Подбирает ширину по максимуму вертикальной связности."""
    alpha = [p[3] for p in pixels]
    best = (0.0, 0)
    for w in wrange:
        h = len(alpha) // w
        if h < 4:
            continue
        vs = vn = 0
        for r in range(min(h - 1, 100)):
            a = alpha[r * w:(r + 1) * w]; b = alpha[(r + 1) * w:(r + 2) * w]
            for k in range(min(len(a), len(b))):
                if abs(a[k] - b[k]) < 30:
                    vs += 1
                vn += 1
        c = vs / vn if vn else 0
        if c > best[0]:
            best = (c, w)
    return best[1]


def main():
    dump = sys.argv[1] if len(sys.argv) > 1 else "../Coolray_25_Dash_U17.bin"
    start = int(sys.argv[2], 16) if len(sys.argv) > 2 else 0x180000
    end = int(sys.argv[3], 16) if len(sys.argv) > 3 else 0x3450000
    data = open(dump, "rb").read()
    end = min(end, len(data))
    print("hunt glyphs in %s  [0x%X..0x%X]" % (dump, start, end))
    hits = []
    step = 1024
    off = start
    while off < end:
        pixels, cbpc_list = scan_stream(data, off, 128)
        if pixels and len(cbpc_list) >= 16:
            fp = glyph_fingerprint(cbpc_list)
            if fp > 0.5:  # alpha-only packets dominate — glyph-like
                w = best_width(pixels)
                coh = twod_coherence(pixels, w) if w else 0
                if coh > 0.55:
                    hits.append((round(coh, 3), round(fp, 2), off, w))
        off += step
    hits.sort(reverse=True)
    print("glyph-atlas candidates:", len(hits))
    with open("output/glyph_hits.txt", "w", encoding="utf-8") as f:
        for coh, fp, o, w in hits:
            f.write("coh=%.3f fp=%.2f @0x%08X w=%d\n" % (coh, fp, o, w))
    for coh, fp, o, w in hits[:30]:
        print("  coh=%.3f fp=%.2f @0x%08X w=%d" % (coh, fp, o, w))
    return hits


if __name__ == "__main__":
    main()
