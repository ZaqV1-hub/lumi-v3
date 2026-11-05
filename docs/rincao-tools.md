# Consultas externas do Rincão (teste local, sem publicar)

`services/rincao/` é uma aplicação independente na porta 8003, sem imports de `app/`. Pode ser levada para outro repositório/servidor. A Lumi não acessa os bancos de negócio: lê os contratos HTTP cadastrados no seu banco. O modelo recebe nome, descrição e parâmetros, nunca endpoint, senha ou SQL.

## Funcionamento e acesso

O servidor oferece somente ferramentas permitidas ao papel atual do contato. Antes de executar, valida novamente tenant, estado da conversa, revisão, papel e parâmetros. O serviço também verifica a credencial, o tenant vinculado e o papel. Há no máximo uma chamada de ferramenta por mensagem nesta etapa; uma segunda inferência redige o resultado com a personalidade configurada. Cada tentativa fica em `feature_calls` com parâmetros, resultado/erro e duração.

Em Conversas, **Papel do contato** permite Cliente, Gestor ou Atendente. Só o admin autenticado daquele tenant pode alterar. O canal público sempre cria contatos como Cliente. Uma alteração de papel invalida respostas em geração. `tool_reply_access` associa as respostas às funcionalidades que forneceram dados: se um gestor volta a cliente, falas financeiras deixam de entrar no contexto, inclusive paráfrases posteriores que herdaram esses dados. Mensagens já entregues ao WhatsApp continuam no aparelho do destinatário.

## Consultas e critérios investigados

`consultar_agenda` permite Cliente, Gestor e Atendente. Lê `agenda` com `tabpreco` no Postgres de homologação, tipos públicos `padra` e `promo`. Retorna data, situação e preços online/bilheteria de adulto e infantil, sem passeios escolares privados nem pessoas. Fechada/lotada não significa disponível; preço nulo não significa grátis. Sem período, consulta hoje até os próximos 90 dias. O retorno avisa se passou de 100 registros.

`consultar_faturamento` permite somente Gestor. O critério foi encontrado no serviço existente `rincao-dados` de homologação, em `src/modules/buffet/buffet.repository.ts`. Calcula em `tevento`: valor fixo + quantidade ajustada de convidados × preço ajustado por convidado − desconto. Quantidade e preço reduzidos substituem os normais quando diferentes de zero, seguindo o relatório existente.

O filtro `date_base=evento` usa `DatEvento`; `contrato` usa `DatContrato`. As datas inicial e final são inclusivas. Pode filtrar parte do nome do representante: `NidResponsavelEvento` liga a `tpessoa.NidPessoa`. O retorno agrupa por representante e explicita o filtro. Todos os valores são parâmetros de consultas fixas; não existe parâmetro SQL.

O relatório existente inclui todos os status de evento. O resultado explicita esse critério; não representa recebimentos, saldo, caixa ou transferências. Conferir com o relatório utilizado pela equipe antes de tratar como número contábil definitivo. Tipo de evento e classificação de escola ainda não são filtros deste contrato.

O serviço não altera os bancos. No Postgres usa transação somente leitura e limite de tempo. O MySQL legado é 5.5 e não suporta a configuração moderna de transação somente leitura: o adaptador só executa o SELECT fixo e fecha com rollback. Um usuário com apenas SELECT pode substituir a credencial atual sem alterar a Lumi.

## Executar

Instale `requirements.txt`. As variáveis `INGRESSO_SISTEMA_DB_*`, `BUFFET_DB_*`, `RINCAO_TENANT_ID` e `RINCAO_TOOLS_SECRET` ficam em `%LOCALAPPDATA%\Lumi\rincao-tools.env`. A Lumi recebe apenas `RINCAO_TOOLS_SECRET` em `whatsapp.env`; as senhas dos bancos ficam no ambiente do serviço externo. Não copiar esses arquivos para o Git.

O Postgres só escuta dentro da VM. Foi usado um túnel local `127.0.0.1:15432` para `127.0.0.1:5432` da VM, com verificação estrita do host SSH. O arquivo privado registra também `RINCAO_SSH_HOST` e `RINCAO_SSH_KEY_PATH`. Para iniciar/reutilizar o túnel e o serviço:

```powershell
.\scripts\start-rincao-tools.ps1 -PythonPath caminho\do\venv\Scripts\python.exe
```

Com o túnel ativo, o serviço também pode ser iniciado manualmente:

```powershell
python -m uvicorn services.rincao.api:app --host 127.0.0.1 --port 8003
```

Cadastrar/atualizar os contratos revisados no tenant, preservando contexto e imagens:

```powershell
python -m app.tool_setup --tenant rincao --service http://127.0.0.1:8003 --secret-env RINCAO_TOOLS_SECRET
```

Reinicie admin (8000) e receptor WhatsApp (8002) depois de atualizar o código. O túnel público do WhatsApp continua expondo apenas 8002. O serviço 8003 e o túnel SSH precisam estar ativos para consultas; fonte indisponível gera aviso, sem inventar resultados. O banco e o serviço de consultas não foram expostos publicamente.

## Verificar

`python -m unittest discover -s tests` cobre autenticação, tenant, permissões, mudança de papel, negação de faturamento para cliente, descarte durante revogação, histórico protegido e registros de chamadas. Também foram feitas consultas somente leitura nos bancos fornecidos. Compras e pagamentos continuam fora desta etapa.
