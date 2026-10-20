"""Web お試し版の入口(Streamlit Community Cloud の Main file に指定する)。

架空レシートだけで操作を体験する版。写真の取り込み・AI の読み取り・APIキーは扱わない。
要件: docs/Web版要件定義.md
"""
import os
import runpy
from pathlib import Path

os.environ["RECEIPTPILOT_WEB_DEMO"] = "1"
runpy.run_path(str(Path(__file__).with_name("streamlit_app.py")), run_name="__main__")
