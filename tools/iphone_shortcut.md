# iPhone → Mac レシート転送(ショートカット)

## 方式A: iCloud Drive 監視(推奨・全自動)
1. iPhone「ショートカット」で新規作成: 「レシート撮影」
   - アクション1: 「写真を撮る」(カメラ起動、編集なし)
   - アクション2: 「ファイルを保存」→ iCloud Drive/ReceiptPilot/inbox
     ファイル名: `現在の日付 (yyyyMMdd-HHmmss).jpg`
2. Mac 側: `~/Library/Mobile Documents/com~apple~CloudDocs/ReceiptPilot/inbox`
   を `data/inbox` にシンボリックリンク:
   ```
   ln -s "$HOME/Library/Mobile Documents/com~apple~CloudDocs/ReceiptPilot/inbox" data/inbox
   ```
3. 処理: `python3 run.py process`(cron/launchd で定期実行も可)

## 方式B: AirDrop(手動・確実)
撮影 → AirDropでMacへ → `data/inbox` に移動 → process

## 注意
- HEICはVLM送信前にJPEGへ変換する:
  `sips -s format jpeg *.heic --out .` (Mac標準コマンド)
- 撮影のコツ: 真上から・影を避ける・レシート全体を入れる。
  かすれがひどいものは判定が review に落ちるだけなので気にせず撮る
