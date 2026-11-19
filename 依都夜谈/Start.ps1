$ErrorActionPreference = 'Stop'
$root = $PSScriptRoot
$native = Join-Path $root 'agent-wechat'
$astrbot = Join-Path $root 'AstrBot'
$logs = Join-Path $root 'logs'
New-Item -ItemType Directory -Force -Path $logs | Out-Null

# Rotate stdout log if it exceeds 5 MB so logs stay fast and readable.
$stdoutLog = Join-Path $logs 'astrbot.stdout.log'
if ((Test-Path $stdoutLog) -and ((Get-Item $stdoutLog).Length -gt 5MB)) {
    $stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
    Move-Item -Force $stdoutLog (Join-Path $logs "astrbot.stdout-$stamp.log")
}

if (-not (Get-NetTCPConnection -LocalPort 6174 -State Listen -ErrorAction SilentlyContinue)) {
    $process = Start-Process -FilePath (Join-Path $native 'wx-v2.7.1-win32-x64.exe') -ArgumentList @('serve','--server-config',"`"$native\server.toml`"") -WorkingDirectory $native -WindowStyle Hidden -RedirectStandardOutput (Join-Path $native 'native.stdout.log') -RedirectStandardError (Join-Path $native 'native.stderr.log') -PassThru
    $process.Id | Set-Content -LiteralPath (Join-Path $native 'native.pid')
}

if (-not (Get-NetTCPConnection -LocalPort 6186 -State Listen -ErrorAction SilentlyContinue)) {
    $env:ASTRBOT_ROOT = $astrbot
    $env:PYTHONUTF8 = '1'
    $process = Start-Process -FilePath (Join-Path $astrbot '.venv\Scripts\python.exe') -ArgumentList @('-X','utf8','-u','main.py','--webui-dir',"`"$root\dashboard\dist`"") -WorkingDirectory $astrbot -WindowStyle Hidden -RedirectStandardOutput $stdoutLog -RedirectStandardError (Join-Path $logs 'astrbot.stderr.log') -PassThru
    $process.Id | Set-Content -LiteralPath (Join-Path $logs 'astrbot.pid')
}
Write-Host 'WeChat Bot dashboard: http://127.0.0.1:6186'
