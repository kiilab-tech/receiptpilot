"""freee取引インポートCSVアダプタ (B2B側の芽)。

freee会計「取引のインポート」最小構成:
収支区分/管理番号/発生日/決済期日/取引先/勘定科目/税区分/金額/備考
※ 勘定科目は費目マスタの freee_account 対応で変換。未対応費目は弾く。
"""
from __future__ import annotations

import csv
from pathlib import Path

import yaml

from ..schema import Record
from .base import Adapter, safe_cell


class FreeeAdapter(Adapter):
    name = "freee"

    def __init__(self, categories_path: str | Path):
        d = yaml.safe_load(Path(categories_path).read_text(encoding="utf-8")) or {}
        self.account_map = {
            c["name"]: c.get("freee_account")
            for c in d.get("categories", [])
        }

    def extra_validate(self, record: Record) -> list[str]:
        acc = self.account_map.get(record.category or "")
        if not acc:
            return [f"freee勘定科目未対応: {record.category}"]
        return []

    def write(self, records: list[Record], out_dir: Path) -> Path:
        out_dir.mkdir(parents=True, exist_ok=True)
        path = out_dir / "freee_import.csv"
        with path.open("w", encoding="utf-8-sig", newline="") as f:  # BOM付き: Excelで文字化けさせない
            w = csv.writer(f)
            w.writerow(["収支区分", "管理番号", "発生日", "決済期日",
                        "取引先", "勘定科目", "税区分", "金額", "備考"])
            for r in sorted(records, key=lambda x: x.date or ""):
                w.writerow([
                    "支出", r.image_hash, r.date, r.date,
                    safe_cell(r.payee), self.account_map[r.category], "課対仕入10%",
                    r.total, f"ReceiptPilot:{r.source_image}",
                ])
        return path
