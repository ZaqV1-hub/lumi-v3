# Chamadas de áudio no handover da Lumi V3

## Resultado e autorização

O operador assume uma conversa no admin, solicita autorização de chamada ao cliente quando necessário e liga pelo navegador. O cliente recebe uma ligação nativa de áudio no WhatsApp. O piloto é o canal final 7916 do tenant `paes-gregori`, em homologação. O usuário autorizou implementar em um novo chat e publicar na VM HML. Produção e os demais canais permanecem fora do escopo.

Esta é uma mudança de arquitetura do adaptador de canal, além da interface: envolve sinalização, transporte de áudio, autorização e estado durável. O plano de execução está em `../plans/2026-11-10-whatsapp-calling.md`. A análise não habilitou chamadas nem alterou a Meta ou a VM.

## Evidências e limitações em 10/11/2026

O usuário confirmou que o WhatsApp do 7916 respondeu. A configuração existente mantém OpenAI `gpt-6-luna` por tenant; chamadas humanas não precisam de modelo de voz ou de outra chave OpenAI.

Consultas autenticadas somente de leitura à Graph API v23.0 retornaram `whatsapp_business_manager_messaging_limit=TIER_2K` e configurações de chamadas `status=NOT_SET`, `call_icon_visibility=NOT_SET`, `callback_permission_status=NOT_SET`. O nível de mensagens é um requisito favorável, mas não comprova elegibilidade completa ou áudio funcionando.

A primeira consulta de saúde retornou código 141006 na WABA, relacionado à forma de pagamento. Depois disso, o usuário informou ter adicionado o pagamento e enviou uma captura da tentativa de habilitar chamadas: erro 2593151, solicitando configurar webhooks ou SIP. Uma segunda consulta confirmou WABA `AVAILABLE`, sem 141006; o número continua `LIMITED`, com nome de exibição ainda pendente na consulta anterior. Reconsultar a saúde antes da ativação, mas não pedir novamente a correção financeira já confirmada. Os códigos 138024/138025 dizem respeito a SIP não configurado e não são motivo para instalar SIP quando a integração usa WebRTC.

O protótipo `/Users/juansouza/Downloads/lumi-conversas.html` foi lido e aberto no Chrome em servidor local descartável. Foram observados o banner de permissão, botão de ligação e barra de chamada simulada. Os textos com acentos apareceram incorretos porque o arquivo não declara charset; manter UTF-8 explícito no produto existente. O servidor usado para a análise foi encerrado.

O protótipo contém controles de demonstração, dados de exemplo, regras e temporizadores. Seu conteúdo é referência visual, não autorização operacional nem contrato da Meta. Não copiar dados de clientes ou transcrições para fixtures. Seus números de limites, expiração e formatos de webhook precisam ser conferidos na versão efetivamente utilizada.

## Experiência que será entregue

Na conversa WhatsApp, o operador responsável vê se o canal oferece chamadas e o estado da autorização: desconhecida, ausente, solicitação em andamento, concedida com validade real, recusada, expirada ou revogada. Uma autorização permanente significa até revogação, não chamadas ilimitadas. Falhas de consulta não se tornam autorização válida.

O botão de solicitação envia a mensagem interativa oficial, dentro da janela em que esse envio é permitido. Fora dela, o MVP explica a indisponibilidade e aguarda o cliente retomar contato; criação e aprovação de templates não entram nesta entrega. Pedidos repetidos respeitam as restrições atuais da Meta e não são reenviados automaticamente após timeout incerto.

Ao clicar em ligar, o navegador obtém acesso ao microfone, prepara a sessão WebRTC e o servidor revalida operador, canal e consentimento antes de iniciar. A interface distingue preparando, chamando, conectando áudio, em ligação, encerrando e resultado final. Aceite da API ou SDP recebido não significa cliente atendido ou áudio conectado. O cronômetro usa o início efetivo da conexão e informa problemas de áudio separadamente.

A barra apresenta contato, estado, duração, silenciar microfone e encerrar/cancelar. Ela permanece visível durante navegação pelo admin, sem perder o áudio quando a lista de conversas é atualizada. Mutar atua na faixa de áudio real; não mostrar medidor de volume fictício. Permitir teclado, foco visível, nomes acessíveis e anúncios de estado sem repetição a cada segundo.

Encerrar uma chamada mantém a conversa em atendimento humano. Devolver à Lumi fica bloqueado no servidor enquanto houver chamada ativa ou resultado incerto; depois do encerramento confirmado, usa-se a ação de handover existente. Não implementar as propostas extras do HTML de notas para a IA, aviso opcional de devolução, biblioteca de vídeos, anexos ou gravação de áudio.

## Decisão de arquitetura

A primeira opção é WebRTC nativo no navegador conectado à infraestrutura de mídia da Meta; o Python existente faz somente controle e sinalização. A negociação passa por HTTPS autenticado no admin, Graph API no servidor e webhook assinado no receptor existente. O SDP de resposta chega ao navegador por consulta autenticada de estado. Um experimento curto de interoperabilidade precede a implementação completa do fluxo de voz.

Isso reaproveita FastAPI, SQLAlchemy, httpx e JavaScript do projeto. Chamadas são capacidade do adaptador WhatsApp, não uma ferramenta de negócio oferecida ao modelo, portanto ficam em módulos pequenos de `app/whatsapp/`. Não modificar o contrato legado de `services/handover.py`, criar um segundo núcleo ou abrir um novo serviço de mídia sem necessidade demonstrada.

SIP com servidor de voz e BSP com SDK são alternativas se o experimento demonstrar uma incompatibilidade concreta. SIP adiciona operação de mídia; um BSP pode exigir migração do número, contrato e cobrança. Nenhum dos dois deve ser contratado ou provisionado silenciosamente. TURN pode ser necessário em redes restritivas; a necessidade deve ser medida. Um teste de áudio local bem-sucedido não prova funcionamento em outra rede.

O admin precisa de contexto seguro para microfone: HTTPS privado já autorizado ou localhost por túnel SSH. Não publicar a porta administrativa como solução. A VM não recebe mídia no caminho direto; não abrir faixas UDP nela por suposição. Tokens Meta, app secret e chaves OpenAI nunca chegam ao navegador. SDP pode revelar endereços de rede: acesso somente ao operador da chamada, sem logs de conteúdo e com descarte após o término.

## Persistência e concorrência

Adicionar tabelas próprias, sem alterar colunas existentes: habilitação por canal; permissões por tenant/número empresarial/destinatário; operações de permissão e chamada com chave idempotente; eventos deduplicados. Reusar o relacionamento de `whatsapp_chats` para obter o destinatário. Nunca aceitar telefone, tenant ou operador livres no corpo de uma solicitação do navegador.

Cada operação registra tenant, conversa, operador, canal, tipo, chave idempotente, estado, identificador externo quando conhecido, horários, código público de erro e prazos necessários. Uma chamada guarda separadamente estado da Meta e conectividade reportada pelo navegador, para não confundir atendimento com mídia. Registrar apenas o necessário, sem gravar áudio.

Garantias no banco: uma chamada ativa por operador e por conversa, inclusive entre abas/processos; chave idempotente única no escopo autorizado; eventos externos deduplicados por canal e identificador/assinatura estável. Reservar a operação em transação antes da chamada externa e não manter transação aberta durante HTTP. O receptor e o admin são processos distintos: trava Python não resolve concorrência entre eles.

Após timeout de início/envio, marcar resultado incerto e reconciliar por evento/correlação suportada. Não repetir `connect` automaticamente. Se não houver consulta externa de reconciliação, apresentar ação operacional segura e manter o bloqueio necessário até resolução; não inventar endpoint nem confirmar término por um timer local. Em terminal confirmado, liberar reservas e apagar SDP. Webhook atrasado não pode ressuscitar chamada terminada.

O polling/heartbeat usa sessão e proprietário atuais; um token de aba vinculado à operação impede que uma segunda aba se aproprie da mídia. Prazo de presença e recuperação após reinício encerram sessões abandonadas pela API e reconciliam confirmação. A saída do navegador é somente um sinal auxiliar: `beforeunload` não é garantia de encerramento. O reconciliador precisa sobreviver sem navegador e sem próxima requisição, com um único responsável no processo do admin e estado compartilhado no banco.

## Integração com o fluxo existente

`app/admin.py` já valida tenant e responsável no handover. As novas rotas usam `current_user`, impedem escrita para perfil leitura e revalidam atendimento humano e responsável em toda mutação. Leitura de SDP exige o proprietário, mesmo que outro operador consiga ver o histórico da conversa. Origem/CSRF e limites de payload precisam proteger as novas escritas com cookie de sessão.

`app/whatsapp/webhook.py` hoje ignora eventos cujo campo não seja `messages`; acrescentar tratamento de chamadas após validar a assinatura com o segredo do canal. Respostas de permissão devem ser interceptadas antes do recebimento genérico, sem criar rodada de IA, alterar papel ou consumir estado de spam. Confirmar os envelopes oficiais antes de codificar o parser. Eventos para canal não habilitado não causam mudanças nem chamadas externas.

`app/whatsapp/bridge.py:queue_messages` põe qualquer `Message` não enviada pelo cliente na outbox. Portanto eventos internos de chamada NÃO devem ser inseridos nessa tabela como mensagens de sistema: isso geraria envios reais indevidos. Exibir auditoria de chamadas a partir de sua própria tabela, escapando os dados no HTML.

`web/admin.js` recria o conteúdo do painel durante refresh. A instância WebRTC e o elemento de áudio devem ficar fora dessa região reconstruída, com limpeza explícita ao terminar ou sair da sessão. Reusar `adminPath`/helper existente para preservar seleção de tenant da equipe Brevia.

## Liberação limitada

Desabilitado por padrão para todos os canais. Primeiro publicar receptor compatível e painel com recurso desligado; depois configurar a assinatura de eventos de chamada sem remover `messages` ou outras assinaturas, verificar o override existente e habilitar somente o 7916. A assinatura do campo pode pertencer ao app compartilhado: documentar esse alcance e filtrar os canais pelo cadastro habilitado. Não substituir callback global ou overrides de terceiros.

A captura de erro 2593151 estabelece a dependência: preparar e assinar corretamente o webhook antes de tentar habilitar o número. Confirmar na documentação vigente como a assinatura, o override do número e a WABA se relacionam; não assumir que o webhook de mensagens basta. Não habilitar recebimento SIP. Não oferecer chamadas recebidas no MVP; esconder o botão de entrada quando suportado e tratar eventual chamada entrante por resposta negativa documentada, sem tomar a conversa nem chamar a IA.

Deploy em `C:\LumiV3-HML`, com backup, migração aditiva explícita, revisão e verificação do painel/receptor. Manter um worker. Preservar os demais tenants, canais e configurações privadas. Alteração de dependência exige atualização separada do venv porque o deploy atual a recusa. Retorno desliga o recurso para novas chamadas, encerra/reconcilia chamadas existentes, restaura configurações alteradas apenas do piloto e retorna o código; tabelas e histórico são preservados.

## Aceitação

Testes isolados comprovam autorização, isolamento, concorrência, idempotência, eventos duplicados/fora de ordem, falha/timeout, expiração/revogação, recuperação e bloqueio de devolução. UI comprova controles, microfone negado, navegação, refresh, falha de áudio e limpeza dos recursos. Isso é diferente de validação real.

Concluir o piloto exige o usuário aceitar a autorização no WhatsApp e participar de ligação de teste: tocar no cliente, ouvir e falar nos dois sentidos, mutar, desligar dos dois lados, recusar/não atender e preservar a resposta textual e os outros canais. Coordenar o destinatário e o teste; não ligar para clientes arbitrários. Se a Meta, pagamento ou participação do usuário impedir essa etapa, registrar claramente o que está implementado/testado e a condição concreta para retomada.

## Fontes e grau de confirmação

Consultadas em 10/11/2026. A consulta Context7 aos exemplos oficiais de WhatsApp não trouxe o contrato Calling; as páginas da Meta retornaram HTTP 429 na leitura automatizada. As referências abaixo ajudam no desenho, mas endpoints de BSP não devem ser copiados como endpoints Graph.

- [Meta: chamadas iniciadas pela empresa](https://developers.facebook.com/documentation/business-messaging/whatsapp/calling/business-initiated-calls) e [pré-requisitos indicados pelo erro](https://developers.facebook.com/docs/whatsapp/cloud-api/calling#step-1-prerequisites): contrato direto a conferir com acesso disponível antes da implementação da sinalização.
- [360dialog: fluxo de chamadas de saída](https://docs.360dialog.com/docs/messaging/calling/outbound-calls/how-to-handle-outbound-calls): oferta SDP, resposta via evento e estados de chamada; o exemplo de permissão é do provedor e não comprova o envelope Meta direto.
- [Infobip: chamadas iniciadas pela empresa](https://www.infobip.com/docs/whatsapp/whatsapp-business-calling/business-initiated-calling): consentimento, modalidades e janela de mensagens. Limites divergem entre fontes, por isso não serão copiados do protótipo.
- [Twilio: WhatsApp Business Calling](https://www.twilio.com/docs/voice/whatsapp-business-calling): requisitos de conta/região e alternativa com provedor, não autorização para migrar o canal.
- [WebRTC: conexões entre pares](https://webrtc.org/getting-started/peer-connections): separação entre sinalização, SDP e conectividade.
