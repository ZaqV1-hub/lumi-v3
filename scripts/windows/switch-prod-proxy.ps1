param([switch]$Restore)
$ErrorActionPreference = 'Stop'
Import-Module WebAdministration
$site = 'LumiApi-PROD'
$config = 'C:\Sites\AzureIIS\RincaoProd\lumi-api\web.config'
$backup = 'C:\LumiV3-PROD\backups\web.config.before-v3'
$state = 'C:\LumiV3-PROD\backups\proxy-state.json'
$filter = 'system.webServer/rewrite/allowedServerVariables'
[xml]$document = Get-Content $config
$rule = $document.configuration.'system.webServer'.rewrite.rules.rule | Where-Object { $_.name -eq 'LumiReverseProxy' }
if ($Restore) {
    if (!(Test-Path $backup) -or !(Test-Path $state)) { throw 'Backup do proxy ausente' }
    if ($rule.action.url -ne 'http://127.0.0.1:8014/{R:1}') { throw 'Proxy atual divergente; revisar antes de restaurar' }
    $saved = Get-Content $state -Raw | ConvertFrom-Json
    if (!$saved.appliedSha256 -or (Get-FileHash $config -Algorithm SHA256).Hash -ne $saved.appliedSha256) { throw 'Configuracao mudou depois da publicacao; revisar antes de restaurar' }
    Copy-Item $backup $config -Force
    if ($saved.addedHeader) {
        Remove-WebConfigurationProperty -PSPath 'MACHINE/WEBROOT/APPHOST' -Location $site -Filter $filter -Name '.' -AtElement @{name='HTTP_X_FORWARDED_PROTO'}
    }
    Write-Output 'Proxy PROD anterior restaurado; bancos e servicos preservados.'
    return
}
if ($rule.action.url -ne 'http://127.0.0.1:4321/{R:1}') { throw 'Proxy anterior divergente; revisar antes de publicar' }
if ($rule.serverVariables) { throw 'Regra ja configura headers; revisar antes de publicar' }
if (Test-Path $backup) { throw 'Backup ja existe; nao sobrescrever' }
if ((Get-Service lumi-v3-prod).Status -ne 'Running') { throw 'Servico V3 nao esta executando' }
if ((Invoke-WebRequest http://127.0.0.1:8014/admin -UseBasicParsing).StatusCode -ne 200) { throw 'V3 indisponivel' }
Copy-Item $config $backup
$existing = @(Get-WebConfiguration -PSPath 'MACHINE/WEBROOT/APPHOST' -Location $site -Filter "$filter/add" | Where-Object { $_.name -eq 'HTTP_X_FORWARDED_PROTO' })
$added = $existing.Count -eq 0
@{addedHeader=$added;previousSha256=(Get-FileHash $backup -Algorithm SHA256).Hash} | ConvertTo-Json | Set-Content $state
try {
    if ($added) {
        Add-WebConfigurationProperty -PSPath 'MACHINE/WEBROOT/APPHOST' -Location $site -Filter $filter -Name '.' -Value @{name='HTTP_X_FORWARDED_PROTO'}
    }
    # Preserva contratos e callback Meta globais anteriores, alem do support-edge.
    $legacy = $document.CreateElement('rule')
    $legacy.SetAttribute('name','LegacyApiPreserved'); $legacy.SetAttribute('stopProcessing','true')
    $legacy.InnerXml = '<match url="^(v1/.*|webhook(/.*)?|health(/.*)?)$" /><action type="Rewrite" url="http://127.0.0.1:4321/{R:0}" logRewrittenUrl="false" />'
    [void]$rule.ParentNode.InsertBefore($legacy,$rule)
    $redirect = $document.CreateElement('rule')
    $redirect.SetAttribute('name','LumiV3Https'); $redirect.SetAttribute('stopProcessing','true')
    $redirect.InnerXml = '<match url="(.*)" /><conditions><add input="{HTTPS}" pattern="^off$" /></conditions><action type="Redirect" url="https://api.lumi.brevia.company/{R:1}" redirectType="Found" />'
    [void]$rule.ParentNode.InsertBefore($redirect,$rule)
    $webhook = $document.CreateElement('rule')
    $webhook.SetAttribute('name','LumiV3Channels'); $webhook.SetAttribute('stopProcessing','true')
    $webhook.InnerXml = '<match url="^(webhooks/(whatsapp|instagram)|channels/instagram/media/[^/]+)$" /><action type="Rewrite" url="http://127.0.0.1:8015/{R:0}" logRewrittenUrl="false" />'
    [void]$rule.ParentNode.InsertBefore($webhook,$rule)
    $variables = $document.CreateElement('serverVariables')
    $variables.InnerXml = '<set name="HTTP_X_FORWARDED_PROTO" value="https" />'
    [void]$rule.InsertBefore($variables,$rule.action)
    $rule.action.SetAttribute('url','http://127.0.0.1:8014/{R:1}')
    $rule.action.SetAttribute('logRewrittenUrl','false')
    $document.Save($config)
    @{addedHeader=$added;previousSha256=(Get-FileHash $backup -Algorithm SHA256).Hash;appliedSha256=(Get-FileHash $config -Algorithm SHA256).Hash} | ConvertTo-Json | Set-Content $state
    Write-Output 'Proxy PROD encaminha V3; /v1 e /webhook legados preservados.'
} catch {
    Copy-Item $backup $config -Force
    if ($added) {
        Remove-WebConfigurationProperty -PSPath 'MACHINE/WEBROOT/APPHOST' -Location $site -Filter $filter -Name '.' -AtElement @{name='HTTP_X_FORWARDED_PROTO'} -ErrorAction SilentlyContinue
    }
    throw
}
