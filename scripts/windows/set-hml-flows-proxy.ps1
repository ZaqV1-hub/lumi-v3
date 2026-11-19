param([switch]$Disable)
$ErrorActionPreference = 'Stop'
$config = 'C:\Sites\AzureIIS\RincaoDeploy\lumi-api\web.config'
$folder = 'C:\LumiV3-HML\backups'
[xml]$document = Get-Content -LiteralPath $config
$rules = $document.configuration.'system.webServer'.rewrite.rules
$name = 'LumiV3WhatsAppFlows'
$existing = @($rules.rule | Where-Object { $_.name -eq $name })
if ($existing.Count -gt 1) { throw 'Regra duplicada; revisar configuracao.' }
if ($existing.Count -and ($existing[0].action.url -ne 'http://127.0.0.1:8013/{R:0}' -or $existing[0].match.url -ne '^webhooks/whatsapp/flows/[0-9]+$')) {
    throw 'Regra existente divergente; preservar e revisar.'
}
if ($Disable -and !$existing.Count) { return }
if (!$Disable -and $existing.Count) { return }
$anchor = @($rules.rule | Where-Object { $_.name -eq 'LumiReverseProxy' })
if ($anchor.Count -ne 1 -or $anchor[0].action.url -ne 'http://127.0.0.1:8012/{R:1}') {
    throw 'Destino HML divergente; nenhuma alteracao aplicada.'
}
$stamp = [DateTime]::UtcNow.ToString('yyyyMMddTHHmmssfffffffZ')
Copy-Item -LiteralPath $config -Destination (Join-Path $folder ('web.config.before-flows-' + $stamp))
if ($Disable) {
    [void]$rules.RemoveChild($existing[0])
} else {
    $rule = $document.CreateElement('rule')
    $rule.SetAttribute('name', $name)
    $rule.SetAttribute('stopProcessing', 'true')
    $rule.InnerXml = '<match url="^webhooks/whatsapp/flows/[0-9]+$" /><action type="Rewrite" url="http://127.0.0.1:8013/{R:0}" logRewrittenUrl="false" />'
    [void]$rules.InsertBefore($rule, $anchor[0])
}
$document.Save($config)
Write-Output 'Rota publica de Flows HML atualizada; demais regras preservadas.'
