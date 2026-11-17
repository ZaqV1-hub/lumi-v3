param(
  [Parameter(Mandatory=$true)][ValidateSet('HML','PROD')][string]$Environment,
  [Parameter(Mandatory=$true)][ValidatePattern('^gha-[0-9a-f]{12}-\d+-\d+$')][string]$ReleaseId,
  [Parameter(Mandatory=$true)][ValidatePattern('^[0-9a-f]{40}$')][string]$Commit,
  [Parameter(Mandatory=$true)][ValidatePattern('^[0-9a-f]{64}$')][string]$ArchiveHash
)
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
$root = "C:\LumiV3-$Environment"
$lower = $Environment.ToLowerInvariant()
$branch = if ($Environment -eq 'HML') { 'develop' } else { 'main' }
$service = "lumi-v3-$lower"
$python = "$root\venv\Scripts\python.exe"
$helper = "$root\staging\$ReleaseId.py"
$release = "$root\releases\$ReleaseId"
$current = "$root\current"
$old = $null
$stopping = $false
$lock = $null

function Invoke-Helper([string[]]$Arguments) {
  & $python $helper @Arguments
  if ($LASTEXITCODE -ne 0) { throw "Etapa $($Arguments[0]) falhou" }
}

function Get-PrivateHashes {
  # Somente hashes internos: nunca copiar nem sobrescrever configuração privada.
  $files = @()
  foreach ($folder in @("$root\private", "$root\data\Lumi", "$root\service")) {
    $files += Get-ChildItem -LiteralPath $folder -File | Where-Object {
      $_.Extension -in @('.env','.xml')
    }
  }
  return (($files | Sort-Object FullName | ForEach-Object {
    "$($_.FullName):$((Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash)"
  }) -join "`n")
}

function Stop-Lumi([string]$Name) {
  Stop-Service -Name $Name
  (Get-Service -Name $Name).WaitForStatus('Stopped', [TimeSpan]::FromSeconds(170))
}

function Start-Lumi([string]$Name) {
  Start-Service -Name $Name
  (Get-Service -Name $Name).WaitForStatus('Running', [TimeSpan]::FromSeconds(45))
}

function Remove-Current {
  $item = Get-Item -LiteralPath $current -ErrorAction SilentlyContinue
  if ($item) {
    if ($item.LinkType -ne 'Junction') { throw 'current deixou de ser junction' }
    & cmd.exe /d /c "rmdir `"$current`""
    if ($LASTEXITCODE -ne 0) { throw 'Falha ao remover junction' }
  }
}

try {
  # Exclui deploys concorrentes mesmo fora do Actions; não cria outro serviço/runner.
  $lock = [System.IO.File]::Open("$root\deploy.lock", 'OpenOrCreate', 'ReadWrite', 'None')
  $item = Get-Item -LiteralPath $current
  if ($item.LinkType -ne 'Junction') { throw 'current precisa ser junction' }
  $old = [string]@($item.Target)[0]
  if (-not $old.StartsWith("$root\releases\", [StringComparison]::OrdinalIgnoreCase)) {
    throw 'Release atual fora do ambiente'
  }
  foreach ($name in @($service,"$service-webhook")) {
    if ((Get-Service -Name $name).Status -ne 'Running') { throw 'Servicos precisam estar saudaveis antes do deploy' }
  }
  $privateBefore = Get-PrivateHashes
  Invoke-Helper -Arguments @('prepare','--environment',$Environment,'--archive',"$root\staging\$ReleaseId.zip",
    '--sha256',$ArchiveHash,'--commit',$Commit,'--branch',$branch,'--release-id',$ReleaseId)
  Invoke-Helper -Arguments @('health','--environment',$Environment)
  # Todas as validações de artefato/dependências acontecem antes da interrupção.
  $stopping = $true
  Stop-Lumi "$service-webhook"
  Stop-Lumi $service
  Invoke-Helper -Arguments @('backup','--environment',$Environment,'--release-id',$ReleaseId)
  Invoke-Helper -Arguments @('migrate-whatsapp-follow-up','--environment',$Environment,'--release-id',$ReleaseId)
  Remove-Current
  New-Item -ItemType Junction -Path $current -Target $release | Out-Null
  Start-Lumi $service
  Start-Lumi "$service-webhook"
  Invoke-Helper -Arguments @('health','--environment',$Environment)
  if ((Get-PrivateHashes) -cne $privateBefore) { throw 'Configuracao privada ou de servico mudou durante o deploy' }
  foreach ($name in @($service,"$service-webhook")) {
    if ((Get-Service -Name $name).Status -ne 'Running') { throw 'Servico deixou de executar' }
  }
  @{
    environment=$Environment; branch=$branch; commit=$Commit; release=$ReleaseId;
    previous=$old; archive_sha256=$ArchiveHash; deployed_at=[DateTime]::UtcNow.ToString('o')
  } | ConvertTo-Json | Set-Content -Encoding UTF8 "$root\deployment-state.json"
  Write-Output "Deploy confirmado: $Environment $Commit $ReleaseId"
} catch {
  $reason = $_.Exception.Message
  if ($stopping -and $old) {
    try {
      foreach ($name in @("$service-webhook",$service)) {
        if ((Get-Service -Name $name).Status -ne 'Stopped') { Stop-Lumi $name }
      }
      $item = Get-Item -LiteralPath $current -ErrorAction SilentlyContinue
      if ($item -and ([string]@($item.Target)[0]) -notin @($old,$release)) {
        throw 'Junction alterada por outra operacao; retorno automatico recusado'
      }
      Remove-Current
      New-Item -ItemType Junction -Path $current -Target $old | Out-Null
      Start-Lumi $service
      Start-Lumi "$service-webhook"
      Invoke-Helper -Arguments @('health','--environment',$Environment)
      Write-Output 'Release anterior restaurada; banco e credenciais preservados.'
    } catch {
      throw "Deploy falhou e exige verificacao operacional do ambiente $Environment. Nenhum banco foi restaurado."
    }
  }
  throw "Deploy nao concluido: $reason"
} finally {
  if ($lock) { $lock.Dispose() }
}
