"""画面で変えられる設定(秘密ではないもの)。データ置き場の settings.json に保存する。"""
from __future__ import annotations

import json
import os
from pathlib import Path

from .extract import DEFAULT_MODEL, MODEL_CHOICES

DEFAULTS = {"model": DEFAULT_MODEL}


def load(data_dir: Path) -> dict:
    p = Path(data_dir) / "settings.json"
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        d = {}
    out = {**DEFAULTS, **d}
    if out["model"] not in [m for _, m, _ in MODEL_CHOICES]:
        out["model"] = DEFAULT_MODEL
    return out


def save(data_dir: Path, values: dict) -> None:
    p = Path(data_dir) / "settings.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(values, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, p)


def cost_per_image(model: str) -> int:
    return next((yen for _, m, yen in MODEL_CHOICES if m == model), 3)
