"""共通スキーマ。

設計原則:
- 抽出結果(Extraction)と正規レコード(Record)を分ける。
  Extraction は「AIが読んだ生の結果」、Record は「ルール・判定を経た家計簿の1行」。
- Record は必ず status を持つ。confirmed 以外は出力してはならない(FR-7.2)。
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field, asdict
from typing import Literal, Optional

Status = Literal["confirmed", "review", "manual", "deleted"]
Origin = Literal["extractor", "rule", "human"]


@dataclass
class LineItem:
    name: str
    amount: int  # 円(整数)


@dataclass
class Extraction:
    """VLMが1枚のレシートから読んだ生の結果。"""
    payee_raw: str                      # 店名(印字のまま)
    date: Optional[str]                 # YYYY-MM-DD
    total: Optional[int]                # 合計(円)
    tax: Optional[int] = None
    items: list[LineItem] = field(default_factory=list)
    payment_method: Optional[str] = None
    currency: str = "JPY"
    model: str = ""                     # 抽出に使ったモデルID
    notes: str = ""                     # VLMの補足(読み取り困難箇所など)

    def items_sum(self) -> Optional[int]:
        if not self.items:
            return None
        return sum(i.amount for i in self.items)

    def sum_matches_total(self) -> Optional[bool]:
        """検算: 明細合計と合計の突合。明細が無ければ None(判定不能)。

        内税: 明細計 == 合計 / 外税: 明細計 + 税額 == 合計(明細が税抜で印字される)。
        どちらも1円単位の完全一致のみ。実物レシートは外税が多かった(M1: 4枚中3枚)。
        """
        s = self.items_sum()
        if s is None or self.total is None:
            return None
        return s == self.total or (self.tax is not None and s + self.tax == self.total)

    def is_tax_exclusive(self) -> bool:
        """外税として検算が合ったか(判定理由の表示用)。"""
        s = self.items_sum()
        return (s is not None and self.total is not None and self.tax is not None
                and s != self.total and s + self.tax == self.total)


@dataclass
class Record:
    """家計簿/仕訳の1行。パイプラインの正規形。"""
    source_image: str                   # 元画像ファイル名
    image_hash: str                     # 二重処理防止用
    payee_raw: str
    payee: str                          # 正規化後の店名(ブランド)
    date: Optional[str]
    total: Optional[int]
    category: Optional[str]             # 費目
    status: Status = "review"           # 既定は安全側(原則1)
    category_origin: Optional[Origin] = None
    reasons: list[str] = field(default_factory=list)  # 判定理由(監査用)
    extraction: Optional[Extraction] = None

    def to_json(self) -> str:
        d = asdict(self)
        return json.dumps(d, ensure_ascii=False)

    @staticmethod
    def from_json(line: str) -> "Record":
        d = json.loads(line)
        ex = d.get("extraction")
        if ex:
            ex["items"] = [LineItem(**i) for i in ex.get("items", [])]
            d["extraction"] = Extraction(**ex)
        return Record(**d)


def file_hash(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()[:16]
