"""ReceiptPilot 画面(FR-8 / docs/UI要件定義.md)。

起動: streamlit run app/streamlit_app.py
ターミナルを使わない人向けに、取り込み・読み取り・確認・出力・ルール・設定を
すべて画面から行えるようにしている。ページ構成:
  読み取り / 確認 / 一覧・出力 / 自分ルール / 設定
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import threading
from datetime import date as _date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import streamlit as st
import yaml

from receiptpilot import credentials, settings
from receiptpilot.adapters import FreeeAdapter, KakeiboCsvAdapter
from receiptpilot.demo import demo_paths, reset_demo
from receiptpilot.extract import MODEL_CHOICES, ClaudeExtractor, MockExtractor, check_api_key, prepare_image
from receiptpilot.intake import MAX_FILES, accept_uploads
from receiptpilot.learn import Learner
from receiptpilot.paths import get_paths
from receiptpilot.pipeline import confirm_record, pending_images, process_inbox
from receiptpilot.rules import PayeeRules
from receiptpilot.store import Store

st.set_page_config(page_title="ReceiptPilot", page_icon="🧾", layout="wide")
ss = st.session_state

# ------------------------------------------------------------------ 共通の状態
base = get_paths()
conf = settings.load(base.data)

with st.sidebar:
    demo = st.toggle("お試しモード", key="demo",
                     help="架空のレシートで操作を試せます。APIキーは不要で、本番のデータには影響しません")

paths = demo_paths(base) if demo else base
if demo and not paths.store.exists():
    reset_demo(paths)

store = Store(paths.store)
rules = PayeeRules.load(paths.rules)
learner = Learner(paths.confirmations)
categories = [c["name"] for c in
              (yaml.safe_load(paths.categories.read_text(encoding="utf-8")) or {})
              .get("categories", [])]
api_key = None if demo else credentials.get_api_key()
records = list(store.load_all().values())
reviews = sorted([r for r in records if r.status == "review"], key=lambda r: r.date or "")
confirmed = sorted([r for r in records if r.status == "confirmed"], key=lambda r: r.date or "")


def yen(n: int | None) -> str:
    return f"¥{n:,}" if n is not None else "金額不明"


def show_image(col, name: str) -> None:
    """原本画像を表示する(HEIC もブラウザで見られるよう JPEG にしてから出す)。"""
    img = paths.inbox / name
    if img.exists():
        try:
            col.image(prepare_image(img, 900), caption=name, width=300)
        except Exception:  # noqa: BLE001
            col.warning("画像を表示できませんでした")


def save_rules() -> None:
    rules.save(paths.rules_writable)


def form_problems(date_s: str, total: int, category: str | None) -> list[str]:
    """人手確定の前に最低限の形を確かめる(誤入力で確定させない)。"""
    problems = []
    try:
        if _date.fromisoformat(date_s) > _date.today():
            problems.append("日付が未来になっています")
    except ValueError:
        problems.append("日付は 2026-10-20 のように入力してください")
    if total <= 0:
        problems.append("金額は1円以上にしてください")
    if not category:
        problems.append("費目を選んでください")
    return problems


def delete_record(r) -> None:
    """レシートを削除する。画像は「ごみ箱」へ移すので、誤っても戻せる。"""
    img = paths.inbox / r.source_image
    if img.exists():
        paths.trash.mkdir(parents=True, exist_ok=True)
        shutil.move(str(img), paths.trash / img.name)
    store.delete(r)


def flash(kind: str, text: str) -> None:
    """次の再描画で一度だけ出すメッセージを積む。"""
    ss.setdefault("flash", []).append((kind, text))


def show_flash() -> None:
    for kind, text in ss.pop("flash", []):
        getattr(st, kind)(text)


# ------------------------------------------------------------------ ページ
def page_read():
    st.title("📥 レシートを読み取る")
    show_flash()
    if store.recovered_lines:
        st.warning(f"保存データに壊れた行が{store.recovered_lines}行あったため、取り除いて退避しました"
                   "(Mac が処理中に止まった可能性があります)。他のデータは無事です。")

    if demo:
        st.info("**お試しモード**です。架空のレシート7枚が読み取り済みになっています。"
                "「確認」ページで、要確認のレシートを確定してみてください。")
        if st.button("お試しデータを最初の状態に戻す"):
            reset_demo(paths)
            st.rerun()
        return

    if not api_key:
        st.warning("**最初に、設定ページで APIキーを登録してください。**"
                   "(APIキーがなくても、サイドバーの「お試しモード」で操作を試せます)")
        st.page_link(PAGES["settings"], label="設定ページを開く", icon="⚙️")

    if not records and not pending_images(paths.inbox, store):
        st.markdown(
            "#### 使い方\n"
            "1. **設定**ページで APIキーを登録する(最初の1回だけ)\n"
            "2. レシートの写真を、下の枠に**ドラッグ&ドロップ**する"
            "(iPhone の写真は AirDrop で Mac に送ってから)\n"
            "3. **読み取る**を押す → 自動で確定できないものは**確認**ページで確かめる\n"
            "4. **一覧・出力**ページから、家計簿のCSVをダウンロードする")

    # --- 取り込み
    up_key = f"uploader_{ss.get('up_n', 0)}"
    files = st.file_uploader(
        f"レシートの写真をここにドラッグ&ドロップ(JPEG・PNG・HEIC、一度に{MAX_FILES}枚まで)",
        type=["jpg", "jpeg", "png", "heic", "heif"], accept_multiple_files=True, key=up_key)
    if files:
        res = accept_uploads([(f.name, f.getvalue()) for f in files], paths.inbox, store)
        if res.saved:
            flash("success", f"{len(res.saved)}枚を取り込みました。")
        for msg in res.skipped:
            flash("warning", msg)
        ss["up_n"] = ss.get("up_n", 0) + 1  # 枠を空にする
        st.rerun()

    # --- 読み取り待ち
    todo = pending_images(paths.inbox, store)
    if todo:
        st.subheader(f"読み取り待ち({len(todo)}枚)")
        cols = st.columns(6)
        for i, (p, _) in enumerate(todo):
            with cols[i % 6]:
                try:
                    st.image(prepare_image(p, 300), width="stretch")
                except Exception:  # noqa: BLE001
                    st.caption(p.name)
                if st.button("取り消す", key=f"cancel_{p.name}", disabled=ss.get("running", False)):
                    p.unlink(missing_ok=True)
                    st.rerun()

        cost = settings.cost_per_image(conf["model"]) * len(todo)
        running = ss.get("running", False)
        if st.button(f"{len(todo)}枚を読み取る(費用の目安 約{cost}円)", type="primary",
                     disabled=running or not api_key):
            ss["running"] = True
            st.rerun()
        if running:
            run_reading()

    # --- 前回の結果
    if ss.get("last_result"):
        auto, review, errors = ss["last_result"]
        st.success(f"読み取りが終わりました。自動で確定: {auto}枚 / 確認が必要: {review}枚")
        for msg in errors:
            st.error(msg)
        if errors:
            st.caption("失敗した写真は「読み取り待ち」に残っています。原因を直してから、もう一度読み取ってください。")
        if review:
            st.page_link(PAGES["review"], label="確認ページを開く", icon="✅")


def run_reading():
    """読み取りを実行する。処理中はボタンを押せない(UI要件 R7)。"""
    bar = st.progress(0.0, text="読み取りを始めます…")

    def progress(i: int, n: int, name: str) -> None:
        bar.progress(i / n, text=f"{i + 1} / {n} 枚目を読み取り中…")

    errors: list[str] = []
    try:
        extractor = (MockExtractor() if demo
                     else ClaudeExtractor(model=conf["model"], api_key=api_key))
        done = process_inbox(paths.inbox, store, rules, extractor, errors, progress)
        auto = sum(1 for r in done if r.status == "confirmed")
        ss["last_result"] = (auto, len(done) - auto, errors)
    finally:
        ss["running"] = False
    st.rerun()


def page_review():
    st.title("✅ 確認する")
    show_flash()
    st.caption("自動で確定できなかったレシートです。原本と見比べて、直してから「確定」してください。")
    props = learner.proposals(rules)
    if props:
        st.info(f"ルール候補が{len(props)}件あります。採用すると、次からその店は自動で確定します。")
        st.page_link(PAGES["rules"], label="自分ルールのページで採用する", icon="📏")
    if not reviews:
        st.success("確認が必要なレシートはありません 🎉")
        return

    for i, r in enumerate(reviews):
        with st.expander(f"{r.date or '日付不明'}  {r.payee}  {yen(r.total)}", expanded=(i == 0)):
            col_img, col_form = st.columns([1, 2])
            show_image(col_img, r.source_image)
            with col_form:
                st.warning("確認が必要な理由: " + " / ".join(r.reasons))
                if r.extraction and r.extraction.items:
                    st.caption("読み取った明細: " + "、".join(
                        f"{it.name} ¥{it.amount:,}" for it in r.extraction.items))
                payee = st.text_input("店名", value=r.payee, key=f"payee_{r.image_hash}")
                date = st.text_input("日付(例: 2026-10-20)", value=r.date or "",
                                     key=f"date_{r.image_hash}")
                total = st.number_input("金額(円)", value=r.total or 0, step=1,
                                        key=f"total_{r.image_hash}")
                idx = categories.index(r.category) if r.category in categories else None
                category = st.selectbox("費目", categories, index=idx,
                                        placeholder="費目を選んでください",
                                        key=f"cat_{r.image_hash}")
                c1, c2 = st.columns([1, 1])
                if c1.button("確定", key=f"ok_{r.image_hash}", type="primary"):
                    problems = form_problems(date, int(total), category)
                    if problems:
                        st.error(" / ".join(problems))
                    else:
                        r.payee, r.date, r.total = payee, date, int(total)
                        confirm_record(store, r, category, learner)
                        flash("success", f"{payee} {yen(int(total))} を確定しました。")
                        st.rerun()
                if ss.get("confirm_delete") == r.image_hash:
                    c2.write("このレシートを削除しますか?")
                    if c2.button("削除する", key=f"del_yes_{r.image_hash}"):
                        delete_record(r)
                        ss.pop("confirm_delete")
                        flash("info", "削除しました(画像はデータ置き場の trash フォルダに移しました)。")
                        st.rerun()
                    if c2.button("やめる", key=f"del_no_{r.image_hash}"):
                        ss.pop("confirm_delete")
                        st.rerun()
                elif c2.button("削除(レシートではない等)", key=f"del_{r.image_hash}"):
                    ss["confirm_delete"] = r.image_hash
                    st.rerun()


def page_list():
    st.title("📒 一覧と出力")
    show_flash()
    if not confirmed:
        st.info("確定したレシートはまだありません。")
        return

    months = sorted({(r.date or "")[:7] for r in confirmed if r.date}, reverse=True)
    month = st.selectbox("表示する月", ["すべて"] + months)
    shown = [r for r in confirmed if month == "すべて" or (r.date or "").startswith(month)]

    origin = {"rule": "自動(自分ルール)", "human": "人が確定", "extractor": "自動"}
    st.dataframe([{"日付": r.date, "店名": r.payee, "費目": r.category, "金額": yen(r.total),
                   "確定のしかた": origin.get(r.category_origin or "", "自動")} for r in shown],
                 width="stretch", hide_index=True)
    st.metric(f"合計({len(shown)}件)", yen(sum(r.total or 0 for r in shown)))

    st.subheader("ダウンロード")
    out = paths.out / "download"
    c1, c2 = st.columns(2)
    p, _ = KakeiboCsvAdapter().emit(shown, out)
    c1.download_button("家計簿CSV(Excelで開けます)", p.read_bytes(),
                       file_name=f"kakeibo_{month}.csv", mime="text/csv", type="primary")
    p, rejected = FreeeAdapter(paths.categories).emit(shown, out)
    c2.download_button("freee 取込CSV", p.read_bytes(),
                       file_name=f"freee_{month}.csv", mime="text/csv")
    if rejected:
        c2.caption(f"freee の勘定科目に対応していない費目の{len(rejected)}件は含めていません。")

    with st.expander("確定を取り消す"):
        label = {f"{r.date} {r.payee} {yen(r.total)}": r for r in shown}
        pick = st.selectbox("取り消すレシート", list(label), index=None, placeholder="選んでください")
        if pick and st.button("確認待ちに戻す"):
            r = label[pick]
            r.status = "review"
            r.reasons = r.reasons + ["人が確定を取り消し"]
            store.update(r)
            flash("info", f"{pick} を確認待ちに戻しました。")
            st.rerun()


def page_rules():
    st.title("📏 自分ルール")
    show_flash()
    st.caption("「店名にこの文字が含まれていたら、この費目」という対応表です。"
               "AIの推測より常に優先され、ルールにある店は自動で確定できるようになります。")

    props = learner.proposals(rules)
    if props:
        st.subheader("ルール候補")
        for pr in props:
            c1, c2 = st.columns([3, 1])
            c1.write(f"**{pr['pattern']}** → {pr['category']}(同じ確定が{pr['confirmed_count']}回)")
            if c2.button("採用する", key=f"adopt_{pr['pattern']}", type="primary"):
                rules.add(pr["pattern"], pr["category"], brand=pr["pattern"])
                save_rules()
                flash("success", f"「{pr['pattern']}」をルールに追加しました。")
                st.rerun()

    st.subheader(f"登録済みのルール({len(rules.rules)}件)")
    match_label = {"partial": "を含む", "prefix": "で始まる", "exact": "と一致"}
    for r in list(rules.rules):
        c1, c2 = st.columns([3, 1])
        c1.write(f"店名が「**{r['pattern']}**」{match_label.get(r.get('match', 'partial'), 'を含む')}"
                 f" → **{r['category']}**")
        if c2.button("削除", key=f"rule_del_{r['pattern']}"):
            rules.remove(r["pattern"])
            save_rules()
            flash("info", f"「{r['pattern']}」のルールを削除しました。")
            st.rerun()

    with st.form("add_rule", clear_on_submit=True):
        st.write("**ルールを追加する**")
        c1, c2, c3 = st.columns([2, 1, 1])
        pattern = c1.text_input("店名に含まれる文字(例: イオン)")
        how = c2.selectbox("照合", ["を含む", "で始まる", "と一致"])
        cat = c3.selectbox("費目", categories)
        if st.form_submit_button("追加"):
            pattern = pattern.strip()
            if not pattern:
                st.error("店名の文字を入力してください")
            elif any(r["pattern"] == pattern for r in rules.rules):
                st.error("同じ文字のルールがすでにあります")
            else:
                rules.add(pattern, cat, brand=pattern,
                          match={v: k for k, v in match_label.items()}[how])
                save_rules()
                flash("success", f"「{pattern}」→ {cat} を追加しました。")
                st.rerun()


def page_settings():
    st.title("⚙️ 設定")
    show_flash()

    st.subheader("APIキー")
    src = credentials.key_source()
    current = credentials.get_api_key()
    st.write(f"現在: **{credentials.mask(current)}**" + (f"({src}に保存)" if src else ""))
    with st.expander("APIキーの取り方", expanded=not current):
        st.markdown(
            "1. [Claude Console](https://console.anthropic.com) を開いてログインする\n"
            "2. 「API Keys」→「Create Key」で作成し、表示された `sk-ant-` で始まる文字列をコピーする"
            "(全文が表示されるのは作成時の1回だけです)\n"
            "3. 「Billing」で残高を確認する(使った分だけ前払いの残高から引かれます。1枚あたり数円です)\n"
            "4. 下の欄に貼り付けて「確かめて保存」を押す\n\n"
            "キーは この Mac のキーチェーンに保存され、ファイルには書き出しません。")
    if src == "環境変数":
        st.info("環境変数 ANTHROPIC_API_KEY のキーを使っています(開発者向けの設定)。")
    new_key = st.text_input("APIキーを貼り付け", type="password", key="new_key")
    c1, c2 = st.columns(2)
    if c1.button("確かめて保存", type="primary"):
        key, problem = credentials.clean_key(new_key)
        if problem:
            st.error(problem)
        else:
            with st.spinner("接続を確かめています…"):
                problem = check_api_key(key, conf["model"])
            if problem:
                st.error(problem)
            else:
                try:
                    credentials.save_api_key(key)
                    flash("success", "APIキーを保存しました。読み取りページから使えます。")
                    st.rerun()
                except Exception as e:  # noqa: BLE001
                    st.error(f"キーチェーンに保存できませんでした({type(e).__name__})")
    if current and src == "キーチェーン" and c2.button("保存したキーを削除"):
        credentials.delete_api_key()
        flash("info", "APIキーを削除しました。")
        st.rerun()

    st.subheader("読み取りの品質と費用")
    labels = [f"{name}(1枚あたり約{yen_}円)" for name, _, yen_ in MODEL_CHOICES]
    ids = [m for _, m, _ in MODEL_CHOICES]
    pick = st.radio("使うAI", labels, index=ids.index(conf["model"]))
    model = ids[labels.index(pick)]
    if model != conf["model"]:
        settings.save(base.data, {**conf, "model": model})
        flash("success", "設定を保存しました。")
        st.rerun()

    st.subheader("データの保存場所")
    st.code(str(base.data), language=None)
    st.caption("レシートの画像・読み取り結果・自分ルールは、すべてこの Mac のこのフォルダにあります。"
               "Time Machine などでバックアップしてください。フォルダごと消すとデータも消えます。")
    if sys.platform == "darwin" and st.button("Finder で開く"):
        base.data.mkdir(parents=True, exist_ok=True)
        subprocess.run(["open", str(base.data)], check=False)


PAGES = {
    "read": st.Page(page_read, title="読み取り", icon="📥", url_path="read", default=True),
    "review": st.Page(page_review, title=f"確認({len(reviews)})", icon="✅", url_path="review"),
    "list": st.Page(page_list, title="一覧・出力", icon="📒", url_path="list"),
    "rules": st.Page(page_rules, title="自分ルール", icon="📏", url_path="rules"),
    "settings": st.Page(page_settings, title="設定", icon="⚙️", url_path="settings"),
}

# ------------------------------------------------------------------ サイドバー
with st.sidebar:
    s = store.stats()
    c1, c2 = st.columns(2)
    c1.metric("確定", s["confirmed"])
    c2.metric("確認待ち", s["review"])
    st.caption(f"自動で確定した割合: {s['auto_confirm_rate']:.0%}")
    st.divider()
    if st.button("終了する", help="ReceiptPilot を終了します。次に使うときは、もう一度アプリを開いてください"):
        ss["quit"] = True

if ss.get("quit"):
    st.title("ReceiptPilot を終了しました")
    st.write("このタブ(ウィンドウ)は閉じて大丈夫です。データは保存されています。")
    if not os.environ.get("RECEIPTPILOT_NO_EXIT"):  # テスト中は止めない
        threading.Timer(1.0, lambda: os._exit(0)).start()
    st.stop()

st.navigation(list(PAGES.values())).run()
