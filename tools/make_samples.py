#!/usr/bin/env python3
"""デモ用の架空レシート画像を生成する(samples/ に PNG + Mock用JSON)。

店名・住所・電話番号はすべて架空。実在の店舗・個人とは関係ない。
各JSONは「VLMがこう読んだ」という想定の抽出結果で、MockExtractor が読む。

  python3 tools/make_samples.py
"""
from __future__ import annotations

import json
import random
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "samples"
FONT = "/System/Library/Fonts/ヒラギノ角ゴシック W3.ttc"
FONT_BOLD = "/System/Library/Fonts/ヒラギノ角ゴシック W6.ttc"

# (ファイル名, 店名, 支店, 日付, 時刻, 明細, 印字された合計, 支払方法, 想定シナリオ)
RECEIPTS = [
    ("s01", "まちかどマート", "駅前店", "2026-10-01", "08:12",
     [("おにぎり 鮭", 150), ("緑茶 500ml", 140), ("幕の内弁当", 498)], None, "現金",
     "ルール既知店・少額 → 自動確定"),
    ("s02", "まちかどマート", "北口店", "2026-10-03", "19:40",
     [("食パン 6枚", 220), ("牛乳 1L", 238)], None, "電子マネー",
     "ルール既知店・少額 → 自動確定"),
    ("s03", "ハーモニー楽器", "中央店", "2026-10-05", "15:03",
     [("ギター弦 セット", 2860), ("クリップチューナー", 3190),
      ("譜面台", 4950), ("ギグバッグ", 13200)], None, "クレジット",
     "ルール既知店だが 20,000円超 → 要確認"),
    ("s04", "ホームセンターみどり中央店", None, "2026-10-06", "10:21",
     [("LED電球", 748), ("結束バンド", 880)], None, "現金",
     "未知店(費目なし) → 要確認 → 人が費目を決める"),
    ("s05", "でんしパーツ工房", "本店", "2026-10-08", "13:47",
     [("デジタルオシロスコープ", 34800)], None, "クレジット",
     "30,000円超 → 常に要確認"),
    ("s06", "まちかどマート", "駅前店", "2026-10-09", "07:55",
     [("乾電池 4本", 500), ("ノート", 300)], 1000, "現金",
     "明細計と合計が合わない → 要確認"),
    ("s07", "ホームセンターみどり西店", None, "2026-10-12", "16:30",
     [("ガムテープ", 398), ("軍手", 582)], None, "現金",
     "未知店 2回目 → 確定するとルール候補が出る"),
]


def yen(n: int) -> str:
    return f"¥{n:,}"


def draw_receipt(store: str, branch: str | None, date: str, time: str,
                 items: list[tuple[str, int]], total: int, pay: str) -> Image.Image:
    W = 520
    f = ImageFont.truetype(FONT, 22)
    fs = ImageFont.truetype(FONT, 18)
    fb = ImageFont.truetype(FONT_BOLD, 34)
    ft = ImageFont.truetype(FONT_BOLD, 30)
    lines_h = 470 + 36 * len(items)
    paper = Image.new("RGB", (W, lines_h), (252, 251, 247))
    d = ImageDraw.Draw(paper)

    def center(y, text, font):
        w = d.textlength(text, font=font)
        d.text(((W - w) / 2, y), text, font=font, fill=(35, 35, 35))

    def row(y, left, right, font=f):
        d.text((40, y), left, font=font, fill=(35, 35, 35))
        w = d.textlength(right, font=font)
        d.text((W - 40 - w, y), right, font=font, fill=(35, 35, 35))

    y = 30
    center(y, store, fb); y += 50
    if branch:
        center(y, branch, f); y += 34
    center(y, "架空市サンプル町1-2-3  TEL 000-0000-0000", fs); y += 44
    row(y, date.replace("-", "/") + f" {time}", "レジ01", fs); y += 36
    d.line((30, y, W - 30, y), fill=(120, 120, 120), width=1); y += 16
    for name, amount in items:
        row(y, name, yen(amount)); y += 36
    d.line((30, y, W - 30, y), fill=(120, 120, 120), width=1); y += 16
    row(y, "小計", yen(sum(a for _, a in items))); y += 40
    row(y, "合計", yen(total), ft); y += 50
    row(y, "(内消費税等 10%)", yen(total * 10 // 110), fs); y += 32
    row(y, pay, yen(total), fs); y += 50
    center(y, "※ポートフォリオ用の架空レシートです", fs)

    # 撮影写真らしく: 少し傾けて背景に置く
    rnd = random.Random(store + date)
    paper = paper.rotate(rnd.uniform(-2.0, 2.0), expand=True, fillcolor=(90, 96, 104),
                         resample=Image.BICUBIC)
    bg = Image.new("RGB", (paper.width + 60, paper.height + 60), (90, 96, 104))
    bg.paste(paper, (30, 30))
    return bg.filter(ImageFilter.GaussianBlur(0.4))


def main() -> None:
    OUT.mkdir(exist_ok=True)
    for name, store, branch, date, time, items, printed_total, pay, _ in RECEIPTS:
        total = printed_total if printed_total is not None else sum(a for _, a in items)
        img = draw_receipt(store, branch, date, time, items, total, pay)
        img.save(OUT / f"{name}.png", optimize=True)
        sidecar = {
            "payee_raw": f"{store} {branch}" if branch else store,
            "date": date,
            "total": total,
            "tax": total * 10 // 110,
            "items": [{"name": n, "amount": a} for n, a in items],
            "payment_method": pay,
        }
        (OUT / f"{name}.json").write_text(
            json.dumps(sidecar, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"{len(RECEIPTS)} 枚を {OUT} に生成しました")
    for name, *_, scenario in RECEIPTS:
        print(f"  {name}: {scenario}")


if __name__ == "__main__":
    main()
