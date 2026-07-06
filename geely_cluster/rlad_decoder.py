#!/usr/bin/env python3
"""
Декодер RLAD (Run-Length Adaptive Dithering) — формат Infineon TRAVEO II.

Формат восстановлен методом oracle (rlad-encoder.exe) — см. oracle.py.
Проверен: decode(encode(x)) == x на контролируемых входах.

СТРУКТУРА (для RGBA8888, bpc=8 на канал, пакет = 8 пикселей):
Пакет начинается с 6-байтового заголовка:
  байт 0: nibble low = cbpc[R], nibble high = cbpc[G]
  байт 1: nibble low = cbpc[B], nibble high = cbpc[A]
  байт 2: bias[R]  (базовое значение канала R)
  байт 3: bias[G]
  байт 4: bias[B]
  байт 5: bias[A]
затем для каждого канала c (R,G,B,A) по очереди, ЕСЛИ cbpc[c] > 0:
  8 значений по cbpc[c] бит (offset), lsb-first в 32-битных словах.
  Итоговое значение канала = bias[c] + offset (для lossless RLA);
  для RLAD (lossy) offset квантуется и добавляется dithering — но при
  cbpc == точной ширине это lossless.

Данные битов читаются как единый BitStream: 32-битные слова LE, биты lsb->msb.
ВАЖНО: заголовок (cbpc+bias, 6 байт = 48 бит) и offset-биты идут в ОДНОМ
битовом потоке подряд. Ниже — точная модель, сверенная с оракулом.
"""
from __future__ import annotations
import struct

NUM_C = 4  # R, G, B, A
CNT_RLAD = 8  # пикселей в пакете


class BitStream:
    """32-битные слова LE, чтение бит lsb->msb (как RLAD::BitStream)."""

    def __init__(self, data: bytes):
        self.data = data
        self.pos = 0
        self.nbits = (len(data) // 4) * 32

    def read(self, bits: int) -> int:
        v = 0
        for i in range(bits):
            bp = self.pos + i
            wi = bp >> 5
            bo = bp & 31
            byte = wi * 4 + (bo >> 3)
            bit = (self.data[byte] >> (bo & 7)) & 1 if byte < len(self.data) else 0
            v |= bit << i
        self.pos += bits
        return v

    def align_byte(self):
        if self.pos & 7:
            self.pos += 8 - (self.pos & 7)


def decode_packet(bs: BitStream, npix: int = CNT_RLAD):
    """Декодирует один RLAD-пакет из npix пикселей. Возвращает список (r,g,b,a)."""
    cbpc = [0] * NUM_C
    # 2 байта cbpc (4 ниббла)
    b0 = bs.read(8)
    b1 = bs.read(8)
    cbpc[0] = b0 & 0xF          # R
    cbpc[1] = (b0 >> 4) & 0xF   # G
    cbpc[2] = b1 & 0xF          # B
    cbpc[3] = (b1 >> 4) & 0xF   # A
    # 4 байта bias
    bias = [bs.read(8) for _ in range(NUM_C)]
    # offset-значения по каналам
    chans = [[bias[c]] * npix for c in range(NUM_C)]
    for c in range(NUM_C):
        if cbpc[c] > 0:
            for k in range(npix):
                off = bs.read(cbpc[c])
                chans[c][k] = (bias[c] + off) & 0xFF
    pixels = [(chans[0][k], chans[1][k], chans[2][k], chans[3][k]) for k in range(npix)]
    return pixels, cbpc, bias


def decode_image(data: bytes, width: int, height: int):
    """Декодирует RLAD-поток целого изображения в список (r,g,b,a) длиной w*h.
    Пакеты идут построчно, по 8 пикселей; последний в строке может быть короче."""
    bs = BitStream(data)
    pixels = []
    total = width * height
    # RLAD пакует построчно; но по нашим тестам поток непрерывный по 8 px.
    while len(pixels) < total and bs.pos + 48 <= bs.nbits:
        n = min(CNT_RLAD, total - len(pixels))
        pk, _, _ = decode_packet(bs, CNT_RLAD)
        pixels.extend(pk[:n])
    return pixels[:total]


# --------------------------------------------------------------------------
# A8 (одноканальный alpha) — формат ГЛИФОВ ШРИФТА
#
# Структура A8-RLAD пакета (8 пикселей), восстановлена методом oracle
# (ResourceGenerator.exe ... -foA8 -cRLAD) и проверена на тест-глифе:
#   4 бита  : cbpc     (бит на значение alpha; 0 = все значения = bias)
#   8 бит   : bias     (базовое значение alpha)
#   8 × cbpc: offset'ы (значение = bias + offset), только если cbpc > 0
# Биты — единый поток из 32-битных слов LE, lsb->msb.
# Отличие от RGBA8888: один канал (4-битный cbpc + 8-битный bias),
# а не 4 канала.
# --------------------------------------------------------------------------

def decode_a8_packet(bs: BitStream, npix: int = CNT_RLAD):
    """Декодирует один A8-пакет из npix значений alpha (0..255)."""
    cbpc = bs.read(4)
    bias = bs.read(8)
    out = []
    for _ in range(npix):
        off = bs.read(cbpc) if cbpc > 0 else 0
        out.append((bias + off) & 0xFF)
    return out, cbpc, bias


def decode_a8_image(data: bytes, width: int, height: int):
    """Декодирует A8-RLAD-поток в список значений alpha (0..255) длиной w*h.
    Это формат глифов шрифта приборки.

    ВАЖНО: RLAD пакует ПОСТРОЧНО. Каждая строка начинается с нового пакета; пакеты
    НЕ переходят границу строки. Последний пакет строки покрывает остаток (width % 8)
    пикселей. (Подтверждено oracle-диффом на ширинах, не кратных 8.)
    """
    bs = BitStream(data)
    alpha = []
    for _y in range(height):
        rem = width
        while rem > 0 and bs.pos + 12 <= bs.nbits:
            n = min(CNT_RLAD, rem)
            cbpc = bs.read(4)
            bias = bs.read(8)
            for _k in range(n):
                off = bs.read(cbpc) if cbpc > 0 else 0
                alpha.append((bias + off) & 0xFF)
            rem -= n
    return alpha[:width * height]
