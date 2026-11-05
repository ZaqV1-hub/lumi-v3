param([string]$PythonPath = 'python')
$ErrorActionPreference = 'Stop'
$lumiRoot = Split-Path -Parent $PSScriptRoot
$lumiData = Join-Path $env:LOCALAPPDATA 'Lumi'
if (-not (Test-Path -LiteralPath (Join-Path $lumiData 'web-tools.env'))) { throw 'Configure o arquivo privado web-tools.env antes de iniciar.' }
if (-not (Get-NetTCPConnection -State Listen -LocalPort 8004 -ErrorAction SilentlyContinue)) {
    Start-Process -FilePath $PythonPath -ArgumentList '-m','uvicorn','services.web_tools.api:app','--host','127.0.0.1','--port','8004','--no-access-log' -WorkingDirectory $lumiRoot -WindowStyle Hidden -RedirectStandardOutput (Join-Path $lumiData 'web-tools.log') -RedirectStandardError (Join-Path $lumiData 'web-tools-error.log')
}
Write-Output 'Serviço de pesquisa iniciado ou já ativo em localhost:8004.'
