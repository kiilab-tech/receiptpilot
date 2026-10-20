"""保存 (FR-9)。JSONL追記型ストア。DB不要。

- 同一 image_hash の二重処理を防止 (FR-1)
- update は「同一 image_hash の最新行が有効」という追記セマンティクス
  (履歴が残る = 監査可能。コンパクションは将来課題)
"""
from __future__ import annotations

from pathlib import Path

from .schema import Record


class Store:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def load_all(self) -> dict[str, Record]:
        """image_hash -> 最新Record"""
        out: dict[str, Record] = {}
        if not self.path.exists():
            return out
        for line in self.path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            r = Record.from_json(line)
            out[r.image_hash] = r
        return out

    def seen(self, image_hash: str) -> bool:
        return image_hash in self.load_all()

    def append(self, record: Record) -> None:
        with self.path.open("a", encoding="utf-8") as f:
            f.write(record.to_json() + "\n")

    def update(self, record: Record) -> None:
        """追記=更新。最新行が有効。"""
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
