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
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))

from receiptpilot.demo import demo_paths, reset_demo
from receiptpilot.extract import get_extractor
from receiptpilot.paths import get_paths
from receiptpilot.pipeline import process_inbox
from receiptpilot.rules import PayeeRules
from receiptpilot.store import Store
from receiptpilot.adapters import FreeeAdapter, GasSheetAdapter, KakeiboCsvAdapter


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
    for r in reset_demo(demo_paths(get_paths())):
        print(f"{r.source_image}: {r.status:9s} {r.payee}  ¥{r.total}  {r.reasons}")
    print("\n確認画面: streamlit run app/streamlit_app.py → サイドバーの「お試しモード」をオン")


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
