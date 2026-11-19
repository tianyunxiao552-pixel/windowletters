$ErrorActionPreference = 'Stop'
$native = Join-Path $PSScriptRoot 'agent-wechat\wx-v2.7.1-win32-x64.exe'
$serverConfig = Join-Path $PSScriptRoot 'agent-wechat\server.toml'
$dashboard = Join-Path $PSScriptRoot 'dashboard\dist'
$processes = Get-CimInstance Win32_Process -Filter "Name = 'python.exe' OR Name = 'wx-v2.7.1-win32-x64.exe'"

$astrbot = $processes | Where-Object {
    $_.Name -ieq 'python.exe' -and
    $_.CommandLine -match '(?:^|[\s"])main\.py(?:[\s"]|$)' -and
    $_.CommandLine -like ('*' + $dashboard + '*')
}
$bridge = $processes | Where-Object {
    $_.ExecutablePath -ieq $native -and
    $_.CommandLine -like ('*' + $serverConfig + '*')
}

$targets = @()
if ($astrbot) { $targets += $astrbot }
if ($bridge) { $targets += $bridge }

foreach ($process in $targets) {
    if (-not $process) { continue }
    try {
        Stop-Process -Id $process.ProcessId -Force -ErrorAction SilentlyContinue
    } catch {}
}

# Wait briefly until all matched processes actually exit.
$deadline = [DateTime]::UtcNow.AddSeconds(5)
while ([DateTime]::UtcNow -lt $deadline) {
    $stillUp = $false
    foreach ($process in $targets) {
        if ($process -and (Get-Process -Id $process.ProcessId -ErrorAction SilentlyContinue)) {
            $stillUp = $true
            break
        }
    }
    if (-not $stillUp) { break }
    Start-Sleep -Milliseconds 100
}
if ($stillUp) { throw 'One or more WeChat bot processes did not stop.' }
