# Contrato HTTP para funcionalidades da Lumi

O protocolo padrão usa `GET /contracts` para descoberta dos contratos revisados e um endpoint POST para cada operação. O serviço pode ser desenvolvido em qualquer linguagem. Não deve importar `app`, ler o banco interno da Lumi ou receber acesso ao provedor de IA. Segredos são configurados no ambiente de cada instalação; não entram no contrato, no repositório ou nas respostas.

Cada contrato contém `name`, `description`, `path`, `roles` e `parameters` (JSON Schema). A descrição explica quando a ferramenta é apropriada e o significado dos dados; não fixa respostas para perguntas do cliente. `path` fica na mesma origem do serviço revisado. A configuração da Lumi relaciona esse contrato a um tenant, uma chave e os papéis aprovados pelo responsável autorizado da equipe. Serviços não se cadastram sozinhos nem alteram permissões pelo texto. O agendamento do exemplo é fictício e não é uma funcionalidade pronta de reservas.

A requisição é `{"tenant_id":"tenant-demo","conversation_id":"conversation-demo","role":"cliente","arguments":{"date":"2027-01-15"},"context":{"contact_id":"contact-demo","message_id":"message-demo","channel":"simulator","whatsapp":null}}`. A credencial chega em `Authorization: Bearer CHAVE_DO_AMBIENTE`. `tenant_id`, `role` e o canal são definidos pelo código da Lumi. O serviço precisa verificar se essa credencial autoriza o tenant e a operação. Um serviço com mais de um tenant usa credenciais ou vínculos distintos e isola consultas, caches e gravações. Um header Bearer não permite confiar em qualquer tenant enviado por qualquer chamador.

`context` é complementar e pode crescer. `whatsapp` só é preenchido automaticamente quando a mensagem realmente vem do WhatsApp; um ID do Instagram não é um telefone. O contexto atual pode incluir as últimas mensagens do cliente para comprovar um CPF digitado em uma compra; não é uma API geral para solicitar todo o histórico. A funcionalidade deve usar apenas os dados necessários à operação. Nunca enviar conteúdo privado a buscadores públicos.

Em caso de sucesso, retorne JSON, normalmente `{"ok":true,"...":"dados da operação"}`. O núcleo entrega esse retorno ao modelo dentro de `data`. Não marque uma compra como paga ou um agendamento como confirmado antes de o sistema responsável confirmar isso. Links de ação devem estar utilizáveis no ambiente de teste e ter escopo e prazo próprios. Identificadores internos não substituem uma URL válida.

Uma validação corrigível pode responder HTTP 422 com `{"ok":false,"error":"dados_invalidos","invalid_fields":[{"field":"cpf","reason":"invalid"}]}`. Os motivos aceitos são `invalid` e `required`. Os nomes dos campos usam letras minúsculas, números e sublinhado. Não incluir valor rejeitado, stack trace, senha, resposta bancária ou instruções arbitrárias nesse erro. A Lumi solicita a correção com o tom configurado, mantendo as outras escolhas. Nem todo HTTP 422 é encaminhado ao modelo: o núcleo só aceita esse formato público restrito.

Indisponibilidade deve ser distinguida de recusa, falta de dados e processamento incerto. No estado atual, outros erros HTTP são tratados pelo núcleo como indisponibilidade genérica. Para permitir uma orientação mais específica, pode-se devolver HTTP 200 com `{"ok":false,"error":"codigo_publico_controlado"}`, sem dados técnicos. Retornos acima de 64 KiB não são aceitos; a chamada tem timeout de 45 segundos. Operações longas devem devolver um estado pendente e permitir consulta posterior. No atendimento atual há uma chamada externa por rodada, seguida da resposta do modelo; não presumir uma cadeia ilimitada de ferramentas no mesmo turno.

Resultados pequenos reutilizáveis podem trazer `context_reference`, e cotações trazem `quote_id`. A Lumi guarda esses resultados com o tenant, conversa e permissão da ferramenta para uso no seguimento. Isso não concede acesso a outras ferramentas e não substitui uma consulta atual quando preço, disponibilidade ou pagamento podem mudar. Evite memorizar respostas volumosas e dados pessoais desnecessários.

Operações que gravam devem ter idempotência no serviço. Para uma reserva ou pedido, use uma chave estável de operação, tenant e conversa; duas requisições concorrentes não podem criar duas cobranças ou duas reservas. `message_id` é contexto útil, mas duas mensagens diferentes também podem se referir à mesma operação. Um timeout deixa o resultado incerto: consultar antes de repetir. Chamadas HTTP, filas e webhooks não garantem execução única por si só.

A Lumi audita nome, parâmetros, resultado e duração. CPF nos parâmetros é mascarado atualmente, mas isso não é uma anonimização geral de todos os campos: o desenvolvedor precisa minimizar dados no contrato e no retorno. O serviço mantém seus próprios logs técnicos sem expor segredos ou dados de cartão.

Antes de devolver a integração à equipe, o desenvolvedor precisa demonstrar sucesso, erro de validação, indisponibilidade, credencial inválida, tenant indevido, papel indevido e repetição/concorrência quando houver escrita. Os testes devem usar dados fictícios e não fazer cobranças ou disparos reais. Ele entrega a versão identificada, a configuração de exemplo e as dependências. O teste final inclui a conversa na Lumi em homologação, com o responsável combinado pela equipe. Isaque participa da validação de experiência sem ser o único responsável pela manutenção.

O serviço falso `services.handover` mantém um protocolo legado com `tenant_id`, `conversation_id` e `reason` no corpo. Ele não usa esse envelope genérico; não alterar esse formato sem uma migração revisada. O e-commerce Estância possui seus contratos no site e depende do projeto desse site. Os adaptadores de cadastro Rincão são referência de integração e não devem substituir sem revisão o que já está publicado no HML.

A funcionalidade `handover` com destino `native:queue` usa a fila de conversas do admin. A Lumi segue os critérios de encaminhamento configurados pelo tenant e o servidor aplica os papéis autorizados. A conversa fica aguardando atendimento e o encaminhamento é registrado no histórico de ferramentas.

Com `native:assist`, a conversa continua na fila e a Lumi pode responder até
um operador assumir. A troca invalida respostas em processamento. A
oferta de encaminhamento fica vinculada à conversa e à revisão atual. A fila
e o aviso são criados depois que o cliente aceita uma oferta anterior. Nos
canais externos, a oferta precisa ter registro de envio. A oferta vence em
24 horas e é consumida no encaminhamento.
A configuração privada `LUMI_HANDOVER_ALERTS` associa o ID do tenant ao
`phone_number_id`, ao `recipient`, à origem HTTPS `admin_url` e, quando
aprovado, ao `template` em pt-BR com dois campos de corpo para assunto e link.
O link exige login e as permissões do tenant. O aviso contém um assunto
padronizado e o link, sem copiar a conversa. Sem modelo aprovado, o envio de
texto exige uma conversa recente do destinatário com o mesmo número empresarial.
Os avisos usam uma fila própria. Envios incertos ficam registrados para
conferência, sem repetição automática. A migração de deploy é aditiva. Para
voltar, restaure a configuração do tenant e preserve os pedidos já recebidos.



O receptor público pode publicar checkouts externos por vínculo configurado em `LUMI_CHECKOUT_BINDINGS` (JSON: nome curto → base HTTPS fixa). A rota `/checkout/{vinculo}/{token}` encaminha somente página, estado e POST de pagamento/autenticação; não permite escolher origem pelo cliente, redirecionar, transportar cookies ou expor contratos administrativos. O serviço de destino valida o token, a origem pública, proteção CSRF e idempotência. Ativos visuais compartilhados são servidos pelo receptor. Vínculos e marcas permanecem na configuração privada/serviço responsável; o núcleo não decide o tenant pelo modelo. O checkout legado sem vínculo permanece disponível.


Os avisos ao atendente incluem um resumo factual de até 600 caracteres, além do assunto e do link autenticado. O resumo é gerado somente com o histórico do tenant e da conversa até a solicitação, omite identificadores e links privados e fica em `handover_briefs`, vinculado à mensagem do pedido. Uma falha de geração usa trechos do próprio cliente, sem inventar um motivo. A migração cria somente essa tabela, sem substituir históricos. O estado `preparing` pode ser retomado após reinício porque ainda não houve envio; `sending` continua incerto e não é repetido. Antes de enviar, a fila e o tenant são verificados novamente para cancelar avisos cujo atendimento já foi assumido. Retorno: usar o código anterior e preservar a tabela, os avisos e as mensagens.

O admin oferece `GET/PUT /api/admin/attendance` para configurar períodos semanais, fuso, aviso de espera e consentimento de telefone do próprio tenant. `GET /api/admin/attendance/waiting` consulta somente a contagem de contatos em espera, inclusive enquanto outras páginas do painel estão abertas. As consultas automáticas não renovam a sessão. Os recursos novos ficam desligados sem configuração. O pedido registra seu horário em `attendance_requests`; a assistente permanece ativa na fila. Fora do expediente, o aviso à equipe fica `deferred` até a próxima abertura. O prazo configurado começa na abertura; após alguém assumir, considera a última pergunta ainda sem resposta. Uma ligação ativa ou resposta humana posterior à pergunta impede a retomada. Ao vencer o prazo, há um único aviso ao cliente, preservando a solicitação e devolvendo à assistente um atendimento assumido sem resposta. Texto livre continua condicionado à janela do WhatsApp.

O consentimento é solicitado em mensagem interativa opcional no início da conversa WhatsApp. O webhook autenticado aceita somente botões vinculados ao tenant, contato, número e mensagem original entregue; texto livre não autoriza divulgação. `phone_consents` registra finalidade e decisão, e `phone_consent_events` registra alterações de forma deduplicada pelo identificador recebido. O telefone só integra o detalhe administrativo após autorização, e a recusa não bloqueia o atendimento. Essa autorização não elimina as regras da Meta para contato fora da janela. A migração de publicação cria as quatro tabelas novas, sem alterar os históricos existentes; faça o backup habitual antes. Para desativar, desligue as opções no admin e preserve os registros e decisões. Reverter código não desfaz mensagens já enviadas.
p
