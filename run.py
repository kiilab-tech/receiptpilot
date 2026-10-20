#!/usr/bin/env python3
"""CLI: 取り込み処理と出力。

  python3 run.py process          # inbox を処理
  python3 run.py export kakeibo   # 家計簿CSV出力
  python3 run.py export gas       # GAS用JSON出力
  python3 run.py export freee     # freee取込CSV出力
  python3 run.py stats
  python3 run.py demo             # 架空レシートでデモ環境(data/demo)を作る。APIキー不要

データ置き場は環境変数 RECEIPTPILOT_DATA で切替(既定 data/)。
"""
import os
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))

from receiptpilot.extract import get_extractor
from receiptpilot.paths import get_paths
from receiptpilot.pipeline import process_inbox
from receiptpilot.rules import PayeeRules
from receiptpilot.store import Store
from receiptpilot.adapters import FreeeAdapter, GasSheetAdapter, KakeiboCsvAdapter

DEMO_DIR = ROOT / "data/demo"


def process(extractor_kind: str = "auto") -> None:
    paths = get_paths()
    store = Store(paths.store)
    rules = PayeeRules.load(paths.rules)
    errors: list[str] = []
    done = process_inbox(paths.inbox, store, rules, get_extractor(extractor_kind), errors)
    for r in done:
        print(f"{r.source_image}: {r.status:9s} {r.payee}  ¥{r.total}  {r.reasons}")
    for msg in errors:
        print(f"  失敗: {msg}")
    print(f"--- {len(done)} 件処理" + (f" / {len(errors)} 件失敗(次回再挑戦)" if errors else ""))


def demo() -> None:
    """架空レシート(samples/)で data/demo を作り直し、Mock抽出で処理する。"""
    if DEMO_DIR.exists():
        shutil.rmtree(DEMO_DIR)
    inbox = DEMO_DIR / "inbox"
    inbox.mkdir(parents=True)
    for p in sorted((ROOT / "samples").glob("s*.*")):
        shutil.copy(p, inbox / p.name)
    shutil.copy(ROOT / "samples/payee_rules.yaml", DEMO_DIR / "payee_rules.yaml")
    os.environ["RECEIPTPILOT_DATA"] = str(DEMO_DIR)
    process("mock")
    print("\n確認画面:  RECEIPTPILOT_DATA=data/demo RECEIPTPILOT_EXTRACTOR=mock "
          "streamlit run app/streamlit_app.py")


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "help"
    if cmd == "process":
        process()
    elif cmd == "demo":
        demo()
    elif cmd == "export":
        paths = get_paths()
        store = Store(paths.store)
        kind = sys.argv[2] if len(sys.argv) > 2 else "kakeibo"
        a = {"kakeibo": KakeiboCsvAdapter(),
             "gas": GasSheetAdapter(),
             "freee": FreeeAdapter(paths.categories)}[kind]
        path, rejected = a.emit(list(store.load_all().values()), paths.out)
        print(f"出力: {path}")
        for msg in rejected:
            print(f"  弾いた: {msg}")
    elif cmd == "stats":
        print(Store(get_paths().store).stats())
    else:
        print(__doc__)


if __name__ == "__main__":
    main()
