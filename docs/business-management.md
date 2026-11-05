# Gestão Brevia

O admin Brevia tem a área **Projetos e contratos**. Os registros reais ficam no banco, separados por cliente: contato e notas internas, projetos, contratos, lançamentos de horas e atualizações com data/responsável. Clientes comuns não acessam a API de gestão. Não há contratos ou horas fictícios.

Cada contrato corresponde a uma vigência e franquia. O orçamento soma horas incluídas e acumuladas. O consumo soma o saldo inicial documentado e as atividades posteriores. Não há renovação automática: cada ciclo pode ser cadastrado como um contrato, encerrando o anterior. Saldo inicial exige data de corte e explicação; atividades anteriores ao corte são recusadas para evitar dupla contagem. O filtro de horas mostra os lançamentos detalhados, e o contrato exibe o consumo completo.

As instruções gerais continuam em **Configurações → Instruções**. **Instruções por papel** edita orientações existentes, somente para o tenant selecionado. Criar papéis ou liberar permissões continua sendo trabalho de engenharia. Texto não libera ferramentas. `administrador` só pode ser atribuído pela equipe Brevia.

## Relatório pela Lumi

O serviço externo `services/brevia` expõe `GET /contracts` e `POST /reports/projects`, na porta local 8005. A Lumi chama o contrato `consultar_projetos_contratos` pelo mecanismo HTTP existente; nome e argumentos são escolhidos pelo modelo. SQL e escopo nunca são gerados pela IA.

`business_report_grants` define escopo `own` ou `all`, por tenant e papel. A integração exige chave exclusiva do tenant e revalida conversa, contato, papel e permissão no banco antes de consultar. Gestor consulta apenas o próprio cliente. O administrador Brevia pode consultar todos os clientes cadastrados ou um deles. Não são enviados notas internas do cadastro, credenciais, mensagens de clientes, custos ou relatórios de velocidade. Chamadas entram em `feature_calls` com parâmetros, resultado e duração, como as outras ferramentas. O relatório limita o contexto enviado ao modelo, sinalizando truncamento sem inventar os dados omitidos.

A ativação do chat de gestão restringe o tenant da equipe ao papel administrador, sem abrir a simulação pública para clientes. Essa política fica no banco e não pode ser alterada pelas instruções.

O botão **Conversar com a Lumi** cria uma conversa com papel administrador a partir do login Brevia. Além do token do simulador, essa conversa exige a sessão autenticada do mesmo operador; sair da conta revoga o acesso. O simulador público continua criando contatos com papel cliente.

```powershell
python -m app.business_setup --tenant SLUG_EQUIPE --role administrador --scope all --enable-lumi
python -m app.business_setup --tenant SLUG_CLIENTE --role gestor --scope own
.\scripts\start-brevia-tools.ps1 -PythonPath CAMINHO_PYTHON
```

Os comandos criam somente permissões e o contrato da ferramenta. Os nomes de clientes, contratos e regras de negócio não ficam no código. As chaves ficam em `%LOCALAPPDATA%\Lumi\tools.env` e `brevia-tools.env`, fora do repositório. O admin continua na porta 8000; o serviço 8005 não deve ser publicado no túnel dos canais.

## Importação do Notion

A conexão do Notion neste chat serve para ler as páginas autorizadas. Não é uma conexão permanente da Lumi ao Notion. Importamos uma seleção revisada das informações de gestão para o banco, preservando o link de origem. Credenciais e anotações pessoais encontradas nas páginas não são importadas para o contexto do gestor. Divergências entre uma planilha e um fechamento narrativo devem ser conciliadas e descritas, sem criar atividades ou datas fictícias.

`python -m app.business_import --tenant SLUG --actor-email EMAIL --file CAMINHO_JSON` importa registros normalizados na ordem projeto, contrato, horas e histórico. Cada registro tem `kind`, `source_url`, `data` e, quando necessário, `project_source` ou `contract_source`. A importação é transacional e idempotente pela origem. Se um registro importado for editado no admin, uma nova importação sinaliza conflito em vez de sobrescrever a edição. Os arquivos de trabalho com dados reais ficam fora do Git. Não há sincronização automática ou alteração do Notion.

Validação: `python -m unittest tests.test_business tests.test_business_import tests.test_tools tests.test_console tests.test_onboarding`.
# Simulações e clientes de gestão

Na página Conversas de cada empresa, os botões Simular cliente, Simular gestor ou Simular administrador são calculados a partir dos papéis e concessões do banco. `POST /api/admin/simulations` exige sessão do operador; o papel não pode ser escolhido na rota pública. O token da simulação continua exigindo a sessão do operador que a criou. O administrador global exige acesso Brevia. Um gestor do Rincão consulta somente o Rincão; um cliente não recebe o contrato de relatórios.

Nesta instalação a Brevia permite `cliente` e `administrador`, sem e-commerce ou ferramentas de dados do Rincão. O administrador usa a ferramenta externa de gestão com escopo global. A Brevia pode ser configurada no admin e usar imagens próprias; nenhuma imagem ou contexto do Rincão foi copiado. Estância e Abiquifi foram cadastradas para gestão com a Lumi desativada e sem novos logins.

A importação revisada de 31/10/2026 acrescentou os projetos da Estância e da Abiquifi a partir do Notion, preservando fontes, datas, limitações e distinção entre planos e entregas confirmadas. A Estância tem seis projetos e o contrato de outubro com 20h consumidas de 20h; os tempos de 28/10 estão identificados como aproximados. A Abiquifi tem o Companies Portfolio, contrato de desenvolvimento de R$ 25 mil e informação de mensalidade futura no contexto do projeto, sem cobrança recorrente criada. Credenciais e notas pessoais da origem não foram importadas. A importação não altera o Notion.


A seleção do cliente no relatório usa o nome, slug ou ID dentro do escopo já autorizado. A comparação ignora acentos, capitalização e pontuação e reconhece o nome cadastrado dentro de um nome mais completo. Isso permite consultar “Clube Rincão” quando o cadastro é “Rincão”, sem conceder ao gestor acesso a outros tenants.
