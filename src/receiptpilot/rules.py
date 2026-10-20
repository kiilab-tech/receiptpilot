"""自分ルール (FR-3, FR-4)。

- payee_rules.yaml の対応付けは AI 推測より常に優先(原則2)。
- ブランド抽出は「スペースがあるときだけ」支店名を落とす(FR-3)。
  無ければ raw のまま(記号での分割は原理的に曖昧 → 安全側)。
"""
from __future__ import annotations

import os
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path

import yaml

# 見た目が同じハイフン類(‐ ‑ ‒ – — ― −)。NFKC では揃わないので ASCII の '-' に寄せる。
# 実物レシートでAIが「セブン‐イレブン」(U+2010)と返し、ルールに当たらなかった(M1)。
# 長音記号「ー」は別物なので含めない。
_DASHES = str.maketrans({c: "-" for c in "‐‑‒–—―−"})


def normalize_text(s: str) -> str:
    """全半角・大小文字・ハイフン類のゆらぎの正規化。突合前に必ず通す。"""
    s = unicodedata.normalize("NFKC", s).translate(_DASHES)
    return s.strip().lower()


def brand_from_raw(payee_raw: str) -> str:
    """区切りがある場合のみ先頭要素をブランドとして返す。無ければ raw のまま。

    例: 'ローソン 駅前店' -> 'ローソン'
        'セブン-イレブン中央町店' -> 区切り '-' はブランド名の一部になり得るため、
        スペース等の明確な区切りが無ければ raw のまま返す(人に決めさせる)。
    """
    s = payee_raw.strip()
    # スペース(全半角)での分割のみ「明確な区切り」とみなす
    parts = re.split(r"[ \u3000]+", s)
    if len(parts) >= 2:
        return parts[0]
    return s


@dataclass
class RuleHit:
    category: str
    brand: str | None
    match_type: str  # exact / prefix / partial
    pattern: str


class PayeeRules:
    """payee_rules.yaml:
    rules:
      - pattern: "ローソン"
        match: prefix        # exact / prefix / partial (既定 partial)
        category: "食費"
        brand: "ローソン"     # 省略時 pattern
    """

    def __init__(self, rules: list[dict]):
        self.rules = rules

    @classmethod
    def load(cls, path: str | Path) -> "PayeeRules":
        p = Path(path)
        if not p.exists():
            return cls([])
        d = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
        return cls(d.get("rules", []))

    def save(self, path: str | Path) -> None:
        """一時ファイルに書いてから置き換える(保存途中の中断でルールが消えない。UI要件 R11)。"""
        p = Path(path)
        tmp = p.with_suffix(".tmp")
        tmp.write_text(
            yaml.safe_dump({"rules": self.rules}, allow_unicode=True, sort_keys=False),
            encoding="utf-8",
        )
        os.replace(tmp, p)

    def remove(self, pattern: str) -> None:
        self.rules = [r for r in self.rules if r["pattern"] != pattern]

    def match(self, payee_raw: str) -> RuleHit | None:
        """完全一致 > 前方一致 > 部分一致 の優先順で最初のヒットを返す。"""
        target = normalize_text(payee_raw)
        for want in ("exact", "prefix", "partial"):
            for r in self.rules:
                mt = r.get("match", "partial")
                if mt != want:
                    continue
                pat = normalize_text(r["pattern"])
                hit = (
                    (want == "exact" and target == pat)
                    or (want == "prefix" and target.startswith(pat))
                    or (want == "partial" and pat in target)
                )
                if hit:
                    return RuleHit(
                        category=r["category"],
                        brand=r.get("brand", r["pattern"]),
                        match_type=want,
                        pattern=r["pattern"],
                    )
        return None

    def add(self, pattern: str, category: str, brand: str | None = None,
            match: str = "partial") -> None:
        self.rules.append({
            "pattern": pattern, "match": match, "category": category,
            **({"brand": brand} if brand else {}),
        })
