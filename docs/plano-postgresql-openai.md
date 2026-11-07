# PostgreSQL e OpenAI API — execução local

Registro histórico da etapa de 05/11/2026. A configuração atual é por tenant, e os deploys posteriores estão em [passagem operacional](plano-homologacao-vm.md). O fluxo de branches está em [versionamento e publicação](versionamento-e-publicacao.md).

Escopo aprovado em 05/11/2026: importar a cópia sanitizada em PostgreSQL local exclusivo, manter Codex e adicionar OpenAI API selecionável, testar aplicação e documentar execução. Sem implantação, commit/push, cobranças, mensagens externas ou alteração da VM.

## Decisões

- Preservar ZIP e SQLite de origem fora do Git. Não incorporar conteúdo de empresas nos testes ou código.
- Usar PostgreSQL 17, banco novo, usuário próprio e portas locais. Não reaproveitar bancos de outro projeto.
- Importar somente configuração sanitizada, com estados operacionais desativados. Exigir destino vazio, transação e validação de tipos, relações, contagens e imagens. Tabelas legadas vazias podem ser omitidas explicitamente; conteúdo desconhecido impede a importação.
- Criar o schema inicial a partir dos modelos atuais. Isto não é migração de colunas de bancos existentes; futuras mudanças exigem uma migração própria. Retorno desta importação: voltar à configuração anterior e preservar ambos os bancos, sem apagar a origem.
- Selecionar `codex`, `openai` ou `demo` por ambiente, sem fallback. OpenAI usa Responses API com saída estruturada, modelo explícito e chave privada. Testar transporte simulado; execução paga depende de autorização específica.
- Desabilitar seed de demonstração na cópia importada. Criar acessos exclusivamente locais e testes com identidade fictícia. Não habilitar canais/ferramentas recebidos.

## Execução e verificação

- [x] Conferir versão, hashes, integridade, relações e sanitização do pacote.
- [x] Preparar Python e PostgreSQL isolados; registrar baseline dos testes existentes.
- [x] Implementar e testar importação com destino vazio, preservação de dados e rollback.
- [x] Implementar e testar OpenAI API, imagens, tool calls, erros e medição; preservar Codex.
- [x] Validar a aplicação no PostgreSQL com isolamento entre empresas, login, configurações, imagens e simulador.
- [x] Abrir painel/simulador local no navegador e executar testes de regressão relevantes.
- [x] Revisar mudanças independentemente, corrigir achados pertinentes e documentar configuração/retorno.

## Estado e recursos

Código de partida: `2a844f4`. Pacote compatível com esse commit, conferido pelo verificador revisado da equipe. Python 3.11.17 em `.venv` e PostgreSQL 17.11 nativo, restrito a `127.0.0.1:55439`. Dados privados em `~/Library/Application Support/LumiV3-Dev`, fora do versionamento. ZIP e SQLite mantiveram seus hashes originais após a importação.

Importação concluída em `lumi_v3_dev`: 53 tabelas; seis tenants, 43 itens de conhecimento e duas imagens preservados, com comparação de todos os registros importados. Ferramentas, canais e runtime dos tenants desativados. Acesso fictício provisionado separadamente. A cópia `lumi_v3_qa` possui somente um tenant ativo para o simulador; permanece sem ferramentas habilitadas ou canais cadastrados.

Servidor local de QA em `127.0.0.1:8011`, provider Codex local ativado após validação autorizada, arquivo privado `qa.env`. PostgreSQL foi iniciado por `pg_ctl`, sem serviço automático. Reinício, acesso, configuração e retorno estão em [desenvolvimento-local.md](desenvolvimento-local.md).

Verificação final: 194 testes passaram, com PostgreSQL real e transports externos simulados; log local ignorado em `.data/tests-isolated.log`. Navegador passou por login, configurações e imagens recebidas, simulador, upload, persistência após recarregar e largura mobile, sem erros JavaScript. Screenshots em `.data/postgres-ui`, fora do Git. `git diff --check` passou. Revisão independente cobriu importador/provider e mudanças complementares; corrigido isolamento de `RINCAO_TOOLS_ENV`, com reprodução usando arquivo fictício. Corrigidos também dois defeitos de fixture preexistentes: adulteração de token eventualmente idêntica ao original e registro de contratos dependente da ordem de importação.

Após a etapa simulada, o usuário autorizou Codex local: conversa real validada no navegador com `gpt-6.1-terra`, duas respostas coerentes com conhecimento importado (aproximadamente 7 e 5 segundos), quatro mensagens persistidas e duas chamadas concluídas com tokens registrados no PostgreSQL. Histórico preservado após recarregar, sem erros JavaScript; ferramentas/canais seguem desligados. Evidência privada em `.data/codex-live-result.json` e `.data/postgres-ui/codex-live.png`. Não foram executados OpenAI API real, transcrição real, canais, integrações externas, cobrança de negócio, commit/push ou deploy. Implantação e migrations futuras continuam etapas separadas.
