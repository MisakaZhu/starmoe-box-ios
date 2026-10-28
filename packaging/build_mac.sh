#!/usr/bin/env bash
# 构建 macOS 版：dist/StarMoe Box.app → dist/StarMoeBox-mac-<arm64|x64>.dmg（拖进“应用程序”的安装界面）
#
# 用法：bash packaging/build_mac.sh
#   可选环境变量：
#     PYTHON=python3.12          用哪个 Python 建虚拟环境（需要 3.9+；CI 传入 setup-python 的绝对路径）
#     SKIP_TESTS=1               跳过测试
#     SKIP_NOTARIZE=1            有证书时只签名、不公证
#   ---- 可选：Developer ID 签名 + 公证（全部没有就构建未签名版本，用户首次需“右键→打开”）----
#     MACOS_SIGN_IDENTITY        例如 "Developer ID Application: Your Name (TEAMID)"
#     MACOS_CERT_P12_BASE64      .p12 证书的 base64（CI 用；本机已在钥匙串里的话可以不设）
#     MACOS_CERT_PASSWORD        .p12 的导出密码
#     公证方式一（Apple ID）：APPLE_ID、APPLE_TEAM_ID、APPLE_APP_PASSWORD（App 专用密码）
#     公证方式二（App Store Connect API 密钥）：APPLE_API_KEY_ID、APPLE_API_ISSUER、APPLE_API_KEY_P8_BASE64
#   本脚本不会打印任何密钥/密码/证书原文。
set -euo pipefail
cd "$(dirname "$0")/.."
PY=${PYTHON:-python3}
APP="dist/StarMoe Box.app"
ENT="packaging/macos/entitlements.plist"
case "$(uname -m)" in arm64) ARCH=arm64 ;; *) ARCH=x64 ;; esac
DMG="dist/StarMoeBox-mac-$ARCH.dmg"
IDENTITY="${MACOS_SIGN_IDENTITY:-${CODESIGN_IDENTITY:-}}"
IDENTITY=$(printf '%s' "$IDENTITY" | sed 's/^[[:space:]]*//;s/[[:space:]]*$//;s/^"//;s/"$//')
TMP=$(mktemp -d)
KEYCHAIN=""
ORIG_LIST=""
ORIG_DEFAULT=""

cleanup() {
  if [ -n "$ORIG_LIST" ]; then
    # shellcheck disable=SC2086
    security list-keychains -d user -s $ORIG_LIST >/dev/null 2>&1 || true
  fi
  if [ -n "$ORIG_DEFAULT" ]; then
    security default-keychain -s "$ORIG_DEFAULT" >/dev/null 2>&1 || true
  fi
  if [ -n "$KEYCHAIN" ]; then
    security delete-keychain "$KEYCHAIN" >/dev/null 2>&1 || true
  fi
  rm -rf "$TMP"
}
trap cleanup EXIT

b64dec() { base64 -D; }   # macOS BSD base64；GNU 的 --decode 在这里不可用

print_cert_dates() {
  local src=${1:-}
  local args=(-p)
  if [ -n "$src" ]; then args+=("$src"); fi
  # 只打印主题 / 颁发者 / 有效期，不打印 PEM
  security find-certificate -c "$IDENTITY" "${args[@]}" \
    | openssl x509 -noout -subject -issuer -startdate -enddate
}

# ---------------------------------------------------------------- 证书（临时钥匙串，在耗时的打包之前失败）
if [ -n "$IDENTITY" ]; then
  case "$IDENTITY" in
    "Developer ID Application:"*) ;;
    *)
      echo "MACOS_SIGN_IDENTITY 必须以 'Developer ID Application:' 开头（Developer ID Installer / Apple Development 不能给 App 签名）。" >&2
      exit 1
      ;;
  esac
fi

if [ -n "${MACOS_CERT_P12_BASE64:-}" ]; then
  if [ -z "$IDENTITY" ]; then echo "设置了 MACOS_CERT_P12_BASE64 但没有 MACOS_SIGN_IDENTITY" >&2; exit 1; fi
  KEYCHAIN="$TMP/build.keychain-db"
  KC_PASS=$(uuidgen)
  if ! printf '%s' "$MACOS_CERT_P12_BASE64" | b64dec > "$TMP/cert.p12"; then
    echo "MACOS_CERT_P12_BASE64 无法用 base64 解码" >&2
    exit 1
  fi
  if [ ! -s "$TMP/cert.p12" ]; then echo "解码后的证书是空文件" >&2; exit 1; fi
  ORIG_LIST=$(security list-keychains -d user | sed -e 's/^[[:space:]]*"//' -e 's/"[[:space:]]*$//')
  ORIG_DEFAULT=$(security default-keychain 2>/dev/null | sed -e 's/^[[:space:]]*"//' -e 's/"[[:space:]]*$//' || true)
  security create-keychain -p "$KC_PASS" "$KEYCHAIN"
  security set-keychain-settings -lut 21600 "$KEYCHAIN"
  security unlock-keychain -p "$KC_PASS" "$KEYCHAIN"
  # 加到搜索列表最前面，并设为默认，否则 codesign 找不到私钥
  # shellcheck disable=SC2086
  security list-keychains -d user -s "$KEYCHAIN" $ORIG_LIST
  security default-keychain -s "$KEYCHAIN"
  import_rc=0
  security import "$TMP/cert.p12" -k "$KEYCHAIN" -P "${MACOS_CERT_PASSWORD:-}" -f pkcs12 \
    -T /usr/bin/codesign -T /usr/bin/security -T /usr/bin/productsign >/dev/null || import_rc=$?
  rm -f "$TMP/cert.p12"
  if [ "$import_rc" -ne 0 ]; then
    echo "导入 p12 失败。若系统提示 MAC verification failed / invalid password，就是 MACOS_CERT_PASSWORD 不正确。" >&2
    exit 1
  fi
  security set-key-partition-list -S apple-tool:,apple:,codesign: -s -k "$KC_PASS" "$KEYCHAIN" >/dev/null
  if ! security find-identity -v -p codesigning "$KEYCHAIN" | grep -F -q "$IDENTITY"; then
    echo "证书里找不到签名身份（MACOS_SIGN_IDENTITY 必须与证书名称完全一致，且类型为 Developer ID Application）。" >&2
    security find-identity -v -p codesigning "$KEYCHAIN" | sed -E 's/[0-9A-Fa-f]{40}/<sha1>/' >&2
    echo "证书主题：" >&2
    security find-certificate -a -p "$KEYCHAIN" | openssl x509 -noout -subject -dates >&2 || true
    exit 1
  fi
  echo "==> 已导入临时钥匙串。证书："
  print_cert_dates "$KEYCHAIN"
fi

# ---------------------------------------------------------------- 构建
if [ ! -d .venv-build ]; then "$PY" -m venv .venv-build; fi
# shellcheck disable=SC1091
source .venv-build/bin/activate
python -m pip install -U pip
# Intel 上禁止从源码编译 cryptography（会动态链接 Homebrew OpenSSL，和 sslpsk 的 libcrypto 冲突）
python -m pip install --only-binary=cryptography -r requirements.txt -r requirements-gui.txt
python -c "import cryptography,sys; print('cryptography', cryptography.__version__, sys.version)"
if [ "${SKIP_TESTS:-}" != "1" ]; then
  PYTHONPATH=. python tests/test_all.py
  PYTHONPATH=. python tests/test_keyfetch.py
  PYTHONPATH=. python tests/test_tls.py
fi
rm -rf build "dist/StarMoe Box.app" dist/StarMoeBox "$DMG"
# 签名统一由下面的 sign_app 完成，这里不让 PyInstaller 签
env -u CODESIGN_IDENTITY pyinstaller --noconfirm --clean packaging/starmoe_box.spec
/usr/libexec/PlistBuddy -c "Print :CFBundleURLTypes:0:CFBundleURLSchemes:0" "$APP/Contents/Info.plist"

shopt -s nullglob
for so in "$APP/Contents/Frameworks/cryptography/hazmat/bindings/"*.so; do
  if otool -L "$so" | grep -E 'libcrypto|libssl' >/dev/null; then
    echo "cryptography 扩展动态链接了 libcrypto/libssl，会和 sslpsk-pmd3 自带的 OpenSSL 撞名。" >&2
    otool -L "$so" >&2
    exit 1
  fi
done
shopt -u nullglob

# ---------------------------------------------------------------- 签名
codesign_bin() {   # 内部 Mach-O：hardened runtime + 时间戳，不附带 App 的 entitlements
  local kc=()
  if [ -n "$KEYCHAIN" ]; then kc=(--keychain "$KEYCHAIN"); fi
  codesign --force --options runtime --timestamp --sign "$IDENTITY" ${kc[@]+"${kc[@]}"} "$@"
}
codesign_sealed() {   # 主程序与 .app：hardened runtime + entitlements
  local kc=()
  if [ -n "$KEYCHAIN" ]; then kc=(--keychain "$KEYCHAIN"); fi
  codesign --force --options runtime --timestamp --entitlements "$ENT" --sign "$IDENTITY" ${kc[@]+"${kc[@]}"} "$@"
}

sign_app() {
  echo "==> 使用 Developer ID 签名（hardened runtime；先签内部二进制和 framework）"
  local main="$APP/Contents/MacOS/StarMoeBox" f
  python3 -c 'import os,sys
root=sys.argv[1]
fs=[os.path.join(d,n) for d,_,ns in os.walk(root) for n in ns if "_CodeSignature" not in d and not os.path.islink(os.path.join(d,n))]
print("\n".join(sorted(fs,key=lambda p:-p.count(os.sep))))' "$APP/Contents" > "$TMP/files.txt"
  while IFS= read -r f; do
    [ "$f" = "$main" ] && continue
    kind=$(file -b "$f" || true)
    case "$kind" in
      *Mach-O*)
        case "$kind" in
          *"object "*) ;;
          *) codesign_bin "$f" >/dev/null ;;
        esac
        ;;
    esac
  done < "$TMP/files.txt"
  python3 -c 'import os,sys
roots=[]
for d,_,_ns in os.walk(sys.argv[1]):
    if d.endswith(".framework") and "_CodeSignature" not in d:
        roots.append(d)
print("\n".join(sorted(set(roots),key=lambda p:-p.count(os.sep))))' "$APP/Contents" > "$TMP/frameworks.txt"
  while IFS= read -r f; do
    [ -n "$f" ] && codesign_bin "$f" >/dev/null
  done < "$TMP/frameworks.txt"
  codesign_sealed "$main"
  codesign_sealed "$APP"
  codesign --verify --deep --strict --verbose=2 "$APP"
  echo "==> 签名身份（codesign / security，不含私钥）"
  codesign -dvv "$APP" 2>&1 | grep -E '^(Authority|TeamIdentifier|Identifier|Format)=' || true
  if [ -n "$KEYCHAIN" ]; then print_cert_dates "$KEYCHAIN"; else print_cert_dates; fi
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
  if ! printf '%s' "$APPLE_API_KEY_P8_BASE64" | b64dec > "$TMP/AuthKey.p8"; then
    echo "APPLE_API_KEY_P8_BASE64 无法解码" >&2
    exit 1
  fi
  NOTARY=(--key "$TMP/AuthKey.p8" --key-id "$APPLE_API_KEY_ID" --issuer "$APPLE_API_ISSUER")
elif [ -n "${APPLE_ID:-}" ] && [ -n "${APPLE_TEAM_ID:-}" ] && [ -n "${APPLE_APP_PASSWORD:-}" ]; then
  NOTARY=(--apple-id "$APPLE_ID" --team-id "$APPLE_TEAM_ID" --password "$APPLE_APP_PASSWORD")
fi

notarize() {   # notarize <文件>：提交并等待；失败时打印 Apple 返回的日志（不含密码）
  echo "==> 提交公证：$1（xcrun notarytool submit --wait）"
  local out id status
  out=$(xcrun notarytool submit "$1" "${NOTARY[@]}" --wait --output-format json 2>"$TMP/notary.err") || true
  if [ -s "$TMP/notary.err" ]; then cat "$TMP/notary.err" >&2; fi
  id=$(printf '%s' "$out" | python3 -c 'import json,sys
raw=sys.stdin.read(); s=raw.find("{"); e=raw.rfind("}")
print("" if s<0 or e<s else json.loads(raw[s:e+1]).get("id",""))' 2>/dev/null || true)
  status=$(printf '%s' "$out" | python3 -c 'import json,sys
raw=sys.stdin.read(); s=raw.find("{"); e=raw.rfind("}")
print("" if s<0 or e<s else json.loads(raw[s:e+1]).get("status",""))' 2>/dev/null || true)
  echo "    公证结果：${status:-未知}（submission id: ${id:-无}）"
  if [ "$status" != "Accepted" ]; then
    echo "==> notarytool log" >&2
    if [ -n "$id" ]; then xcrun notarytool log "$id" "${NOTARY[@]}" >&2 || true; fi
    printf '%s\n' "$out" >&2
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
  codesign --verify --strict --verbose=2 "$DMG"
fi
if [ "$DO_NOTARIZE" = 1 ]; then
  notarize "$DMG"
  xcrun stapler staple "$DMG"
  xcrun stapler validate "$APP"
  xcrun stapler validate "$DMG"
  echo "==> Gatekeeper 校验"
  codesign --verify --deep --strict --verbose=2 "$APP"
  codesign --verify --strict --verbose=2 "$DMG"
  spctl -a -vvv -t install "$APP"
  spctl -a -vvv -t install "$DMG"
fi
hdiutil verify "$DMG" >/dev/null
echo "完成：$DMG （签名：$([ "$SIGNED" = 1 ] && echo Developer ID || echo 无)，公证：$([ "$DO_NOTARIZE" = 1 ] && echo 已公证 || echo 无)）"
