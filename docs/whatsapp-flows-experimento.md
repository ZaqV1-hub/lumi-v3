# Experimento de atendimento por WhatsApp Flows

Este adaptador é opcional e começa desligado. Não incorpora o HTML do simulador. O arquivo `app/whatsapp/flows/layout.py` define duas telas nativas, com pergunta, histórico textual recente, atualização da resposta e encerramento. A inferência acontece no servidor; durante o processamento, a pessoa toca em “Ver resposta”. Não há streaming nem atualização automática garantida pelo Flows. Fotos, áudios e anexos não estão cobertos por este primeiro teste.

## Ativação em homologação

Depois do backup, a migração aditiva de publicação cria `whatsapp_flow_sessions`, `whatsapp_flow_launches`, `whatsapp_flow_turns` e `whatsapp_flow_pricing`. Não altera históricos ou canais existentes. O admin e o receptor devem usar a mesma versão e o mesmo banco. Não habilitar antes de validar o JSON no compilador da Meta, cadastrar a chave pública do telefone e confirmar a saúde do endpoint.

O ambiente privado aponta `LUMI_WHATSAPP_FLOWS_FILE` para um JSON. Cada chave é o ID do telefone, e seu valor contém `enabled`, `tenant_id`, `flow_id` e `private_key_path` absoluto. O campo opcional `recipients` limita o teste aos números autorizados, apenas dígitos internacionais. O tenant deve coincidir com o dono atual do canal no banco. Sem configuração, o adaptador não intercepta mensagens. O arquivo, os identificadores comerciais, os destinatários e a chave RSA permanecem privados, fora do Git. A chave privada não usa senha neste experimento e deve ter ACL restrita ao serviço. Não substituir a chave de um telefone que já utiliza outro Flow sem revisar a integração existente.

O endpoint público é `POST /webhooks/whatsapp/flows/{phone_number_id}`. Rejeita requisições sem HMAC válido do aplicativo do canal e recebe somente o envelope criptografado padrão RSA-OAEP/SHA256 + AES-GCM. Não expõe as rotas do simulador administrativo. O mesmo pool de processamento do receptor executa a IA; não cria workers adicionais.

## Conversa e isolamento

O primeiro texto recebido no canal habilitado cria uma abertura interativa de Flow. O token opaco fica vinculado ao telefone, tenant e conversa, com validade de 24 horas. Nova abertura tem proteção de dois minutos contra repetição. A sessão cria uma conversa separada para o mesmo contato, sem registro em `whatsapp_chats`. Assim, as mensagens da IA e do operador nessa conversa ficam no admin, mas não entram na fila de envio do WhatsApp. O canal do admin é “WhatsApp Flows”. O telefone mostrado no perfil segue a política de visibilidade do tenant e um vínculo verificado com o canal original. Ferramentas recebem a identidade WhatsApp original pelo servidor, preservando a validação de tenant e papel.

Cada envio usa um nonce de turno. Repetições do mesmo pedido consultam o estado existente e não refazem inferência ou ferramentas. Há limite de 30 perguntas por sessão de teste. O núcleo mantém anti-spam, ordem por contato e pausa da IA ao assumir o atendimento. Respostas humanas aparecem na tela na próxima atualização feita pelo usuário. Interações nas telas não devem ser usadas como renovação da janela de mensagens do WhatsApp. Não presumir acesso permanente ao Flow: sessão, token e regras da Meta têm validade própria.

## Validação e custos

`tests.test_whatsapp_flows` usa banco isolado, chaves e dados fictícios e provider simulado. Verifica criptografia, assinatura, reenvio sem duplicação, tenant incorreto, troca de canal, expiração e handover. Deve comprovar uma única mensagem na Outbox (a abertura) mesmo depois de respostas no Flow.

Os webhooks de status guardam `category`, `type` e `billable` em `whatsapp_flow_pricing` para o telefone configurado. Informação ausente fica desconhecida, nunca é inferida como gratuidade. Isso registra a cobrança das mensagens entregues, não substitui a fatura nem prova o preço final. A abertura e mensagens adicionais podem ser cobradas. IA, hospedagem, ferramentas e eventuais notificações de outros sistemas continuam tendo seus custos. Validar no número real de QA, comparar a fila de envio antes/depois e conferir o relatório da Meta antes de prometer economia. Nenhuma compra ou cobrança real é necessária para validar a tela.

## Desativação e retirada

Definir `enabled: false` (ou retirar o arquivo de configuração do ambiente) impede novas aberturas e chamadas do endpoint. Aberturas ainda pendentes são canceladas quando o envio é processado. Restaurar o tenant anterior do telefone com `app.whatsapp.transfer.transfer_channel`, após conferir ausência de mensagens/respostas/ligações em andamento e guardar backup. Não alterar assinaturas de webhook de outros aplicativos como atalho.

Para retirar o código, reverter o commit do experimento pela branch do ambiente. O pacote `app/whatsapp/flows` concentra a implementação; os pontos de integração são o receptor, o envio interativo, a identificação do canal no admin, o contexto verificado das ferramentas, a visibilidade do telefone e a migração aditiva. Preservar as quatro tabelas e os históricos para consulta/retorno. Excluir tabelas depois exige decisão e backup separados. Reverter código não recolhe mensagens já entregues nem cancela cobranças já realizadas.
