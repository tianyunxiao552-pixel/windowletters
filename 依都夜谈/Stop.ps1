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

foreach ($process in (@($astrbot) + @($bridge))) {
    if (-not $process) { continue }
    try {
        $terminated = Stop-Process -Id $process.ProcessId -PassThru -ErrorAction Stop
        $terminated | Wait-Process -Timeout 5 -ErrorAction Stop
    } catch {
        if (Get-Process -Id $process.ProcessId -ErrorAction SilentlyContinue) { throw }
    }
}
