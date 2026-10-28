# 构建 Windows 版：dist\StarMoeBox\（程序目录） → dist\StarMoeBox-Setup.exe（安装包，按用户安装、无需管理员）
# 用法（PowerShell，仓库根目录）：powershell -ExecutionPolicy Bypass -File packaging\build_windows.ps1
# 需要 Inno Setup 6（https://jrsoftware.org/isinfo.php）；没有时如果有 choco 会自动安装。
# 解释器：优先用环境变量 PYTHON（CI 里应设为 setup-python 的 python-path）。
# 不要用「py -3」：GitHub 托管镜像上它会选到最新的自由线程 Python（3.15），
# cryptography 的 abi3t wheel 依赖 python3t.dll，PyInstaller 打不进去，selftest 导入 _rust 失败。
$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..")
if ($env:PYTHON) {
    $py = $env:PYTHON
} elseif (Get-Command python -ErrorAction SilentlyContinue) {
    $py = (Get-Command python).Source
} else {
    $py = "py"
}
Write-Host "build interpreter: $py"
& $py -c "import sys; print(sys.executable); print(sys.version)"
if ($LASTEXITCODE -ne 0) { throw "python probe failed" }
if (-not (Test-Path ".venv-build")) {
    $leaf = [IO.Path]::GetFileName($py)
    if ($leaf -match '^py(\.exe)?$') {
        # 没有 PATH 上的 python 时，固定要 3.12，避免 py -3 选中 3.15t
        & $py -3.12 -m venv .venv-build
    } else {
        & $py -m venv .venv-build
    }
    if ($LASTEXITCODE -ne 0) { throw "venv failed" }
}
& .\.venv-build\Scripts\Activate.ps1
python -c "import sys; print('venv', sys.version); raise SystemExit(2 if 't' in getattr(sys, 'abiflags', '') else 0)"
if ($LASTEXITCODE -ne 0) { throw "refusing to package with free-threaded Python; use CPython 3.12" }
python -m pip install -U pip
python -m pip install --only-binary=cryptography -r requirements.txt -r requirements-gui.txt
$env:PYTHONPATH = "."
if ($env:SKIP_TESTS -ne "1") {
  python tests\test_all.py
  if ($LASTEXITCODE -ne 0) { throw "tests failed" }
  python tests\test_keyfetch.py
  if ($LASTEXITCODE -ne 0) { throw "keyfetch tests failed" }
  python tests\test_tls.py
  if ($LASTEXITCODE -ne 0) { throw "tls tests failed" }
}
if (Test-Path "dist\StarMoeBox") { Remove-Item -Recurse -Force "dist\StarMoeBox" }
pyinstaller --noconfirm --clean packaging\starmoe_box.spec
if ($LASTEXITCODE -ne 0) { throw "pyinstaller failed" }
$p = Start-Process -FilePath "dist\StarMoeBox\StarMoeBox.exe" -ArgumentList "--selftest" -Wait -PassThru
if ($p.ExitCode -ne 0) { Get-Content "$env:LOCALAPPDATA\StarMoeBox\logs\selftest.txt"; throw "selftest failed" }

# ---- Inno Setup ----
$iscc = (Get-Command ISCC.exe -ErrorAction SilentlyContinue).Source
foreach ($c in @("${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe", "$env:ProgramFiles\Inno Setup 6\ISCC.exe",
                 "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe")) {
  if (-not $iscc -and (Test-Path $c)) { $iscc = $c }
}
if (-not $iscc -and (Get-Command choco -ErrorAction SilentlyContinue)) {
  choco install innosetup -y --no-progress
  $iscc = "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe"
}
if (-not $iscc -or -not (Test-Path $iscc)) { throw "找不到 Inno Setup 6（ISCC.exe），请先安装：https://jrsoftware.org/isdl.php" }
# 旧版 Inno Setup 不自带简体中文语言文件时，从官方仓库取一份（只在构建时使用）
$langDir = Join-Path (Split-Path $iscc) "Languages"
if (-not (Test-Path (Join-Path $langDir "ChineseSimplified.isl")) -and -not (Test-Path "packaging\windows\ChineseSimplified.isl")) {
  try {
    Invoke-WebRequest "https://raw.githubusercontent.com/jrsoftware/issrc/main/Files/Languages/ChineseSimplified.isl" `
      -OutFile "packaging\windows\ChineseSimplified.isl" -UseBasicParsing
  } catch { Write-Warning "无法下载简体中文语言文件，安装界面将使用英文" }
}
$ver = [regex]::Match((Get-Content "starmoe_ios\gui\__init__.py" -Raw -Encoding UTF8), 'VERSION\s*=\s*"([^"]+)"').Groups[1].Value
& $iscc "/DAppVersion=$ver" "packaging\windows\StarMoeBox.iss"
if ($LASTEXITCODE -ne 0) { throw "ISCC failed" }
Write-Host "完成：dist\StarMoeBox-Setup.exe（程序目录：dist\StarMoeBox\）"
