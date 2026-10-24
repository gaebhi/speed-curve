param([switch]$NoBrowser)
$ErrorActionPreference = 'Stop'
$appRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$bundledPython = Join-Path $env:USERPROFILE '.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
$pythonPath = if (Test-Path -LiteralPath $bundledPython) { $bundledPython } else { (Get-Command python -ErrorAction Stop).Source }
if (-not (Get-Command ffmpeg -ErrorAction SilentlyContinue) -or -not (Get-Command ffprobe -ErrorAction SilentlyContinue)) {
    throw 'FFmpeg/ffprobe를 찾을 수 없습니다. FFmpeg를 설치하고 다시 실행해 주세요.'
}
$selectedPort = $null
foreach ($candidatePort in 8765..8775) {
    try {
        $health = Invoke-RestMethod -Uri "http://127.0.0.1:$candidatePort/api/health" -TimeoutSec 1
        if ($health.app -eq 'speed-curve') { $selectedPort = $candidatePort; break }
    } catch { }
    $listener = [System.Net.Sockets.TcpListener]::new([System.Net.IPAddress]::Loopback, $candidatePort)
    try { $listener.Start(); $listener.Stop(); $selectedPort = $candidatePort; break } catch { $listener.Stop() }
}
if (-not $selectedPort) { throw '8765~8775 포트를 사용할 수 없습니다.' }
$url = "http://127.0.0.1:$selectedPort"
$running = $false
try { $running = (Invoke-RestMethod -Uri "$url/api/health" -TimeoutSec 1).app -eq 'speed-curve' } catch { }
if (-not $running) {
    $serverPath = Join-Path $appRoot 'server.py'
    $quotedServerPath = '"' + $serverPath + '"'
    $serverArguments = @($quotedServerPath, '--port', [string]$selectedPort)
    $null = Start-Process -FilePath $pythonPath -ArgumentList $serverArguments -WorkingDirectory $appRoot -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $appRoot 'server-output.log') -RedirectStandardError (Join-Path $appRoot 'server-error.log')
    for ($attempt = 0; $attempt -lt 50; $attempt++) {
        Start-Sleep -Milliseconds 150
        try { if ((Invoke-RestMethod -Uri "$url/api/health" -TimeoutSec 1).app -eq 'speed-curve') { $running = $true; break } } catch { }
    }
    if (-not $running) { throw '도구를 시작하지 못했습니다. server-error.log를 확인해 주세요.' }
}
if (-not $NoBrowser) { Start-Process $url }
