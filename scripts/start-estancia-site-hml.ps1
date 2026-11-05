$ErrorActionPreference = 'Stop'
$lumiData = Join-Path $env:LOCALAPPDATA 'Lumi'
$lumiHml = Join-Path $lumiData 'estancia-site-hml'
if (-not (Test-Path -LiteralPath (Join-Path $lumiHml '.env.local'))) { throw 'Prepare a cópia isolada do site antes.' }
if (-not (Test-Path -LiteralPath (Join-Path $lumiHml '.next\BUILD_ID'))) { throw 'Compile primeiro a cópia de homologação do site.' }
if (-not (Get-NetTCPConnection -State Listen -LocalPort 15432 -ErrorAction SilentlyContinue)) { throw 'Inicie o túnel SSH verificado para o banco.' }
if (-not (Get-NetTCPConnection -State Listen -LocalPort 3002 -ErrorAction SilentlyContinue)) {
    $lumiNode = (Get-Command node).Source
    Start-Process -FilePath $lumiNode -ArgumentList (Join-Path $lumiHml 'node_modules\next\dist\bin\next'),'start','--hostname','127.0.0.1','--port','3002' -WorkingDirectory $lumiHml -WindowStyle Hidden -RedirectStandardOutput (Join-Path $lumiData 'estancia-site-hml.log') -RedirectStandardError (Join-Path $lumiData 'estancia-site-hml-error.log')
}
Write-Output 'Site de homologação da Estância disponível em http://127.0.0.1:3002.'
