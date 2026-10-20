"""出力アダプタ共通IF (FR-7)。

FR-7.2 最終検証ゲート:
  項目充足だけでなく **status を必ず検査** する。
  未確定(review/manual)は、全項目が埋まっていても書き出さない。
  「検算が合っていないレシートが静かに家計簿へ流れ込む」事故をここで止める。
  この検査は基底クラスに置き、サブクラスが省略できない構造にする。
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path

from ..schema import Record


def safe_cell(value):
    """CSV数式インジェクション対策。

    店名などはAIが画像から読んだ外部入力。'=' '+' '-' '@' で始まる文字列は
    Excel で数式として実行され得るので、先頭に ' を付けて文字列として扱わせる。
    """
    if isinstance(value, str) and value[:1] in ("=", "+", "-", "@", "\t", "\r"):
        return "'" + value
    return value


class Adapter(ABC):
    name: str = "base"

    def validate(self, record: Record) -> list[str]:
        """出力直前の最終検証。戻り値が空でなければ書き出し禁止。"""
        missing: list[str] = []
        if record.status != "confirmed":
            missing.append(f"not_confirmed:{record.status}")
        if not record.date:
            missing.append("date")
        if record.total is None:
            missing.append("total")
        if not record.category:
            missing.append("category")
        missing.extend(self.extra_validate(record))
        return missing

    def extra_validate(self, record: Record) -> list[str]:
        """アダプタ固有の追加検証(任意)。"""
        return []

    def emit(self, records: list[Record], out_dir: str | Path) -> tuple[Path, list[str]]:
        """検証を通ったレコードだけ書き出す。戻り値: (出力パス, 弾いた理由ログ)"""
        ok, rejected = [], []
        for r in records:
            problems = self.validate(r)
            if problems:
                rejected.append(f"{r.source_image}: {','.join(problems)}")
            else:
                ok.append(r)
        path = self.write(ok, Path(out_dir))
        return path, rejected

    @abstractmethod
    def write(self, records: list[Record], out_dir: Path) -> Path: ...
