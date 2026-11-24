# Скачать архив модели в папку установки.
# Вызывается из мастера Inno Setup. Большой zip не должен попадать в %TEMP%.
param(
    [Parameter(Mandatory = $true)][string]$Url,
    [Parameter(Mandatory = $true)][string]$Dest
)
$ErrorActionPreference = "Stop"
if ($Url -notmatch '^https://') {
    throw "Нужен адрес https: $Url"
}
$destDir = Split-Path -Parent $Dest
if (-not $destDir) {
    throw "Нет папки для $Dest"
}
New-Item -ItemType Directory -Force -Path $destDir | Out-Null
$part = "$Dest.part"
if (Test-Path -LiteralPath $part) {
    Remove-Item -LiteralPath $part -Force
}
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
$client = New-Object System.Net.WebClient
$proxyUrl = $env:HTTPS_PROXY
if (-not $proxyUrl) { $proxyUrl = $env:HTTP_PROXY }
if (-not $proxyUrl) { $proxyUrl = $env:https_proxy }
if (-not $proxyUrl) { $proxyUrl = $env:http_proxy }
if ($proxyUrl) {
    $client.Proxy = New-Object System.Net.WebProxy($proxyUrl)
}
try {
    $client.DownloadFile($Url, $part)
} catch {
    if (Test-Path -LiteralPath $part) {
        Remove-Item -LiteralPath $part -Force
    }
    throw
} finally {
    $client.Dispose()
}
if (-not (Test-Path -LiteralPath $part)) {
    throw "Файл не появился: $part"
}
Move-Item -LiteralPath $part -Destination $Dest -Force
Write-Host "Скачано в $Dest"
