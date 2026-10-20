"""判定理由を、一般の人向けの「何が起きたか + どうすればよいか」に言い換える。

judge.py が記録する理由(reasons)は監査用の短い記録なので、そのまま残す。
画面ではこのモジュールの言い換えを表示し、元の記録は「詳細」として添える。
"""
from __future__ import annotations

from dataclasses import dataclass

from .judge import HARD_LIMIT, RULE_TRUSTED_LIMIT, UNKNOWN_LIMIT
from .schema import Record


@dataclass
class Explanation:
    title: str     # 何が起きたか
    advice: str    # どうすればよいか


def yen(n: int | None) -> str:
    return f"{n:,}円" if n is not None else "不明"


def _sum_mismatch(r: Record) -> Explanation:
    ex = r.extraction
    items = ex.items_sum() if ex else None
    title = f"明細の合計({yen(items)})と合計金額({yen(r.total)})が合いません"
    advice = ("- **写真と読み取り結果が違う**(AIの読み間違い)→ 写真に合わせて金額を直してください\n"
              "- **写真のとおりに読めている** → 値引き・クーポン・レジ袋などの行が明細に入っていない"
              "可能性があります。**支払った合計金額のまま**確定してください")
    return Explanation(title, advice)


def explain(r: Record) -> list[Explanation]:
    out: list[Explanation] = []
    for reason in r.reasons:
        if reason.startswith("必須項目欠落"):
            if "費目" in reason:
                out.append(Explanation(
                    "初めての店です(自分ルールにありません)",
                    "費目を選んで確定してください。同じ店を2回確定すると、"
                    "「自分ルール」に登録する候補として提案されます。"))
            if "日付" in reason:
                out.append(Explanation("日付を読み取れませんでした",
                                       "写真を見て、日付を入力してください。"))
            if "金額" in reason:
                out.append(Explanation("合計金額を読み取れませんでした",
                                       "写真を見て、合計金額を入力してください。"))
        elif reason.startswith("日付形式不正"):
            out.append(Explanation(f"日付を正しく読み取れませんでした(読み取り結果: {r.date})",
                                   "写真を見て、正しい日付に直してください。"))
        elif reason.startswith("未来日付"):
            out.append(Explanation(f"日付が未来になっています({r.date})",
                                   "読み間違いの可能性があります。写真を見て、日付を直してください。"))
        elif reason.startswith("金額が0以下"):
            out.append(Explanation(f"合計金額が{yen(r.total)}になっています",
                                   "写真を見て、合計金額を直してください。"))
        elif reason.startswith("検算不一致"):
            out.append(_sum_mismatch(r))
        elif reason.startswith("高額"):
            out.append(Explanation(
                f"{yen(HARD_LIMIT)}を超える高額なレシートです",
                "金額の大きいものは、念のため必ず人が確認します。"
                "写真と見比べて、合っていれば確定してください。"))
        elif reason.startswith("ルール既知店だが"):
            out.append(Explanation(
                f"いつもの店ですが、{yen(RULE_TRUSTED_LIMIT)}を超えています",
                "金額の大きいものは、念のため人が確認します。"
                "写真と見比べて、合っていれば確定してください。"))
        elif reason.startswith("未知店 かつ"):
            out.append(Explanation(
                f"初めての店で、{yen(UNKNOWN_LIMIT)}を超えています",
                "写真と見比べて、費目を確かめてから確定してください。"))
        elif reason == "人が確定を取り消し":
            out.append(Explanation("確定を取り消したレシートです",
                                   "内容を直して、もう一度確定してください。"))
    if not out:  # 想定外の理由でも、何をすればよいかは必ず示す
        out.append(Explanation("確認が必要です",
                               "写真と見比べて、内容が合っていれば確定してください。"))
    return out
