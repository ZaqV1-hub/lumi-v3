# WhatsApp Cloud API — ambiente de teste

A Lumi usa a API oficial da Meta. O número de entrada (`metadata.phone_number_id`) é vinculado a um tenant no banco. O perfil recebido pelo WhatsApp nunca define o tenant nem o papel: novos remetentes entram como clientes. O mesmo remetente no mesmo número reutiliza contato e conversa, incluindo o bloqueio de spam.

## Credenciais locais

As credenciais ficam em `%LOCALAPPDATA%\Lumi\whatsapp.env`, fora do repositório. Crie o arquivo com estes nomes, preenchendo os valores pelo painel da Meta:

```dotenv
WHATSAPP_APP_SECRET=
WHATSAPP_VERIFY_TOKEN=
WHATSAPP_ACCESS_TOKEN=
WHATSAPP_GRAPH_VERSION=
```

Use um valor aleatório longo para o token de verificação. `APP_SECRET` é o segredo do aplicativo, e `ACCESS_TOKEN` é o token de acesso do WhatsApp. Em `GRAPH_VERSION`, use a versão mostrada na chamada de exemplo do painel, no formato `vNN.0`. Não coloque credenciais em commits, no README, em argumentos de terminal ou em capturas de tela. O token temporário de teste pode precisar ser renovado no painel.

## Rodar

Inicie a Lumi e o serviço de handover conforme o README, com as dependências atualizadas. Vincule o Phone Number ID do número de teste ao tenant escolhido:

```powershell
python -m app.whatsapp.configure --tenant breve --phone-number-id ID_EXIBIDO_PELA_META
```

O comando recusa transferir um número já cadastrado para outro tenant. Para mais de um token de acesso, use `--token-env NOME_DA_VARIAVEL`; coloque essa variável no arquivo local. Cada número mantém seu vínculo no banco.

Em outro terminal com o ambiente virtual ativo, execute o receptor:

```powershell
uvicorn app.whatsapp.webhook:app --host 127.0.0.1 --port 8002 --no-access-log
```

Abra um túnel HTTPS **somente para a porta 8002**, por exemplo:

```powershell
cloudflared tunnel --url http://127.0.0.1:8002
```

O endereço de callback é `https://ENDERECO_DO_TUNEL/webhooks/whatsapp`. No painel da Meta, configure o callback, o mesmo verify token e a assinatura do campo `messages`. Se necessário, conclua também a inscrição do aplicativo na conta do WhatsApp. Cadastre e verifique seu telefone como destinatário permitido do número de teste, conforme as opções do painel. Comece enviando uma mensagem desse telefone ao número de teste. A API de testes ainda precisa dessa configuração externa para funcionar.

O túnel expõe apenas o receptor do WhatsApp: ele não serve admin, simulador, arquivos ou documentação da API. O acesso ao admin continua em `http://127.0.0.1:8000/admin`. O endereço de um Quick Tunnel é temporário e muda quando ele é recriado; atualize o callback da Meta quando isso acontecer. Consulte a [documentação da Cloudflare](https://developers.cloudflare.com/tunnel/get-started/quick-tunnels/).

## Processamento e entrega

O receptor verifica `X-Hub-Signature-256` com HMAC-SHA256 antes de interpretar o evento. A mensagem externa é deduplicada pelo identificador da Meta e registrada antes da confirmação HTTP. O processamento da IA acontece fora da requisição do webhook, usando as mesmas regras do simulador: contexto, imagens, spam e handover.

As respostas da Lumi, os avisos e as mensagens humanas entram em `whatsapp_outbox` na mesma transação do histórico. O receptor também entrega essa fila pela Graph API. Mensagens humanas usam `*Nome do operador*` em negrito no WhatsApp. Imagens são enviadas pelo upload de mídia autenticado da Meta; não é preciso publicar arquivos de clientes no túnel.

O admin identifica as conversas como WhatsApp e mostra o estado de envio. `sent` significa aceito pela API, sem confirmar leitura pelo destinatário. Eventos de status da Meta não geram respostas. Recebimento de áudio, imagem e outros formatos do cliente ainda não é interpretado: esta primeira integração aceita texto e envia texto ou imagens cadastradas.

Falhas de envio ficam marcadas como `failed` e não são repetidas automaticamente, pois uma falha de conexão pode ocorrer depois de a Meta já ter aceitado o envio. Após interrupção do servidor, entradas em processamento ficam marcadas como `interrupted`; saídas em `sending` precisam de conferência antes de qualquer reenvio. A fila e os registros persistem no banco, mas este laboratório ainda não possui recuperação automática desses casos.

Use um processo da Lumi e um do receptor. Reiniciar qualquer um limpa os contadores de mensagens em andamento; faça isso quando não houver atendimento em processamento. Este caminho foi preparado para um número de teste e destinatários verificados, sem expor a instalação local para clientes reais.

## Verificação

`python -m unittest discover -s tests` cobre assinatura inválida, desafio de verificação, webhook sem admin público, deduplicação, tenant do número de entrada, contato com papel de cliente, geração em segundo plano, fila de entrega, nome do atendente, falha sem reenvio automático e upload de mídia. A prova final exige enviar e receber uma mensagem pelo número da Meta depois de configurar a conta.

Referência de implementação: [exemplos oficiais da Meta para a WhatsApp Cloud API](https://github.com/fbsamples/whatsapp-api-examples).

## Confirmação de entrega

Os webhooks de status agora registram `sent`, `delivered`, `read` e `failed`. O admin distingue “Aceito pela Meta” de “Entregue no WhatsApp” e exibe o código da falha. Confirmações fora de ordem não rebaixam leitura para envio. Se o status chegar antes de a resposta HTTP de envio terminar, ele é reconciliado ao concluir a entrega.

No teste desta instalação, a Meta aceitou a requisição, mas retornou depois o erro `130497`, informando uma restrição da conta empresarial para destinatários daquele país. O código não contorna essa restrição: ela precisa ser resolvida na conta da Meta. Até lá, a entrada de mensagens pode funcionar e a saída continuar bloqueada.
# Retomada e PDFs

O receptor pode agendar uma retomada por resposta da Lumi que ficou sem retorno. A contagem começa quando a Meta aceita a última parte da resposta. Após cinco minutos, a Lumi usa o histórico da conversa para escrever uma mensagem de continuação. Uma nova mensagem, mudança para atendimento humano, bloqueio ou desativação cancela o envio. O agendamento é gravado no banco, vale para novas respostas após a habilitação e expira dentro da janela de atendimento do WhatsApp. A retomada não agenda outra retomada.

Para tenants com objetivo de visita cadastrado em `tenant_visit_goals`, uma reserva confirmada pela ferramenta configurada marca a conversa como **Visita agendada** no painel e suprime a retomada da resposta àquela mensagem. Uma nova mensagem do cliente pode iniciar outra contagem. A marca é baseada no histórico auditado da ferramenta e também aparece em conversas anteriores com confirmação registrada. A publicação cria a tabela de configuração antes de iniciar a nova versão. O cadastro é por ambiente e vincula o tenant à ferramenta de confirmação de visita.

A publicação cria as tabelas aditivas `whatsapp_follow_up_channels`, `whatsapp_follow_ups`, `document_assets` e `message_documents` após o backup do banco do ambiente. Elas não alteram colunas existentes. O cadastro é por empresa e canal. Com o ambiente HML carregado, use `python -m app.whatsapp.follow_up_setup SLUG --pdf ARQUIVO --filename NOME.pdf --title TITULO --description DESCRICAO`. O arquivo fica no banco da empresa e a Meta recebe o PDF como documento, com nome e legenda. Para interromper as retomadas e retirar os PDFs do catálogo dessa empresa, execute o mesmo módulo com `SLUG --disable`. Mensagens e anexos históricos são preservados.

## Anexos no atendimento humano

Depois de assumir uma conversa, o operador pode anexar imagem, gravar ou anexar áudio, enviar vídeo MP4 e, no WhatsApp, enviar PDF. Imagem, vídeo e PDF aceitam legenda. A gravação do navegador é convertida para MP3; o vídeo usa H.264 e, se tiver som, AAC. Os limites do painel são 5 MB para imagem, 12 MB e dois minutos para áudio, e 16 MB para vídeo ou PDF. No Instagram Direct, os anexos usam a URL HTTPS temporária já usada para imagens. Comentários públicos continuam com texto.

O painel grava a mensagem, o autor, o anexo e a fila de entrega na mesma transação. O anexo usa o armazenamento existente de mídia da conversa, sem migração de banco. Se o upload for repetido com a mesma chave e o mesmo conteúdo, a mensagem anterior é reaproveitada. Reverter o código não apaga mídia já enviada.
