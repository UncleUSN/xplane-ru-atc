# Прописать папку X-Plane 12 в config.yaml.
# Те же правила, что у ru_atc.setup_config.apply_xplane_path:
#   заменяются все строки xplane_path (flight_plan_import и navdata);
#   если такой строки нет, в конец дописывается только navdata.xplane_path;
#   пустой путь файл не меняет. Файл остаётся UTF-8 без BOM.
param(
    [Parameter(Mandatory = $true)][string]$Config,
    [Parameter(Mandatory = $true)][string]$XPlane
)
$ErrorActionPreference = "Stop"
if (-not (Test-Path -LiteralPath $Config)) { exit 2 }
$dir = $XPlane.Trim().Trim('"').Trim("'")
if (-not $dir) { exit 0 }
$dir = ($dir -replace '\\', '/').TrimEnd('/')
$dir = $dir -replace '"', ''
$utf8 = New-Object System.Text.UTF8Encoding $false
$text = [System.IO.File]::ReadAllText($Config)
$newline = if ($text.Contains("`r`n")) { "`r`n" } else { "`n" }
$lines = $text -split "`r?`n", -1
$changed = $false
for ($i = 0; $i -lt $lines.Length; $i++) {
    if ($lines[$i] -match '^(\s*)xplane_path\s*:') {
        $lines[$i] = $Matches[1] + 'xplane_path: "' + $dir + '"'
        $changed = $true
    }
}
if (-not $changed) {
    if (-not $text.EndsWith("`n")) { $text += $newline }
    $text += 'navdata:' + $newline + '  xplane_path: "' + $dir + '"' + $newline
    [System.IO.File]::WriteAllText($Config, $text, $utf8)
    exit 0
}
$joined = ($lines -join $newline)
[System.IO.File]::WriteAllText($Config, $joined, $utf8)
exit 0
