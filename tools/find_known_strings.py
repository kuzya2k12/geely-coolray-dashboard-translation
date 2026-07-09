#!/usr/bin/env python3
"""
Crib-атака: искать в дампах ЦЕЛЫЕ известные строки сообщений приборки (из таблицы
перевода) во всех вероятных кодировках. В отличие от прошлого поиска "частотных
иероглифов" по одному (давал шум), целое сообщение из 4+ иероглифов достаточно
специфично — ложных срабатываний почти не будет.

Если хоть одна известная строка найдётся байтами — значит текст в приборке хранится
как СТРОКИ (в этой кодировке), а не только как индексы глифов. Это пробивает главный
тупик и указывает регион таблицы локализации.

Запуск: python find_known_strings.py [dump1.bin dump2.bin ...]
"""
import sys

DUMPS = sys.argv[1:] or ["Coolray_25_Dash_U17.bin", "Coolray_25_Dash_U18.bin"]

# Известные китайские сообщения приборки (из таблицы перевода). Брать ДЛИННЫЕ и
# уверенно прочитанные — чем длиннее, тем специфичнее байтовый паттерн.
KNOWN = [
    "TPMS系统故障",
    "TPMS系统关闭",
    "TPMS信号异常",
    "传感器故障",
    "充电已完成",
    "充电准备中",
    "安全带",
    "主动提速",
    "制动灯故障",
    "定速巡航系统关闭",
    "钥匙电量低",
    "钥匙遗忘在车内",
    "请挂入P挡驻车",
    "发动机水温过高",
    "变速箱温度过高",
    "行车视觉监测摄像头",
    "乘客安全气囊已停用",
    "人脸识别成功",
    "自动泊车",
    "驾驶模式",
]

ENCODINGS = ["gb2312", "gbk", "gb18030", "utf-16le", "utf-16be", "utf-8", "big5"]


def main():
    for path in DUMPS:
        try:
            data = open(path, "rb").read()
        except FileNotFoundError:
            print("НЕ найден:", path)
            continue
        print("==== %s (%d MB) ====" % (path, len(data) // 1048576))
        any_hit = False
        for s in KNOWN:
            for enc in ENCODINGS:
                try:
                    needle = s.encode(enc)
                except (UnicodeEncodeError, LookupError):
                    continue
                if len(needle) < 4:
                    continue
                idx = data.find(needle)
                if idx != -1:
                    any_hit = True
                    # сколько всего вхождений
                    cnt = data.count(needle)
                    print("  ✔ '%s' [%s] @0x%08X  (вхождений: %d, %d байт)"
                          % (s, enc, idx, cnt, len(needle)))
        if not any_hit:
            print("  (ни одна известная строка не найдена байтами ни в одной кодировке)")
        print()


if __name__ == "__main__":
    main()
