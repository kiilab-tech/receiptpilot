"""GASスプレッドシートアダプタ。Webhook POST 用の JSON を生成する。

実運用では tools/gas/kakeibo_sheet.gs をスプレッドシートに配置し、
このJSONを curl 等で POST する(pipeline からは JSON 生成まで)。
"""
from __future__ import annotations

import json
from pathlib import Path

from ..schema import Record
from .base import Adapter


class GasSheetAdapter(Adapter):
    name = "gas_sheet"

    def write(self, records: list[Record], out_dir: Path) -> Path:
        out_dir.mkdir(parents=True, exist_ok=True)
        path = out_dir / "gas_payload.json"
        rows = [
            {"date": r.date, "payee": r.payee, "category": r.category,
             "amount": r.total, "source": r.source_image}
            for r in sorted(records, key=lambda x: x.date or "")
        ]
        path.write_text(json.dumps({"rows": rows}, ensure_ascii=False, indent=2),
                        encoding="utf-8")
        return path
