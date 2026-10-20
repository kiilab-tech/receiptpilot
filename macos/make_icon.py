#!/usr/bin/env python3
"""アプリのアイコン(ReceiptPilot.icns)を描いて作る。macos/build.sh から呼ばれる。

  python3 macos/make_icon.py 出力先ディレクトリ
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from PIL import Image, ImageDraw

GREEN = (47, 125, 91)
PAPER = (252, 251, 247)
INK = (120, 128, 136)


def draw(size: int = 1024) -> Image.Image:
    s = size / 1024
    im = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    # 角丸の背景(macOS のアイコンの余白に合わせて少し内側)
    d.rounded_rectangle([100 * s, 100 * s, 924 * s, 924 * s], radius=185 * s, fill=GREEN)
    # レシート(下端はギザギザ)
    left, right, top, bottom = 300 * s, 724 * s, 200 * s, 790 * s
    teeth = 8
    w = (right - left) / teeth
    outline = [(left, top), (right, top), (right, bottom)]
    for i in range(teeth):
        x = right - (i + 0.5) * w
        outline += [(x, bottom + 34 * s), (right - (i + 1) * w, bottom)]
    d.polygon(outline, fill=PAPER)
    # 明細の線
    for i, y in enumerate(range(290, 600, 70)):
        end = right - (60 if i % 2 else 120) * s
        d.rounded_rectangle([left + 50 * s, y * s, end, y * s + 26 * s], radius=13 * s, fill=INK)
    # 確認済みのチェック
    cx, cy, r = 650 * s, 690 * s, 150 * s
    d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=GREEN, outline=PAPER, width=int(22 * s))
    d.line([(cx - 72 * s, cy + 2 * s), (cx - 18 * s, cy + 58 * s), (cx + 78 * s, cy - 58 * s)],
           fill=PAPER, width=int(40 * s), joint="curve")
    return im


def main() -> None:
    out = Path(sys.argv[1])
    iconset = out / "ReceiptPilot.iconset"
    iconset.mkdir(parents=True, exist_ok=True)
    base = draw(1024)
    for px in (16, 32, 128, 256, 512):
        base.resize((px, px), Image.LANCZOS).save(iconset / f"icon_{px}x{px}.png")
        base.resize((px * 2, px * 2), Image.LANCZOS).save(iconset / f"icon_{px}x{px}@2x.png")
    base.save(out / "icon_1024.png")
    subprocess.run(["iconutil", "-c", "icns", str(iconset), "-o", str(out / "ReceiptPilot.icns")],
                   check=True)


if __name__ == "__main__":
    main()
