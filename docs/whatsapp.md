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

## Saudação rápida e confirmação de entrega

Cada tenant pode cadastrar uma saudação rápida em Configurações > Instruções, usando `{nome}` e `{empresa}`. Ela responde apenas a saudações isoladas como “Oi”, “Olá” e “Bom dia”, sem iniciar uma inferência no Codex. Deixar o campo vazio devolve essas mensagens ao modelo. Pedidos com informações adicionais continuam seguindo o fluxo normal. Os exemplos de instalação usam textos guardados em `demo/tenants.json`; edições posteriores ficam em `tenant_greetings`, sem sobrescrita pelo seed.

Os webhooks de status agora registram `sent`, `delivered`, `read` e `failed`. O admin distingue “Aceito pela Meta” de “Entregue no WhatsApp” e exibe o código da falha. Confirmações fora de ordem não rebaixam leitura para envio. Se o status chegar antes de a resposta HTTP de envio terminar, ele é reconciliado ao concluir a entrega.

No teste desta instalação, a Meta aceitou a requisição, mas retornou depois o erro `130497`, informando uma restrição da conta empresarial para destinatários daquele país. O código não contorna essa restrição: ela precisa ser resolvida na conta da Meta. Até lá, a entrada de mensagens pode funcionar e a saída continuar bloqueada.
