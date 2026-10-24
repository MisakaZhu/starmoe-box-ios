#!/usr/bin/env bash
# 构建 macOS 版：dist/StarMoe Box.app → dist/StarMoeBox-mac-<arm64|x64>.dmg（拖进“应用程序”的安装界面）
#
# 用法：bash packaging/build_mac.sh
#   可选环境变量：
#     PYTHON=python3.12          用哪个 Python 建虚拟环境（需要 3.9+）
#     SKIP_TESTS=1               跳过测试
#     SKIP_NOTARIZE=1            有证书时只签名、不公证
#   ---- 可选：Developer ID 签名 + 公证（全部没有就构建未签名版本，用户首次需“右键→打开”）----
#     MACOS_SIGN_IDENTITY        例如 "Developer ID Application: Your Name (TEAMID)"
#     MACOS_CERT_P12_BASE64      .p12 证书的 base64（CI 用；本机已在钥匙串里的话可以不设）
#     MACOS_CERT_PASSWORD        .p12 的导出密码
#     公证方式一（Apple ID）：APPLE_ID、APPLE_TEAM_ID、APPLE_APP_PASSWORD（App 专用密码）
#     公证方式二（App Store Connect API 密钥）：APPLE_API_KEY_ID、APPLE_API_ISSUER、APPLE_API_KEY_P8_BASE64
#   本脚本不会打印任何密钥/密码。
set -euo pipefail
cd "$(dirname "$0")/.."
PY=${PYTHON:-python3}
APP="dist/StarMoe Box.app"
ENT="packaging/macos/entitlements.plist"
case "$(uname -m)" in arm64) ARCH=arm64 ;; *) ARCH=x64 ;; esac
DMG="dist/StarMoeBox-mac-$ARCH.dmg"
IDENTITY="${MACOS_SIGN_IDENTITY:-${CODESIGN_IDENTITY:-}}"
TMP=$(mktemp -d)
KEYCHAIN=""

cleanup() {
  if [ -n "$KEYCHAIN" ]; then
    security delete-keychain "$KEYCHAIN" >/dev/null 2>&1 || true
  fi
  rm -rf "$TMP"
}
trap cleanup EXIT

# ---------------------------------------------------------------- 构建
if [ ! -d .venv-build ]; then "$PY" -m venv .venv-build; fi
source .venv-build/bin/activate
python -m pip install -U pip
python -m pip install -r requirements.txt -r requirements-gui.txt
if [ "${SKIP_TESTS:-}" != "1" ]; then
  PYTHONPATH=. python tests/test_all.py
  PYTHONPATH=. python tests/test_keyfetch.py
fi
rm -rf build "dist/StarMoe Box.app" dist/StarMoeBox "$DMG"
# 签名统一由下面的 sign_app 完成，这里不让 PyInstaller 签
env -u CODESIGN_IDENTITY pyinstaller --noconfirm --clean packaging/starmoe_box.spec
/usr/libexec/PlistBuddy -c "Print :CFBundleURLTypes:0:CFBundleURLSchemes:0" "$APP/Contents/Info.plist"

# ---------------------------------------------------------------- 证书（临时钥匙串）
if [ -n "${MACOS_CERT_P12_BASE64:-}" ]; then
  if [ -z "$IDENTITY" ]; then echo "设置了 MACOS_CERT_P12_BASE64 但没有 MACOS_SIGN_IDENTITY" >&2; exit 1; fi
  KEYCHAIN="$TMP/build.keychain-db"
  KC_PASS=$(uuidgen)
  printf '%s' "$MACOS_CERT_P12_BASE64" | base64 --decode > "$TMP/cert.p12"
  security create-keychain -p "$KC_PASS" "$KEYCHAIN"
  security set-keychain-settings -lut 21600 "$KEYCHAIN"
  security unlock-keychain -p "$KC_PASS" "$KEYCHAIN"
  security import "$TMP/cert.p12" -k "$KEYCHAIN" -P "${MACOS_CERT_PASSWORD:-}" -T /usr/bin/codesign -T /usr/bin/security >/dev/null
  rm -f "$TMP/cert.p12"
  security set-key-partition-list -S apple-tool:,apple:,codesign: -s -k "$KC_PASS" "$KEYCHAIN" >/dev/null
  # 加到搜索列表最前面（保留原有钥匙串）
  security list-keychains -d user -s "$KEYCHAIN" $(security list-keychains -d user | tr -d '"')
  security find-identity -v -p codesigning "$KEYCHAIN" | grep -q "$IDENTITY" || {
    echo "证书里找不到签名身份：$IDENTITY（请检查 MACOS_SIGN_IDENTITY 是否与证书名称完全一致）" >&2
    security find-identity -v -p codesigning "$KEYCHAIN" | sed 's/[0-9A-F]\{40\}/<sha1>/' >&2
    exit 1
  }
fi

# ---------------------------------------------------------------- 签名
cs() {   # codesign 包装：Developer ID 时启用 hardened runtime + 时间戳
  local kc=()
  if [ -n "$KEYCHAIN" ]; then kc=(--keychain "$KEYCHAIN"); fi
  codesign --force --options runtime --timestamp --entitlements "$ENT" --sign "$IDENTITY" ${kc[@]+"${kc[@]}"} "$@"
}

sign_app() {
  echo "==> 使用 Developer ID 签名（hardened runtime）"
  # 由内向外：先签所有 Mach-O（.so / .dylib / 可执行文件），再签 .framework，最后签 .app 本身
  local f
  # 按目录深度从深到浅列出文件（不跟随符号链接）
  python3 -c 'import os,sys
fs=[os.path.join(d,n) for d,_,ns in os.walk(sys.argv[1]) for n in ns if "_CodeSignature" not in d and not os.path.islink(os.path.join(d,n))]
print("\n".join(sorted(fs,key=lambda p:-p.count(os.sep))))' "$APP/Contents" > "$TMP/files.txt"
  while IFS= read -r f; do
    if file -b "$f" | grep -q "Mach-O"; then cs "$f" >/dev/null; fi
  done < "$TMP/files.txt"
  while IFS= read -r -d '' f; do cs "$f" >/dev/null; done < <(find "$APP/Contents" -type d -name "*.framework" -print0)
  cs "$APP"
  codesign --verify --deep --strict --verbose=2 "$APP"
}

if [ -n "$IDENTITY" ]; then
  sign_app
  SIGNED=1
else
  echo "==> 未提供签名证书：使用 ad-hoc 签名（Apple Silicon 上才能运行；首次打开需“右键→打开”）"
  codesign --force --deep --sign - "$APP"
  SIGNED=0
fi
"$APP/Contents/MacOS/StarMoeBox" --selftest   # 检查依赖是否打包完整

# ---------------------------------------------------------------- 公证
NOTARY=()
if [ -n "${APPLE_API_KEY_ID:-}" ] && [ -n "${APPLE_API_ISSUER:-}" ] && [ -n "${APPLE_API_KEY_P8_BASE64:-}" ]; then
  printf '%s' "$APPLE_API_KEY_P8_BASE64" | base64 --decode > "$TMP/AuthKey.p8"
  NOTARY=(--key "$TMP/AuthKey.p8" --key-id "$APPLE_API_KEY_ID" --issuer "$APPLE_API_ISSUER")
elif [ -n "${APPLE_ID:-}" ] && [ -n "${APPLE_TEAM_ID:-}" ] && [ -n "${APPLE_APP_PASSWORD:-}" ]; then
  NOTARY=(--apple-id "$APPLE_ID" --team-id "$APPLE_TEAM_ID" --password "$APPLE_APP_PASSWORD")
fi

notarize() {   # notarize <文件>：提交并等待；失败时打印 Apple 返回的日志
  echo "==> 提交公证：$1（通常需要几分钟）"
  local out id status
  out=$(xcrun notarytool submit "$1" "${NOTARY[@]}" --wait --output-format json) || true
  id=$(printf '%s' "$out" | python3 -c 'import json,sys; print(json.load(sys.stdin).get("id",""))' 2>/dev/null || true)
  status=$(printf '%s' "$out" | python3 -c 'import json,sys; print(json.load(sys.stdin).get("status",""))' 2>/dev/null || true)
  echo "    公证结果：${status:-未知}（submission id: ${id:-无}）"
  if [ "$status" != "Accepted" ]; then
    [ -n "$id" ] && xcrun notarytool log "$id" "${NOTARY[@]}" || printf '%s\n' "$out"
    exit 1
  fi
}

DO_NOTARIZE=0
if [ "$SIGNED" = 1 ] && [ ${#NOTARY[@]} -gt 0 ] && [ "${SKIP_NOTARIZE:-}" != "1" ]; then DO_NOTARIZE=1; fi
if [ "$SIGNED" = 1 ] && [ ${#NOTARY[@]} -eq 0 ]; then echo "==> 已签名但未提供公证凭据，跳过公证"; fi

if [ "$DO_NOTARIZE" = 1 ]; then   # 先公证 .app 并装订票据，这样拖出 DMG 后离线也能通过 Gatekeeper
  ditto -c -k --sequesterRsrc --keepParent "$APP" "$TMP/app.zip"
  notarize "$TMP/app.zip"
  xcrun stapler staple "$APP"
fi

# ---------------------------------------------------------------- DMG
echo "==> 制作 $DMG"
STAGE="$TMP/dmg"
mkdir -p "$STAGE"
ditto "$APP" "$STAGE/StarMoe Box.app"
BG="packaging/icons/dmg_background.png"
made=0
if command -v create-dmg >/dev/null 2>&1; then
  # create-dmg 需要操作 Finder 来摆放图标；在无界面的环境里可能失败，失败时退回 hdiutil
  if create-dmg --volname "StarMoe Box" --volicon packaging/icons/app.icns --background "$BG" \
      --window-pos 200 120 --window-size 660 400 --icon-size 112 \
      --icon "StarMoe Box.app" 180 190 --hide-extension "StarMoe Box.app" --app-drop-link 480 190 \
      "$DMG" "$STAGE"; then
    made=1
  else
    echo "create-dmg 失败，改用 hdiutil" >&2
    rm -f "$DMG"
  fi
fi
if [ "$made" = 0 ]; then
  ln -s /Applications "$STAGE/Applications"
  hdiutil create -volname "StarMoe Box" -srcfolder "$STAGE" -ov -fs HFS+ -format UDZO "$DMG"
fi

if [ "$SIGNED" = 1 ]; then
  kc=()
  if [ -n "$KEYCHAIN" ]; then kc=(--keychain "$KEYCHAIN"); fi
  codesign --force --timestamp --sign "$IDENTITY" ${kc[@]+"${kc[@]}"} "$DMG"
fi
if [ "$DO_NOTARIZE" = 1 ]; then
  notarize "$DMG"
  xcrun stapler staple "$DMG"
  xcrun stapler validate "$DMG"
  spctl -a -t open --context context:primary-signature -v "$DMG" || true
  spctl -a -t exec -vv "$APP" || true
fi
hdiutil verify "$DMG" >/dev/null
echo "完成：$DMG （签名：$([ "$SIGNED" = 1 ] && echo Developer ID || echo 无)，公证：$([ "$DO_NOTARIZE" = 1 ] && echo 已公证 || echo 无)）"
