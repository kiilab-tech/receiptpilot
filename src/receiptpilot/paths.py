"""データの置き場所。CLI と UI で共通。

既定は リポジトリ直下の data/。環境変数 RECEIPTPILOT_DATA で切り替えられる
(デモ用の data/demo/ を本番データと混ぜないため)。
自分ルールは データ置き場に payee_rules.yaml があればそれを、
無ければ masters/payee_rules.yaml を使う。
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class Paths:
    data: Path

    @property
    def inbox(self) -> Path:
        return self.data / "inbox"

    @property
    def store(self) -> Path:
        return self.data / "store/records.jsonl"

    @property
    def confirmations(self) -> Path:
        return self.data / "store/confirmations.jsonl"

    @property
    def out(self) -> Path:
        return self.data / "out"

    @property
    def rules(self) -> Path:
        local = self.data / "payee_rules.yaml"
        return local if local.exists() else ROOT / "masters/payee_rules.yaml"

    @property
    def categories(self) -> Path:
        return ROOT / "masters/categories.yaml"


def get_paths() -> Paths:
    d = os.environ.get("RECEIPTPILOT_DATA")
    if not d:
        return Paths(ROOT / "data")
    p = Path(d)
    return Paths(p if p.is_absolute() else ROOT / p)
