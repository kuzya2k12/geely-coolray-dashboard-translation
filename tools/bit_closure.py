#!/usr/bin/env python3
"""
Эксперимент "замыкание битов": привязать ширину/высоту A8-глифа к РЕАЛЬНОЙ длине
ресурса, а не гадать вслепую.

Идея: границы ресурсов берём из diff двух чипов (места "идентично↔различается" в
общей секции). Для куска длиной L байт правильные (W,H) при построчном RLAD-декоде
должны потребить ~L*8 бит с маленьким остатком (ресурс "замыкается" по битам).
Это физическое ограничение, которого не было в слепом переборе ширин.

Запуск: python bit_closure.py [U17.bin] [U18.bin]
"""
import sys

A = sys.argv[1] if len(sys.argv) > 1 else "Coolray_25_Dash_U17.bin"
B = sys.argv[2] if len(sys.argv) > 2 else "Coolray_25_Dash_U18.bin"
# Общая секция 5A-9E-64: U17@0xD7C782, U18@0xD51C33
SEC_A, SEC_B, SCAN = 0xD7C782, 0xD51C33, 0x100000

a = open(A, "rb").read()
b = open(B, "rb").read()


def decode_a8_used(data, width, height, CNT=8):
    """Построчный A8-декод; возвращает (декодировано_пикселей, использовано_бит)."""
    val = int.from_bytes(data, "little")
    nbits = len(data) * 8
    pos = 0
    count = 0
    for _y in range(height):
        rem = width
        while rem > 0:
            n = CNT if rem >= CNT else rem
            if pos + 12 > nbits:
                return count, pos
            c = (val >> pos) & 0xF
            pos += 4
            pos += 8  # bias
            for _k in range(n):
                if c > 0:
                    if pos + c > nbits:
                        return count, pos
                    pos += c
                count += 1
            rem -= n
    return count, pos


def boundaries(oa, ob, maxlen):
    bnds = []
    prev = None
    for k in range(maxlen):
        eq = a[oa + k] == b[ob + k]
        if eq != prev:
            bnds.append((oa + k, eq))
            prev = eq
    return bnds


def main():
    bnds = boundaries(SEC_A, SEC_B, SCAN)
    chunks = []
    for i in range(len(bnds) - 1):
        st = bnds[i][0]
        L = bnds[i + 1][0] - st
        if 40 <= L <= 1500:
            chunks.append((st, L, bnds[i][1]))
    print("resource chunks (40..1500B) from diff:", len(chunks), flush=True)

    hits = []
    for idx, (st, L, shared) in enumerate(chunks):
        body = a[st:st + L]
        target = L * 8
        best = None
        for W in range(6, 41):
            for H in range(6, 33):
                cnt, used = decode_a8_used(body, W, H)
                if cnt < W * H:
                    continue
                rem = target - used
                if 0 <= rem < 32:  # ресурс замкнулся в пределах одного 32-битного слова
                    if best is None or rem < best[0]:
                        best = (rem, W, H, used)
        if best:
            hits.append((st, L, shared, best))
        if idx % 50 == 0:
            print("..%d/%d" % (idx, len(chunks)), flush=True)

    print("clean bit-closure hits:", len(hits), flush=True)
    for st, L, sh, (rem, W, H, used) in sorted(hits, key=lambda x: x[3][0])[:30]:
        print("  0x%08X L=%4d %s W=%2d H=%2d used=%d rem=%d px=%d"
              % (st, L, "sh" if sh else "uq", W, H, used, rem, W * H), flush=True)


if __name__ == "__main__":
    main()
