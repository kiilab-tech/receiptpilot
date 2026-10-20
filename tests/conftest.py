"""全テスト共通: 本物のキーチェーン・APIキー・データ置き場に触れない。"""
import pytest


@pytest.fixture(autouse=True)
def _isolate(monkeypatch, tmp_path):
    monkeypatch.setenv("RECEIPTPILOT_NO_KEYRING", "1")
    monkeypatch.setenv("RECEIPTPILOT_NO_EXIT", "1")
    monkeypatch.setenv("RECEIPTPILOT_DATA", str(tmp_path / "data"))
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("RECEIPTPILOT_EXTRACTOR", raising=False)
