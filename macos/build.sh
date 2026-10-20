#!/bin/bash
# ReceiptPilot.app と配布用の ReceiptPilot.dmg を作る(docs/UI要件定義.md の B)。
#
#   bash macos/build.sh
#
# - Python 本体(python-build-standalone, macOS 11 以降で動く版)とライブラリをアプリに同梱する。
#   利用者の Mac には何もインストールしなくてよく、初回のダウンロードも不要。
# - ライブラリは macOS 13 / Apple シリコン向けの配布物だけを選ぶ(手元の macOS 用を混ぜない)。
# - 署名はアドホック署名のみ(Apple の公証はしない。利用者には「このまま開く」を案内する)。
set -euo pipefail
cd "$(dirname "$0")/.."

VERSION="$(cat macos/VERSION)"
MIN_MACOS="13.0"
PY_VER="3.12"
APP="build/app.noindex/ReceiptPilot.app"   # 組み立て場所。配布するのは dist/ の .dmg だけ
RES="$APP/Contents/Resources"

# 組み立て途中のアプリは Mac のアプリ一覧(Spotlight)に出さない。
# フォルダ名を .noindex で終わらせると索引の対象外になる(重複して見えるのを防ぐ)
mkdir -p build dist

echo "== 道具の準備"
if [ ! -x build/tools/bin/uv ]; then
  python3 -m venv build/tools
  build/tools/bin/pip install -q uv
fi
build/tools/bin/uv python install "$PY_VER" --install-dir build/pythons >/dev/null
PYSRC="$(ls -d build/pythons/cpython-${PY_VER}.*-macos-aarch64-none | sort -V | tail -1)"
echo "   Python: $PYSRC"

echo "== アプリの組み立て"
rm -rf build/app.noindex dist/*.dmg
mkdir -p dist
mkdir -p "$APP/Contents/MacOS" "$RES"
cp -R "$PYSRC" "$RES/python"
rm -rf "$RES/python/include" "$RES/python/share" "$RES/python/lib/python${PY_VER}/test"
SITE="$RES/python/lib/python${PY_VER}/site-packages"

"$RES/python/bin/python3" -m pip install -q --disable-pip-version-check \
  --target "$SITE" --upgrade \
  --platform "macosx_${MIN_MACOS/./_}_arm64" --python-version "$PY_VER" \
  --implementation cp --only-binary=:all: \
  -r requirements.txt

# 実行に使わないもの(各ライブラリのテスト・Jupyter用ファイル・ヘッダー・pip)を除いて小さくする
find "$SITE" -type d -name tests -prune -exec rm -rf {} +
rm -rf "$SITE/share/jupyter" "$SITE/pyarrow/include" "$SITE/pyarrow/src" \
       "$SITE"/pip "$SITE"/pip-*.dist-info
find "$SITE" \( -name "*.pxd" -o -name "*.pyx" -o -name "*.h" -o -name "*.cc" \) -delete

for d in src app masters samples; do cp -R "$d" "$RES/$d"; done
cp macos/launcher.py "$RES/launcher.py"
cp macos/VERSION "$RES/VERSION"
find "$RES" -name "__pycache__" -type d -prune -exec rm -rf {} +
# 起動を速くするため、あらかじめ変換しておく(実行中にアプリの中へ書き込まない)
"$RES/python/bin/python3" -m compileall -q -j 0 "$RES" >/dev/null || true

cat > "$APP/Contents/MacOS/ReceiptPilot" <<'SH'
#!/bin/bash
RES="$(cd "$(dirname "$0")/../Resources" && pwd)"
unset PYTHONPATH PYTHONHOME
export PYTHONDONTWRITEBYTECODE=1 PYTHONNOUSERSITE=1
exec "$RES/python/bin/python3" -s "$RES/launcher.py"
SH
chmod +x "$APP/Contents/MacOS/ReceiptPilot"

build/tools/bin/pip install -q pillow
build/tools/bin/python macos/make_icon.py build/icon
cp build/icon/ReceiptPilot.icns "$RES/ReceiptPilot.icns"

cat > "$APP/Contents/Info.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleName</key><string>ReceiptPilot</string>
  <key>CFBundleDisplayName</key><string>ReceiptPilot</string>
  <key>CFBundleIdentifier</key><string>tech.kiilab.receiptpilot</string>
  <key>CFBundleVersion</key><string>${VERSION}</string>
  <key>CFBundleShortVersionString</key><string>${VERSION}</string>
  <key>CFBundleExecutable</key><string>ReceiptPilot</string>
  <key>CFBundleIconFile</key><string>ReceiptPilot</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleDevelopmentRegion</key><string>ja</string>
  <key>LSMinimumSystemVersion</key><string>${MIN_MACOS}</string>
  <key>LSArchitecturePriority</key><array><string>arm64</string></array>
  <key>NSHighResolutionCapable</key><true/>
  <key>NSDocumentsFolderUsageDescription</key>
  <string>レシートの画像と読み取り結果を「書類」フォルダの ReceiptPilot に保存するために使います。</string>
</dict>
</plist>
PLIST

echo "== 署名(アドホック)"
codesign --force --deep --sign - "$APP" >/dev/null 2>&1
codesign --verify --deep "$APP"

echo "== ディスクイメージ(.dmg)"
STAGE=build/dmg.noindex
rm -rf "$STAGE" && mkdir -p "$STAGE"
cp -R "$APP" "$STAGE/"
ln -s /Applications "$STAGE/アプリケーション"
cp macos/はじめにお読みください.txt "$STAGE/"
hdiutil create -quiet -volname "ReceiptPilot ${VERSION}" -srcfolder "$STAGE" \
  -ov -format UDZO "dist/ReceiptPilot-${VERSION}.dmg"

rm -rf "$STAGE"  # 作業用のコピーを残すと、Mac のアプリ一覧に重複して出てしまう

echo "== 完成"
du -sh "$APP" "dist/ReceiptPilot-${VERSION}.dmg"
