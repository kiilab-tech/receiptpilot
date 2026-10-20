"""学習 (FR-6)。

人手確定した (店名, 費目) からルール候補を生成。
同じ対応付けが2回確定されたら追加を「提案」する(自動追加はしない — 原則2は
人の決定を最上位に置くため、ルール追加自体も人が承認する)。
"""
from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

from .rules import PayeeRules, brand_from_raw, normalize_text

PROPOSE_AFTER = 2  # 同じ対応付けがこの回数確定されたら提案


class Learner:
    def __init__(self, log_path: str | Path):
        self.log_path = Path(log_path)
        self.log_path.parent.mkdir(parents=True, exist_ok=True)

    def note_confirmation(self, payee_raw: str, category: str,
                          payee: str | None = None) -> None:
        """人手確定を1件記録する。

        payee は人が確認・修正したブランド名(あれば最優先)。
        区切り無し店名は brand_from_raw では分割されないため、
        人がUIでブランド名を直したものを学習の主キーにする(原則2)。
        """
        with self.log_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(
                {"payee_raw": payee_raw, "category": category,
                 **({"payee": payee} if payee else {})},
                ensure_ascii=False) + "\n")

    def proposals(self, rules: PayeeRules) -> list[dict]:
        """既存ルールでカバーされていない頻出対応付けを提案する。"""
        if not self.log_path.exists():
            return []
        counts: Counter[tuple[str, str]] = Counter()
        for line in self.log_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            d = json.loads(line)
            brand = d.get("payee") or brand_from_raw(d["payee_raw"])
            counts[(brand, d["category"])] += 1

        out = []
        for (brand, category), n in counts.most_common():
            if n < PROPOSE_AFTER:
                continue
            if rules.match(brand):  # 既にルールがある
                continue
            out.append({
                "pattern": brand, "category": category,
                "match": "partial", "confirmed_count": n,
            })
        return out
