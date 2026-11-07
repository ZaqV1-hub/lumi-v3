param([string]$DeployScript = "$PSScriptRoot\..\..\scripts\windows\deploy-release.ps1")
$ErrorActionPreference = 'Stop'
# Serviços e banco são simulados; junctions e arquivos usam somente pasta temporária.
$source = Get-Content -Raw -LiteralPath $DeployScript
$pythonPath = (Get-Command python.exe).Source
$base = Join-Path ([IO.Path]::GetTempPath()) ("lumi-deploy-test-" + [guid]::NewGuid().ToString('N'))
$commit = 'a' * 40
$id = 'gha-' + $commit.Substring(0,12) + '-1-1'
$global:lumiDeployTestStates = @{}
$global:lumiDeployTestOperations = @()

function Get-Service([string]$Name) {
  if ($Name -notin @('lumi-v3-hml','lumi-v3-hml-webhook')) { throw 'Tentativa de tocar outro servico' }
  $result = [pscustomobject]@{ Status=$global:lumiDeployTestStates[$Name] }
  $result | Add-Member ScriptMethod WaitForStatus {
    param($Expected,$Timeout)
    if ($this.Status -ne $Expected) { throw 'Estado inesperado no teste' }
  }
  return $result
}
function Stop-Service([string]$Name) {
  Get-Service $Name | Out-Null
  $global:lumiDeployTestStates[$Name] = 'Stopped'
  $global:lumiDeployTestOperations += "stop:$Name"
}
function Start-Service([string]$Name) {
  Get-Service $Name | Out-Null
  $global:lumiDeployTestStates[$Name] = 'Running'
  $global:lumiDeployTestOperations += "start:$Name"
}

try {
  foreach ($scenario in @('success','prepare','backup','health')) {
    $testRoot = Join-Path $base $scenario
    foreach ($folder in @('releases\previous','staging','backups','private','data\Lumi','service')) {
      New-Item -ItemType Directory -Path (Join-Path $testRoot $folder) -Force | Out-Null
    }
    New-Item -ItemType Junction -Path "$testRoot\current" -Target "$testRoot\releases\previous" | Out-Null
    Set-Content "$testRoot\private\hml.env" 'TEST_ONLY=preserve'
    Set-Content "$testRoot\data\Lumi\whatsapp.env" 'TEST_ONLY=preserve'
    Set-Content "$testRoot\service\test.xml" '<test>preserve</test>'
    $env:LUMI_DEPLOY_TEST_ROOT = $testRoot
    $env:LUMI_DEPLOY_TEST_FAILURE = $scenario
    @'
import os,sys
from pathlib import Path
root=Path(os.environ['LUMI_DEPLOY_TEST_ROOT'])
failure=os.environ['LUMI_DEPLOY_TEST_FAILURE']
operation=sys.argv[1]
if operation==failure and (operation!='health' or (root/'current').resolve().name!='previous'):
    sys.exit(7)
if operation=='prepare':
    release_id=sys.argv[sys.argv.index('--release-id')+1]
    (root/'releases'/release_id).mkdir()
if operation=='backup':
    (root/'backups'/'fixture.dump').write_text('fixture')
'@ | Set-Content -Encoding UTF8 "$testRoot\staging\$id.py"
    $copy = $source.Replace('$root = "C:\LumiV3-$Environment"', ('$root = ''' + $testRoot + ''''))
    $copy = $copy.Replace('$python = "$root\venv\Scripts\python.exe"', ('$python = ''' + $pythonPath + ''''))
    if ($copy -eq $source -or $copy.Contains('$root = "C:\LumiV3-$Environment"')) { throw 'Isolamento do teste falhou' }
    $copy | Set-Content -Encoding UTF8 "$testRoot\staging\deploy.ps1"
    $global:lumiDeployTestStates = @{'lumi-v3-hml'='Running';'lumi-v3-hml-webhook'='Running'}
    $global:lumiDeployTestOperations = @()
    $failed = $false
    try {
      & "$testRoot\staging\deploy.ps1" -Environment HML -ReleaseId $id -Commit $commit -ArchiveHash ('b' * 64)
    } catch { $failed = $true; Write-Output "Observed fixture failure: $($_.Exception.Message)" }
    if ($failed -ne ($scenario -ne 'success')) { throw "Resultado inesperado: $scenario" }
    $expected = if ($scenario -eq 'success') { "$testRoot\releases\$id" } else { "$testRoot\releases\previous" }
    if (([string]@((Get-Item "$testRoot\current").Target)[0]) -ne $expected) { throw "Junction incorreta: $scenario" }
    if ($global:lumiDeployTestStates.Values -contains 'Stopped') { throw "Servico ficou parado: $scenario" }
    if ($scenario -eq 'prepare' -and $global:lumiDeployTestOperations.Count -ne 0) { throw 'Falha de validacao interrompeu servicos' }
    if ((Get-Content "$testRoot\private\hml.env") -ne 'TEST_ONLY=preserve') { throw 'Arquivo privado alterado' }
    if ((Test-Path "$testRoot\deployment-state.json") -ne ($scenario -eq 'success')) { throw 'Registro de deploy incorreto' }
    Write-Output "PASS: $scenario"
  }
} finally {
  Remove-Variable lumiDeployTestStates,lumiDeployTestOperations -Scope Global -ErrorAction SilentlyContinue
  Remove-Item Env:LUMI_DEPLOY_TEST_ROOT,Env:LUMI_DEPLOY_TEST_FAILURE -ErrorAction SilentlyContinue
  foreach ($scenario in @('success','prepare','backup','health')) {
    $junction = Join-Path $base "$scenario\current"
    if (Test-Path $junction) { & cmd.exe /d /c "rmdir `"$junction`"" }
  }
  if (Test-Path $base) { Remove-Item -LiteralPath $base -Recurse -Force }
}
