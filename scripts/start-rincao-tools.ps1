param([string]$PythonPath = "python")
$ErrorActionPreference = "Stop"
$lumiRoot = Split-Path -Parent $PSScriptRoot
$lumiData = Join-Path $env:LOCALAPPDATA 'Lumi'
$config = @{}
foreach ($line in Get-Content -LiteralPath (Join-Path $lumiData 'rincao-tools.env')) {
    if ($line -match '^(RINCAO_SSH_HOST|RINCAO_SSH_KEY_PATH)=(.*)$') { $config[$Matches[1]] = $Matches[2] }
}
if (-not (Get-NetTCPConnection -State Listen -LocalPort 15432 -ErrorAction SilentlyContinue)) {
    $ssh = (Get-Command ssh).Source
    $sshTarget = $config['RINCAO_SSH_HOST']
    $sshKey = $config['RINCAO_SSH_KEY_PATH']
    if (-not $sshTarget -or -not $sshKey) { throw 'Configure o host SSH e o caminho da chave no arquivo privado.' }
    Start-Process -FilePath $ssh -ArgumentList '-N','-L','127.0.0.1:15432:127.0.0.1:5432','-i',"`"$sshKey`"",'-o','IdentitiesOnly=yes','-o','BatchMode=yes','-o','StrictHostKeyChecking=yes','-o','ExitOnForwardFailure=yes','-o','ServerAliveInterval=30',$sshTarget -WindowStyle Hidden -RedirectStandardError (Join-Path $lumiData 'site-db-tunnel-error.log')
    for ($attempt = 0; $attempt -lt 20; $attempt++) {
        if (Get-NetTCPConnection -State Listen -LocalPort 15432 -ErrorAction SilentlyContinue) { break }
        Start-Sleep -Milliseconds 250
    }
    if (-not (Get-NetTCPConnection -State Listen -LocalPort 15432 -ErrorAction SilentlyContinue)) { throw 'O túnel SSH não iniciou. Confira o log local.' }
}
if (-not (Get-NetTCPConnection -State Listen -LocalPort 8003 -ErrorAction SilentlyContinue)) {
    Start-Process -FilePath $PythonPath -ArgumentList '-m','uvicorn','services.rincao.api:app','--host','127.0.0.1','--port','8003','--no-access-log' -WorkingDirectory $lumiRoot -WindowStyle Hidden -RedirectStandardOutput (Join-Path $lumiData 'rincao-tools.log') -RedirectStandardError (Join-Path $lumiData 'rincao-tools-error.log')
}
Write-Output 'Túnel e serviço de consultas iniciados ou já ativos. Logs ficam na pasta local da Lumi.'
