#!/usr/bin/env python3
"""
Декодер RLC/RLD (Run-Length) формата Infineon Graphics Driver.

Формат восстановлен из дизассемблера utRldEncode / utRldWriteBits
(libutil_cm7.a, см. ../output/rlc_disasm.txt):

- Поток RLD = последовательность 8-битных ТОКЕНОВ, упакованных в 32-битные
  слова в порядке бит lsb->msb (little-endian bitstream).
- Токен T:
    * если (T & 0x80) == 0  -> RUN: следующий 1 пиксель повторяется (T & 0x7F)+1 раз
    * если (T & 0x80) != 0  -> LITERAL: далее идут ((T & 0x7F)+1) пикселей подряд
  (счётчик ограничен 128 = MAX_CNT_RL)
- Пиксель = dataBpp бит (1,2,4,8,16,24,32), тоже из битстрима lsb->msb.
- Декодирование останавливается, когда получено width*height пикселей.
  (Размер задаётся снаружи — в потоке его нет; хвост дополнен нулевыми битами.)
"""
from __future__ import annotations


class BitReader:
    """Читает биты из потока 32-битных слов, lsb->msb внутри слова (LE)."""

    def __init__(self, data: bytes, word_le: bool = True):
        # поток адресуется словами по 32 бита
        self.data = data
        self.bitpos = 0
        self.nbits = len(data) * 8

    def read(self, bits: int) -> int:
        """Прочитать `bits` бит (как в utRldWriteBits: слово 32b, lsb->msb)."""
        val = 0
        for i in range(bits):
            bp = self.bitpos + i
            word_idx = bp >> 5
            bit_in_word = bp & 31
            byte_idx = word_idx * 4 + (bit_in_word >> 3)
            if byte_idx >= len(self.data):
                bit = 0
            else:
                bit = (self.data[byte_idx] >> (bit_in_word & 7)) & 1
            val |= bit << i
        self.bitpos += bits
        return val

    def eof(self) -> bool:
        return self.bitpos >= self.nbits


def decode_rld(data: bytes, num_pixels: int, bpp: int, max_tokens: int = 10_000_000):
    """
    Декодирует RLD-поток в список значений пикселей (по bpp бит каждый).
    Возвращает (pixels, bits_consumed, ok).
    ok=False если поток кончился раньше, чем набрано num_pixels.
    """
    br = BitReader(data)
    pixels = []
    tokens = 0
    while len(pixels) < num_pixels and tokens < max_tokens:
        if br.bitpos + 8 > br.nbits:
            return pixels, br.bitpos, False
        token = br.read(8)
        count = (token & 0x7F) + 1
        if token & 0x80:  # LITERAL: count пикселей подряд
            for _ in range(count):
                if len(pixels) >= num_pixels:
                    break
                pixels.append(br.read(bpp))
        else:  # RUN: 1 пиксель, повторить count раз
            v = br.read(bpp)
            pixels.extend([v] * min(count, num_pixels - len(pixels)))
        tokens += 1
    return pixels, br.bitpos, len(pixels) >= num_pixels


def score_decoding(pixels, bpp) -> float:
    """
    Оценка «похоже ли на осмысленную графику»: у настоящего глиф-атласа/картинки
    много повторов (фон) и ограниченный набор значений. Возвращает 0..1 (выше=лучше).
    """
    if not pixels:
        return 0.0
    from collections import Counter
    c = Counter(pixels)
    distinct = len(c)
    top = c.most_common(1)[0][1]
    # доля самого частого значения (фон); у графики фон доминирует
    bg_ratio = top / len(pixels)
    # у 4bpp максимум 16 значений, у 8bpp — 256; графика использует не все
    maxv = (1 << bpp)
    fill = distinct / maxv
    # хороший признак: заметный фон (0.2..0.95) и не все значения заняты
    return bg_ratio * (1.0 - abs(fill - 0.5))
