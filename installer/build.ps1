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

# Только для проверки exe. В установщик эти переменные не попадают.
$env:PYGAME_HIDE_SUPPORT_PROMPT = "1"
$env:SDL_VIDEODRIVER = "dummy"
$env:SDL_AUDIODRIVER = "dummy"
$env:KMP_DUPLICATE_LIB_OK = "TRUE"

function Invoke-RuAtc {
    param(
        [Parameter(Mandatory = $true)][string]$Argument,
        [Parameter(Mandatory = $true)][int]$TimeoutMs,
        [Parameter(Mandatory = $true)][string]$Report
    )
    if (Test-Path -LiteralPath $Report) { Remove-Item -LiteralPath $Report -Force }
    $env:RU_ATC_SMOKE_REPORT = $Report
    Write-Host "Проверка запуска RU-ATC.exe $Argument..."
    $proc = Start-Process -FilePath $Exe -ArgumentList $Argument -WorkingDirectory $Dist -WindowStyle Hidden -PassThru
    if (-not $proc.WaitForExit($TimeoutMs)) {
        & taskkill.exe /PID $proc.Id /T /F 2>$null | Out-Null
        if (Test-Path -LiteralPath $Report) {
            Write-Host "---- $Argument (таймаут) ----"
            Get-Content -LiteralPath $Report -Encoding UTF8 | Write-Host
        }
        throw "RU-ATC.exe $Argument не завершился за $([int]($TimeoutMs / 1000)) с"
    }
    $proc.Refresh()
    if (Test-Path -LiteralPath $Report) {
        Write-Host "---- $Argument ----"
        Get-Content -LiteralPath $Report -Encoding UTF8 | Write-Host
        Write-Host "---- /$Argument ----"
    }
    if ($proc.ExitCode -ne 0) {
        throw "RU-ATC.exe $Argument завершился с кодом $($proc.ExitCode)"
    }
}

# --help проверяет, что загрузчик и пакет вообще стартуют. --smoke грузит torch;
# import sounddevice там нет: Pa_Initialize на бегуне без звуковой карты не возвращается.
Invoke-RuAtc -Argument "--help" -TimeoutMs 120000 -Report (Join-Path $Root "dist\help.txt")
Invoke-RuAtc -Argument "--smoke" -TimeoutMs 600000 -Report (Join-Path $Root "dist\smoke.txt")
Remove-Item -ErrorAction SilentlyContinue Env:\RU_ATC_SMOKE_REPORT
# --smoke направляет кеши в папку exe и может создать пустые cache и models\torch.
# В установщик их не кладём. Пустые models\ и logs\ скрипт создал сам, их оставляем.
foreach ($rel in @("cache", "models\torch")) {
    $leftover = Join-Path $Dist $rel
    if (Test-Path -LiteralPath $leftover) {
        Remove-Item -LiteralPath $leftover -Recurse -Force
        Write-Host "Убран служебный каталог проверки: $rel"
    }
}

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
