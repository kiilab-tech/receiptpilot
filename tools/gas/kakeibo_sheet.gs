/**
 * ReceiptPilot → Googleスプレッドシート受け口。
 * デプロイ: 拡張機能 > Apps Script > デプロイ > ウェブアプリ(全員/自分)
 * POST: {"rows":[{"date","payee","category","amount","source"}]}
 * 送信例: curl -X POST -H "Content-Type: application/json" \
 *   -d @data/out/gas_payload.json "$GAS_WEBHOOK_URL"
 */
function doPost(e) {
  const sheet = SpreadsheetApp.getActiveSpreadsheet().getSheetByName("家計簿")
      || SpreadsheetApp.getActiveSpreadsheet().insertSheet("家計簿");
  if (sheet.getLastRow() === 0) {
    sheet.appendRow(["日付", "店名", "費目", "金額", "元画像"]);
  }
  const body = JSON.parse(e.postData.contents);
  // 二重登録防止: 既存の元画像名を集める
  const last = sheet.getLastRow();
  const seen = last > 1
      ? new Set(sheet.getRange(2, 5, last - 1, 1).getValues().flat()) : new Set();
  let added = 0;
  for (const r of body.rows) {
    if (seen.has(r.source)) continue;
    sheet.appendRow([r.date, r.payee, r.category, r.amount, r.source]);
    added++;
  }
  return ContentService.createTextOutput(JSON.stringify({added: added}))
      .setMimeType(ContentService.MimeType.JSON);
}
