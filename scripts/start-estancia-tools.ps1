param([string]$PythonPath = 'python')
$ErrorActionPreference = 'Stop'
$lumiRoot = Split-Path -Parent $PSScriptRoot
$lumiData = Join-Path $env:LOCALAPPDATA 'Lumi'
if (-not (Test-Path -LiteralPath (Join-Path $lumiData 'estancia-tools.env'))) { throw 'Configure a integração privada da Estância primeiro.' }
if (-not (Get-NetTCPConnection -State Listen -LocalPort 15432 -ErrorAction SilentlyContinue)) { throw 'Inicie o túnel SSH verificado para o banco antes.' }
if (-not (Get-NetTCPConnection -State Listen -LocalPort 8006 -ErrorAction SilentlyContinue)) {
    Start-Process -FilePath $PythonPath -ArgumentList '-m','uvicorn','services.estancia.api:app','--host','127.0.0.1','--port','8006','--no-access-log' -WorkingDirectory $lumiRoot -WindowStyle Hidden -RedirectStandardOutput (Join-Path $lumiData 'estancia-tools.log') -RedirectStandardError (Join-Path $lumiData 'estancia-tools-error.log')
}
Write-Output 'Integração de consulta da Estância iniciada em localhost:8006.'
