"""画面からの写真の受け付け(UI要件 R1, R2, R13)。

- 形式は JPEG / PNG / HEIC だけ。1枚20MBまで、一度に50枚まで
- 中身が画像として開けるかも確かめる(拡張子だけ変えたファイルを弾く)
- 取り込み済み・処理済みと同じ写真は保存しない(二重計上の防止)
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from hashlib import sha256
from io import BytesIO
from pathlib import Path

from .pipeline import IMAGE_EXTS
from .schema import file_hash
from .store import Store

MAX_BYTES = 20 * 1024 * 1024
MAX_FILES = 50


@dataclass
class IntakeResult:
    saved: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)  # 「ファイル名: 理由」


def _is_image(data: bytes) -> bool:
    from PIL import Image
    try:
        from pillow_heif import register_heif_opener
        register_heif_opener()
    except ImportError:
        pass
    try:
        with Image.open(BytesIO(data)) as im:
            im.verify()
        return True
    except Exception:  # noqa: BLE001
        return False


def _safe_name(name: str) -> str:
    stem = re.sub(r"[^\w\-.]", "_", Path(name).stem)[:40] or "receipt"
    return stem


def accept_uploads(files: list[tuple[str, bytes]], inbox: Path, store: Store) -> IntakeResult:
    """files: [(元のファイル名, 中身)]。inbox に保存し、結果を返す。"""
    res = IntakeResult()
    inbox.mkdir(parents=True, exist_ok=True)
    if len(files) > MAX_FILES:
        res.skipped += [f"{n}: 一度に入れられるのは{MAX_FILES}枚までです" for n, _ in files[MAX_FILES:]]
        files = files[:MAX_FILES]

    known = set(store.load_all())
    known |= {file_hash(str(p)) for p in inbox.iterdir() if p.suffix.lower() in IMAGE_EXTS}
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")

    for i, (name, data) in enumerate(files):
        ext = Path(name).suffix.lower()
        if ext not in IMAGE_EXTS:
            res.skipped.append(f"{name}: レシートの写真(JPEG・PNG・HEIC)ではありません")
            continue
        if len(data) > MAX_BYTES:
            res.skipped.append(f"{name}: ファイルが大きすぎます(20MBまで)")
            continue
        if not _is_image(data):
            res.skipped.append(f"{name}: 画像として開けませんでした")
            continue
        h = sha256(data).hexdigest()[:16]  # schema.file_hash と同じ方式
        if h in known:
            res.skipped.append(f"{name}: 同じ写真を取り込み済みのため飛ばしました")
            continue
        out = inbox / f"{stamp}_{i:02d}_{_safe_name(name)}{ext}"
        out.write_bytes(data)
        known.add(h)
        res.saved.append(name)
    return res
