"""家計簿CSVアダプタ (B2C)。日付/店名/費目/金額 のUTF-8(BOM付き) CSV。"""
from __future__ import annotations

import csv
from pathlib import Path

from ..schema import Record
from .base import Adapter, safe_cell


class KakeiboCsvAdapter(Adapter):
    name = "kakeibo_csv"

    def write(self, records: list[Record], out_dir: Path) -> Path:
        out_dir.mkdir(parents=True, exist_ok=True)
        path = out_dir / "kakeibo.csv"
        with path.open("w", encoding="utf-8-sig", newline="") as f:  # BOM付き: Excelで文字化けさせない
            w = csv.writer(f)
            w.writerow(["日付", "店名", "費目", "金額"])
            for r in sorted(records, key=lambda x: x.date or ""):
                w.writerow([r.date, safe_cell(r.payee), r.category, r.total])
        return path
