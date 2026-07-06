#!/usr/bin/env python3
"""
Детектор RLD-изображений: сканирует дамп, на каждом смещении пробует
декодировать RLD и оценивает, похож ли результат на реальную графику.

Поскольку в NOR нет оглавления (адреса surface зашиты в код MCU),
единственный надёжный признак surface — самодостаточный: RLD-поток,
который декодируется чисто и даёт изображение с ровными краями/фоном.

Запуск: python scan_rld.py <dump.bin> [start_hex] [end_hex]
Пишет находки в output/rld_hits.txt
"""
import sys, os
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "geely_cluster"))
from rlc_decoder import decode_rld

DUMP = sys.argv[1] if len(sys.argv) > 1 else "../Coolray_25_Dash_U17.bin"
START = int(sys.argv[2], 16) if len(sys.argv) > 2 else 0x180000
END = int(sys.argv[3], 16) if len(sys.argv) > 3 else 0x3450000


def image_quality(px, w):
    """Оценка качества как изображения: доля строк с малым отличием от соседней
    + доминирование фонового значения. Возвращает 0..1."""
    if len(px) < w * 8:
        return 0.0
    from collections import Counter
    c = Counter(px)
    bg = c.most_common(1)[0][1] / len(px)
    h = len(px) // w
    smooth_rows = 0
    for r in range(min(h - 1, 200)):
        a = px[r * w:(r + 1) * w]
        b = px[(r + 1) * w:(r + 2) * w]
        if len(b) < w:
            break
        diff = sum(1 for k in range(w) if a[k] != b[k])
        if diff < w * 0.3:  # <30% пикселей меняется = гладкая строка
            smooth_rows += 1
    smoothness = smooth_rows / max(1, min(h - 1, 200))
    # хорошее изображение: заметный фон (0.3..0.95) и гладкие строки
    if not (0.25 < bg < 0.97):
        return 0.0
    return smoothness * bg


def main():
    data = open(DUMP, "rb").read()
    hits = []
    step = 512  # грубый проход; вокруг находок уточним
    off = START
    while off < min(END, len(data)):
        best_here = 0.0
        best_cfg = None
        for bpp in (4, 8):
            for w in (16, 24, 32, 48, 64, 96, 128):
                px, bits, ok = decode_rld(data[off:off + 60000], w * 48, bpp)
                if not ok:
                    continue
                q = image_quality(px, w)
                ratio = (w * 48 * bpp) / bits if bits else 0
                # требуем реальное сжатие (ratio>1.5) и качество
                if q > best_here and ratio > 1.3:
                    best_here = q
                    best_cfg = (bpp, w, round(ratio, 2))
        if best_here > 0.45:
            hits.append((round(best_here, 3), off, best_cfg))
        off += step
    hits.sort(reverse=True)
    with open("output/rld_hits.txt", "w", encoding="utf-8") as f:
        f.write("quality  offset      cfg(bpp,w,ratio)\n")
        for q, o, cfg in hits[:200]:
            f.write("%.3f   0x%08X  %s\n" % (q, o, cfg))
    print("найдено кандидатов:", len(hits))
    for q, o, cfg in hits[:30]:
        print("  q=%.3f @0x%08X %s" % (q, o, cfg))


if __name__ == "__main__":
    main()
