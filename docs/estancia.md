# Estância na Lumi

O tenant `estancia` aproveita o cadastro existente de projetos, com identidade, instruções e 18 itens de conhecimento originalmente importados para o SQLite da Lumi, depois preservados no PostgreSQL da V3 HML e PROD. O conteúdo original e credenciais ficam fora do repositório. Em HML, preços antigos não validados foram retirados dos textos ativos em 09/11/2026; produção não recebeu essa revisão. As ferramentas de catálogo têm prioridade quando habilitadas. Papéis cliente, gestor e atendente. Há objetivos iniciais de nome e motivo do contato, editáveis no admin.

Em 09/11/2026, o WhatsApp terminado em 5705 foi vinculado à Estância somente na V3 HML, com override específico confirmado na Meta. O usuário confirmou funcionamento, e o banco registrou respostas entregues e lidas. O usuário confirmou o Instagram `@testebrev`; o receptor HML está preparado, mas o vínculo depende das credenciais e do acesso ao app dos testes do Isaque, indisponíveis nesta sessão. PROD continua sem canais da Estância. As ferramentas de negócio da VM estão desligadas. Configuração, verificações técnicas, limitações e retorno estão em [homologação na VM](homologacao-vm.md#estância--whatsapp-5705).

A revisão de conteúdo de 09/11/2026 corrigiu identidade e instruções para não afirmar atendimento exclusivo no simulador, compra habilitada ou transferência automática para a equipe. Cinco itens foram revisados, mantendo os 18 IDs: passaportes, adicionais, evento de domingo, alimentação e compra. Foram cadastradas quatro fotos oficiais, com descrição e orientação de uso: lago, caiaque, trilha e salão de eventos. Arquivos e fontes estão no manifesto privado da VM. As imagens e sua inclusão no catálogo do prompt foram verificadas; seleção pelo modelo e entrega de foto no WhatsApp ainda dependem de teste real após essa atualização. Não houve alteração de código nem ativação de integrações.

## Integrações externas

O serviço `services.estancia.api` (8006) consulta somente a agenda, com SQL fixo, transação somente leitura, autorização por tenant e papel e credencial exclusiva. O e-commerce usa endpoints `/api/lumi/{catalog,quote,purchase,status}` no site de homologação local (3002), com contratos em `services/estancia/commerce_contracts.py`. Nenhuma ferramenta de faturamento do Rincão é atribuída à Estância. A origem do faturamento depende de definição com Lucas. Pesquisa e previsão usam o serviço web existente, com credencial e cache separados por tenant.

## Homologação

O banco real fornecido foi lido para gerar uma cópia isolada `clestancia_sistema_lumi_test` na mesma infraestrutura do site. Nenhuma alteração foi aplicada ao banco real ou ao site publicado. A aplicação de homologação roda no notebook, em `%LOCALAPPDATA%\Lumi\estancia-site-hml`, e usa o túnel SSH verificado na porta 15432. `estancia-tools.env`, a `.env.local` dessa cópia e as credenciais Cielo ficam privados. O gateway Cielo usa as credenciais existentes autorizadas: um pagamento confirmado pode cobrar de verdade, mesmo que o pedido esteja no banco de homologação. O agente testou preparação e abertura do checkout, sem cobrar.

Os endpoints Lumi do site só funcionam com flag explícita e banco terminado em `_lumi_test`; ficam bloqueados no banco real. O site reutiliza seu cálculo e criação normal de pedidos e vouchers pendentes, registra `origem_checkout=lumi` sem alterar `tpcompra` e cria perfil incompleto sem senha conhecida para novos CPFs. Um token aleatório permite pagar somente o pedido correspondente, sem conceder login na conta do usuário. O cadastro completo posterior de convidados ainda deve ter seu fluxo de verificação de titularidade definido antes de produção.

## Rodar

Inicie o túnel com `scripts/start-rincao-tools.ps1` (aproveita o acesso SSH já configurado), o serviço de agenda com `scripts/start-estancia-tools.ps1` e o site de teste com `scripts/start-estancia-site-hml.ps1`. Pesquisa, gestão, handover e API principal continuam nos serviços existentes. O conteúdo pode ser importado de um arquivo revisado pelo comando `python -m app.tenant_content --tenant estancia --file CAMINHO`; ele atualiza os três blocos no banco e não altera canais ou logins.

O HML não tem credenciais de entrega de ingressos, SMTP ou WhatsApp do site. A página de pagamento usa a Cielo existente; a conclusão bancária e as entregas externas não foram executadas pelo agente. O gestor só consulta os próprios projetos; administrador Brevia continua com acesso aos projetos autorizados.
