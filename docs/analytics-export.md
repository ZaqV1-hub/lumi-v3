# Exportação de mensagens e eventos para análise

O banco da Lumi continua sendo a fonte do atendimento. O comando `app.analytics_export` envia lotes para um receptor HTTP privado, fora do processamento das mensagens. O receptor é responsável por persistir os registros em abas de análise no Google Sheets com idempotência. A API externa não recebe acesso ao banco da Lumi, e o núcleo não recebe credenciais Google.

## Escopo e dados

A configuração identifica exatamente um tenant e um destino. Só são selecionadas mensagens de WhatsApp criadas depois da ativação. O vínculo é conferido no servidor, incluindo conversas arquivadas durante transferências de canal. Mensagens anteriores ao marco, simulador, Instagram e outros tenants não são exportados. O marco não é alterado por uma segunda execução de `prepare`.

Mensagens exportam identificadores de conversa e mensagem, horário UTC, canal, autor e texto. Textos extensos são divididos em partes estáveis, sem truncamento, com o mesmo `message_id` e IDs terminados em `-part-N`; a análise deve reuni-los na ordem numérica. Texto de aparência de fórmula continua sendo texto: o receptor deve usar `RAW` ao gravar no Sheets. Nenhum áudio ou imagem binário é enviado. Transcrições existentes fazem parte do texto.

Eventos exportam chamadas de ferramentas e do modelo, vinculadas à mensagem que disparou o processamento, com horário, tipo, operação, estado, código de erro controlado, duração e referência de reserva quando disponível. Não exportam parâmetros brutos, resultados completos, mensagens de exceção, prompts, credenciais, telefone do vínculo ou arquivos de log. Erros não reconhecidos recebem `unclassified_error`. A classificação comercial de interesses e o dashboard não fazem parte deste exportador.

Para evitar congelar o texto antes da transcrição, mensagens de clientes aguardam o término das operações pendentes do contato. Áudios recebidos em atendimento humano ou com IA desativada são exportados com o texto/marcador disponível, sem prometer uma transcrição inexistente. Um contato continuamente ocupado ou com um contador preso após falha pode ter sua exportação adiada até a recuperação do atendimento. Não se descarta a fonte nesse caso. A exportação é de mensagens estabilizadas, não um histórico de edições manuais posteriores ou de cada transição de entrega do WhatsApp.

## Preparação e migração

Configure o ambiente do banco antes de importar qualquer módulo da aplicação. Use o banco do ambiente autorizado, nunca uma pasta padrão ou banco ativo como fixture de teste. Faça backup antes da migração.

O arquivo JSON privado tem esta estrutura, com valores fictícios:

```json
{
  "tenant_id": "tenant-demo",
  "endpoint": "http://127.0.0.1:8011/analytics",
  "secret_env": "LUMI_VISITS_ANALYTICS_SECRET",
  "destination": "visits-sheet"
}
```

O segredo fica no arquivo privado apontado por `LUMI_TOOLS_ENV`, ou na variável indicada por `secret_env`, seguindo o padrão das ferramentas. Use segredo dedicado de 32 a 256 caracteres ASCII visíveis. O destino aceita HTTPS ou HTTP apenas em loopback, exige `/analytics` e recusa credenciais na URL, query e fragmento. Redirecionamentos e proxies de ambiente ficam desabilitados para não encaminhar a credencial a outro destino.

```sh
python -m app.analytics_export migrate --config /caminho/privado/analytics.json
# Publicar e conferir a versão com produtores que registram data e mensagem.
python -m app.analytics_export prepare --config /caminho/privado/analytics.json
python -m app.analytics_export run --config /caminho/privado/analytics.json --max-batches 5
```

`migrate` adiciona explicitamente `created_at` e `message_id` nullable em `feature_calls` e cria apenas `analytics_activations` e `analytics_receipts`, sem ativar exportação. `prepare` confere a migração e registra o marco UTC de ativação, depois da publicação. Suporta SQLite e PostgreSQL. Não preenche logs antigos com datas inventadas, não regrava mensagens e não usa seed. Colunas e tabelas existentes são preservadas; repetir os comandos é seguro. O mesmo destino não pode ser silenciosamente associado a outro endpoint.

As colunas precisam existir antes de iniciar o código novo que grava `FeatureCall`. Execute `migrate` com a nova release preparada, publique o núcleo pelo fluxo autorizado, confira a versão ativa e só então execute `prepare`. Isso evita ativar a exportação enquanto produtores antigos ainda não gravam os metadados novos, sem exigir pausa do WhatsApp. O retorno ao código anterior preserva as colunas e tabelas; pare a tarefa exportadora se for necessário interromper a cópia. Um rollback de código não remove dados já exportados.

Agende `run` separadamente, por exemplo a cada minuto, sem sobreposição. Cada execução envia no máximo cinco lotes por padrão, de até vinte registros e 256 KiB. O limite pode ser ajustado até cem lotes. Falhas retornam exit code 1 e um código fixo, sem imprimir configurações ou payloads. Monitore a saída da tarefa; uma falha não é sucesso e não pode ser descartada operacionalmente.

Para a tarefa Windows, `python scripts/export-analytics.py --env-file <ambiente-privado> --config <config-privada> --max-batches 5` carrega o ambiente antes de importar o banco. O mesmo wrapper aceita `--action migrate` ou `--action prepare`. Use o diretório `current` do ambiente como pasta de trabalho; não copie o código para fora da release nem coloque o segredo nos argumentos da tarefa. Configure execução sem sobreposição e confira o resultado da última execução no Agendador.

## Contrato e recuperação

`POST /analytics` usa Bearer dedicado e JSON `{tenant_id, records}`. Cada registro contém `id`, `kind` (`message` ou `event`), `conversation_id`, `message_id`, `occurred_at` ISO com fuso, `channel` (`whatsapp`), `sender`, `content`, `event_type`, `operation`, `status`, `error_code`, `duration_ms` inteiro ou null e `reference`. Campos sem aplicação ficam vazios.

O receptor responde `{ok: true, accepted: [ids]}` somente depois de confirmar persistência. O exportador grava recibos apenas para IDs presentes no lote e explicitamente aceitos. ACK parcial deixa os demais pendentes. Timeout, falha do processo ou perda do ACK repetem os mesmos IDs: o receptor deve deduplicar e rejeitar conteúdo diferente com o mesmo identificador.

A seleção usa ausência de recibos por tenant/destino/tipo/ID, não um cursor por data. Assim, uma transação que confirme atrasada ainda será encontrada. O marcador do texto completo só é confirmado quando todas as partes forem aceitas. As fontes continuam no banco; uma falha no Google não altera o atendimento nem executa novamente uma ferramenta de negócio.

## Verificações

`python -m unittest tests.test_analytics_export` usa SQLite temporário e transporte simulado. Cobre isolamento, marco de ativação, fonte que aparece depois com data anterior, ACK parcial/timeout, divisão de texto, áudio pendente, migração preservadora, projeção de erros e vínculo de auditoria. Não comprova recebimento no Google nem execução da tarefa agendada; esses itens exigem validação operacional separada.
