# Сборка установщика RU ATC в Windows.
# Нужны: Python 3.11 или 3.12 x64, Inno Setup 6.3 или новее.
# Запуск из любой папки:  powershell -ExecutionPolicy Bypass -File installer\build.ps1
# Корень репозитория — родитель каталога этого скрипта ($PSScriptRoot = installer\).
# Результат: dist\installer\RU-ATC-<версия>-setup.exe
$ErrorActionPreference = "Stop"
if ($env:OS -ne "Windows_NT") {
    Write-Error "Сборка установщика запускается только в Windows. Скрипт и workflow лежат в репозитории, exe здесь не создаётся."
    exit 1
}
if (-not $PSScriptRoot) {
    throw "Запустите файл так: powershell -ExecutionPolicy Bypass -File installer\build.ps1"
}

# Один уровень вверх от installer\. Два уровня на бегуне дали бы D:\a\xplane-ru-atc\
# вместо D:\a\xplane-ru-atc\xplane-ru-atc\ — там нет ru_atc\__main__.py.
$Root = Split-Path -Parent $PSScriptRoot
$Entry = Join-Path $Root "ru_atc\__main__.py"
if (-not (Test-Path -LiteralPath $Entry)) {
    throw "Не найден $Entry. Корень определён как $Root (родитель $PSScriptRoot)."
}
Set-Location -LiteralPath $Root
Write-Host "Корень репозитория: $Root"

# Консоль бегуна часто cp1252. Без UTF-8 python падает на русской строке,
# а Windows PowerShell 5.1 из-за кода выхода внешнего процесса сам не останавливается.
$env:PYTHONUTF8 = "1"
$env:PYTHONIOENCODING = "utf-8"

function Invoke-Python {
    param([Parameter(Mandatory = $true)][string[]]$PyArgs)
    # Аргументы передаются массивом: «-m» и «--quad» иначе становятся параметрами этой функции.
    & python @PyArgs
    if ($LASTEXITCODE -ne 0) {
        throw "python $($PyArgs -join ' ') завершился с кодом $LASTEXITCODE"
    }
}

$Version = "$(Invoke-Python -PyArgs @('installer\print_version.py'))".Trim()
if (-not $Version) { throw "Не удалось прочитать ru_atc/__init__.py" }
$VersionInfo = "$(Invoke-Python -PyArgs @('installer\print_version.py', '--quad'))".Trim()
if (-not $VersionInfo) { throw "Не удалось собрать числовую версию для Windows" }
Write-Host "Версия: $Version ($VersionInfo)"

Write-Host "Зависимости сборки (torch CPU, PyInstaller)..."
Invoke-Python -PyArgs @("-m", "pip", "install", "--upgrade", "pip")
Invoke-Python -PyArgs @("-m", "pip", "install", "-r", "requirements-build.txt")

Write-Host "Страница моделей и шаблоны config.yaml..."
Invoke-Python -PyArgs @("installer\render_catalog.py")

Write-Host "PyInstaller..."
$DistPath = Join-Path $Root "dist"
$WorkPath = Join-Path $Root "build"
Invoke-Python -PyArgs @(
    "-m", "PyInstaller", "--noconfirm", "--clean",
    "--distpath", $DistPath,
    "--workpath", $WorkPath,
    (Join-Path $Root "installer\ru_atc.spec")
)

$Dist = Join-Path $Root "dist\RU-ATC"
$Exe = Join-Path $Dist "RU-ATC.exe"
if (-not (Test-Path -LiteralPath $Exe)) {
    throw "PyInstaller не создал dist\RU-ATC\RU-ATC.exe"
}

# Рядом с exe, а не внутри _internal: отсюда программа читает data и config.
Copy-Item -Force (Join-Path $Root "config.example.yaml") $Dist
Copy-Item -Force (Join-Path $Root "THIRD_PARTY_LICENSES.md") $Dist
Copy-Item -Force (Join-Path $Root "CHANGELOG.md") $Dist
$dataDest = Join-Path $Dist "data"
if (Test-Path -LiteralPath $dataDest) { Remove-Item -LiteralPath $dataDest -Recurse -Force }
Copy-Item -Recurse -Force (Join-Path $Root "data") $dataDest
New-Item -ItemType Directory -Force -Path (Join-Path $Dist "models") | Out-Null
New-Item -ItemType Directory -Force -Path (Join-Path $Dist "logs") | Out-Null

$PortAudio = Get-ChildItem -LiteralPath $Dist -Recurse -Filter "libportaudio64bit.dll" -ErrorAction SilentlyContinue |
    Where-Object { $_.FullName -match "_sounddevice_data" } |
    Select-Object -First 1
if (-not $PortAudio) {
    throw "В dist\RU-ATC нет _sounddevice_data\...\libportaudio64bit.dll (PortAudio для sounddevice)."
}
Write-Host "PortAudio: $($PortAudio.FullName)"

Write-Host "Проверка запуска RU-ATC.exe --smoke..."
$SmokeReport = Join-Path $Root "dist\smoke.txt"
if (Test-Path -LiteralPath $SmokeReport) { Remove-Item -LiteralPath $SmokeReport -Force }
$env:RU_ATC_SMOKE_REPORT = $SmokeReport
$proc = Start-Process -FilePath $Exe -ArgumentList "--smoke" -WorkingDirectory $Dist -WindowStyle Hidden -PassThru
if (-not $proc.WaitForExit(300000)) {
    & taskkill.exe /PID $proc.Id /T /F 2>$null | Out-Null
    if (Test-Path -LiteralPath $SmokeReport) {
        Write-Host "---- smoke (таймаут) ----"
        Get-Content -LiteralPath $SmokeReport -Encoding UTF8 | Write-Host
    }
    throw "RU-ATC.exe --smoke не завершился за 5 минут"
}
$proc.Refresh()
if (Test-Path -LiteralPath $SmokeReport) {
    Write-Host "---- smoke ----"
    Get-Content -LiteralPath $SmokeReport -Encoding UTF8 | Write-Host
    Write-Host "---- /smoke ----"
}
if ($proc.ExitCode -ne 0) {
    throw "RU-ATC.exe --smoke завершился с кодом $($proc.ExitCode)"
}
Remove-Item -ErrorAction SilentlyContinue Env:\RU_ATC_SMOKE_REPORT

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
$InstallerDir = Join-Path $Root "dist\installer"
New-Item -ItemType Directory -Force -Path $InstallerDir | Out-Null
# Пути в ru-atc.iss относительны каталогу installer\ (один «..» — корень репозитория).
& $Iscc "/DMyAppVersion=$Version" "/DMyVersionInfo=$VersionInfo" (Join-Path $Root "installer\ru-atc.iss")
if ($LASTEXITCODE -ne 0) { throw "ISCC завершился с кодом $LASTEXITCODE" }
$Setup = Join-Path $InstallerDir "RU-ATC-$Version-setup.exe"
if (-not (Test-Path -LiteralPath $Setup)) {
    throw "ISCC не создал $Setup"
}
Write-Host "Готово: dist\installer\RU-ATC-$Version-setup.exe"
