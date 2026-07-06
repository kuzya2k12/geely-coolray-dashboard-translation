#!/usr/bin/env python3
"""
Парсер surface-дескриптора Infineon Graphics Driver.

Структура восстановлена из дизассемблера utSurfLoadBitmapEx (sm_util.c.obj):
Заголовок = 20 байт (0x14), затем данные пикселей.

Смещение  Тип     Поле (по коду loadBitmapEx)
  +0x00    u32     data_size (полный размер записи; данные = size - 0x14)
  +0x04    u16     width      (attr WIDTH=1)
  +0x06    u16     height
  +0x08    u16     ? (attr 0x11) — вероятно compression/format-related
  +0x0A    u8      bitperpixel (attr BITPERPIXEL=8)
  +0x0B    u8      flags: биты color-format/compression; код проверяет &5, &0x1e,
                   старший бит (0x80) = есть палитра/CLUT
  +0x0C    u32     colorbits  (маска 0x0F0F0F0F = ширины каналов R,G,B,A по 4 бита нибблами)
                   >>4 & 0x0F0F0F0F = colorshift (attr COLORSHIFT=0xC)
  +0x10    u32     stride (attr STRIDE=0xA), байт на строку
  +0x14    ...     данные пикселей (или CLUT-заголовок, если flags&0x80)

flags &5 == compression-ish selector в loadBitmapEx:
  0 -> uncompressed path, 1 -> RLC/RLD, 4/5 -> другие ветки.
"""
from __future__ import annotations
import struct

HDR = 0x14


def parse_descriptor(buf: bytes, off: int):
    """Пробует прочитать surface-дескриптор по смещению off. Возвращает dict или None."""
    if off + HDR > len(buf):
        return None
    size = struct.unpack_from("<I", buf, off + 0)[0]
    width = struct.unpack_from("<H", buf, off + 4)[0]
    height = struct.unpack_from("<H", buf, off + 6)[0]
    a8 = struct.unpack_from("<H", buf, off + 8)[0]
    bpp = buf[off + 0x0A]
    flags = buf[off + 0x0B]
    colorbits = struct.unpack_from("<I", buf, off + 0x0C)[0]
    stride = struct.unpack_from("<I", buf, off + 0x10)[0]
    return dict(off=off, size=size, width=width, height=height, a8=a8,
                bpp=bpp, flags=flags, colorbits=colorbits, stride=stride)


def is_plausible(d, filesize):
    """Эвристика правдоподобности дескриптора изображения приборки."""
    if d is None:
        return False
    if not (1 <= d["width"] <= 4096 and 1 <= d["height"] <= 1920):
        return False
    if d["bpp"] not in (1, 2, 4, 8, 16, 24, 32):
        return False
    # stride должен согласовываться с width*bpp (с округлением вверх до байта/выравнивания)
    min_stride = (d["width"] * d["bpp"] + 7) // 8
    if not (min_stride <= d["stride"] <= min_stride + 64):
        # для сжатых surface stride может быть 0 или иным — допустим 0
        if d["stride"] != 0:
            return False
    # size разумный
    if not (HDR <= d["size"] <= filesize):
        return False
    # colorbits: каждый ниббл 0..8
    cb = d["colorbits"]
    for k in range(8):
        if ((cb >> (k * 4)) & 0xF) > 8:
            return False
    return True


def scan(buf, step=2, limit=None):
    """Сканирует весь буфер, возвращает список правдоподобных дескрипторов."""
    out = []
    n = len(buf)
    end = limit or n
    i = 0
    while i < end - HDR:
        d = parse_descriptor(buf, i)
        if is_plausible(d, n):
            out.append(d)
        i += step
    return out
