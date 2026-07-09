#!/usr/bin/env python3
"""
Обзорная визуализация всего NOR-дампа приборки: увидеть структуру секторов целиком
и найти кандидатов в "атлас/фон" (большие ровные зоны) прежде, чем рендерить прицельно.

Три режима:

1) overview  — вся флешка одной картинкой. Каждый пиксель = блок из BLOCK байт,
   цвет кодирует тип содержимого:
     чёрный   = стёрто (0xFF) или нули (пустой сектор)
     синий    = низкая энтропия (<4) — РОВНЫЕ данные, кандидат в несжатый фон/атлас
     зелёный  = средняя (4..7) — вероятно RLAD-сжатая графика / структура
     красный  = высокая (>7) — сильно сжато / случайно
   Так сразу видно раскладку: где пусто, где данные, где возможный несжатый атлас.

2) raw       — прямоугольный участок как СЫРЫЕ байты в grayscale (1 байт = 1 пиксель)
   при заданной ширине. Показывает визуальную структуру: границы блоков, регулярные
   сетки (глифы), ровные заливки (фон). Не декодирует — только «как лежат байты».

3) sectors   — печатает список секторов (границы по смене типа содержимого) с
   энтропией — готовые адреса, чтобы затем прицельно смотреть raw/декодером.

Запуск:
  python sector_map.py overview Coolray_25_Dash_U17.bin
  python sector_map.py raw      Coolray_25_Dash_U17.bin 0x180000 1MB 1024
  python sector_map.py sectors  Coolray_25_Dash_U17.bin
"""
import sys, os, math

sys.path.insert(0, os.path.dirname(__file__))
try:
    from PIL import Image
except ImportError:
    print("Нужен Pillow: pip install pillow")
    sys.exit(1)

OUT = os.path.join(os.path.dirname(__file__), "..", "output", "sector_map")


def parse_size(s):
    s = s.strip().upper()
    mult = 1
    if s.endswith("KB"):
        mult, s = 1024, s[:-2]
    elif s.endswith("MB"):
        mult, s = 1024 * 1024, s[:-2]
    elif s.endswith("B"):
        s = s[:-1]
    return int(float(s) * mult)


def entropy(b):
    if not b:
        return 0.0
    counts = [0] * 256
    for x in b:
        counts[x] += 1
    e, n = 0.0, len(b)
    for c in counts:
        if c:
            p = c / n
            e -= p * math.log2(p)
    return e


def block_class(blk):
    """Вернуть (тип, энтропия). тип: 'empty' 'flat' 'mid' 'high'."""
    ln = len(blk)
    if blk.count(0xFF) > 0.98 * ln or blk.count(0x00) > 0.98 * ln:
        return "empty", 0.0
    e = entropy(blk)
    if e < 4.0:
        return "flat", e
    if e <= 7.0:
        return "mid", e
    return "high", e


COLORS = {
    "empty": (0, 0, 0),
    "flat": (60, 120, 255),    # синий — кандидат в несжатый фон/атлас
    "mid": (60, 200, 80),      # зелёный — вероятно RLAD-графика/структура
    "high": (230, 70, 70),     # красный — сильно сжато/случайно
}


def cmd_overview(path, block=4096, width=512):
    data = open(path, "rb").read()
    nblocks = (len(data) + block - 1) // block
    height = (nblocks + width - 1) // width
    img = Image.new("RGB", (width, height), (20, 20, 20))
    px = img.load()
    counts = {"empty": 0, "flat": 0, "mid": 0, "high": 0}
    for i in range(nblocks):
        cls, _ = block_class(data[i * block:(i + 1) * block])
        counts[cls] += 1
        px[i % width, i // width] = COLORS[cls]
    os.makedirs(OUT, exist_ok=True)
    name = os.path.join(OUT, "overview_%s_b%d.png" % (os.path.basename(path), block))
    # увеличим x4 для читаемости
    img.resize((width * 2, height * 2), Image.NEAREST).save(name)
    total = sum(counts.values())
    print("Обзор %s: %d блоков по %d Б, %dx%d px" % (path, nblocks, block, width, height))
    for k in ("empty", "flat", "mid", "high"):
        print("  %-6s %7d блоков  %5.1f%%  (%s)"
              % (k, counts[k], 100 * counts[k] / total,
                 {"empty": "пусто", "flat": "РОВНОЕ<4 — кандидат в фон/атлас",
                  "mid": "средняя 4..7 — RLAD?", "high": "высокая>7 — сжато"}[k]))
    print("PNG:", name)
    print("Синие зоны = ровные данные. Если крупный несжатый атлас есть — он тут синим.")


def cmd_raw(path, off, size, width, fmt="gray8"):
    with open(path, "rb") as f:
        f.seek(off)
        data = f.read(size)
    os.makedirs(OUT, exist_ok=True)
    if fmt == "gray8":
        h = len(data) // width
        img = Image.frombytes("L", (width, h), bytes(data[:width * h]))
    elif fmt == "bits":  # 1 бит = 1 пиксель (полезно для A1/масок)
        bits = bytearray()
        for b in data:
            for k in range(7, -1, -1):
                bits.append(255 if (b >> k) & 1 else 0)
        h = len(bits) // width
        img = Image.frombytes("L", (width, h), bytes(bits[:width * h]))
    else:
        raise ValueError("fmt: gray8 | bits")
    name = os.path.join(OUT, "raw_%s_%08X_w%d_%s.png"
                        % (os.path.basename(path), off, width, fmt))
    img.save(name)
    print("Сырой рендер 0x%08X..0x%08X ширина=%d fmt=%s -> %dx%d"
          % (off, off + len(data), width, fmt, width, img.height))
    print("PNG:", name)


def cmd_sectors(path, block=65536):
    data = open(path, "rb").read()
    nblocks = (len(data) + block - 1) // block
    runs = []  # (start_block, cls)
    prev = None
    for i in range(nblocks):
        cls, _ = block_class(data[i * block:(i + 1) * block])
        if cls != prev:
            runs.append([i, cls])
            prev = cls
    print("Сектора %s (блок=%d КБ, границы по смене типа):" % (path, block // 1024))
    print("  %-12s %-12s %-8s %s" % ("start", "end", "size", "тип"))
    for j, (start, cls) in enumerate(runs):
        end = runs[j + 1][0] if j + 1 < len(runs) else nblocks
        a, b = start * block, end * block
        print("  0x%08X   0x%08X   %6.2fMB  %s"
              % (a, b, (b - a) / 1048576, cls))


def main():
    if len(sys.argv) < 3:
        print(__doc__)
        return
    cmd, path = sys.argv[1], sys.argv[2]
    if cmd == "overview":
        block = parse_size(sys.argv[3]) if len(sys.argv) > 3 else 4096
        cmd_overview(path, block=block)
    elif cmd == "raw":
        off = int(sys.argv[3], 16)
        size = parse_size(sys.argv[4])
        width = int(sys.argv[5]) if len(sys.argv) > 5 else 1024
        fmt = sys.argv[6] if len(sys.argv) > 6 else "gray8"
        cmd_raw(path, off, size, width, fmt)
    elif cmd == "sectors":
        cmd_sectors(path)
    else:
        print(__doc__)


if __name__ == "__main__":
    main()
