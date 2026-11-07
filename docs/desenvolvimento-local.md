# Desenvolvimento local com PostgreSQL e OpenAI

Esta configuração prepara um banco PostgreSQL exclusivo, importa configuração sanitizada e permite escolher Codex, OpenAI ou demonstração. Não publica a aplicação, conecta canais nem habilita ferramentas externas. Execute com um único processo: a fila de mensagens continua local ao processo.

## Ambiente e banco

Use Python 3.11 ou superior. No macOS/Linux, dentro do projeto:

```sh
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env
chmod 600 .env
```

Se `.env` já existir, revise-o sem sobrescrever. Defina uma senha local privada e ajuste `POSTGRES_PASSWORD` e `DATABASE_URL` de forma correspondente. Caracteres especiais da senha precisam de codificação de URL na conexão. Não versione `.env`, bancos, arquivos de acesso, dumps ou conteúdo dos tenants. Configure o ambiente antes de importar módulos da aplicação; `DATABASE_URL` tem precedência sobre a pasta de dados.

Com Docker disponível, `docker compose up -d db` cria PostgreSQL 17 em `127.0.0.1:55439`. Use um projeto/volume exclusivo: as variáveis do Compose só inicializam volumes novos e não alteram usuários, senhas ou bancos em volumes existentes. Não apague volumes para resolver divergências. Um PostgreSQL nativo também serve, desde que tenha banco e usuário exclusivos; não inicie Docker na porta já usada pelo servidor nativo.

Mantenha `LUMI_SEED_DEMO=false` durante a importação e conferência. O seed continua habilitado por padrão para instalações antigas; desabilitá-lo impede a criação automática dos acessos de demonstração. Configure `demo` por tenant antes de testar conversas, conforme a seção Providers.

## Importação e preservação

Confira o pacote e mantenha o SQLite original fora do repositório. O importador aceita somente as tabelas de configuração sanitizada previstas. Recusa conversas, canais, usuários e demais dados operacionais; também recusa tenants ativos, ferramentas habilitadas, endpoints não bloqueados e conteúdo de tabelas desconhecidas. Tabelas desconhecidas vazias são informadas e omitidas.

Execute antes de iniciar a aplicação, apontando para um banco PostgreSQL novo, com schema `public` vazio:

```sh
python -m dotenv -f .env run -- python -m app.import_sqlite --source /caminho/privado/lumi-sanitizado.db
```

O importador abre SQLite somente para leitura, verifica integridade e relacionamentos, converte tipos para os modelos atuais, cria as tabelas e compara todos os registros e os hashes das imagens. Toda a criação e carga PostgreSQL ocorre na mesma transação, com trava contra importações concorrentes. Falhas desfazem a criação/carga; destino ocupado é recusado. O arquivo de origem não é modificado.

Isso é uma importação inicial, não um sistema de migrations. Alterações futuras em colunas exigem migração própria; `create_all` não atualiza colunas existentes. Para retornar à configuração anterior, pare a aplicação e restaure a conexão anterior, preservando ambos os bancos. Novas gravações feitas no PostgreSQL não retornam automaticamente ao SQLite.

O pacote recebido em 05/11/2026 forneceu seis tenants, 43 itens de conhecimento, duas imagens, 19 instruções por papel, cinco objetivos de onboarding e 17 contratos de ferramentas. Não forneceu os logins ou históricos antigos. O importador preservou IDs e conteúdo; a conta de desenvolvimento foi criada separadamente.

## Acesso e execução

Depois da importação, provisione um acesso fictício para um tenant existente. O comando solicita a senha sem eco; não a passe por argumento. Reexecutá-lo pode redefinir o acesso e invalidar sessões:

```sh
python -m dotenv -f .env run -- python -m app.console_setup --email dev@lumi.local --name 'Desenvolvimento local' --tenant SLUG_EXISTENTE --role brevia
python -m uvicorn app.main:app --host 127.0.0.1 --port 8010 --env-file .env
```

Abra `/admin`. Para usar `/chat/SLUG_EXISTENTE`, ative o tenant somente na cópia local pelo painel. Mantenha ferramentas e canais desligados. O modo demo verifica interface, persistência e fluxo; sua resposta fixa não avalia a qualidade da IA nem a interpretação do conhecimento importado.

## Providers

Provider, modelo e chave OpenAI são configurados por tenant. As antigas variáveis globais não selecionam IA. Após importar o banco, inicialize somente as configurações ausentes em modo sem inferência:

```sh
python -m dotenv -f .env run -- python -m app.migrate_tenant_ai --provider demo
```

O comando preserva escolhas existentes. Para alterá-las, use Configurações → Inteligência artificial no painel Brevia. `codex` mantém o CLI local e sua autenticação; `codex_gateway` usa a infraestrutura privada de gateway; `demo` dispensa inferência. Para OpenAI, prepare `LUMI_AI_SECRET_KEY` privadamente e cadastre a chave e o modelo da empresa pelo painel. Siga [IA por tenant](ia-por-tenant.md), incluindo preservação da chave Fernet.

O modelo escolhido precisa aceitar Responses API e Structured Outputs; para imagens, também precisa aceitar entrada visual. A implementação usa HTTPS para `/v1/responses`, `store=false`, saída JSON validada e imagens JPEG. As ferramentas de negócio continuam no fluxo da Lumi, com validação de tenant, papel e argumentos no servidor. Não há execução de ferramentas locais pela API nem fallback para Codex.

Falhas de acesso, conexão, recusa, saída incompleta ou inválida não são tratadas como resposta válida. Tokens, modelo, tempo e status são registrados; valores monetários da OpenAI são estimados somente quando tarifa e metadados estão completos. Custos desconhecidos e totais parciais são identificados. Referências de contrato: [Structured Outputs](https://developers.openai.com/api/docs/guides/structured-outputs) e [imagens](https://developers.openai.com/api/docs/guides/images-vision).

## Testes e limites

```sh
python scripts/test-local.py
python scripts/test-local.py --postgres-env /caminho/privado/tests.env
```

O primeiro comando usa pastas temporárias, limpa conexões e chave de API herdadas e bloqueia chamadas externas pelo transporte Python e invocações reais do Codex. Os testes de PostgreSQL são omitidos sem configuração explícita. O segundo lê apenas `LUMI_TEST_POSTGRES_URL` do arquivo privado, exige host loopback e usa uma conta de teste com permissão de criar bancos. Cada teste cria e remove apenas seu banco temporário. Nunca use credenciais de produção ou banco compartilhado como ambiente de teste.

Em 05/11/2026, passaram 194 testes com PostgreSQL 17 real, incluindo importação, rollback, concorrência de importação, isolamento entre tenants, login, ferramentas, histórico, ordem de mensagens e um fluxo OpenAI + ferramenta com HTTP simulado. O teste de navegador `tests/postgres-ui.cjs` passou em uma cópia local com provider demo: login, configurações e imagens importadas, simulador, upload, histórico após recarregar e largura mobile, sem erros JavaScript.

Para repetir o navegador, prepare uma cópia descartável com tenant ativo, ferramentas/canais desligados e provider demo. Instale Playwright localmente em `.data/browser` (`npm install --prefix .data/browser --no-save playwright`), tenha um navegador compatível e uma imagem fictícia em `.data/qa-image.png`. Defina `NODE_PATH=.data/browser/node_modules`, `LUMI_QA_URL` (origem `http://127.0.0.1:PORTA`), `LUMI_QA_TENANT` (slug), `LUMI_QA_CREDENTIALS` (arquivo privado JSON com `email` e `password`) e `CHECKOUT_QA_BROWSER` (executável). Execute `node tests/postgres-ui.cjs`. O teste cria conversa e anexo na cópia; screenshots ficam em `.data/postgres-ui` fora do Git.

Depois da suíte simulada, foi validada uma conversa real no simulador com Codex local, autenticado via ChatGPT, modelo `gpt-6.1-terra`. Duas respostas coerentes com o conhecimento importado foram produzidas em aproximadamente 7 e 5 segundos; as duas chamadas e quatro mensagens foram confirmadas no PostgreSQL, e o histórico persistiu após recarregar o navegador, sem erros JavaScript. Evidência local em `.data/postgres-ui/codex-live.png`. Não houve chamada real à OpenAI API, cobrança de negócio, envio em canais, teste de integrações reais ou implantação. OpenAI ainda depende de chave/modelo privados e validação real. Os testes de áudio usam simulações; nenhum modelo de transcrição foi baixado nesta etapa.

## Instalação preparada neste Mac

O PostgreSQL 17 nativo atende somente `127.0.0.1:55439`. Seus dados ficam em `~/Library/Application Support/LumiV3-Dev/postgres17`; ele foi iniciado diretamente, sem serviço automático do Homebrew. Para retomá-lo após reiniciar o Mac, use o `pg_ctl` de `/opt/homebrew/opt/postgresql@17/bin`, apontando `-D` para essa pasta e `-l` para `../postgres17.log`. Não inicie uma segunda instância se já estiver ativo.

O banco `lumi_v3_dev`, configurado no `.env` privado, preserva todos os tenants desativados e contém um acesso de desenvolvimento. O banco `lumi_v3_qa` é sua cópia para o simulador, com somente o tenant Rincão ativo, ferramentas e canais desligados. A validação local usou Codex com `gpt-6.1-terra`; a escolha atual deve ser conferida por tenant no painel. O servidor foi iniciado em `http://127.0.0.1:8011/admin`, com `.venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8011 --env-file "$HOME/Library/Application Support/LumiV3-Dev/qa.env" --no-access-log`.

O acesso está no arquivo privado `~/Library/Application Support/LumiV3-Dev/acesso-local.txt`. O arquivo `tests.env` da mesma pasta configura os testes PostgreSQL. ZIP, SQLite e credenciais permanecem fora do Git. Este servidor não inicia automaticamente após reiniciar o Mac e não altera a VM Rincão.

Para voltar ao modo sem inferência, selecione `demo` para o tenant da cópia de QA no painel Brevia. O teste automatizado `tests/postgres-ui.cjs` exige demo; não o execute com a expectativa de chamadas reais.
