# Estância na Lumi

O tenant `estancia` aproveita o cadastro existente de projetos, com identidade, instruções e 18 itens de conhecimento importados para o SQLite da Lumi. O conteúdo original e credenciais ficam fora do repositório. As pendências do material não entram na base; preços antigos aguardam validação, e as ferramentas de catálogo têm prioridade. Papéis cliente, gestor e atendente; sem WhatsApp ou Instagram vinculados. Há objetivos iniciais de nome e motivo do contato, editáveis no admin.

## Integrações externas

O serviço `services.estancia.api` (8006) consulta somente a agenda, com SQL fixo, transação somente leitura, autorização por tenant e papel e credencial exclusiva. O e-commerce usa endpoints `/api/lumi/{catalog,quote,purchase,status}` no site de homologação local (3002), com contratos em `services/estancia/commerce_contracts.py`. Nenhuma ferramenta de faturamento do Rincão é atribuída à Estância. A origem do faturamento depende de definição com Lucas. Pesquisa e previsão usam o serviço web existente, com credencial e cache separados por tenant.

## Homologação

O banco real fornecido foi lido para gerar uma cópia isolada `clestancia_sistema_lumi_test` na mesma infraestrutura do site. Nenhuma alteração foi aplicada ao banco real ou ao site publicado. A aplicação de homologação roda no notebook, em `%LOCALAPPDATA%\Lumi\estancia-site-hml`, e usa o túnel SSH verificado na porta 15432. `estancia-tools.env`, a `.env.local` dessa cópia e as credenciais Cielo ficam privados. O gateway Cielo usa as credenciais existentes autorizadas: um pagamento confirmado pode cobrar de verdade, mesmo que o pedido esteja no banco de homologação. O agente testou preparação e abertura do checkout, sem cobrar.

Os endpoints Lumi do site só funcionam com flag explícita e banco terminado em `_lumi_test`; ficam bloqueados no banco real. O site reutiliza seu cálculo e criação normal de pedidos e vouchers pendentes, registra `origem_checkout=lumi` sem alterar `tpcompra` e cria perfil incompleto sem senha conhecida para novos CPFs. Um token aleatório permite pagar somente o pedido correspondente, sem conceder login na conta do usuário. O cadastro completo posterior de convidados ainda deve ter seu fluxo de verificação de titularidade definido antes de produção.

## Rodar

Inicie o túnel com `scripts/start-rincao-tools.ps1` (aproveita o acesso SSH já configurado), o serviço de agenda com `scripts/start-estancia-tools.ps1` e o site de teste com `scripts/start-estancia-site-hml.ps1`. Pesquisa, gestão, handover e API principal continuam nos serviços existentes. O conteúdo pode ser importado de um arquivo revisado pelo comando `python -m app.tenant_content --tenant estancia --file CAMINHO`; ele atualiza os três blocos no banco e não altera canais ou logins.

O HML não tem credenciais de entrega de ingressos, SMTP ou WhatsApp do site. A página de pagamento usa a Cielo existente; a conclusão bancária e as entregas externas não foram executadas pelo agente. O gestor só consulta os próprios projetos; administrador Brevia continua com acesso aos projetos autorizados.
