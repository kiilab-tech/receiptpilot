#!/usr/bin/env python3
"""読み取り精度の評価: 保存済みの抽出結果を、人が作った正解データと突き合わせる。

  python3 tools/evaluate.py private/m1_truth.json

正解データ(JSON)の形式: { "画像ファイル名": {"payee_raw", "date", "total", "tax",
"items": [[品名, 金額], ...], "payment_method"}, ... }。"_" で始まるキーは無視する。
APIは呼ばない(data/store に保存済みの抽出結果を読むだけ)。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from receiptpilot.paths import get_paths
from receiptpilot.rules import normalize_text
from receiptpilot.store import Store

FIELDS = ["店名", "日付", "合計", "税額", "明細数", "明細金額", "支払方法"]


def compare(ex, truth: dict) -> dict[str, bool]:
    t_items = [a for _, a in truth["items"]]
    e_items = [i.amount for i in ex.items]
    want_payee = normalize_text(truth["payee_raw"]).replace(" ", "")
    got_payee = normalize_text(ex.payee_raw or "").replace(" ", "")
    return {
        "店名": want_payee in got_payee or got_payee in want_payee,
        "日付": ex.date == truth["date"],
        "合計": ex.total == truth["total"],
        "税額": ex.tax == truth.get("tax"),
        "明細数": len(e_items) == len(t_items),
        "明細金額": sorted(e_items) == sorted(t_items),
        "支払方法": truth.get("payment_method", "") in (ex.payment_method or ""),
    }


def main() -> None:
    truth = {k: v for k, v in json.loads(Path(sys.argv[1]).read_text(encoding="utf-8")).items()
             if not k.startswith("_")}
    records = {r.source_image: r for r in Store(get_paths().store).load_all().values()}

    ok_count = {f: 0 for f in FIELDS}
    n = 0
    for name, t in truth.items():
        r = records.get(name)
        if r is None or r.extraction is None:
            print(f"{name}: 未処理")
            continue
        n += 1
        res = compare(r.extraction, t)
        for f, ok in res.items():
            ok_count[f] += ok
        ex = r.extraction
        print(f"\n■ {name}  [{r.status}] {' / '.join(r.reasons)}")
        print(f"  読み取り: {ex.payee_raw} | {ex.date} | 合計{ex.total} 税{ex.tax} | "
              f"明細{len(ex.items)}件 計{ex.items_sum()} | {ex.payment_method}")
        print(f"  正解    : {t['payee_raw']} | {t['date']} | 合計{t['total']} 税{t.get('tax')} | "
              f"明細{len(t['items'])}件 計{sum(a for _, a in t['items'])} | {t.get('payment_method')}")
        bad = [f for f, ok in res.items() if not ok]
        print("  " + ("全項目一致" if not bad else "不一致: " + ", ".join(bad)))
        if ex.notes:
            print(f"  AIのメモ: {ex.notes}")

    if n:
        print(f"\n=== 項目別の正解率({n}枚) ===")
        for f in FIELDS:
            print(f"  {f:6s} {ok_count[f]}/{n}")


if __name__ == "__main__":
    main()
