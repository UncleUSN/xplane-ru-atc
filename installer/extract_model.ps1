# Распаковать zip модели Vosk в папку установки.
# tar.exe есть в Windows 10 и новее и спокойнее относится к архиву на 1,8 ГБ,
# чем Expand-Archive. Вызывается из установщика Inno Setup.
param(
    [Parameter(Mandatory = $true)][string]$Zip,
    [Parameter(Mandatory = $true)][string]$Dest
)
$ErrorActionPreference = "Stop"
if (-not (Test-Path -LiteralPath $Zip)) {
    throw "Архив не найден: $Zip"
}
New-Item -ItemType Directory -Force -Path $Dest | Out-Null
$tar = Join-Path $env:SystemRoot "System32\tar.exe"
if (Test-Path -LiteralPath $tar) {
    & $tar -xf $Zip -C $Dest
    if ($LASTEXITCODE -ne 0) {
        throw "tar.exe завершился с кодом $LASTEXITCODE"
    }
} else {
    Expand-Archive -LiteralPath $Zip -DestinationPath $Dest -Force
}
Write-Host "Распаковано в $Dest"
