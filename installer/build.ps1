# Сборка установщика RU ATC в Windows.
# Нужны: Python 3.11 или 3.12 x64, Inno Setup 6.3 или новее.
# Запуск из любой папки:  powershell -ExecutionPolicy Bypass -File installer\build.ps1
# Результат: dist\installer\RU-ATC-<версия>-setup.exe
# Готовый exe в среде подготовки релиза (Linux) не собирался — см. вики «Сборка установщика».
$ErrorActionPreference = "Stop"
if ($env:OS -ne "Windows_NT") {
    Write-Error "Сборка установщика запускается только в Windows. Скрипт и workflow лежат в репозитории, exe здесь не создаётся."
    exit 1
}

$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $Root

$Version = (python installer\print_version.py).Trim()
if (-not $Version) { throw "Не удалось прочитать ru_atc/__init__.py" }
$VersionInfo = (python installer\print_version.py --quad).Trim()
if (-not $VersionInfo) { throw "Не удалось собрать числовую версию для Windows" }
Write-Host "Версия: $Version ($VersionInfo)"

Write-Host "Зависимости сборки (torch CPU, PyInstaller)..."
python -m pip install --upgrade pip
python -m pip install -r requirements-build.txt

Write-Host "Страница моделей и шаблоны config.yaml..."
python installer\render_catalog.py

Write-Host "PyInstaller..."
python -m PyInstaller --noconfirm --clean installer\ru_atc.spec
$Dist = Join-Path $Root "dist\RU-ATC"
if (-not (Test-Path (Join-Path $Dist "RU-ATC.exe"))) {
    throw "PyInstaller не создал dist\RU-ATC\RU-ATC.exe"
}

# Рядом с exe, а не внутри _internal: отсюда программа читает data и config.
Copy-Item -Force (Join-Path $Root "config.example.yaml") $Dist
Copy-Item -Force (Join-Path $Root "THIRD_PARTY_LICENSES.md") $Dist
Copy-Item -Force (Join-Path $Root "CHANGELOG.md") $Dist
Copy-Item -Recurse -Force (Join-Path $Root "data") (Join-Path $Dist "data")
New-Item -ItemType Directory -Force -Path (Join-Path $Dist "models") | Out-Null
New-Item -ItemType Directory -Force -Path (Join-Path $Dist "logs") | Out-Null

$IsccCandidates = @(
    "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
    "$env:ProgramFiles\Inno Setup 6\ISCC.exe"
)
$Iscc = $IsccCandidates | Where-Object { $_ -and (Test-Path -LiteralPath $_) } | Select-Object -First 1
if (-not $Iscc) {
    $cmd = Get-Command iscc.exe -ErrorAction SilentlyContinue
    if ($cmd) { $Iscc = $cmd.Source }
}
if (-not $Iscc) {
    throw "Не найден ISCC.exe. Установите Inno Setup 6.3+ с https://jrsoftware.org/isinfo.php"
}

Write-Host "Inno Setup: $Iscc"
New-Item -ItemType Directory -Force -Path (Join-Path $Root "dist\installer") | Out-Null
& $Iscc "/DMyAppVersion=$Version" "/DMyVersionInfo=$VersionInfo" (Join-Path $Root "installer\ru-atc.iss")
if ($LASTEXITCODE -ne 0) { throw "ISCC завершился с кодом $LASTEXITCODE" }
Write-Host "Готово: dist\installer\RU-ATC-$Version-setup.exe"
