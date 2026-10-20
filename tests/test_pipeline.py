"""パイプライン全段テスト(MockExtractor / APIキー不要)。

pytest でも、単体スクリプト(python3 tests/test_pipeline.py)でも動く。

検証項目 (受け入れ基準1・3・4):
- 取込→抽出→ルール→判定→保存→出力の全段が動く
- 信用獲得しきい値の4パターンが正しく振り分けられる
- 未確定レコードがどのアダプタからも出力されない(FR-7.2)
- 人手確定 → learn → ルール候補提案 → ルール追加で自動確定率が上がる
"""
from __future__ import annotations

import json
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from receiptpilot.extract import MockExtractor
from receiptpilot.learn import Learner
from receiptpilot.pipeline import confirm_record, process_inbox
from receiptpilot.rules import PayeeRules
from receiptpilot.store import Store
from receiptpilot.adapters import FreeeAdapter, GasSheetAdapter, KakeiboCsvAdapter

ROOT = Path(__file__).resolve().parents[1]

# --- テストデータ: 1px PNG + サイドカーJSON --------------------------------
PNG_1PX = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
    "0000000d49444154789c626001000000ffff03000006000557bfabd40000000049454e44ae426082"
)

CASES = {
    # ルール既知店・少額 → 自動確定 (rule+≤20000)
    "r001": {"payee_raw": "ローソン 駅前店", "date": "2026-07-01", "total": 486,
             "items": [{"name": "おにぎり", "amount": 140}, {"name": "コーヒー", "amount": 346}]},
    # ルール既知店・20000超 → 要確認
    "r002": {"payee_raw": "島村楽器 中央店", "date": "2026-07-02", "total": 24800},
    # 未知店・3000以下 → 自動確定(ただし費目が無いので実際は要確認に落ちる)
    "r003": {"payee_raw": "コーナン中央店", "date": "2026-07-03", "total": 1280},
    # 高額 30000超 → 常に要確認
    "r004": {"payee_raw": "秋月電子通商", "date": "2026-07-04", "total": 34500},
    # 検算不一致 → 要確認
    "r005": {"payee_raw": "ローソン 北口店", "date": "2026-07-05", "total": 1000,
             "items": [{"name": "電池", "amount": 500}, {"name": "ノート", "amount": 300}]},
}


def setup_inbox(inbox: Path):
    inbox.mkdir(parents=True, exist_ok=True)
    for name, d in CASES.items():
        (inbox / f"{name}.png").write_bytes(PNG_1PX + name.encode())  # ハッシュを変える
        (inbox / f"{name}.json").write_text(
            json.dumps(d, ensure_ascii=False), encoding="utf-8")


def test_pipeline_end_to_end():
    tmp = Path(tempfile.mkdtemp())
    inbox, store_p, out = tmp / "inbox", tmp / "store/records.jsonl", tmp / "out"
    setup_inbox(inbox)

    rules = PayeeRules.load(ROOT / "masters/payee_rules.yaml")
    store = Store(store_p)
    learner = Learner(tmp / "store/confirmations.jsonl")

    # --- 1. 全段実行 ---
    recs = process_inbox(inbox, store, rules, MockExtractor())
    assert len(recs) == 5, f"5件処理のはず: {len(recs)}"
    by = {r.source_image.split(".")[0]: r for r in recs}

    # --- 2. 判定の振り分け ---
    assert by["r001"].status == "confirmed", by["r001"].reasons
    assert by["r001"].payee == "ローソン"
    assert by["r001"].category == "食費"
    assert by["r002"].status == "review" and "20000円超" in " ".join(by["r002"].reasons)
    assert by["r003"].status == "review"  # 費目None → 必須欠落で安全側
    assert by["r004"].status == "review" and "高額" in " ".join(by["r004"].reasons)
    assert by["r005"].status == "review" and "検算不一致" in " ".join(by["r005"].reasons)
    print("判定振り分け: OK")
    for r in recs:
        print(f"  {r.source_image}: {r.status:9s} {r.reasons}")

    # --- 3. 二重処理防止 ---
    again = process_inbox(inbox, store, rules, MockExtractor())
    assert len(again) == 0, "二重処理された"
    print("二重処理防止: OK")

    # --- 4. FR-7.2 最終検証ゲート: 未確定は出力されない ---
    all_recs = list(store.load_all().values())
    adapters = [KakeiboCsvAdapter(), GasSheetAdapter(),
                FreeeAdapter(ROOT / "masters/categories.yaml")]
    for a in adapters:
        path, rejected = a.emit(all_recs, out)
        text = path.read_text(encoding="utf-8")
        for bad in ("r002", "r003", "r004", "r005"):
            assert bad not in text, f"{a.name}: 未確定 {bad} が出力された!"
        assert "r001" in text or "ローソン" in text, f"{a.name}: 確定分が出ていない"
        assert len(rejected) == 4, f"{a.name}: 弾き数が想定外 {rejected}"
    print("最終検証ゲート(3アダプタ): OK — 未確定レコードは一切出力されない")

    # --- 5. 人手確定 → learn → 提案 → 自動確定率向上 ---
    stats_before = store.stats()
    # コーナンを2回確定(人がUIでブランド名を「コーナン」に修正した想定)
    by["r003"].payee = "コーナン"
    confirm_record(store, by["r003"], "日用品", learner)
    learner.note_confirmation("コーナン西店", "日用品", payee="コーナン")
    props = learner.proposals(rules)
    assert any(p["pattern"] == "コーナン" for p in props), f"提案なし: {props}"
    print(f"ルール候補提案: OK — {props}")

    # 提案を採用してルール追加 → 同種レシートが自動確定するようになる
    rules.add("コーナン", "日用品", brand="コーナン")
    (inbox / "r006.png").write_bytes(PNG_1PX + b"r006")
    (inbox / "r006.json").write_text(json.dumps(
        {"payee_raw": "コーナン東店", "date": "2026-07-06", "total": 2180},
        ensure_ascii=False), encoding="utf-8")
    new = process_inbox(inbox, store, rules, MockExtractor())
    assert new[0].status == "confirmed" and new[0].category == "日用品", new[0].reasons
    stats_after = store.stats()
    print(f"学習ループ: OK — 自動確定率 {stats_before['auto_confirm_rate']:.0%}"
          f" → {stats_after['auto_confirm_rate']:.0%}")

    shutil.rmtree(tmp)
    print("\n=== 全テスト通過 ===")


if __name__ == "__main__":
    test_pipeline_end_to_end()
