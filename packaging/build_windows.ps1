# 构建 Windows 版：dist\StarMoeBox\（程序目录） → dist\StarMoeBox-Setup.exe（安装包，按用户安装、无需管理员）
# 用法（PowerShell，仓库根目录）：powershell -ExecutionPolicy Bypass -File packaging\build_windows.ps1
# 需要 Inno Setup 6（https://jrsoftware.org/isinfo.php）；没有时如果有 choco 会自动安装。
$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..")
$py = if ($env:PYTHON) { $env:PYTHON } else { "py" }
if (-not (Test-Path ".venv-build")) { & $py -3 -m venv .venv-build }
& .\.venv-build\Scripts\Activate.ps1
python -m pip install -U pip
python -m pip install -r requirements.txt -r requirements-gui.txt
$env:PYTHONPATH = "."
if ($env:SKIP_TESTS -ne "1") {
  python tests\test_all.py
  if ($LASTEXITCODE -ne 0) { throw "tests failed" }
  python tests\test_keyfetch.py
  if ($LASTEXITCODE -ne 0) { throw "keyfetch tests failed" }
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
