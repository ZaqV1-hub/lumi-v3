param([string]$PythonPath = 'python', [switch]$PublicTunnel)
$ErrorActionPreference = 'Stop'
$lumiRoot = Split-Path -Parent $PSScriptRoot
$lumiData = Join-Path $env:LOCALAPPDATA 'Lumi'
New-Item -ItemType Directory -Path $lumiData -Force | Out-Null
$env:LUMI_DATA_DIR = $lumiData
$env:LUMI_TOOLS_ENV = Join-Path $lumiData 'tools.env'
if (-not $env:LUMI_PROVIDER) { $env:LUMI_PROVIDER = 'codex' }
if (-not $env:LUMI_CODEX_MODEL) { $env:LUMI_CODEX_MODEL = 'gpt-6.1-terra' }
$channelListener = Get-NetTCPConnection -State Listen -LocalPort 8002 -ErrorAction SilentlyContinue
if ($channelListener) {
    $channelProcess = Get-CimInstance Win32_Process -Filter "ProcessId = $($channelListener[0].OwningProcess)"
    if ($channelProcess.CommandLine -notlike '*uvicorn app.whatsapp.webhook:app*') {
        throw 'A porta 8002 está ocupada por outro serviço; nenhum processo foi alterado.'
    }
} else {
    Start-Process -FilePath $PythonPath -ArgumentList '-m','uvicorn','app.whatsapp.webhook:app','--host','127.0.0.1','--port','8002','--no-access-log' -WorkingDirectory $lumiRoot -WindowStyle Hidden -RedirectStandardOutput (Join-Path $lumiData 'channels.log') -RedirectStandardError (Join-Path $lumiData 'channels-error.log')
}
if ($PublicTunnel) {
    $channelTunnel = Join-Path $lumiData 'bin\cloudflared.exe'
    if (-not (Test-Path -LiteralPath $channelTunnel)) { $channelTunnel = Join-Path $env:TEMP 'lumi-cloudflared.exe' }
    if (-not (Test-Path -LiteralPath $channelTunnel)) { throw 'Instale o cloudflared da Cloudflare antes de abrir o túnel.' }
    if (Get-NetTCPConnection -State Listen -LocalPort 20241 -ErrorAction SilentlyContinue) {
        throw 'Já existe um serviço na porta de métricas do túnel (20241). Confira o túnel existente antes de abrir outro.'
    }
    Start-Process -FilePath $channelTunnel -ArgumentList 'tunnel','--url','http://127.0.0.1:8002','--metrics','127.0.0.1:20241' -WindowStyle Hidden -RedirectStandardOutput (Join-Path $lumiData 'channels-tunnel.log') -RedirectStandardError (Join-Path $lumiData 'channels-tunnel-error.log')
    Write-Output 'Túnel solicitado somente para o receptor da porta 8002. Confira a URL HTTPS e atualize a Meta; o admin continua privado.'
} else {
    Write-Output 'Receptor local solicitado na porta 8002. Não foi aberto túnel público.'
}
