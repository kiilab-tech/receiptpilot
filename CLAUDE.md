# CLAUDE.md — ReceiptPilot

## 最初にやること
1. `private/HANDOFF.md` があれば読む(現在地と次の作業。Git管理外のローカルメモ)
2. docs/要件定義書.md の「1. 設計原則」を確認してから コードを触る

## プロジェクト概要
AI-OCR レシート → 家計簿/仕訳 パイプライン。iPhone撮影 → Claude API(VLM)抽出 →
自分ルール → 信用獲得しきい値で判定 → Streamlit確認UI → 3種アダプタ出力。
ローカル実行のみ。B2C(家計簿)で鍛えてB2B(freee/税理士事務所)へ移植する戦略。

## 絶対に守る設計原則
1. **迷ったら安全側(review)へ倒す** — 自動確定の条件を緩める変更は原則禁止
2. **自分ルール(payee_rules)がAIの推測に勝つ** — この優先順位を崩さない
3. **コアは共通、違いはアダプタだけ** — コアにB2C/B2B分岐を入れない
4. **最終検証ゲート(adapters/base.py の validate)は削除・迂回禁止**
   — status未検査で未確定データが出力された事故の再発防止

## コマンド
```bash
source .venv/bin/activate
pytest -q                           # 全テスト(APIキー不要)
python3 run.py demo                 # 架空レシートでデモ環境 data/demo を作る
python3 run.py process              # inbox処理(APIキーあれば実API、なければMock)
streamlit run app/streamlit_app.py  # 確認UI
python3 run.py export kakeibo|gas|freee
```
デモのUI: `streamlit run app/streamlit_app.py` → サイドバーの「お試しモード」をオン
画面の要件は docs/UI要件定義.md(R番号はテスト tests/test_ui_parts.py と対応)。
`.streamlit/config.toml` で 127.0.0.1 待ち受けに固定している(外部公開しない。変更禁止)

## 環境
- Python 3.11+ / venv、依存: anthropic, streamlit, pyyaml, pillow, pillow-heif, keyring
  - f文字列の中で同じ種類の引用符を入れ子にしない(3.11 で構文エラーになる)
- APIキー: 画面からはキーチェーン(credentials.py)。CLI は環境変数 ANTHROPIC_API_KEY(優先)。ファイルや .zshrc に置かない
  - **未設定でもエラーにならず MockExtractor に落ちる**(extract.py の get_extractor)。
    実APIを使うつもりなら `echo $ANTHROPIC_API_KEY` で必ず確認すること
- 抽出モデル: claude-sonnet-4-6(extract.py DEFAULT_MODEL。低コスト: claude-haiku-4-5)
  - 4.6系より新しいモデルへ替える場合、tool_choice の強制指定が使えないモデルがある。
    切替時は extract.py の呼び出し方を確認すること
- データ置き場: 環境変数 RECEIPTPILOT_DATA(既定 data/)。paths.py 参照

## 触ってよい調整ポイント
- extract.py の SYSTEM プロンプト(実物レシートでの誤読対策)
- judge.py のしきい値(ただし下げる=厳しくする方向のみ推奨)
- masters/payee_rules.yaml(ルールは基本UIから育てるが手編集も可)

## コミット規約
- data/ 以下(レシート画像・store・out)と private/ はコミットしない(.gitignore済み)
- samples/ は架空データのみ。実物レシートを置かない
- 変更後は必ず `pytest -q` を通してからコミット
