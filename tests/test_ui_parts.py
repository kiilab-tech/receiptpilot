"""かんたん版(ターミナル不要化)の部品と画面のテスト。docs/UI要件定義.md の R 番号に対応。

APIキー・キーチェーン・本物のデータ置き場には触れない(conftest.py)。
"""
from __future__ import annotations

import io
import json
import sys
from pathlib import Path

import httpx
import pytest
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from receiptpilot import credentials, settings
from receiptpilot.extract import describe_error
from receiptpilot.intake import MAX_FILES, accept_uploads
from receiptpilot.paths import Paths
from receiptpilot.pipeline import pending_images
from receiptpilot.rules import PayeeRules
from receiptpilot.schema import Record
from receiptpilot.store import Store


def png(seed: int) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (8, 8 + seed), "white").save(buf, format="PNG")
    return buf.getvalue()


def rec(h: str, status: str = "review") -> Record:
    return Record(source_image=f"{h}.png", image_hash=h, payee_raw="店", payee="店",
                  date="2026-10-01", total=100, category="食費", status=status)


# --- R1, R2, R13: 写真の受け付け ------------------------------------------------

def test_intake_saves_images_and_skips_duplicates(tmp_path):
    store = Store(tmp_path / "store/records.jsonl")
    inbox = tmp_path / "inbox"
    res = accept_uploads([("a.png", png(1)), ("b.PNG", png(2))], inbox, store)
    assert res.saved == ["a.png", "b.PNG"] and not res.skipped
    # 同じ写真をもう一度(別名でも)入れても取り込まない
    res = accept_uploads([("again.png", png(1))], inbox, store)
    assert not res.saved and "取り込み済み" in res.skipped[0]
    assert len(pending_images(inbox, store)) == 2


def test_intake_rejects_wrong_type_fake_image_and_too_many(tmp_path):
    store = Store(tmp_path / "store/records.jsonl")
    inbox = tmp_path / "inbox"
    res = accept_uploads([("doc.pdf", b"%PDF-1.4"), ("fake.jpg", b"not an image")], inbox, store)
    assert not res.saved
    assert "JPEG・PNG・HEIC" in res.skipped[0] and "開けません" in res.skipped[1]
    many = [(f"r{i}.png", png(i)) for i in range(MAX_FILES + 2)]
    res = accept_uploads(many, inbox, store)
    assert len(res.saved) == MAX_FILES and len(res.skipped) == 2


def test_intake_keeps_names_inside_inbox(tmp_path):
    store = Store(tmp_path / "store/records.jsonl")
    inbox = tmp_path / "inbox"
    accept_uploads([("../../evil.png", png(3))], inbox, store)
    assert [p.parent for p in inbox.iterdir()] == [inbox]


# --- R10, R14: 保存データ ---------------------------------------------------------

def test_store_survives_a_truncated_last_line(tmp_path):
    store = Store(tmp_path / "records.jsonl")
    store.append(rec("h1"))
    with store.path.open("a", encoding="utf-8") as f:
        f.write('{"source_image": "h2.png", "image_ha')  # 書き込み途中で電源断
    assert list(store.load_all()) == ["h1"]
    assert store.recovered_lines == 1
    assert store.path.with_suffix(".broken.jsonl").exists()
    store.append(rec("h3"))  # 以後の追記も壊れない
    assert set(Store(store.path).load_all()) == {"h1", "h3"}


def test_append_after_truncation_starts_on_a_new_line(tmp_path):
    store = Store(tmp_path / "records.jsonl")
    store.path.write_text('{"broken', encoding="utf-8")
    store.append(rec("h1"))
    assert set(Store(store.path).load_all()) == {"h1"}


def test_deleted_record_is_hidden_and_can_be_processed_again(tmp_path):
    store = Store(tmp_path / "records.jsonl")
    r = rec("h1", "confirmed")
    store.append(r)
    store.delete(r)
    assert store.load_all() == {} and not store.seen("h1")
    assert store.stats()["total"] == 0


# --- R11: ルールの保存 -----------------------------------------------------------

def test_rules_save_is_atomic_and_remove_works(tmp_path):
    path = tmp_path / "payee_rules.yaml"
    rules = PayeeRules([])
    rules.add("イオン", "食費")
    rules.add("コーナン", "日用品")
    rules.save(path)
    assert not path.with_suffix(".tmp").exists()
    rules.remove("イオン")
    rules.save(path)
    assert [r["pattern"] for r in PayeeRules.load(path).rules] == ["コーナン"]


def test_ui_saves_rules_to_data_dir_not_to_masters(tmp_path):
    paths = Paths(tmp_path)
    assert paths.rules == ROOT / "masters/payee_rules.yaml"  # 初回は同梱のルールを読む
    assert paths.rules_writable == tmp_path / "payee_rules.yaml"


# --- R3, R20: APIキー ------------------------------------------------------------

@pytest.mark.parametrize("raw, ok", [
    ("  sk-ant-api03-" + "x" * 40 + "\n", True),     # 前後の空白・改行は取り除く
    ("sk-ant-api03-" + "x" * 20 + " " + "x" * 20, True),
    ("", False),
    ("sk-proj-" + "x" * 40, False),                   # 別サービスのキー
    ("sk-ant-api03-abc", False),                      # 途中まで
])
def test_clean_key(raw, ok):
    key, problem = credentials.clean_key(raw)
    assert (problem is None) == ok
    assert " " not in key and "\n" not in key


def test_key_is_masked_and_keychain_is_not_touched_in_tests():
    assert credentials.mask("sk-ant-api03-abcdWXYZ") == "sk-ant-…WXYZ"
    assert credentials.get_api_key() is None
    with pytest.raises(RuntimeError):
        credentials.save_api_key("sk-ant-test")


# --- R4: 日本語のエラー ------------------------------------------------------------

def _api_error(cls, status: int, message: str = "error"):
    req = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    return cls(message, response=httpx.Response(status, request=req), body=None)


@pytest.mark.parametrize("make, word", [
    (lambda a: _api_error(a.AuthenticationError, 401), "APIキーが正しくありません"),
    (lambda a: _api_error(a.BadRequestError, 400, "Your credit balance is too low"), "残高"),
    (lambda a: _api_error(a.RateLimitError, 429), "待って"),
    (lambda a: _api_error(a.InternalServerError, 500), "混み合って"),
    (lambda a: a.APIConnectionError(request=httpx.Request("POST", "https://x")), "インターネット"),
])
def test_errors_are_explained_in_japanese(make, word):
    import anthropic
    assert word in describe_error(make(anthropic))


# --- 設定 --------------------------------------------------------------------------

def test_settings_fall_back_to_default_model(tmp_path):
    (tmp_path / "settings.json").write_text(json.dumps({"model": "no-such-model"}))
    assert settings.load(tmp_path)["model"] == "claude-sonnet-4-6"
    settings.save(tmp_path, {"model": "claude-haiku-4-5"})
    assert settings.load(tmp_path)["model"] == "claude-haiku-4-5"
    assert settings.cost_per_image("claude-haiku-4-5") < settings.cost_per_image("claude-sonnet-4-6")


# --- 画面(Streamlit AppTest) ------------------------------------------------------

APP = str(ROOT / "app/streamlit_app.py")


def _texts(at) -> str:
    parts = [e.value for kind in ("markdown", "warning", "info", "success", "error", "title")
             for e in getattr(at, kind)]
    return "\n".join(str(p) for p in parts)


def test_first_launch_guides_user_to_register_api_key():
    from streamlit.testing.v1 import AppTest
    at = AppTest.from_file(APP, default_timeout=30).run()
    assert not at.exception
    text = _texts(at)
    assert "APIキーを登録してください" in text and "使い方" in text


def test_demo_mode_works_without_api_key():
    from streamlit.testing.v1 import AppTest
    at = AppTest.from_file(APP, default_timeout=30).run()
    at.sidebar.toggle(key="demo").set_value(True).run()
    assert not at.exception
    assert "お試しモード" in _texts(at)
    assert [m.value for m in at.sidebar.metric] == ["2", "5"]  # 確定2・確認待ち5


def test_quit_button_shows_goodbye_page():
    from streamlit.testing.v1 import AppTest
    at = AppTest.from_file(APP, default_timeout=30).run()
    next(b for b in at.sidebar.button if b.label == "終了する").click().run()
    assert "終了しました" in _texts(at)


# --- 判定理由の言い換え(一般の人向け) -------------------------------------------

def _judged(total, items, tax=None, category="食費", rule_hit=True, d="2026-10-09"):
    from datetime import date
    from receiptpilot.explain import explain
    from receiptpilot.judge import judge
    from receiptpilot.schema import Extraction, LineItem
    ex = Extraction(payee_raw="まちかどマート", date=d, total=total, tax=tax,
                    items=[LineItem(n, a) for n, a in items])
    r = Record(source_image="x.png", image_hash="h", payee_raw="まちかどマート", payee="まちかどマート",
               date=d, total=total, category=category, extraction=ex)
    j = judge(r, ex, rule_hit=rule_hit, today=date(2026, 10, 20))
    r.status, r.reasons = j.status, j.reasons
    return r, explain(r)


def test_sum_mismatch_explains_both_causes_with_amounts():
    r, exps = _judged(1000, [("乾電池", 500), ("ノート", 300)], tax=90)
    assert r.status == "review" and len(exps) == 1
    assert "800円" in exps[0].title and "1,000円" in exps[0].title
    assert "写真と読み取り結果が違う" in exps[0].advice
    assert "支払った合計金額のまま" in exps[0].advice


@pytest.mark.parametrize("kwargs, word", [
    (dict(total=500, items=[], category=None, rule_hit=False), "初めての店"),
    (dict(total=34800, items=[]), "高額"),
    (dict(total=24200, items=[]), "いつもの店"),
    (dict(total=500, items=[], d="2026-12-01"), "未来"),
    (dict(total=0, items=[]), "0円"),
])
def test_every_review_reason_has_plain_advice(kwargs, word):
    r, exps = _judged(**kwargs)
    assert r.status == "review"
    assert any(word in e.title for e in exps)
    assert all(e.advice for e in exps)
    assert not any("!=" in e.title or "既知" in e.title for e in exps)  # 専門的な記号・用語を出さない


def test_unknown_reason_still_gives_advice():
    from receiptpilot.explain import explain
    r = rec("h1")
    r.reasons = ["想定外の理由"]
    assert explain(r)[0].advice


def test_demo_starts_fresh_every_time_it_is_turned_on(tmp_path):
    """前回の続きが残っていても、お試しモードをオンにすると最初の状態に戻る。"""
    from streamlit.testing.v1 import AppTest
    from receiptpilot.demo import demo_paths, reset_demo
    from receiptpilot.paths import get_paths
    dp = demo_paths(get_paths())
    reset_demo(dp)
    store = Store(dp.store)
    for r in list(store.load_all().values()):  # 前回すべて確定した状態を作る
        r.status = "confirmed"
        store.update(r)
    assert Store(dp.store).stats()["review"] == 0

    at = AppTest.from_file(APP, default_timeout=30).run()
    at.sidebar.toggle(key="demo").set_value(True).run()
    assert not at.exception
    assert [m.value for m in at.sidebar.metric] == ["2", "5"]


# --- Web お試し版(docs/Web版要件定義.md) ------------------------------------------

WEB = str(ROOT / "app/web_demo.py")


@pytest.fixture
def web_tmp(monkeypatch, tmp_path):
    import tempfile
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))
    yield tmp_path
    monkeypatch.delenv("RECEIPTPILOT_WEB_DEMO", raising=False)


def test_web_demo_opens_with_fake_receipts_and_hides_real_features(web_tmp):
    from streamlit.testing.v1 import AppTest
    at = AppTest.from_file(WEB, default_timeout=30).run()
    assert not at.exception
    text = _texts(at)
    assert "Web お試し版" in text and "Mac 版" in text
    assert [m.value for m in at.sidebar.metric] == ["2", "5"]
    labels = [b.label for b in at.button] + [b.label for b in at.sidebar.button]
    assert "終了する" not in labels                           # W9
    assert not at.get("file_uploader") and not at.toggle      # W1: 取り込みなし・切り替えなし


def test_web_demo_visitors_do_not_share_data(web_tmp):
    from streamlit.testing.v1 import AppTest
    a = AppTest.from_file(WEB, default_timeout=30).run()
    b = AppTest.from_file(WEB, default_timeout=30).run()
    da, db = Path(a.session_state["web_dir"]), Path(b.session_state["web_dir"])
    assert da != db                                            # W5
    store = Store(Paths(da).data / "demo/store/records.jsonl")
    for r in list(store.load_all().values()):                  # A さんが全部確定
        r.status = "confirmed"
        store.update(r)
    assert [m.value for m in a.run().sidebar.metric] == ["7", "0"]
    assert [m.value for m in b.run().sidebar.metric] == ["2", "5"]


def test_web_demo_removes_old_visitor_folders(web_tmp):
    import os
    import time
    from streamlit.testing.v1 import AppTest
    old = web_tmp / "receiptpilot-web" / "old_visitor"
    old.mkdir(parents=True)
    past = time.time() - 7 * 3600
    os.utime(old, (past, past))
    AppTest.from_file(WEB, default_timeout=30).run()
    assert not old.exists()                                    # W6
