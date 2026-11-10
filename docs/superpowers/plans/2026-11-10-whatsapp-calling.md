# WhatsApp Calling — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task in the new chat requested by the user. Steps use checkbox syntax for tracking. Review independent security/state changes when available; do not parallelize shared files or VM mutations.

**Goal:** Permitir ligação humana de áudio pelo admin da Lumi V3 ao WhatsApp do cliente, com consentimento, isolamento e validação em HML pelo canal 7916 de Paes & Gregori.

**Architecture:** WebRTC nativo no navegador, sinalização e autorização no adaptador WhatsApp existente e webhook assinado. Estado e idempotência em tabelas aditivas compartilhadas pelo admin e receptor. Comprovar interoperabilidade antes de adicionar infraestrutura de mídia.

**Tech Stack:** Python, FastAPI, SQLAlchemy, httpx, PostgreSQL/SQLite, JavaScript e WebRTC; sem novas dependências inicialmente.

**Spec:** `docs/superpowers/specs/2026-11-10-whatsapp-calling-design.md`.

## Global Constraints

- Piloto somente no tenant `paes-gregori`, canal final 7916, VM HML; código genérico e configuração por canal no banco.
- Somente áudio iniciado pelo operador responsável; IA permanece pausada até devolução explícita após término.
- Sem gravação, transcrição, vídeo, IA de voz, templates novos, migração de BSP ou alterações de outros canais.
- Segredos somente nos arquivos privados existentes; nunca em navegador, fixtures, logs, commits ou documentação.
- Um worker; testes com dados fictícios, banco descartável e rede externa bloqueada.
- Não substituir o admin pelo HTML; portar somente os elementos de chamadas, preservando acessibilidade e UTF-8.
- Não declarar teste real a partir de HTTP 200, mocks ou cronômetro de demonstração.

## 1. Retomada e contrato verificável

**Arquivos:** ler `AGENTS.md`, `docs/desenvolvimento-e-passagem.md`, `docs/contrato-de-integracoes.md`, `docs/whatsapp.md`, `docs/homologacao-vm.md`, `docs/deploy-automatico.md` e o spec; criar `docs/whatsapp-calling.md` para contrato e operação confirmados.

- [x] Criar o objetivo desta thread com `create_goal`, sem orçamento artificial: implementar, testar, publicar em HML e validar o piloto conforme o Goal acima. Não marcar concluído se a chamada real ainda estiver pendente.
- [x] Conferir Git, processos, branch e diferenças locais. Preservar as alterações prévias em `docs/estancia.md`, `docs/homologacao-vm.md` e `docs/plano-homologacao-vm.md`; não incluir mudanças alheias em commits.
- [x] Conferir instalação das ferramentas e o acesso privado existente. Ler tokens só no processo que chama a Meta; imprimir apenas status, códigos e capacidades não secretas.
- [x] Reconsultar configurações, saúde, versão Graph, escopos do token e assinatura do app/WABA. A última leitura encontrou `TIER_2K`/`NOT_SET`; depois o usuário adicionou pagamento e recebeu erro 2593151 por ausência de webhook/SIP.
- [x] Validar na documentação direta da Meta os corpos de `connect`/`terminate`, consulta/envio de permissão, envelopes de resposta/revogação, correlação da operação e configuração do campo `calls`. Registrar exemplos sanitizados, limites, regras de expiração, assinatura e versão. Usar Context7; na ausência de cobertura, documentação oficial. Não transformar exemplos de BSP em contrato Graph por troca de hostname.
- [x] Documentar o transporte de SDP e a exigência de ICE/DTLS-SRTP/Opus aceitos pela Meta. Fazer prova mínima em ambiente isolado, com peer simulado, e reservar prova real do piloto após receptor pronto e consentimento. Não instalar SIP/TURN/BSP antes de demonstrar necessidade.

**Saída verificável:** contrato suficiente para escrever fixtures corretas e uma decisão de transporte sustentada por documentação. Um bloqueio externo de habilitação não impede tarefas isoladas; falta de contrato impede inventar o parser real.

## 2. Estado durável e migração aditiva

**Criar:** `app/whatsapp/calling_models.py`, `app/whatsapp/calling.py`, `app/whatsapp/calling_setup.py`, `tests/test_whatsapp_calling.py`.

**Responsabilidades:** modelos de canal habilitado, permissão, operação e evento; regras transacionais; comando explícito para preparar schema e habilitar/desabilitar canal existente. O comando recebe identificador de canal/tenant e recusa vínculo divergente; não cria tenant, não grava tokens e não habilita todos os canais.

**Interface interna proposta:**

```python
# calling.py: tipos concretos são os modelos declarados em calling_models.py.
def reserve_call(db, *, tenant_id, conversation_id, operator_id, idempotency_key): ...
def apply_call_event(db, *, channel, event): ...
def has_active_call(db, *, tenant_id, conversation_id): ...
```

As reticências acima indicam assinaturas de contrato, não implementação a copiar. `reserve_call` devolve a operação persistida ou erro público de conflito; a chamada de rede pertence à tarefa 3. `apply_call_event` recebe evento normalizado de fixture verificada na tarefa 1 e retorna se houve transição. `has_active_call` inclui estado incerto.

- [x] Escrever casos inicialmente falhos: reserva em canal desligado, tenant divergente, duas chamadas concorrentes do mesmo operador ou conversa e replay da mesma chave.
- [x] Criar tabelas novas com FKs e índices únicos compatíveis com SQLite e PostgreSQL. Definir reservas ativas no banco, com liberação somente após término confirmado. Incluir hash dos parâmetros na chave idempotente para rejeitar seu reuso com conteúdo diferente.
- [x] Implementar estados de permissão, chamada, conexão e resultado incerto; timestamps UTC; deduplicação e transições monotônicas. Não persistir transcrições nem áudio. Validar destinatário contra `Chat` e canal contra tenant.
- [x] Criar migração executável e repetível das novas tabelas/índices, modo de inspeção e provisionamento seletivo desligado por padrão. Testar a migração duas vezes sobre banco que já contém conversas, canais e configurações; comparar IDs/conteúdo existentes.
- [x] Testar em PostgreSQL descartável concorrência entre conexões, não apenas threads sob lock Python. Confirmar que término antigo não encerra outra operação e evento atrasado não reabre terminal.

**Assertivas mínimas a incluir nos testes:**

```python
self.assertEqual(replayed.id, first.id)
self.assertEqual(conflict.status_code, 409)
self.assertEqual(existing_conversations_after, existing_conversations_before)
self.assertFalse(has_active_call(db, tenant_id=tenant.id, conversation_id=chat.id))
```

## 3. Graph, consentimento e webhook

**Criar:** `app/whatsapp/calling_graph.py`, `app/whatsapp/calling_webhook.py`, `tests/test_whatsapp_calling_webhook.py`.
**Modificar:** `app/whatsapp/webhook.py`; reutilizar `app/whatsapp/config.py` e os padrões de `graph.py`. Alterar `bridge.py` somente se um ponto mínimo de integração comprovadamente exigir.

**Interfaces:** `calling_graph` recebe referência de credencial resolvida no servidor e IDs já autorizados; expõe `get_permission`, `request_permission`, `connect`, `terminate` com HTTP e schemas confirmados na tarefa 1. Nunca aceita URL Graph arbitrária ou token enviado pelo navegador. O parser produz os eventos normalizados usados em `apply_call_event`.

- [x] Criar fixtures fictícias dos envelopes confirmados: permissão aceita/negada/revogada, validade temporária, SDP answer, ringing, accepted, rejected e término. Acrescentar assinatura inválida e lote com mais de um canal/segredo.
- [x] Implementar cliente com timeouts, erros públicos sanitizados e sem retry automático de operações de efeito incerto. Separar erro de autorização, bloqueio/cota e indisponibilidade. Registrar operação antes do envio e reconciliar resposta/evento mesmo quando o webhook chegar primeiro.
- [x] Processar `calls` e respostas de permissão após autenticar o webhook. Preservar o tratamento atual de mensagens, mídia e recibos. Não criar `Message`/outbox/rodada de IA para eventos internos.
- [x] Consultar autorização atual antes de ligar; expiração e revogação bloqueiam chamadas. Um estado local vencido ou consulta indisponível não autoriza por fallback. Pedidos fora da janela permitida retornam motivo acionável sem envio de template implícito.
- [x] Ignorar sem efeitos externos eventos de canal não habilitado. Para chamadas entrantes no canal piloto, usar somente a rejeição documentada e deduplicada; não aceitar mídia nem abrir handover automaticamente.
- [x] Executar os novos testes junto com `tests/test_whatsapp.py`, `tests/test_whatsapp_secrets.py`, `tests/test_incoming.py`, `tests/test_message_order.py` e `tests/test_instagram.py` no harness isolado.

**Regressão crítica:**

```python
self.assertEqual(outbox_after, outbox_before)
process_message.assert_not_called()
self.assertEqual(call.status, terminal_status)
graph_connect.assert_called_once()
```

As variáveis representam os estados antes/depois e mocks preparados no próprio teste; verificar banco e efeitos, não somente retorno HTTP.

## 4. Rotas do admin, posse e recuperação

**Criar:** `app/whatsapp/calling_admin.py`, `tests/test_whatsapp_calling_admin.py`.
**Modificar:** `app/main.py`, `app/admin.py`, `app/whatsapp/calling.py`.

**Contrato HTTP local:** todas as rotas sob `/api/admin/conversations/{cid}/calling`, preservando `?tenant=` do console:

| Método/sufixo | Entrada | Resultado e proteção |
|---|---|---|
| GET raiz | nenhuma | capacidade, estado de permissão, motivo de bloqueio, chamada ativa; sem segredo ou SDP de outro operador |
| POST `/permission` | `idempotency_key` | operação de solicitação e estado real; proprietário atual obrigatório |
| POST `/calls` | `idempotency_key`, `sdp_offer` | `call_id`, estado, token de posse de aba; destino obtido de `Chat` |
| GET `/calls/{call_id}` | token de posse em header | estado/versão e SDP answer apenas ao operador proprietário; `Cache-Control: no-store` |
| GET `/calls/by-key/{idempotency_key}` | chave original e token de posse em header | recupera a tentativa original, inclusive terminal; ausência ainda não confirma falha |
| POST `/calls/{call_id}/heartbeat` | token de posse, estado de conexão | renova presença; não altera aceite/término confirmado pela Meta |
| POST `/calls/{call_id}/terminate` | chave idempotente, token de posse | encerramento em andamento ou resultado já final; pode ser repetido sem duplicar início |

- [x] Testar rotas antes de implementar: sessão ausente 401, leitura escrita 403, tenant/conversa indevidos sem dados, operador concorrente 409 e canal Instagram/simulador indisponível sem Graph.
- [x] Validar a posse no servidor, estado humano, ativação do tenant/canal e autorização no instante do efeito. Limitar SDP em 64 KiB, aceitar somente áudio e recusar campos extras capazes de mudar destino, tenant ou URL externa. Proteger origem das escritas com sessão e testar pedido cross-origin negado.
- [x] Integrar o bloqueio de `/release` enquanto a chamada estiver ativa/incerta sob a mesma coordenação transacional da reserva, evitando corrida entre devolver e ligar. Não alterar `/claim` ou o protocolo legado sem necessidade.
- [x] Iniciar no lifespan do admin um reconciliador cancelável para operações abandonadas: heartbeat a cada 10 segundos, lease de 45 segundos, verificação a cada 10 segundos; esses são parâmetros locais, não limites Meta. Reinício reconcilia operações persistidas. Nenhuma tarefa depende de uma nova requisição para rodar.
- [x] Em perda de sessão/propriedade, rejeitar novos controles do navegador e encerrar pelo reconciliador. Timeout de encerramento permanece incerto, com retry seguro apenas do término conforme contrato e tentativa limitada; nunca recomeçar chamada. Registrar necessidade de intervenção após esgotar reconciliação.
- [x] Testar corrida release/connect, segundo navegador, logout, falta de heartbeat, reinício e término incerto. Garantir encerramento/cancelamento da tarefa no shutdown, sem vazamento ou segundo worker.

**Aceitação:** teste `test_release_during_call_returns_409_and_keeps_human` comprova tanto 409 como `Conversation.status == 'humano'`; `test_late_ringing_does_not_reopen_terminated_call` preserva o resultado final.

## 5. WebRTC e interface do operador

**Criar:** `web/admin-calling.js`, `web/admin-calling.css`, `tests/calling-ui.cjs`.
**Modificar:** `web/admin.js`, `web/admin.html`; incluir os assets no console caso o carregamento atual do workspace os exija (`web/console.html`/`web/console.js`, conferir antes).

**Interface JS:** módulo exporta `renderCallingControls(conversation)` e `mountCallingControls(conversation)` para o detalhe, além de `disposeCalling()` no logout. Um controlador único mantém `RTCPeerConnection`, tracks e elemento de áudio em região estável fora de `#content`. O estado vem das rotas da tarefa 4; callbacks jamais definem tenant ou destino por texto livre.

- [x] Reproduzir em teste de navegador os estados do banner e botão, posse por outro operador, canal indisponível e consentimento pendente. Fixtures somente fictícias; controles de demonstração ficam exclusivamente no teste.
- [x] Portar o botão, banner e barra de chamada do HTML, sem substituir a tela inteira. Estilos locais e nomes acessíveis; teclado e foco após erros. Não importar bibliotecas/fontes adicionais apenas para imitar o arquivo.
- [x] No gesto de ligar, executar `getUserMedia({audio: true, video: false})`, criar oferta, esperar a coleta ICE exigida pelo contrato e enviar SDP. Aplicar answer uma vez por versão; conectar áudio remoto via `ontrack`. Microfone negado ou falha antes do POST limpa tracks e não toca no cliente.
- [x] Polling de estado a cada segundo enquanto a chamada estiver ativa, sem sobreposição de requests; heartbeat conforme tarefa 4. Cancelar timers no término/logout. O estado de mídia utiliza `connectionState` e métricas locais; dados do navegador não substituem consentimento Meta.
- [x] Ligar mute a `track.enabled`, liberar todas as tracks/peer ao encerrar, preservar a barra ao trocar conversa/página e impedir nova chamada em outra aba. Recarregar mostra a sessão abandonada em reconciliação, sem simular reconexão automática.
- [x] Testar em Chrome desktop e viewport 390x844: pedir/aceitar/recusar permissão, chamar, conectar, mutar, cancelar, encerrar, microfone negado, falha ICE, refresh de conversas e mudança de tenant. Usar mídia fictícia e API simulada no teste; nunca clicar em destinatário real nessa etapa.
- [x] Verificar o fluxo pelo navegador disponível e capturar evidência visual. Os scripts CJS seguem o padrão existente; execução interativa deve usar as ferramentas de navegador autorizadas na sessão.

**Pseudofluxo que deve ser preservado:**

```javascript
const stream = await navigator.mediaDevices.getUserMedia({audio: true, video: false});
for (const track of stream.getAudioTracks()) peer.addTrack(track, stream);
await peer.setLocalDescription(await peer.createOffer());
// Após ICE completo conforme contrato, o servidor inicia a chamada.
// Ao receber answer autenticado da mesma operação:
await peer.setRemoteDescription({type: 'answer', sdp: answer});
// Mute real e encerramento local, respectivamente:
stream.getAudioTracks().forEach(track => { track.enabled = !muted; });
stream.getTracks().forEach(track => track.stop());
peer.close();
```

Não copiar esse bloco como fluxo síncrono completo; answer chega por webhook, encerramento só ocorre na transição correspondente e a Meta deve receber término mesmo se o browser falhar.

## 6. Validação e publicação HML

**Modificar:** `docs/whatsapp-calling.md`, `docs/homologacao-vm.md`; manter neste plano o registro curto da execução. `scripts/deploy_release.py` e o workflow existentes devem ser reutilizados, sem refatoração incidental.

- [x] Executar `rtk proxy python scripts/test-local.py` no Python do venv do projeto. O harness remove banco/chave herdados, usa diretório temporário e bloqueia rede externa. Rodar também com `--postgres-env CAMINHO_PRIVADO_DE_TESTE` apontando exclusivamente para PostgreSQL descartável local; não usar o banco da VM como fixture.
- [x] Executar `rtk proxy node tests/calling-ui.cjs` com URL loopback do app isolado, mídia fictícia, sem chaves reais e sem acesso externo. Preparação deve seguir os testes existentes, com pasta temporária definida antes de importar `app`.
- [x] Fazer revisão independente focada em isolamento, posse, estado incerto, migração, sigilo e diferenças de código da entrega. Resolver achados materiais e repetir somente checks afetados.
- [ ] Conferir diff, schema e compatibilidade de retorno. Publicação HML foi autorizada; usar o fluxo de release existente com mudanças revisadas, sem incluir documentação alheia, sem push em `main` e sem ampliar permissões. Se o fluxo exigir integração remota não abrangida pela autorização vigente, preparar a revisão concreta antes da confirmação final.
- [ ] Antes de parar serviços, confirmar ausência de chamadas ativas. Fazer backup do banco HML e registrar release/configuração anterior. Aplicar migração aditiva testada. Publicar com chamadas desligadas; conferir saúde de 8012/8013, assinatura inválida rejeitada, banco e canal textual.
- [ ] Preparar assinatura `calls` da Meta e confirmar seu alcance no app Lumi, preservando assinaturas existentes e override do 7916. Só então habilitar chamadas no 7916 e no cadastro de capacidade. Ler configuração após cada mudança e registrar evidência sanitizada. Não alterar callbacks globais, outros números, Instagram ou PROD.
- [ ] Revalidar forma de pagamento e eventual bloqueio Meta; não cadastrar cartão, aceitar contrato novo ou contratar provedor sem ação/autorização específica do usuário. O usuário já informou ter adicionado pagamento, portanto checar o estado antes de pedir qualquer ação repetida.
- [ ] Coordenar teste com o usuário: conversa no 7916, assumir, pedir consentimento, aceitar no WhatsApp, ligar pelo admin, confirmar áudio nos dois sentidos, mute e término dos dois lados. Testar rejeição/não atendimento e confirmar que a IA não voltou sozinha. Não fazer ligações espontâneas para outros contatos.
- [ ] Confirmar mensagem textual após o teste e ausência de alterações nos demais vínculos/configurações. Registrar o que foi provado em mocks, navegador, VM e canal real, separadamente. Publicar só código não basta para concluir o objetivo.

## Retorno

Desligar novas chamadas somente no canal piloto. Encerrar/reconciliar as existentes antes de retornar código ou parar o responsável pelo controle. Restaurar configurações Meta alteradas do piloto a partir da leitura anterior, sem sobrescrever assinaturas compartilhadas que outra pessoa tenha atualizado. Retornar a release pela rotina existente, sem restaurar banco sobre conversas novas. Preservar tabelas aditivas e registros de eventos para auditoria; retirar o recurso da UI pelo flag.

## Execução e passagem — 10/11/2026

Objetivo ativo: implementação e publicação HML autorizadas, conclusão somente após aceitação real. Tarefas 1–5 implementadas. Contrato Meta direto documentado; preflight confirmou modelo preservado, WABA AVAILABLE, chamadas NOT_SET e somente messages no app. Nenhuma ligação real realizada.

Suíte integrada: 354 testes aprovados, incluindo PostgreSQL descartável e rede externa bloqueada. Navegador: desktop/mobile, peers WebRTC nativos com mídia fictícia, áudio local nos dois sentidos, mute, limpeza e estados incertos aprovados. Isso não comprova áudio com a Meta.

Revisão independente corrigiu revogação no mesmo segundo, cancelamento durante resultado incerto e migração implícita. Revisão final encontrou recuperação incompleta quando a resposta de início se perde e a operação já terminou; consulta pela chave original implementada, 28 testes de rotas SQLite/PostgreSQL aprovados. Regressão final no navegador aprovada: terminal antes do primeiro polling e reserva temporariamente ausente recuperados sem novo connect. Revisão das correções sem novo achado material. Publicação HML pendente.

Usuário operará WhatsApp e admin, usando somente o contato autorizado informado na conversa. Acesso privado existente validado; entregar URL e link para o arquivo privado após publicação. Não iniciar chamadas espontâneas. Nenhum commit, deploy ou habilitação Meta realizado nesta etapa.

Próximo passo: publicar somente develop pelo workflow existente, aplicar migração explícita, preservar callback global/messages e habilitar apenas o piloto. Baseline privado de configuração e release anterior salvo na VM; o workflow fará backup antes da troca. As alterações prévias em três documentos de operação permanecem fora desta entrega.

Recursos temporários: PostgreSQL local descartável em `.data/calling/postgres-process.json`, configuração em `.data/calling/postgres.env`; instância encerrada após os checks. Relatórios transitórios em `.superpowers/sdd/2026-11-10-whatsapp-calling/`. Sem processo local de teste UI persistente. A credencial temporária de gestão deve ser revalidada antes de usar; a assinatura calls pode ser alterada individualmente no painel Meta sem reescrever messages ou callback.
