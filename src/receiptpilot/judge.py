"""信頼度判定 (FR-5)。「ルールが信用を獲得する」。

一律しきい値は機能しない(前回実測)。金額 × ルール既知性 の二軸:
- 30,000円超              → 常に要確認(絶対防衛線)
- 自分ルール既知の店       → 20,000円以下なら自動確定可
- ルール無し(AI推測のみ)  → 3,000円以下なら自動確定可
  (現状はAI費目推測が無いので、ルール無しの店は費目欠落で必ず要確認になる)
- 検算不一致・必須項目欠落 → 常に要確認
- 日付が不正・未来日付、金額が0以下 → 常に要確認(読み違いの典型)

判定理由は必ず reasons に残す(監査可能性)。
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date as _date

from .schema import Extraction, Record

HARD_LIMIT = 30_000        # これを超えたら無条件で要確認
RULE_TRUSTED_LIMIT = 20_000  # ルール既知店の自動確定上限
UNKNOWN_LIMIT = 3_000        # ルール無し店の自動確定上限


@dataclass
class Judgement:
    status: str            # "confirmed" or "review"
    reasons: list[str]


def judge(record: Record, extraction: Extraction, rule_hit: bool,
          today: _date | None = None) -> Judgement:
    reasons: list[str] = []

    # --- 必須項目 ---
    missing = []
    if not record.date:
        missing.append("日付")
    if record.total is None:
        missing.append("金額")
    if not record.category:
        missing.append("費目(自分ルールに無い店)")
    if missing:
        reasons.append(f"必須項目欠落: {','.join(missing)}")
        return Judgement("review", reasons)

    # --- 値の妥当性(VLMの読み違いの典型を止める) ---
    try:
        d = _date.fromisoformat(record.date)
    except ValueError:
        reasons.append(f"日付形式不正: {record.date}")
        return Judgement("review", reasons)
    if d > (today or _date.today()):
        reasons.append(f"未来日付: {record.date}")
        return Judgement("review", reasons)
    if record.total <= 0:
        reasons.append(f"金額が0以下: {record.total}")
        return Judgement("review", reasons)

    # --- 検算 ---
    m = extraction.sum_matches_total()
    if m is False:
        reasons.append(
            f"検算不一致: 明細計{extraction.items_sum()} != 合計{extraction.total}")
        return Judgement("review", reasons)
    if m is True:
        reasons.append("検算一致")
    else:
        reasons.append("明細なし(検算スキップ)")

    total = record.total
    assert total is not None

    # --- 金額 × 信用 ---
    if total > HARD_LIMIT:
        reasons.append(f"高額({total}円 > {HARD_LIMIT}円): 常に要確認")
        return Judgement("review", reasons)

    if rule_hit:
        if total <= RULE_TRUSTED_LIMIT:
            reasons.append(f"ルール既知店 かつ {RULE_TRUSTED_LIMIT}円以下: 自動確定")
            return Judgement("confirmed", reasons)
        reasons.append(f"ルール既知店だが {RULE_TRUSTED_LIMIT}円超: 要確認")
        return Judgement("review", reasons)

    if total <= UNKNOWN_LIMIT:
        reasons.append(f"未知店だが少額({UNKNOWN_LIMIT}円以下): 自動確定")
        return Judgement("confirmed", reasons)

    reasons.append(f"未知店 かつ {UNKNOWN_LIMIT}円超: 要確認")
    return Judgement("review", reasons)
