"""APIキーの保管(UI要件 R3, R20)。

- 保存先は Mac のキーチェーン(keyring 経由)。ファイルには書かない
- 環境変数 ANTHROPIC_API_KEY があればそれを優先する(開発者・CLI 向け)
- キーチェーンが使えない環境(CIなど)では「未設定」として扱い、落ちない
"""
from __future__ import annotations

import os

SERVICE = "ReceiptPilot"
ACCOUNT = "anthropic_api_key"


def _keyring():
    if os.environ.get("RECEIPTPILOT_NO_KEYRING"):  # テスト中は本物のキーチェーンを触らない
        return None
    try:
        import keyring
        return keyring
    except ImportError:
        return None


def get_api_key() -> str | None:
    env = os.environ.get("ANTHROPIC_API_KEY")
    if env:
        return env
    kr = _keyring()
    if kr is None:
        return None
    try:
        return kr.get_password(SERVICE, ACCOUNT)
    except Exception:  # noqa: BLE001 — キーチェーンが使えない環境
        return None


def key_source() -> str | None:
    """どこからキーを読んでいるか(画面表示用)。"""
    if os.environ.get("ANTHROPIC_API_KEY"):
        return "環境変数"
    return "キーチェーン" if get_api_key() else None


def save_api_key(key: str) -> None:
    kr = _keyring()
    if kr is None:
        raise RuntimeError("キーチェーンを利用できません")
    kr.set_password(SERVICE, ACCOUNT, key)


def delete_api_key() -> None:
    kr = _keyring()
    if kr is None:
        return
    try:
        kr.delete_password(SERVICE, ACCOUNT)
    except Exception:  # noqa: BLE001 — 未保存なら何もしない
        pass


def clean_key(raw: str) -> tuple[str, str | None]:
    """貼り付けられたキーを整える。戻り値: (整えたキー, 問題があれば日本語の説明)。"""
    key = "".join(raw.split())  # 前後・途中の空白や改行を取り除く
    if not key:
        return key, "APIキーを貼り付けてください"
    if not key.startswith("sk-ant-"):
        return key, "Anthropic のAPIキーは「sk-ant-」で始まります。コピーした内容を確認してください"
    if len(key) < 40:
        return key, "APIキーが短すぎます。途中までしかコピーされていない可能性があります"
    return key, None


def mask(key: str | None) -> str:
    return f"sk-ant-…{key[-4:]}" if key else "未設定"
