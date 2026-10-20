"""保存 (FR-9)。JSONL追記型ストア。DB不要。

- 同一 image_hash の二重処理を防止 (FR-1)
- update は「同一 image_hash の最新行が有効」という追記セマンティクス
  (履歴が残る = 監査可能。コンパクションは将来課題)
- 書き込み途中の中断(スリープ・電源断)で壊れた行があっても読み込みを止めない。
  壊れた行は *.broken.jsonl へ退避し、本体から取り除く(UI要件 R10)
- 削除は status="deleted" の行を追記する。削除済みは一覧・統計・出力に出さず、
  同じ画像を入れ直せば再処理される(UI要件 R14)
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from .schema import Record


class Store:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.recovered_lines = 0  # 退避した壊れた行の数(UI表示用)

    def _latest(self) -> dict[str, Record]:
        """image_hash -> 最新Record(削除済みを含む)。壊れた行は退避する。"""
        out: dict[str, Record] = {}
        if not self.path.exists():
            return out
        good, bad = [], []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                r = Record.from_json(line)
            except (json.JSONDecodeError, TypeError, KeyError, ValueError):
                bad.append(line)
                continue
            good.append(line)
            out[r.image_hash] = r
        if bad:
            self._quarantine(good, bad)
        return out

    def _quarantine(self, good: list[str], bad: list[str]) -> None:
        broken = self.path.with_suffix(".broken.jsonl")
        with broken.open("a", encoding="utf-8") as f:
            f.write("\n".join(bad) + "\n")
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text("".join(g + "\n" for g in good), encoding="utf-8")
        os.replace(tmp, self.path)  # 置き換えは一瞬で終わるので途中で壊れない
        self.recovered_lines += len(bad)

    def load_all(self) -> dict[str, Record]:
        """image_hash -> 最新Record(削除済みは除く)"""
        return {h: r for h, r in self._latest().items() if r.status != "deleted"}

    def seen(self, image_hash: str) -> bool:
        return image_hash in self.load_all()

    def append(self, record: Record) -> None:
        # 前回の書き込みが途中で切れていても、新しい行が巻き込まれないよう改行から始める
        needs_newline = False
        if self.path.exists() and self.path.stat().st_size > 0:
            with self.path.open("rb") as f:
                f.seek(-1, os.SEEK_END)
                needs_newline = f.read(1) != b"\n"
        with self.path.open("a", encoding="utf-8") as f:
            f.write(("\n" if needs_newline else "") + record.to_json() + "\n")

    def update(self, record: Record) -> None:
        """追記=更新。最新行が有効。"""
        self.append(record)

    def delete(self, record: Record) -> None:
        """削除(削除済みの行を追記)。履歴は残る。"""
        record.status = "deleted"
        record.reasons = record.reasons + ["人が削除"]
        self.append(record)

    def stats(self) -> dict:
        recs = list(self.load_all().values())
        n = len(recs)
        confirmed = [r for r in recs if r.status == "confirmed"]
        # 自動確定率は「人の手を介さず確定した割合」。人手確定は数えない
        auto = sum(1 for r in confirmed if r.category_origin != "human")
        return {
            "total": n,
            "confirmed": len(confirmed),
            "auto_confirmed": auto,
            "manual_confirmed": len(confirmed) - auto,
            "review": sum(1 for r in recs if r.status == "review"),
            "auto_confirm_rate": (auto / n) if n else 0.0,
        }
