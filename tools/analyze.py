#!/usr/bin/env python3
"""
Анализ дампов приборки Geely Coolray (Infineon SEMPER NOR S25HL512T, 2x64MB).
Только чтение. Запуск: python analyze.py [файл.bin]
"""
import sys, re, math, struct

def entropy(b):
    if not b:
        return 0.0
    counts = [0] * 256
    for x in b:
        counts[x] += 1
    e = 0.0
    length = len(b)
    for n in counts:
        if n:
            p = n / length
            e -= p * math.log2(p)
    return e

def entropy_map(data, block=65536):
    """Карта энтропии: '.'=стёрто(FF) '0'=нули '#'=сжато/шифр '+'=код/данные '-'=разреженно"""
    line = ""
    for i in range(0, len(data), block):
        blk = data[i:i + block]
        if blk.count(0xFF) > 0.98 * len(blk):
            line += "."
        elif blk.count(0x00) > 0.98 * len(blk):
            line += "0"
        else:
            e = entropy(blk)
            line += "#" if e > 7.5 else ("+" if e > 4 else "-")
    return line

def find_signatures(data):
    sigs = {
        b"\x00\x01\x00\x00": "sfnt(TTF)", b"OTTO": "OTF", b"ttcf": "TTC",
        b"\x89PNG": "PNG", b"\xff\xd8\xff": "JPEG", b"BM": "BMP",
        b"\x1f\x8b": "gzip", b"PK\x03\x04": "ZIP", b"\x28\xb5\x2f\xfd": "zstd",
        b"hsqs": "squashfs", b"UBI#": "UBI", b"\x7fELF": "ELF",
        b"KANZI": "Kanzi", b"KZB": "KZB", b"DDS ": "DDS", b"KTX ": "KTX",
    }
    out = {}
    for s, name in sigs.items():
        idx, start = [], 0
        while len(idx) < 8:
            i = data.find(s, start)
            if i < 0:
                break
            idx.append(i)
            start = i + 1
        if idx:
            out[name] = idx
    return out

def validate_sfnt(data, off):
    """Настоящий sfnt: numTables + осмысленные 4-байтовые теги таблиц."""
    if off + 12 > len(data):
        return None
    num = struct.unpack(">H", data[off + 4:off + 6])[0]
    if not (1 <= num <= 60):
        return None
    tags = []
    for i in range(min(num, 20)):
        p = off + 12 + i * 16
        tag = data[p:p + 4]
        if not all(32 <= c < 127 for c in tag):
            return None
        tags.append(tag.decode("latin1"))
    known = {"cmap", "glyf", "head", "CFF ", "name", "loca"}
    return (num, tags) if known & set(tags) else None

def ascii_strings(data, minlen=5):
    return [m.decode("latin1") for m in re.findall(rb"[\x20-\x7e]{%d,}" % minlen, data)]

def utf16_strings(data, minlen=4):
    return [m.decode("utf-16le", "replace")
            for m in re.findall(rb"(?:[\x20-\x7e]\x00){%d,}" % minlen, data)]

def main():
    fn = sys.argv[1] if len(sys.argv) > 1 else "Coolray_25_Dash_U17.bin"
    data = open(fn, "rb").read()
    print("Файл: %s  (%d МБ)" % (fn, len(data) // (1024 * 1024)))
    print("0xFF=%.1f%%  0x00=%.1f%%" % (
        100 * data.count(0xFF) / len(data), 100 * data.count(0x00) / len(data)))
    print("\nКарта энтропии (1 символ = 64 КБ):")
    print(entropy_map(data))
    print("\nСигнатуры форматов (первые смещения):")
    for name, idx in find_signatures(data).items():
        print("  %-10s %s" % (name, ", ".join("0x%X" % x for x in idx[:6])))
    print("\nВалидные шрифты sfnt:")
    found, start = 0, 0
    while found < 20:
        i = data.find(b"\x00\x01\x00\x00", start)
        if i < 0:
            break
        start = i + 1
        r = validate_sfnt(data, i)
        if r:
            print("  0x%08X numTables=%d %s" % (i, r[0], r[1][:10]))
            found += 1
    if not found:
        print("  (стандартных TTF/OTF нет — шрифты в проприетарном/битмап-формате)")
    a = ascii_strings(data)
    u = utf16_strings(data)
    print("\nСтроки: ASCII=%d  UTF-16LE=%d" % (len(a), len(u)))

if __name__ == "__main__":
    main()
