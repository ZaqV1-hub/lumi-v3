# WhatsApp Calling: contrato direto e operação

Pesquisa conferida em 10/11/2026, sem chamadas, mensagens ou alterações na Meta. Este documento fundamenta as fixtures e a integração; não declara áudio validado nem canal habilitado. O escopo e os critérios do piloto permanecem no [spec](superpowers/specs/2026-11-10-whatsapp-calling-design.md) e no [plano](superpowers/plans/2026-11-10-whatsapp-calling.md).

## Fontes e versão

A versão de requisição do projeto é Graph `v23.0`. Os guias públicos de Calling são documentos vivos, sem seletor de versão; a referência de Settings consultada exibe `v23.0`. Não mudar a versão da assinatura de mensagens existente para acompanhar a versão HTTP por suposição: são configurações distintas.

As páginas da Meta retornaram 429 pelo leitor web, mas foram lidas diretamente no Chrome em aba de pesquisa. O original inglês de permissões também foi conferido. Context7 `/fbsamples/whatsapp-api-examples` não cobre Calling. Context7 `/facebook/openapi` cobre parte do contrato, mas seus resumos e o YAML têm divergências reais em relação aos guias atuais. Não usar o resumo gerado como schema.

Fontes primárias usadas:

- [C — chamadas iniciadas pela empresa](https://developers.facebook.com/documentation/business-messaging/whatsapp/calling/business-initiated-calls/), atualização exibida: 02/11/2026.
- [P — permissões do usuário](https://developers.facebook.com/documentation/business-messaging/whatsapp/calling/user-call-permissions/), atualização exibida: 26/06/2026.
- [R — referência Calling](https://developers.facebook.com/documentation/business-messaging/whatsapp/calling/reference/), atualização exibida: 02/11/2026.
- [S — configurações Calling](https://developers.facebook.com/documentation/business-messaging/whatsapp/calling/call-settings/), atualização exibida: 06/07/2026.
- [S23 — Settings API v23.0](https://developers.facebook.com/documentation/business-messaging/whatsapp/reference/whatsapp-business-phone-number/settings-api).
- [I — integração e requisitos de mídia](https://developers.facebook.com/documentation/business-messaging/whatsapp/calling/integration-patterns/), atualização exibida: 02/11/2026.
- [O — visão geral e pré-requisitos](https://developers.facebook.com/documentation/business-messaging/whatsapp/calling/), atualização exibida: 26/06/2026.
- [W — receptor, assinatura e reentrega](https://developers.facebook.com/documentation/business-messaging/whatsapp/webhooks/create-webhook-endpoint/).
- [WO — campos e permissões de webhook](https://developers.facebook.com/documentation/business-messaging/whatsapp/webhooks/overview/).
- [OV — override de callback](https://developers.facebook.com/documentation/business-messaging/whatsapp/webhooks/override), atualização exibida: 28/09/2026.
- [AS — subscriptions do app](https://developers.facebook.com/docs/graph-api/webhooks/subscriptions-edge).
- [AS25 — referência genérica de subscriptions v25.0](https://developers.facebook.com/docs/graph-api/reference/v25.0/app/subscriptions), inclusive seções Creating e Updating; também conferida em v27.0.
- [Y23 — OpenAPI oficial fixado](https://github.com/meta/openapi/blob/e96a1c9dbf240c2937b6a95920685230458e346b/business-messaging-api_v23.0.yaml), commit de 11/08/2026; antigo `facebook/openapi` redireciona para `meta/openapi`.

## Requisições e correlação

Base `https://graph.facebook.com/v23.0`; `Authorization: Bearer` resolvido somente no servidor e `Content-Type: application/json`. Calling e mensagens exigem `whatsapp_business_messaging`; Settings exige `whatsapp_business_management`. O ID do caminho é o ID do número empresarial, não seu telefone. Fontes: O, S e Y23.

Iniciar: `POST /{PHONE_NUMBER_ID}/calls`. Exemplo sanitizado baseado em C, R e `CallRequestPayload` de Y23; `SDP_OFFER` é um marcador, não uma oferta utilizável:

```json
{
  "messaging_product": "whatsapp",
  "to": "15555550102",
  "action": "connect",
  "session": {"sdp_type": "offer", "sdp": "SDP_OFFER"},
  "biz_opaque_callback_data": "calling-operation-demo"
}
```

Sucesso HTTP 200, confirmado por C e `CallResponsePayload` de Y23:

```json
{"messaging_product":"whatsapp","calls":[{"id":"wacid.demo"}]}
```

Isso confirma a criação da tentativa, não atendimento ou mídia. O código `138006` significa falta de permissão para ligar. `biz_opaque_callback_data` aceita até 512 caracteres, é opaco para a Meta e pode chegar a qualquer app inscrito em `calls`. Usar identificador aleatório da operação, sem dados privados ou token de posse. C mostra o campo em connect, status e terminate; as tabelas garantem o eco em status/terminate. Persistir a operação antes do envio e correlacionar evento por canal + ID externo ou token opaco vinculado à operação. O token não é uma chave de idempotência Meta. Fontes: C e Y23.

Encerrar: `POST /{PHONE_NUMBER_ID}/calls`, fonte C/R/Y23:

```json
{"messaging_product":"whatsapp","call_id":"wacid.demo","action":"terminate"}
```

Sucesso `{"success":true}`; a referência também mostra `messaging_product` junto de `success`. Não exigir esse campo extra. É necessário encerrar por API mesmo após RTCP BYE; quando o cliente encerra, não é necessário reenviar terminate. A Meta emite webhook terminal. A documentação lista tentativa de encerrar chamada já terminada como erro possível: repetição não é documentada como sempre HTTP 200. Não converter qualquer erro de término em conclusão. Fonte C/R.

Rejeitar chamada recebida usa o mesmo endpoint com `{"messaging_product":"whatsapp","call_id":"wacid.demo","action":"reject"}`; sucesso com `success:true`, seguido por webhook terminal. Fonte R, seção Reject call. O exemplo antigo Y23 que rejeita apenas por `to` não deve orientar a implementação.

C/R atuais oferecem `recipient` para BSUID e `messaging_account_id` quando um token acessa mais de uma conta de mensagens no mesmo número. Não inventar telefone a partir de BSUID. No piloto com vínculo telefônico existente, usar o destino autorizado pelo servidor; eventos sem identidade que possa ser vinculada ficam sem efeito. A identificação da conta deve ser consistente em todas as ações da chamada se necessária. Isso não autoriza ampliar o escopo do piloto.

## Consentimento

Consulta: `GET /{PHONE_NUMBER_ID}/call_permissions?user_wa_id={WA_ID}`. P também documenta alternativa `recipient={BSUID}`. Exemplo sanitizado derivado da estrutura de P (limites e horários são fictícios):

```json
{
  "messaging_product":"whatsapp",
  "permission":{"status":"temporary","expiration_time":1794938400},
  "actions":[
    {"action_name":"start_call","can_perform_action":true,"limits":[{"time_period":"PT24H","max_allowed":100,"current_usage":0}]},
    {"action_name":"send_call_permission_request","can_perform_action":false}
  ]
}
```

P define `status` como `no_permission`, `temporary` ou `permanent`. Permanente omite expiração. Temporária exige prazo ainda válido. `actions[].can_perform_action` inclui as restrições atuais; permissão concedida sozinha não garante que uma chamada possa começar. `limit_expiration_time` só aparece quando pertinente ao limite. Falha, schema desconhecido, ação ausente ou prazo inválido não autorizam ligação por fallback.

O YAML Y23 enumera `granted/pending/denied/expired`, incompatível com P; a referência R omite permanente em uma tabela embora a página P o documente. Priorizar P atual para fixtures, registrar qualquer divergência encontrada na resposta real v23.0 e falhar de forma fechada. Não aceitar um valor desconhecido como autorização nem criar múltiplos formatos sem evidência. A tabela P chama o prazo de `expiration`, mas o JSON e Y23 usam `expiration_time`; esse é o nome usado nas fixtures.

Enviar solicitação: `POST /{PHONE_NUMBER_ID}/messages`, somente na janela de atendimento; P documenta corpo opcional, sem header/footer para a mensagem livre. Exemplo sanitizado de P:

```json
{
  "messaging_product":"whatsapp",
  "recipient_type":"individual",
  "to":"15555550102",
  "type":"interactive",
  "interactive":{
    "type":"call_permission_request",
    "action":{"name":"call_permission_request"},
    "body":{"text":"Podemos ligar para ajudar neste atendimento?"}
  }
}
```

Resposta, fonte P:

```json
{"messaging_product":"whatsapp","contacts":[{"input":"15555550102","wa_id":"15555550102"}],"messages":[{"id":"wamid.permission-demo"}]}
```

O recibo é de mensagem e não concede permissão. A resposta de consentimento referencia esse WAMID em `context.id`, quando existe. Não foi encontrada garantia específica de correlação opaca da solicitação de permissão após perda da resposta HTTP. Manter resultado incerto e consultar permissão atual, sem reenviar automaticamente. Não usar o correlation token de chamada como autorização de mensagem.

P informa permissão temporária de 168 horas a partir da aprovação; permanente até revogação. Não há webhook quando a temporária expira. Solicitações expiram sete dias após aceite/recusa, sete dias após entrega sem resposta, ou quando o cliente interage com uma solicitação subsequente. São conceitos diferentes: expiração da solicitação não revoga uma permissão permanente.

P informa um pedido por 24 horas e dois por sete dias, reiniciados após chamada conectada entre as partes; até 100 chamadas conectadas por par/número em 24 horas. Quatro chamadas consecutivas não atendidas podem revogar automaticamente a permissão. Há exemplos antigos na própria documentação com limites menores e texto inconsistente; decisões usam `can_perform_action`/limites retornados, não números copiados para liberar tentativas. Fora da janela, P exige template; templates não fazem parte deste MVP.

O modelo novo baseado em qualidade descrito em C cobre números elegíveis da Colômbia/México e pode devolver `permanent` sem aprovação explícita. Isso não modifica o requisito local de consentimento do piloto brasileiro.

## Webhooks para fixtures

Todos os IDs e telefones abaixo são fictícios. Os envelopes foram normalizados para JSON válido a partir de C/R/P/WO; os exemplos oficiais têm comentários, vírgulas finais e enumerações ilustrativas. Não copiar essas imperfeições para o parser. Campos extras e arrays com múltiplos itens devem ser tolerados; cada item continua sujeito a vínculo, assinatura e deduplicação.

Connect, fonte C (envelope e SDP answer):

```json
{
  "object":"whatsapp_business_account",
  "entry":[{"id":"waba-demo","changes":[{"field":"calls","value":{
    "messaging_product":"whatsapp",
    "metadata":{"phone_number_id":"phone-demo","display_phone_number":"15555550101"},
    "calls":[{"id":"wacid.demo","from":"15555550101","to":"15555550102","event":"connect","timestamp":"1794333600","direction":"BUSINESS_INITIATED","biz_opaque_callback_data":"calling-operation-demo","session":{"sdp_type":"answer","sdp":"SDP_ANSWER"}}]
  }}]}]
}
```

O `session.sdp` é texto SDP direto, não JSON serializado dentro de string. `connection.webrtc.sdp` aparece como legado em R; o novo cliente usa `session`. Receber answer permite negociar mídia e não prova que o usuário atendeu.

Status, fonte C/R:

```json
{
  "object":"whatsapp_business_account",
  "entry":[{"id":"waba-demo","changes":[{"field":"calls","value":{
    "messaging_product":"whatsapp",
    "metadata":{"phone_number_id":"phone-demo","display_phone_number":"15555550101"},
    "statuses":[{"id":"wacid.demo","type":"call","status":"RINGING","timestamp":"1794333601","recipient_id":"15555550102","biz_opaque_callback_data":"calling-operation-demo"}]
  }}]}]
}
```

Fixtures adicionais substituem `status` por `ACCEPTED` e `REJECTED`; esses são os três valores documentados. `ACCEPTED` é auditoria da aceitação e chega depois do estabelecimento; conectividade do navegador deve ser acompanhada separadamente. Rejeição também produz terminate. Não exigir `calls` em mudanças que trazem `statuses`.

Terminate, fonte C/R:

```json
{
  "object":"whatsapp_business_account",
  "entry":[{"id":"waba-demo","changes":[{"field":"calls","value":{
    "messaging_product":"whatsapp",
    "metadata":{"phone_number_id":"phone-demo","display_phone_number":"15555550101"},
    "calls":[{"id":"wacid.demo","from":"15555550101","to":"15555550102","event":"terminate","direction":"BUSINESS_INITIATED","timestamp":"1794333720","status":"COMPLETED","start_time":"1794333600","end_time":"1794333720","duration":120,"biz_opaque_callback_data":"calling-operation-demo"}]
  }}]}]
}
```

`status` é uma string `COMPLETED` ou `FAILED`, segundo a tabela; o exemplo que escreve `[FAILED | COMPLETED]` é notação de alternativas. Chamada não atendida pode ser `COMPLETED` sem `start_time/end_time/duration`. Em falha, `value.errors` pode conter `code`, `message`, `href`, `error_data.details`; não exigir erros para todo FAILED e não expor texto técnico na UI. O `timestamp` do evento é string Unix; duração é inteiro.

Permissão temporária aceita: fragmento de P inserido no envelope padrão de mensagens de WO. P omite `messages[].type` nos exemplos; não exigir esse campo para reconhecer `interactive.type`:

```json
{
  "object":"whatsapp_business_account",
  "entry":[{"id":"waba-demo","changes":[{"field":"messages","value":{
    "messaging_product":"whatsapp",
    "metadata":{"phone_number_id":"phone-demo","display_phone_number":"15555550101"},
    "messages":[{"from":"15555550102","id":"wamid.reply-demo","timestamp":"1794333600","context":{"from":"15555550102","id":"wamid.permission-demo"},"interactive":{"type":"call_permission_reply","call_permission_reply":{"response":"accept","is_permanent":false,"expiration_timestamp":"1794938400","response_source":"user_action"}}}]
  }}]}]
}
```

Variações documentadas em P para fixtures: aceite permanente usa `response=accept`, `is_permanent=true` e omite `expiration_timestamp`; concessão no perfil também omite `context`. Recusa usa `response=reject`, `response_source=user_action`, sem exigir `is_permanent`/expiração. Revogação automática usa `response=reject`, `response_source=automatic` e omite `context`. Callback automático usa aceite temporário, fonte `automatic` e `context.id` WACID. Uma rejeição manual posterior invalida permissão existente; não há enum externo `revoked` a exigir. O prazo do webhook é um timestamp absoluto em segundos, codificado como string, confirmado pelo original inglês de P.

Para chamadas entrantes, R documenta `direction=USER_INITIATED`, `event=connect` e `session.sdp_type=offer`. Tratar só em canal habilitado e rejeitar pelo `call_id` documentado, sem aceitar mídia, tomar conversa ou inserir mensagens internas na outbox.

## Assinatura, subscriptions e configurações

W define POST com `X-Hub-Signature-256: sha256=<hex>`, HMAC-SHA256 do corpo original usando app secret; comparar antes de interpretar/aplicar eventos. O desafio GET usa `hub.mode=subscribe`, `hub.verify_token` e devolve `hub.challenge` com HTTP 200 após validação. Token de verificação e app secret têm funções diferentes.

W/WO documentam lotes, duplicatas e reentregas por até sete dias. Não existe API para buscar histórico de webhooks. Processar todas as entradas/mudanças e deduplicar no banco; resposta 200 não pode esconder perda de persistência. Não copiar payloads completos para logs.

O exige app inscrito no campo `calls` e na WABA/conta de mensagens do número; `messages` continua necessário para consentimento e mensagens existentes. AS documenta `GET /{APP_ID}/subscriptions` com `data[].object/callback_url/active/fields[{name,version}]`; `POST` no mesmo caminho usa `object=whatsapp_business_account`, `callback_url`, `verify_token`, `fields` e token do app. Essa configuração tem alcance do app, não apenas do piloto. Reutilizar o callback atual e preservar todos os campos/versões existentes; qualquer atualização deve ser conferida por leitura posterior. Nenhum POST foi executado nesta pesquisa.

OV confirma que `calls`, `messages` e `account_settings_update` aceitam override. A precedência é callback do número, depois WABA, depois app. `GET /{PHONE_NUMBER_ID}?fields=webhook_configuration` retorna `phone_number`, `whatsapp_business_account` quando existente e `application`. O campo `calls` pode usar o override do número já existente, sem trocar o callback global. Webhooks de conta como `account_update` não aceitam esse override.

OV documenta `POST /{WABA_ID}/subscribed_apps` com `override_callback_uri`/`verify_token` para definir override. **POST sem corpo remove o override da WABA**; não usar como simples verificação/reinscrição. O override do número é `POST /{PHONE_NUMBER_ID}` com `webhook_configuration`, não Settings. Preservar ambos os níveis e outros apps/canais.

S/S23 confirmam `GET /{PHONE_NUMBER_ID}/settings` sem `fields` obrigatório; único query opcional documentado é `include_sip_credentials`, que não é necessário e não deve ser pedido neste piloto. `whatsapp_business_management` é necessário para ler Settings. Ter só escopo de mensagens não comprova acesso a configurações. Não deduzir causa exata de HTTP 400 apenas pelo código genérico 100.

S define atualização `POST /{PHONE_NUMBER_ID}/settings`, resposta `success:true`. Corpo mínimo proposto para o piloto, derivado dos valores documentados e sujeito à liberação operacional:

```json
{"calling":{"status":"ENABLED","call_icon_visibility":"DISABLE_ALL"}}
```

`call_icon_visibility` permite `DEFAULT`/`DISABLE_ALL`; não usar os valores antigos `visible/hidden` de Y23. `callback_permission_status` permite `ENABLED`/`DISABLED`, mas não precisa ser alterado para pedir consentimento via mensagem. SIP é opcional e vem desabilitado por padrão; habilitá-lo interfere em Graph/webhooks e não faz parte deste caminho. Não enviar `call_hours`, servidores SIP, voicemail, gravação ou transcrição por conveniência. Atualizar `call_hours` substitui todo esse objeto, inclusive feriados omitidos. S avisa que a UI do WhatsApp pode levar até sete dias para refletir mudanças; abrir as informações da conversa força atualização.

`DISABLE_ALL` reduz entradas de chamadas não solicitadas; manter o tratamento defensivo de entrada porque a própria documentação contém uma ressalva geral divergente sobre ocultar ícones e existem outros pontos de entrada. Habilitar o número exige limite de mensagens de pelo menos 2.000 e pré-requisitos O. Um HTTP 200 de settings não demonstra chamada funcional.

### Adicionar `calls` preservando a assinatura existente

Pesquisa operacional adicional em 10/11/2026, somente leitura. AS25 diz que um POST de atualização altera a assinatura do objeto sem substituir os campos existentes. Isso sustenta semântica aditiva para campos na referência genérica. Porém, não documenta um exemplo de atualização com somente `object` e `fields`, não define quais parâmetros podem ser omitidos em uma assinatura existente e não garante dispensa de nova verificação do callback. A descrição de `callback_url` informa que a operação de publicação provoca GET de verificação, e o exemplo envia `object`, `callback_url`, `fields` e `verify_token`. Portanto, não considerar `POST /{APP_ID}/subscriptions` com apenas `object=whatsapp_business_account&fields=calls` uma receita verificada para este ambiente. [AS25](https://developers.facebook.com/docs/graph-api/reference/v25.0/app/subscriptions)

Há uma divergência explícita de documentação: AS25, inclusive quando selecionada v27.0, declara que WhatsApp deve ser configurado pelo App Dashboard; W, atualizado em 17/06/2026 e conferido no original inglês, permite a Application Subscriptions API como alternativa, com app token e objeto `whatsapp_business_account`. O guia específico sustenta o uso geral da API, mas não resolve a omissão de callback/token em updates. O seletor v25.0 da referência genérica ainda exibe exemplos HTTP v27.0; não usar essa página como prova da versão efetiva dos eventos. [AS25](https://developers.facebook.com/docs/graph-api/reference/v25.0/app/subscriptions), [W](https://developers.facebook.com/documentation/business-messaging/whatsapp/webhooks/create-webhook-endpoint/)

AS mostra a versão por campo no GET (`fields[].name/version`), mas não documenta parâmetro de POST para fixar versões diferentes por campo, nem garante o que ocorre com a versão de campos reapresentados. Assim, não reenviar `messages` pela API v23.0 presumindo preservação de `messages` v25.0. Também não inventar sintaxe como `messages:v25.0` ou um campo de override de versão. A preservação precisa ser observada no GET posterior; o contrato consultado não permite garantir antecipadamente uma atualização somente por API sem atingir callback ou versões. [AS](https://developers.facebook.com/docs/graph-api/webhooks/subscriptions-edge)

Caminho operacional sustentado pelos documentos: inspecionar a configuração existente no Dashboard e usar o controle individual de assinatura de `calls`, mantendo o controle e versão de `messages` intactos, sem editar callback ou verify token. W separa a edição desses dois campos, que dispara verificação GET, da seleção posterior dos campos de webhook. Isso favorece uma alteração localizada pelo painel, mas **não prova** que o painel atual aceitará a ação sem outra verificação; se pedir edição/revalidação do callback legado, parar a operação e tratar essa dependência. A pesquisa não abriu a configuração privada nem acionou qualquer controle de assinatura. [W](https://developers.facebook.com/documentation/business-messaging/whatsapp/webhooks/create-webhook-endpoint/)

Antes e depois de uma futura mudança autorizada, comparar `GET /{APP_ID}/subscriptions`: mesmo objeto/callback/active, `messages` ainda v25.0, novo `calls` e sua versão registrada; conferir também o override do número por GET. O override existente suporta `calls`, mas direcionamento de eventos e verificação do callback global são mecanismos distintos: não assumir que o override torna um POST de configuração independente da saúde do receptor legado. Não remover/recriar a assinatura, não reenviar subscribed_apps sem corpo e não trocar callback para contornar uma revalidação. [OV](https://developers.facebook.com/documentation/business-messaging/whatsapp/webhooks/override/)

## Transporte e prova necessária

O documenta como caminho padrão HTTPS Graph + webhooks para sinalização e WebRTC `ICE + DTLS + SRTP` para mídia. Opus é padrão; S confirma que sempre permanece habilitado. I impõe Opus com clock 48 kHz, pacotes de 20 ms e uma única fonte SSRC de áudio. DTMF, se usado, tem clock 8 kHz; não é recurso necessário neste MVP.

I descreve Meta como ICE-Lite, recomenda peer ICE-Full/controlador iniciando STUN, nominação regular, concluir ICE antes de DTLS e não trocar candidato durante a chamada. Recomenda certificados ECDH e papel cliente DTLS. Os exemplos R mostram oferta `UDP/TLS/RTP/SAVPF`, `ice-ufrag`, `ice-pwd`, fingerprint SHA-256, `rtcp-mux`, Opus, e answer com candidatos públicos IPv4/IPv6 e `a=ice-lite`. Há divergência entre a recomendação de cliente DTLS e um exemplo de answer Meta `a=setup:active`: deixar a negociação real WebRTC determinar papéis, sem reescrever SDP por suposição.

Conclusão técnica: testar `RTCPeerConnection` nativo diretamente com a Meta é sustentado por esses contratos; Python fica na sinalização. Isso ainda é uma hipótese de interoperabilidade, não uma validação do navegador/rede do piloto. Não há evidência que obrigue SIP/BSP/TURN antes da prova. A documentação consultada não fornece endpoint Graph para enviar candidatos ICE incrementais; não inventá-lo a partir de `a=ice-options:trickle`. A implementação pode aguardar coleta ICE e enviar uma oferta completa, com prazo de preparo limitado, conservando o SDP gerado pelo navegador e um único track de áudio.

Prova isolada informada pelo coordenador em 10/11/2026: `.data/calling/peer-proof.cjs`, Chromium 1248 com dispositivo/UI de mídia simulados, dois `RTCPeerConnection` locais em `connected`, somente áudio, Opus, fingerprint DTLS SHA-256, ICE completo e cinco pacotes de áudio recebidos por cada lado; mute confirmou `track.enabled=false`. Sem Meta nem rede remota. Essa evidência não demonstra ainda transporte pelo fluxo HTTP da aplicação, pacote Opus de 20 ms, ICE-Lite Meta ou conectividade externa. Prova real pendente: consentimento, ringing, atendimento, áudio bidirecional, mute, término de ambos os lados, rejeição/não atendimento e preservação das mensagens do canal. Só o piloto autorizado pode fechar essas lacunas.

## Resultado incerto e limites da evidência

Nenhum endpoint de consulta individual de chamada nem chave de idempotência Meta foi encontrado nos contratos C/R/Y23. Não fabricar `GET /calls/{id}`. Persistir e reconciliar pelo ID/correlação dos webhooks; timeout de connect não autoriza nova tentativa. Um timer local não confirma encerramento. O documento não garante entrega de um evento correlacionado após todo timeout nem recuperação quando todos os eventos se perdem.

Preflight somente leitura informado pelo coordenador em 10/11/2026: runtime v23.0, token de sistema válido com `whatsapp_business_messaging`; leitura Settings com esse token retornou HTTP 400/código 100. A mesma consulta sem `fields`, com credencial de gestão, retornou `calling.status=NOT_SET`, `call_icon_visibility=NOT_SET`, `callback_permission_status=NOT_SET`. WABA `AVAILABLE`; assinatura do app contém apenas `messages` em v25.0; override do número aponta ao receptor WhatsApp existente, com callback global legado preservado. A pesquisa pública confirma compatibilidade de `calls` com esse override; a entrega efetiva ainda precisa ser verificada após liberação.

O contrato permite iniciar implementação e testes com fixtures documentadas. Permanecem pendentes a resposta real de permissões em v23.0, a versão efetiva do novo campo de webhook, a configuração e saúde do piloto no instante da liberação, a interoperabilidade de mídia e participação do usuário no teste real. Nenhuma credencial, configuração de tenant, VM, assinatura ou estado Meta foi alterado durante esta pesquisa.

## Instalação, operação e retorno

As quatro tabelas `whatsapp_calling_channels`, `whatsapp_call_permissions`, `whatsapp_call_operations` e `whatsapp_call_events` são aditivas. A inicialização do painel/receptor não as migra automaticamente. Com a configuração privada do ambiente já carregada, banco confirmado e backup verificado, usar o Python do venv da instalação:

```text
python -m app.whatsapp.calling_setup inspect
python -m app.whatsapp.calling_setup migrate
python -m app.whatsapp.calling_setup inspect
python -m app.whatsapp.calling_setup enable --tenant-id ID_EXISTENTE --phone-number-id ID_EXISTENTE
```

`migrate` pode ser repetido; não altera colunas antigas nem conteúdo de tenants/canais. `enable` valida o vínculo já existente. Nenhuma credencial deve ser passada como argumento. O piloto permanece desligado até migração, assinatura `calls` e configuração Meta confirmadas. O fluxo de release existente cria backup do banco HML antes da troca; a migração pode ocorrer após publicar o código com a capacidade desligada. Não usar seed nem importar banco sanitizado sobre HML.

O operador abre Conversas, assume o atendimento e usa o painel de ligação. O servidor consulta o consentimento atual antes de iniciar, respeitando também as ações permitidas pela Meta. Pedidos de permissão exigem mensagem do cliente nas últimas 24 horas; não há template implícito. No navegador, liberar microfone em HTTPS ou localhost. Mute desativa a track real; o estado “Em ligação” exige aceite externo e conexão WebRTC. Trocar de conversa não destrói o peer; logout, troca de tenant, saída da página ou erro de áudio liberam a mídia local e solicitam término quando há ID conhecido.

O admin mantém um reconciliador com verificação a cada 10 segundos; a aba informa presença a cada 10 segundos, com lease de 45 segundos. Ausência de presença, sessão revogada/expirada ou perda de posse provoca término. A intenção de terminar permanece persistida mesmo se o ID Meta chegar depois do pedido de cancelamento. Até três tentativas de término são permitidas, sem repetir `connect`. Shutdown aguarda a tentativa já despachada; reinício retoma as operações persistidas. Manter um worker de admin e um receptor conforme a operação existente.

Se a resposta HTTP de início se perder, a aba consulta a operação pela chave idempotente original, com a mesma autorização de sessão/aba, inclusive quando ela já terminou. Ausência de reserva ainda não confirma falha e não dispara outro connect. Operação incerta continua bloqueando nova chamada/devolução à IA. Falta de ID externo ou ausência de confirmação após as tentativas exige conferência operacional; não apagar a reserva nem marcar como concluída apenas por tempo decorrido. A auditoria fica nas tabelas de chamadas e aparece no painel sem criar `Message` ou outbox. Nenhum áudio é gravado. SDP recebido é restrito ao operador/aba, removido ao término; SDP órfão não consumido expira em cinco minutos.

Para retorno, encerrar e reconciliar chamadas primeiro. `python -m app.whatsapp.calling_setup disable --tenant-id ID_EXISTENTE --phone-number-id ID_EXISTENTE` recusa desabilitar um canal com chamada ativa/incerta, para preservar a recepção da confirmação terminal. Não contornar essa proteção alterando o banco diretamente. Depois desabilitar o piloto na Meta conforme a configuração anterior e retornar a release pelo procedimento existente. Preservar as tabelas aditivas, conversas e auditoria; retornar código não restaura nem desfaz operações externas. Assinaturas compartilhadas devem ser comparadas antes de qualquer restauração.

Testes locais usam `python scripts/test-local.py` e a variante `--postgres-env ARQUIVO_PRIVADO_DE_TESTE`, sempre com PostgreSQL descartável em loopback. `tests/calling-ui.cjs` serve fixtures locais e bloqueia requisições externas; `NODE_PATH` e `CHECKOUT_QA_BROWSER` apontam ao Playwright/Chromium já instalados quando não estão disponíveis na resolução padrão. As provas automáticas usam mídia fictícia e não demonstram conectividade com a Meta.
