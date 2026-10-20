"""抽出 (FR-2)。

- Claude API の tool 定義で型を強制する(自由文パースはしない)。
- モデルは設定で切替。既定 claude-sonnet-4-6、低コスト claude-haiku-4-5。
- 送信前に画像を整える(EXIF回転補正・長辺1568pxへ縮小・JPEG化)。
  iPhone写真(4032px・数MB・HEIC)をそのまま送るとサイズ上限で失敗するため。
- MockExtractor はAPIキー不要。ファイル名に埋めたヒント、または隣接する
  同名 .json を読んで Extraction を返す(パイプラインのオフライン検証用)。
"""
from __future__ import annotations

import base64
import io
import json
import os
from pathlib import Path
from typing import Protocol

from .schema import Extraction, LineItem

DEFAULT_MODEL = "claude-sonnet-4-6"
MAX_LONG_EDGE = 1568  # claude-sonnet-4-6 の画像解像度上限(これ以上は送っても縮小される)

RECEIPT_TOOL = {
    "name": "record_receipt",
    "description": "レシート画像から読み取った内容を構造化して記録する",
    "input_schema": {
        "type": "object",
        "properties": {
            "payee_raw": {"type": "string", "description": "店名。印字のまま。推測で補完しない"},
            "date": {"type": ["string", "null"], "description": "YYYY-MM-DD。読めなければ null"},
            "total": {"type": ["integer", "null"], "description": "合計金額(円)。読めなければ null"},
            "tax": {"type": ["integer", "null"], "description": "税額(円)"},
            "items": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                        "amount": {"type": "integer"},
                    },
                    "required": ["name", "amount"],
                },
                "description": "明細行。読み取れた分だけ。無理に埋めない",
            },
            "payment_method": {"type": ["string", "null"]},
            "notes": {"type": "string", "description": "かすれ・不明瞭など読み取り上の注意"},
        },
        "required": ["payee_raw", "date", "total"],
    },
}

SYSTEM = (
    "あなたはレシート読み取り係です。画像に印字されている内容だけを読み取り、"
    "record_receipt ツールで記録してください。読めない項目は null にしてください。"
    "推測で補完してはいけません。読み取りに不安がある箇所は notes に書いてください。"
)


def prepare_image(image_path: str | Path, max_long_edge: int = MAX_LONG_EDGE) -> bytes:
    """API送信用のJPEGバイト列を作る。EXIF回転補正 → 縮小 → RGB化 → JPEG。"""
    from PIL import Image, ImageOps
    try:
        from pillow_heif import register_heif_opener  # HEIC対応(任意依存)
        register_heif_opener()
    except ImportError:
        pass

    with Image.open(image_path) as im:
        im = ImageOps.exif_transpose(im)
        im.thumbnail((max_long_edge, max_long_edge))
        buf = io.BytesIO()
        im.convert("RGB").save(buf, format="JPEG", quality=90)
    return buf.getvalue()


class Extractor(Protocol):
    def extract(self, image_path: str) -> Extraction: ...


class ClaudeExtractor:
    def __init__(self, model: str = DEFAULT_MODEL, api_key: str | None = None):
        from anthropic import Anthropic  # 遅延import(Mock運用時に不要)
        self.model = model
        self.client = Anthropic(api_key=api_key or os.environ.get("ANTHROPIC_API_KEY"))

    def extract(self, image_path: str) -> Extraction:
        data = base64.standard_b64encode(prepare_image(image_path)).decode()
        msg = self.client.messages.create(
            model=self.model,
            max_tokens=2000,
            system=SYSTEM,
            tools=[RECEIPT_TOOL],
            tool_choice={"type": "tool", "name": "record_receipt"},
            messages=[{
                "role": "user",
                "content": [
                    {"type": "image",
                     "source": {"type": "base64", "media_type": "image/jpeg", "data": data}},
                    {"type": "text", "text": "このレシートを読み取ってください。"},
                ],
            }],
        )
        tool_use = next((b for b in msg.content if b.type == "tool_use"), None)
        if tool_use is None:
            raise RuntimeError(f"抽出結果が返りませんでした(stop_reason={msg.stop_reason})")
        d = tool_use.input
        return Extraction(
            payee_raw=d.get("payee_raw", ""),
            date=d.get("date"),
            total=d.get("total"),
            tax=d.get("tax"),
            items=[LineItem(**i) for i in d.get("items", [])],
            payment_method=d.get("payment_method"),
            model=self.model,
            notes=d.get("notes", ""),
        )


class MockExtractor:
    """オフライン検証用。画像と同名の .json (例: r001.jpg → r001.json) を読む。"""

    def extract(self, image_path: str) -> Extraction:
        sidecar = Path(image_path).with_suffix(".json")
        if not sidecar.exists():
            raise FileNotFoundError(f"Mock用サイドカーがありません: {sidecar}")
        d = json.loads(sidecar.read_text(encoding="utf-8"))
        return Extraction(
            payee_raw=d.get("payee_raw", ""),
            date=d.get("date"),
            total=d.get("total"),
            tax=d.get("tax"),
            items=[LineItem(**i) for i in d.get("items", [])],
            payment_method=d.get("payment_method"),
            model="mock",
            notes=d.get("notes", ""),
        )


def get_extractor(kind: str = "auto", model: str = DEFAULT_MODEL) -> Extractor:
    """auto: 環境変数 RECEIPTPILOT_EXTRACTOR(mock/claude)があればそれに従う。
    無ければ APIキーがあれば Claude、なければ Mock。"""
    if kind == "auto":
        kind = os.environ.get("RECEIPTPILOT_EXTRACTOR", "auto")
    if kind == "mock":
        return MockExtractor()
    if kind == "claude":
        return ClaudeExtractor(model=model)
    if os.environ.get("ANTHROPIC_API_KEY"):
        return ClaudeExtractor(model=model)
    return MockExtractor()
