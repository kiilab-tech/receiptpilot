"""ReceiptPilot 確認UI (FR-8)。

起動: streamlit run app/streamlit_app.py
- 要確認レコードの確認・修正・確定
- ルール候補の提案と採用
- 統計(自動確定率)
"""
from __future__ import annotations

import sys
from datetime import date as _date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import streamlit as st
import yaml

from receiptpilot.extract import get_extractor
from receiptpilot.learn import Learner
from receiptpilot.paths import get_paths
from receiptpilot.pipeline import confirm_record, process_inbox
from receiptpilot.rules import PayeeRules
from receiptpilot.store import Store

paths = get_paths()

st.set_page_config(page_title="ReceiptPilot", page_icon="🧾", layout="wide")
st.title("🧾 ReceiptPilot")
st.caption("AIが読んだレシートを、自分ルールと金額で「自動確定 / 要確認」に振り分けます。"
           "要確認は人が確かめてから確定します。")

store = Store(paths.store)
rules = PayeeRules.load(paths.rules)
learner = Learner(paths.confirmations)
categories = [c["name"] for c in
              (yaml.safe_load(paths.categories.read_text(encoding="utf-8")) or {})
              .get("categories", [])]


def form_problems(date_s: str, total: int, category: str | None) -> list[str]:
    """人手確定の前に最低限の形を確かめる(誤入力で確定させない)。"""
    problems = []
    try:
        if _date.fromisoformat(date_s) > _date.today():
            problems.append("日付が未来になっています")
    except ValueError:
        problems.append("日付は YYYY-MM-DD で入力してください")
    if total <= 0:
        problems.append("金額は1円以上にしてください")
    if not category:
        problems.append("費目を選んでください")
    return problems


# --- サイドバー: 取り込みと統計 ---
with st.sidebar:
    st.header("取り込み")
    if st.button("inbox を処理する", type="primary"):
        errors: list[str] = []
        with st.spinner("抽出中..."):
            done = process_inbox(paths.inbox, store, rules, get_extractor("auto"), errors)
        st.success(f"{len(done)} 件処理しました")
        for msg in errors:
            st.error(msg)

    s = store.stats()
    st.header("統計")
    st.metric("自動確定率", f"{s['auto_confirm_rate']:.0%}",
              help="人の手を介さずに確定した割合(人手確定は含まない)")
    c1, c2, c3 = st.columns(3)
    c1.metric("自動確定", s["auto_confirmed"])
    c2.metric("人手確定", s["manual_confirmed"])
    c3.metric("要確認", s["review"])

    # ルール候補の提案
    props = learner.proposals(rules)
    if props:
        st.header("ルール候補")
        for p in props:
            st.write(f"**{p['pattern']}** → {p['category']} "
                     f"(確定 {p['confirmed_count']} 回)")
            if st.button(f"採用: {p['pattern']}", key=f"adopt_{p['pattern']}"):
                rules.add(p["pattern"], p["category"], brand=p["pattern"])
                rules.save(paths.rules)
                st.rerun()

# --- メイン: 要確認一覧 ---
records = list(store.load_all().values())
reviews = [r for r in records if r.status == "review"]

st.subheader(f"要確認 ({len(reviews)} 件)")
if not reviews:
    st.info("要確認レコードはありません 🎉")

for i, r in enumerate(reviews):
    amount = f"¥{r.total:,}" if r.total is not None else "金額不明"
    with st.expander(f"{r.date or '日付不明'}  {r.payee}  {amount}", expanded=(i == 0)):
        col_img, col_form = st.columns([1, 2])
        img = paths.inbox / r.source_image
        if img.exists():
            col_img.image(str(img), caption=r.source_image, width=280)
        with col_form:
            st.warning("判定理由: " + " / ".join(r.reasons))
            if r.extraction and r.extraction.items:
                st.caption("読み取った明細: " + "、".join(
                    f"{i.name} ¥{i.amount:,}" for i in r.extraction.items))
            payee = st.text_input("店名(ブランド)", value=r.payee,
                                  key=f"payee_{r.image_hash}")
            date = st.text_input("日付 (YYYY-MM-DD)", value=r.date or "",
                                 key=f"date_{r.image_hash}")
            total = st.number_input("金額", value=r.total or 0, step=1,
                                    key=f"total_{r.image_hash}")
            idx = categories.index(r.category) if r.category in categories else None
            category = st.selectbox("費目", categories, index=idx,
                                    placeholder="費目を選んでください",
                                    key=f"cat_{r.image_hash}")
            if st.button("確定", key=f"ok_{r.image_hash}", type="primary"):
                problems = form_problems(date, int(total), category)
                if problems:
                    st.error(" / ".join(problems))
                else:
                    r.payee = payee
                    r.date = date
                    r.total = int(total)
                    confirm_record(store, r, category, learner)
                    st.rerun()

# --- 確定済み一覧 ---
confirmed = [r for r in records if r.status == "confirmed"]
if confirmed:
    st.subheader(f"確定済み ({len(confirmed)} 件)")
    st.dataframe([
        {"日付": r.date, "店名": r.payee, "費目": r.category, "金額": f"¥{r.total:,}",
         "由来": {"rule": "自分ルール", "human": "人手確定",
                  "extractor": "AI"}.get(r.category_origin or "", "-")}
        for r in sorted(confirmed, key=lambda x: x.date or "")
    ], width="stretch")
