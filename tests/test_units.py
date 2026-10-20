"""部品ごとの単体テスト(APIキー不要)。

判定しきい値の境界、店名正規化、ルールの優先順位、最終検証ゲート、
画像の前処理、抽出失敗時の継続を確かめる。
"""
from __future__ import annotations

import io
import json
import sys
from datetime import date
from pathlib import Path

import pytest
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from receiptpilot.adapters import KakeiboCsvAdapter
from receiptpilot.extract import MockExtractor, prepare_image
from receiptpilot.judge import HARD_LIMIT, RULE_TRUSTED_LIMIT, UNKNOWN_LIMIT, judge
from receiptpilot.pipeline import process_inbox
from receiptpilot.rules import PayeeRules, brand_from_raw, normalize_text
from receiptpilot.schema import Extraction, LineItem, Record
from receiptpilot.store import Store

TODAY = date(2026, 10, 20)


def make(total: int | None, category: str | None = "食費", d: str | None = "2026-10-01",
         items: list[LineItem] | None = None) -> tuple[Record, Extraction]:
    ex = Extraction(payee_raw="テスト商店", date=d, total=total, items=items or [])
    rec = Record(source_image="x.png", image_hash="h", payee_raw="テスト商店",
                 payee="テスト商店", date=d, total=total, category=category)
    return rec, ex


# --- 判定しきい値: 境界の「以下は確定 / 超えたら要確認」 ---------------------

@pytest.mark.parametrize("total, rule_hit, expected", [
    (UNKNOWN_LIMIT, False, "confirmed"),
    (UNKNOWN_LIMIT + 1, False, "review"),
    (RULE_TRUSTED_LIMIT, True, "confirmed"),
    (RULE_TRUSTED_LIMIT + 1, True, "review"),
    (HARD_LIMIT, True, "review"),       # ルール既知でも 20,000円超は要確認
    (HARD_LIMIT + 1, True, "review"),
])
def test_judge_thresholds(total, rule_hit, expected):
    rec, ex = make(total)
    assert judge(rec, ex, rule_hit=rule_hit, today=TODAY).status == expected


def test_hard_limit_reason_is_recorded():
    rec, ex = make(HARD_LIMIT + 1)
    j = judge(rec, ex, rule_hit=True, today=TODAY)
    assert j.status == "review" and "高額" in " ".join(j.reasons)


@pytest.mark.parametrize("d, total, word", [
    ("2026-13-01", 500, "日付形式不正"),
    ("令和8年10月1日", 500, "日付形式不正"),
    ("2026-10-21", 500, "未来日付"),
    ("2026-10-01", 0, "金額が0以下"),
    ("2026-10-01", -300, "金額が0以下"),
])
def test_judge_rejects_implausible_values(d, total, word):
    rec, ex = make(total, d=d)
    j = judge(rec, ex, rule_hit=True, today=TODAY)
    assert j.status == "review" and word in " ".join(j.reasons)


def test_judge_missing_category_goes_to_review():
    rec, ex = make(500, category=None)
    j = judge(rec, ex, rule_hit=False, today=TODAY)
    assert j.status == "review" and "費目" in j.reasons[0]


def test_judge_sum_mismatch_goes_to_review_even_if_small():
    rec, ex = make(1000, items=[LineItem("a", 500), LineItem("b", 300)])
    j = judge(rec, ex, rule_hit=True, today=TODAY)
    assert j.status == "review" and "検算不一致" in j.reasons[0]


# --- 店名の正規化とルール ---------------------------------------------------

@pytest.mark.parametrize("raw, brand", [
    ("ローソン 駅前店", "ローソン"),
    ("ローソン　駅前店", "ローソン"),          # 全角スペース
    ("コーナン中央店", "コーナン中央店"),           # 区切りなし → 切らない(人が決める)
    ("セブン-イレブン中央町店", "セブン-イレブン中央町店"),
])
def test_brand_from_raw_only_splits_on_clear_delimiters(raw, brand):
    assert brand_from_raw(raw) == brand


def test_normalize_absorbs_width_and_case():
    assert normalize_text("ＡＢＣ　ﾏｰﾄ ") == normalize_text("abc マート")


def test_rule_priority_exact_beats_prefix_beats_partial():
    rules = PayeeRules([
        {"pattern": "マート", "match": "partial", "category": "部分"},
        {"pattern": "まちかどマート", "match": "prefix", "category": "前方"},
        {"pattern": "まちかどマート 駅前店", "match": "exact", "category": "完全"},
    ])
    assert rules.match("まちかどマート 駅前店").category == "完全"
    assert rules.match("まちかどマート 北口店").category == "前方"
    assert rules.match("よつかどマート").category == "部分"
    assert rules.match("八百屋") is None


# --- 最終検証ゲート -----------------------------------------------------------

def test_gate_blocks_unconfirmed_even_when_all_fields_are_filled(tmp_path):
    rec, _ = make(500)
    rec.status = "review"  # 項目は全部埋まっているが未確定
    path, rejected = KakeiboCsvAdapter().emit([rec], tmp_path)
    assert "テスト商店" not in path.read_text(encoding="utf-8")
    assert rejected and "not_confirmed" in rejected[0]


# --- 画像の前処理 -------------------------------------------------------------

def test_prepare_image_downscales_large_photo_to_jpeg(tmp_path):
    src = tmp_path / "big.png"
    Image.new("RGB", (4032, 3024), "white").save(src)
    out = Image.open(io.BytesIO(prepare_image(src)))
    assert out.format == "JPEG"
    assert max(out.size) == 1568


def test_prepare_image_applies_exif_rotation(tmp_path):
    src = tmp_path / "rot.jpg"
    exif = Image.Exif()
    exif[0x0112] = 6  # 90度回転して表示すべき写真
    Image.new("RGB", (300, 200), "white").save(src, exif=exif)
    out = Image.open(io.BytesIO(prepare_image(src)))
    assert out.size == (200, 300)


# --- 抽出失敗で全体を止めない -------------------------------------------------

def test_one_failed_extraction_does_not_stop_the_batch(tmp_path):
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    Image.new("RGB", (10, 10)).save(inbox / "a_ok.png")
    (inbox / "a_ok.json").write_text(json.dumps(
        {"payee_raw": "テスト商店", "date": "2026-10-01", "total": 100}), encoding="utf-8")
    Image.new("RGB", (10, 11)).save(inbox / "b_ng.png")   # サイドカー無し → 抽出失敗

    store = Store(tmp_path / "store/records.jsonl")
    errors: list[str] = []
    done = process_inbox(inbox, store, PayeeRules([]), MockExtractor(), errors)
    assert [r.source_image for r in done] == ["a_ok.png"]
    assert len(errors) == 1 and "b_ng.png" in errors[0]
    # 失敗分は保存していないので、次回また処理対象になる
    (inbox / "b_ng.json").write_text(json.dumps(
        {"payee_raw": "テスト商店", "date": "2026-10-02", "total": 200}), encoding="utf-8")
    again = process_inbox(inbox, store, PayeeRules([]), MockExtractor(), errors)
    assert [r.source_image for r in again] == ["b_ng.png"]


# --- 統計: 人手確定は自動確定率に数えない -------------------------------------

def test_auto_confirm_rate_excludes_human_confirmations(tmp_path):
    store = Store(tmp_path / "records.jsonl")
    for i, origin in enumerate(["rule", "human", None]):
        rec, _ = make(500)
        rec.image_hash = f"h{i}"
        rec.category_origin = origin
        rec.status = "review" if origin is None else "confirmed"
        store.append(rec)
    s = store.stats()
    assert (s["auto_confirmed"], s["manual_confirmed"], s["review"]) == (1, 1, 1)
    assert s["auto_confirm_rate"] == pytest.approx(1 / 3)


# --- CSV出力: Excelでの文字化け・数式実行を防ぐ -------------------------------

def test_csv_has_bom_and_neutralizes_formula_like_payee(tmp_path):
    rec, _ = make(500)
    rec.status = "confirmed"
    rec.payee = "=HYPERLINK(\"http://example.com\")"
    path, rejected = KakeiboCsvAdapter().emit([rec], tmp_path)
    raw = path.read_bytes()
    assert raw.startswith(b"\xef\xbb\xbf") and not rejected
    assert "'=HYPERLINK" in raw.decode("utf-8-sig")


# --- M1(実物レシート)で見つかった問題の再発防止 -----------------------------

@pytest.mark.parametrize("dash", ["‐", "‑", "–", "—", "−", "－"])
def test_rule_matches_even_if_ai_returns_another_hyphen(dash):
    rules = PayeeRules([{"pattern": "セブン-イレブン", "match": "partial", "category": "食費"}])
    assert rules.match(f"セブン{dash}イレブン 中央町店").category == "食費"


def test_long_vowel_mark_is_not_turned_into_hyphen():
    assert normalize_text("コーナン") == "コーナン"


def test_tax_exclusive_receipt_passes_sum_check():
    # 外税: 明細は税抜(288) + 税(23) = 合計(311)。セブン-イレブンの実物レシート
    rec, ex = make(311, items=[LineItem("紅茶", 170), LineItem("デニッシュ", 118)])
    ex.tax = 23
    j = judge(rec, ex, rule_hit=True, today=TODAY)
    assert j.status == "confirmed" and "外税" in j.reasons[0]


def test_tax_exclusive_off_by_one_yen_is_still_review():
    rec, ex = make(312, items=[LineItem("紅茶", 170), LineItem("デニッシュ", 118)])
    ex.tax = 23
    j = judge(rec, ex, rule_hit=True, today=TODAY)
    assert j.status == "review" and "検算不一致" in j.reasons[0]


def test_subtotal_lines_mixed_into_items_go_to_review():
    # AIが小計・税の行まで明細に入れた場合(トライアルの実物レシート)は安全側へ
    rec, ex = make(4347, items=[LineItem("天津飯", 368), LineItem("小計", 3986),
                                LineItem("8%外税", 144)])
    ex.tax = 361
    assert judge(rec, ex, rule_hit=True, today=TODAY).status == "review"
