#!/usr/bin/env python3
"""
Извлекает объектный файл ut_rlc.c.obj из статической либы Infineon (ar-архив)
и дизассемблирует функции RLD (utRldEncode / utRldWriteBits) через capstone.
Цель — восстановить точную битовую логику RLD, чтобы написать декодер.
"""
import sys, struct, re
sys.stdout.reconfigure(encoding="utf-8")
from capstone import Cs, CS_ARCH_ARM, CS_MODE_THUMB, CS_MODE_LITTLE_ENDIAN

LIB = sys.argv[1] if len(sys.argv) > 1 else "../infineon-gfx/libutil_cm7.a"

def parse_ar(path):
    """Разбирает System V ar-архив -> {имя: bytes}. Поддерживает длинные имена (//)."""
    data = open(path, "rb").read()
    assert data[:8] == b"!<arch>\n", "не ar-архив"
    pos = 8
    members = {}
    longnames = b""
    while pos + 60 <= len(data):
        hdr = data[pos:pos + 60]
        name = hdr[0:16].decode("latin1").rstrip()
        size = int(hdr[48:58].decode("latin1").strip())
        body = data[pos + 60: pos + 60 + size]
        pos += 60 + size
        if pos & 1:
            pos += 1
        if name == "//":
            longnames = body
            continue
        if name.startswith("/") and name[1:].isdigit():
            off = int(name[1:])
            end = longnames.find(b"\n", off)
            name = longnames[off:end].decode("latin1").rstrip("/")
        else:
            name = name.rstrip("/")
        members[name] = body
    return members

def find_elf_symbols(obj):
    """Мини-парсер ELF: вернуть {имя_символа: (offset_в_.text, size)} для .text."""
    if obj[:4] != b"\x7fELF":
        return {}, None, 0
    is64 = obj[4] == 2
    le = obj[5] == 1
    end = "<" if le else ">"
    if is64:
        e_shoff = struct.unpack(end + "Q", obj[0x28:0x30])[0]
        e_shentsize = struct.unpack(end + "H", obj[0x3a:0x3c])[0]
        e_shnum = struct.unpack(end + "H", obj[0x3c:0x3e])[0]
        e_shstrndx = struct.unpack(end + "H", obj[0x3e:0x40])[0]
    else:
        e_shoff = struct.unpack(end + "I", obj[0x20:0x24])[0]
        e_shentsize = struct.unpack(end + "H", obj[0x2e:0x30])[0]
        e_shnum = struct.unpack(end + "H", obj[0x30:0x32])[0]
        e_shstrndx = struct.unpack(end + "H", obj[0x32:0x34])[0]
    secs = []
    for i in range(e_shnum):
        b = obj[e_shoff + i * e_shentsize: e_shoff + (i + 1) * e_shentsize]
        if is64:
            sh_name, sh_type, sh_flags, sh_addr, sh_offset, sh_size, sh_link, sh_info = \
                struct.unpack(end + "IIQQQQII", b[:40])
            sh_entsize = struct.unpack(end + "Q", b[56:64])[0]
        else:
            sh_name, sh_type, sh_flags, sh_addr, sh_offset, sh_size, sh_link, sh_info, sh_align, sh_entsize = \
                struct.unpack(end + "IIIIIIIIII", b[:40])
        secs.append(dict(name=sh_name, type=sh_type, off=sh_offset, size=sh_size,
                         link=sh_link, info=sh_info, entsize=sh_entsize, addr=sh_addr))
    shstr = obj[secs[e_shstrndx]["off"]: secs[e_shstrndx]["off"] + secs[e_shstrndx]["size"]]
    def secname(n):
        e = shstr.find(b"\0", n)
        return shstr[n:e].decode("latin1")
    text_idx = None
    for i, s in enumerate(secs):
        if secname(s["name"]) == ".text":
            text_idx = i
    # symbol table
    syms = {}
    for s in secs:
        if s["type"] == 2:  # SHT_SYMTAB
            strtab = secs[s["link"]]
            strdata = obj[strtab["off"]: strtab["off"] + strtab["size"]]
            n = s["size"] // s["entsize"]
            for k in range(n):
                e = obj[s["off"] + k * s["entsize"]: s["off"] + (k + 1) * s["entsize"]]
                if is64:
                    st_name = struct.unpack(end + "I", e[0:4])[0]
                    st_shndx = struct.unpack(end + "H", e[6:8])[0]
                    st_value = struct.unpack(end + "Q", e[8:16])[0]
                    st_size = struct.unpack(end + "Q", e[16:24])[0]
                else:
                    st_name = struct.unpack(end + "I", e[0:4])[0]
                    st_value = struct.unpack(end + "I", e[4:8])[0]
                    st_size = struct.unpack(end + "I", e[8:12])[0]
                    st_shndx = struct.unpack(end + "H", e[14:16])[0]
                nm_end = strdata.find(b"\0", st_name)
                nm = strdata[st_name:nm_end].decode("latin1")
                if nm and st_shndx == text_idx:
                    syms[nm] = (st_value, st_size)
    text = None
    if text_idx is not None:
        t = secs[text_idx]
        text = obj[t["off"]: t["off"] + t["size"]]
    return syms, text, (text_idx is not None)

def main():
    members = parse_ar(LIB)
    obj_name = next((n for n in members if "rlc" in n.lower() and (".o" in n or ".obj" in n)), None)
    print("объекты RLC в архиве:", [n for n in members if "rlc" in n.lower()])
    if not obj_name:
        print("ut_rlc объект не найден")
        return
    obj = members[obj_name]
    print("объект:", obj_name, "size", len(obj), "magic", obj[:4])
    syms, text, has = find_elf_symbols(obj)
    print("символы в .text:", list(syms.keys()))
    if not text:
        return
    md = Cs(CS_ARCH_ARM, CS_MODE_THUMB | CS_MODE_LITTLE_ENDIAN)
    for name, (val, size) in sorted(syms.items(), key=lambda x: x[1][0]):
        if size == 0:
            continue
        addr = val & ~1  # thumb bit
        code = text[addr:addr + size]
        print("\n===== %s @0x%X size=%d =====" % (name, addr, size))
        for ins in md.disasm(code, addr):
            print("  0x%04x: %-8s %s" % (ins.address, ins.mnemonic, ins.op_str))

if __name__ == "__main__":
    main()
