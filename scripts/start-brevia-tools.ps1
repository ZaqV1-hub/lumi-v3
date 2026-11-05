param([string]$PythonPath = 'python')
$ErrorActionPreference = 'Stop'
$lumiRoot = Split-Path -Parent $PSScriptRoot
$lumiData = Join-Path $env:LOCALAPPDATA 'Lumi'
if (-not (Test-Path -LiteralPath (Join-Path $lumiData 'brevia-tools.env'))) { throw 'Provisione primeiro as permissões com python -m app.business_setup.' }
if (-not (Get-NetTCPConnection -State Listen -LocalPort 8005 -ErrorAction SilentlyContinue)) {
    Start-Process -FilePath $PythonPath -ArgumentList '-m','uvicorn','services.brevia.api:app','--host','127.0.0.1','--port','8005','--no-access-log' -WorkingDirectory $lumiRoot -WindowStyle Hidden -RedirectStandardOutput (Join-Path $lumiData 'brevia-tools.log') -RedirectStandardError (Join-Path $lumiData 'brevia-tools-error.log')
}
Write-Output 'Ferramenta de gestão disponível em localhost:8005.'
