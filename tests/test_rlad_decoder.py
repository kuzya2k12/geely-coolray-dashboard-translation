#!/usr/bin/env python3
"""
Автономный тест RLAD-декодера — БЕЗ проприетарного энкодера Infineon.

Тест-векторы (пары «RLAD-байты → ожидаемые пиксели») заранее сняты через
референс-энкодер Infineon (rlad-encoder.exe) на контролируемых входах и зашиты
сюда как константы. Поэтому проверить корректность декодера может любой, не имея
самого энкодера.

Запуск:
    python -m pytest tests/            # если установлен pytest
    python tests/test_rlad_decoder.py  # без pytest (просто запустить)
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "geely_cluster"))
from rlad_decoder import decode_image, decode_a8_image  # noqa: E402

# Векторы получены оракулом (rlad-encoder.exe ... RLAD) на входах 8x1 RGBA.
# Это режимы малого/среднего cbpc — именно то, из чего состоят глифы шрифта.
VECTORS = {
    "ramp_r": {
        "rlad_hex": "0300000000ff88c6fa000000",
        "width": 8, "height": 1,
        "expected": [[i, 0, 0, 255] for i in range(8)],
    },
    "bias_r": {
        "rlad_hex": "0300640000ff88c6fa000000",
        "width": 8, "height": 1,
        "expected": [[100 + i, 0, 0, 255] for i in range(8)],
    },
    "const5": {
        "rlad_hex": "0000050000ff0000",
        "width": 8, "height": 1,
        "expected": [[5, 0, 0, 255]] * 8,
    },
    "gray_grad": {
        "rlad_hex": "0000404040ff0000",
        "width": 8, "height": 1,
        "expected": [[64, 64, 64, 255]] * 8,
    },
    "alpha_ramp": {
        "rlad_hex": "0080ffffff000020406080a0c0e00000",
        "width": 8, "height": 1,
        "expected": [[255, 255, 255, i * 32] for i in range(8)],
    },
    "alpha_edge": {
        "rlad_hex": "00800000000000003ca0e6ffffff0000",
        "width": 8, "height": 1,
        "expected": [[0, 0, 0, 0], [0, 0, 0, 0], [0, 0, 0, 60], [0, 0, 0, 160],
                     [0, 0, 0, 230], [0, 0, 0, 255], [0, 0, 0, 255], [0, 0, 0, 255]],
    },
}


# --- A8 (глифы шрифта) ---
# Тест-глиф 16x16 (крест), закодирован ResourceGenerator.exe -foA8 -cRLAD.
# Зашиты RLAD-данные и ожидаемый декод (первая строка + контроль по всему кадру).
A8_GLYPH = {
    "rlad_hex": (
        "080000f8ff0f0800000000070800fcff0000000080f00ffff00fff070800fcff0000"
        "000080080000f8ff0f0800000000080000f8ff0f0800000000080000f8ff0f080000"
        "0000080000f8ff0f0800000000080000f8ff0f0800000000080000f8ff0f08000000"
        "00080000f8ff0f0800000000080000f8ff0f0800000000080000f8ff0f0800000000"
        "080000f8ff0f0800000000080000f8ff0f08000000000000"
    ),
    "width": 16, "height": 16,
    "first_row": [0, 128, 255, 255, 128, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0],
}

# A8, ширина 12 (НЕ кратна 8) — проверяет ПОСТРОЧНУЮ упаковку (пакеты не переходят
# границу строки; последний пакет строки = остаток width%8). Крест на x=3 и y=3.
A8_ROWWISE = {
    "rlad_hex": (
        "08000000f00f000000000008000000f00f000000000008000000f00f0000000000"
        "f00fff08000000f00f000000000008000000f00f000000000008000000f00f0000"
        "00000008000000f00f000000000008000000f00f000000000008000000f00f0000"
        "00000008000000f00f000000000008000000f00f0000000000"
    ),
    "width": 12, "height": 12,
    # эталон: крест — строка 3 вся 255, столбец 3 везде 255, остальное 0
    "expected": [
        (255 if (x == 3 or y == 3) else 0)
        for y in range(12) for x in range(12)
    ],
}


def _decode(vec):
    data = bytes.fromhex(vec["rlad_hex"])
    pixels = decode_image(data, vec["width"], vec["height"])
    return [list(p) for p in pixels]


def test_rlad_vectors():
    """Каждый RGBA-вектор должен декодироваться байт-в-байт как ожидается."""
    for name, vec in VECTORS.items():
        got = _decode(vec)
        assert got == vec["expected"], (
            "RLAD decode mismatch for %r:\n  expected %r\n  got      %r"
            % (name, vec["expected"], got)
        )


def test_a8_glyph():
    """A8-глиф должен декодироваться в ожидаемую форму (формат шрифта приборки)."""
    alpha = decode_a8_image(bytes.fromhex(A8_GLYPH["rlad_hex"]),
                            A8_GLYPH["width"], A8_GLYPH["height"])
    assert len(alpha) == 256
    assert alpha[:16] == A8_GLYPH["first_row"], alpha[:16]
    # значения только из набора {0,128,255} — как в исходном глифе
    assert set(alpha) <= {0, 128, 255}, sorted(set(alpha))


def test_a8_rowwise():
    """A8 с шириной, не кратной 8 — проверяет построчную упаковку пакетов."""
    alpha = decode_a8_image(bytes.fromhex(A8_ROWWISE["rlad_hex"]),
                            A8_ROWWISE["width"], A8_ROWWISE["height"])
    assert alpha == A8_ROWWISE["expected"], alpha


if __name__ == "__main__":
    ok = total = 0
    for name, vec in VECTORS.items():
        total += 1
        got = _decode(vec)
        if got == vec["expected"]:
            print("PASS  rgba:%s" % name); ok += 1
        else:
            print("FAIL  rgba:%s" % name)
            print("  expected:", vec["expected"]); print("  got:     ", got)
    # A8
    for fn, label in [(test_a8_glyph, "a8:glyph"), (test_a8_rowwise, "a8:rowwise")]:
        total += 1
        try:
            fn()
            print("PASS  %s" % label); ok += 1
        except AssertionError as e:
            print("FAIL  %s -> %s" % (label, e))
    print("\n%d/%d passed" % (ok, total))
    sys.exit(0 if ok == total else 1)
