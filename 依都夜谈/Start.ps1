$ErrorActionPreference = 'Stop'
$root = $PSScriptRoot
$native = Join-Path $root 'agent-wechat'
$astrbot = Join-Path $root 'AstrBot'
$logs = Join-Path $root 'logs'
New-Item -ItemType Directory -Force -Path $logs | Out-Null

function Test-LocalPortListening([int]$Port) {
    $props = [System.Net.NetworkInformation.IPGlobalProperties]::GetIPGlobalProperties()
    foreach ($ep in $props.GetActiveTcpListeners()) {
        if ($ep.Port -eq $Port) { return $true }
    }
    return $false
}

$serverToml = Join-Path $native 'server.toml'

# Rotate stdout log if it exceeds 5 MB so logs stay fast and readable.
$stdoutLog = Join-Path $logs 'astrbot.stdout.log'
if ((Test-Path $stdoutLog) -and ((Get-Item $stdoutLog).Length -gt 5MB)) {
    $stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
    Move-Item -Force $stdoutLog (Join-Path $logs "astrbot.stdout-$stamp.log")
}

$nativeErr = Join-Path $native 'native.stderr.log'
if (-not (Test-LocalPortListening 6174)) {
    $wxExe = Join-Path $native 'wx-v2.7.1-win32-x64.exe'
    $wxProc = Start-Process -FilePath $wxExe `
        -ArgumentList @('serve', '--server-config', "`"$serverToml`"") `
        -WorkingDirectory $native `
        -WindowStyle Hidden `
        -RedirectStandardOutput (Join-Path $native 'native.stdout.log') `
        -RedirectStandardError $nativeErr `
        -PassThru
    $wxProc.Id | Set-Content -LiteralPath (Join-Path $native 'native.pid')

    # Wait briefly for 6174 to bind or fail fast if wx crashes on startup.
    $deadline = [DateTime]::UtcNow.AddSeconds(3)
    while ([DateTime]::UtcNow -lt $deadline) {
        if (Test-LocalPortListening 6174) { break }
        if ($wxProc.HasExited) {
            $errText = if (Test-Path $nativeErr) { ([string](Get-Content -LiteralPath $nativeErr -Raw -ErrorAction SilentlyContinue)).Trim() } else { '' }
            if (-not $errText) { $errText = "wx exited with code $($wxProc.ExitCode)" }
            [Console]::Error.WriteLine("WeChat bridge (6174) failed to start: $errText")
            exit 1
        }
        Start-Sleep -Milliseconds 50
    }
}

if (-not (Test-LocalPortListening 6186)) {
    $env:ASTRBOT_ROOT = $astrbot
    $env:PYTHONUTF8 = '1'
    $pyExe = Join-Path $astrbot '.venv\Scripts\python.exe'
    $astrProc = Start-Process -FilePath $pyExe `
        -ArgumentList @('-X', 'utf8', '-u', 'main.py', '--webui-dir', "`"$root\dashboard\dist`"") `
        -WorkingDirectory $astrbot `
        -WindowStyle Hidden `
        -RedirectStandardOutput $stdoutLog `
        -RedirectStandardError (Join-Path $logs 'astrbot.stderr.log') `
        -PassThru
    $astrProc.Id | Set-Content -LiteralPath (Join-Path $logs 'astrbot.pid')
}

Write-Host 'WeChat Bot dashboard: http://127.0.0.1:6186'
