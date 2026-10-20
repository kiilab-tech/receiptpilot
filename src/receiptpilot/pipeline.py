"""パイプライン: 取込 → 抽出 → ルール → 判定 → 保存。

原則:
1. 迷ったら安全側(review)へ倒す
2. 自分ルールがAIの推測に勝つ
3. コアは共通、違いはアダプタだけ
"""
from __future__ import annotations

from pathlib import Path
from typing import Callable

from .extract import Extractor, describe_error
from .judge import judge
from .rules import PayeeRules, brand_from_raw
from .schema import Record, file_hash
from .store import Store

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".heic", ".heif"}


def guess_category_by_ai(extraction) -> str | None:
    """AI由来の費目推測(MVPでは未実装: 抽出時に費目を推測させない設計)。

    費目の第一決定者は payee_rules(原則2)。ルールに無い店は
    費目None → judge が必須項目欠落で review に落とす → 人が決める →
    learn がルール候補化、という「人がルールを育てる」ループを回す。
    """
    return None


def pending_images(inbox: str | Path, store: Store) -> list[tuple[Path, str]]:
    """inbox のうち、まだ保存されていない画像の (パス, ハッシュ) 一覧。"""
    inbox = Path(inbox)
    if not inbox.exists():
        return []
    seen = store.load_all()
    out = []
    for p in sorted(inbox.iterdir()):
        if p.suffix.lower() not in IMAGE_EXTS:
            continue
        h = file_hash(str(p))
        if h not in seen:
            out.append((p, h))
            seen[h] = None  # 同じ内容のファイルが2つあっても1回だけ処理する
    return out


def process_inbox(
    inbox: str | Path,
    store: Store,
    rules: PayeeRules,
    extractor: Extractor,
    errors: list[str] | None = None,
    on_progress: Callable[[int, int, str], None] | None = None,
) -> list[Record]:
    """inbox の未処理画像を処理して保存。処理した Record 一覧を返す。

    1枚の抽出失敗(API障害・壊れた画像など)で全体を止めない。失敗分は保存せず
    errors に理由を積む(保存しないので次回の process で再挑戦される)。
    """
    done: list[Record] = []
    todo = pending_images(inbox, store)
    for i, (p, h) in enumerate(todo):
        if on_progress:
            on_progress(i, len(todo), p.name)
        try:
            ex = extractor.extract(str(p))
        except Exception as e:  # noqa: BLE001 — 1枚の失敗でバッチを止めない
            if errors is not None:
                errors.append(f"{p.name}: {describe_error(e)}")
            continue

        hit = rules.match(ex.payee_raw)
        if hit:
            payee = hit.brand or brand_from_raw(ex.payee_raw)
            category = hit.category
            origin = "rule"
        else:
            payee = brand_from_raw(ex.payee_raw)
            category = guess_category_by_ai(ex)
            origin = "extractor" if category else None

        rec = Record(
            source_image=p.name,
            image_hash=h,
            payee_raw=ex.payee_raw,
            payee=payee,
            date=ex.date,
            total=ex.total,
            category=category,
            category_origin=origin,
            extraction=ex,
        )
        j = judge(rec, ex, rule_hit=bool(hit))
        rec.status = j.status
        rec.reasons = j.reasons

        store.append(rec)
        done.append(rec)
    return done


def confirm_record(
    store: Store,
    record: Record,
    category: str,
    learner=None,
) -> Record:
    """人手確定 (Streamlit UI から呼ばれる)。"""
    record.category = category
    record.category_origin = "human"
    record.status = "confirmed"
    record.reasons = record.reasons + ["人手確定"]
    store.update(record)
    if learner:
        learner.note_confirmation(record.payee_raw, category, payee=record.payee)
    return record
