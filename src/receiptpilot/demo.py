"""お試しモード: 架空レシート(samples/)でデモ用のデータ置き場を作り直す。APIキー不要。"""
from __future__ import annotations

import shutil
from pathlib import Path

from .extract import MockExtractor
from .paths import ROOT, Paths
from .pipeline import process_inbox
from .rules import PayeeRules
from .schema import Record
from .store import Store

SAMPLES = ROOT / "samples"


def demo_paths(base: Paths) -> Paths:
    return Paths(base.data / "demo")


def reset_demo(paths: Paths) -> list[Record]:
    if paths.data.exists():
        shutil.rmtree(paths.data)
    paths.inbox.mkdir(parents=True)
    for p in sorted(SAMPLES.glob("s*.*")):
        shutil.copy(p, paths.inbox / p.name)
    shutil.copy(SAMPLES / "payee_rules.yaml", paths.data / "payee_rules.yaml")
    return process_inbox(paths.inbox, Store(paths.store), PayeeRules.load(paths.rules),
                         MockExtractor())
