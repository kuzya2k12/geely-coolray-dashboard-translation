#!/usr/bin/env python3
"""
Шаг 2 crib-атаки: искать ТАБЛИЦУ СТРОК как индексов глифов по её ТОПОЛОГИИ, а не по
байтам. Байтовый поиск известных строк дал 0 (текст не хранится читаемым) => текст,
вероятно, лежит как массивы индексов глифов. У такого массива есть отпечаток, который
МЫ ЗНАЕМ из таблицы перевода:

  1) последовательность ДЛИН сообщений (число иероглифов в каждом) — напр. 5,5,4,5,6...
  2) ПРЕФИКСНЫЕ группы: сообщения на 充电.. делят первые 2 индекса; TPMS.. делят первые
     4; 转向锁.. делят первые 3. В массиве индексов это = записи с общим началом.

Стратегия: индекс глифа обычно u16 (2 байта, <~4000 глифов). Строка = массив u16,
разделённая терминатором (0x0000) ИЛИ фиксированной длины. Ищем в дампе зоны, где:
  - идут подряд u16 в правдоподобном диапазоне индексов (напр. 1..0x2000),
  - разбиты на записи, длины которых совпадают с нашей известной последовательностью длин,
  - записи с общим китайским префиксом имеют общее начало (одинаковые первые u16).

Запуск: python find_string_table.py [dump.bin]
"""
import sys, struct

DUMP = sys.argv[1] if len(sys.argv) > 1 else "Coolray_25_Dash_U17.bin"

# Известные сообщения → их длины (в иероглифах) и префиксные группы.
# (китайский, длина). Порядок как в таблице перевода (первые ~30).
MESSAGES = [
    "EPS条件不满足", "EPS系统条件不满足", "GPF满载再生频繁", "ICN继电器故障",
    "P挡驻车失效", "TPMS信号异常", "TPMS系统关闭", "TPMS系统故障",
    "主动提速", "主动格栅故障", "乘客安全气囊已停用", "人脸信息注册中",
    "人脸信息注册失败", "人脸信息注册成功", "人脸识别失败", "人脸识别成功",
    "传感器故障", "传感器未学习", "传感器电量低", "位置灯故障",
    "充电准备中", "充电已完成", "充电插座故障", "充电机故障", "充电桩故障",
]
# Длина = число «символов». Для смешанных (латиница+иероглифы) считаем грубо по символам.
LENGTHS = [len(m) for m in MESSAGES]


def read_u16_le(data, off, n):
    return list(struct.unpack_from("<%dH" % n, data, off))


def scan_for_index_arrays(data, idx_lo=1, idx_hi=0x2000, min_run=200):
    """Найти зоны, где идут подряд правдоподобные u16-индексы глифов."""
    runs = []
    i = 0x180000
    n = len(data)
    start = None
    good = 0
    while i < n - 1:
        v = data[i] | (data[i + 1] << 8)
        ok = (idx_lo <= v <= idx_hi) or v == 0  # 0 = возможный терминатор
        if ok:
            if start is None:
                start = i
            good += 1
        else:
            if start is not None and good >= min_run:
                runs.append((start, i - start))
            start = None
            good = 0
        i += 2
    if start is not None and good >= min_run:
        runs.append((start, n - start))
    return runs


def length_sequence_match(data, off, count, target_lengths, term=0x0000):
    """Прочитать `count` строк (u16-массивы, разделённые term) и сравнить их длины
    с target_lengths. Вернуть долю совпавших длин."""
    lengths = []
    p = off
    for _ in range(count):
        ln = 0
        while p + 1 < len(data):
            v = data[p] | (data[p + 1] << 8)
            p += 2
            if v == term:
                break
            ln += 1
            if ln > 40:
                break
        lengths.append(ln)
    if not lengths:
        return 0.0, lengths
    m = sum(1 for a, b in zip(lengths, target_lengths) if a == b)
    return m / len(target_lengths), lengths


def main():
    data = open(DUMP, "rb").read()
    print("==== %s ====" % DUMP)
    print("target length sequence (first %d msgs):" % len(LENGTHS), LENGTHS)
    print()

    runs = scan_for_index_arrays(data)
    print("зоны подряд-идущих правдоподобных u16-индексов (>=200 значений):", len(runs))
    # показать крупнейшие
    runs.sort(key=lambda x: -x[1])
    for off, ln in runs[:12]:
        print("  0x%08X  %d значений (%.1f KB)" % (off, ln // 2, ln / 1024))
    print()

    # В каждой зоне искать null-разделённые записи с совпадающей последовательностью длин
    print("поиск последовательности длин %s в null-разделённых u16-записях:" % LENGTHS[:6])
    best = []
    for off, ln in runs:
        p = off
        endp = off + ln
        while p < endp - 2:
            score, lengths = length_sequence_match(data, p, len(LENGTHS), LENGTHS)
            if score > 0.5:
                best.append((score, p, lengths))
            # шагаем к следующему нулю-терминатору или на 2
            p += 2
    best.sort(key=lambda x: -x[0])
    if best:
        for score, p, lengths in best[:10]:
            print("  ✔ 0x%08X score=%.2f lengths=%s" % (p, score, lengths[:12]))
    else:
        print("  (совпадений последовательности длин не найдено)")


if __name__ == "__main__":
    main()
