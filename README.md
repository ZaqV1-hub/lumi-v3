# Lumi v3

A versão inicial sincronizada de homologação e produção foi `20261107-tenant-ai-r3`; as releases atuais são identificadas pelo commit em `deployment-state.json` de cada ambiente. Push em `develop` publica homologação e em `main` publica produção, após os testes do [deploy automático](docs/deploy-automatico.md); veja [versionamento e publicação](docs/versionamento-e-publicacao.md). O WhatsApp Rincão de produção aguarda a verificação Meta e ainda não foi transferido. Operação de homologação: [operação, acesso privado, gateway Codex, WhatsApp e retorno](docs/homologacao-vm.md). A VM usa PostgreSQL. Cada tenant escolhe Codex local/gateway ou OpenAI API com chave própria, em Configurações → Inteligência artificial. Veja [configuração, migração e proteção de credenciais](docs/ia-por-tenant.md).

Para desenvolver ou assumir a manutenção, leia [a passagem para a equipe](docs/desenvolvimento-e-passagem.md) e as regras do [AGENTS.md](AGENTS.md). Elas explicam configuração de tenants, serviços externos, alterações no núcleo e testes. O núcleo pode ser mantido pelos desenvolvedores autorizados; a divisão em serviços não restringe todas as correções a Isaque. Os exemplos de instalação abaixo não são um inventário atualizado dos logins e canais ativos: confira a configuração do ambiente antes de executar.

Laboratório local multi-tenant com admin autenticado e simulador de cliente separado. O admin usa o HTML e o CSS originais enviados como referência, incluindo as fontes Poppins e Inter. Login, conversas e formulários de personalidade, conhecimento e imagens estão conectados ao banco. O dashboard mostra contagens reais do simulador; estatísticas fictícias do protótipo foram substituídas. As fontes usam o mesmo Google Fonts do HTML original e precisam de conexão para o primeiro carregamento.

## Rodar no Windows

O acesso único está em [http://127.0.0.1:8000/admin](http://127.0.0.1:8000/admin). `/console` apenas redireciona para `/admin`: o papel salvo no banco abre o console Brevia ou o painel restrito do cliente. Nesta instalação, `isaque@brevia.company` é o acesso da equipe e `isaque@cluberincao.com.br` é o administrador do Rincão. As senhas fornecidas foram configuradas no banco somente como hash, sem gravá-las no repositório. O console tem visão geral, tenants, problemas, acessos, custos e auditoria. Documentação de funcionamento e provisionamento local em [docs/console.md](docs/console.md).

Python 3.11 ou superior e Codex CLI instalado e autenticado são necessários. Execute no PowerShell dentro da pasta do projeto:

```powershell
$venv = Join-Path $env:LOCALAPPDATA "Lumi-venv"
python -m venv $venv
& "$venv\Scripts\Activate.ps1"
pip install -r requirements.txt
uvicorn services.handover:app --host 127.0.0.1 --port 8001
```

Mantenha esse terminal aberto para o serviço falso de handover. Em outro terminal, ative o mesmo ambiente e inicie a Lumi:

```powershell
$venv = Join-Path $env:LOCALAPPDATA "Lumi-venv"
& "$venv\Scripts\Activate.ps1"
uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

Admin: <http://127.0.0.1:8000/admin>. Rincão: `isaque@rincao.local`, nome Isaque. Breve: `ana@breve.local`, nome Ana. A senha fictícia de ambos é `demo1234`. As senhas são armazenadas com PBKDF2 e salt; sessões usam cookie HttpOnly, SameSite e expiram em 24 horas.

Simulador do cliente Rincão: <http://127.0.0.1:8000/chat/rincao>. Breve: <http://127.0.0.1:8000/chat/breve>. Abra o simulador em outra aba, informe seu nome e converse. O cliente não usa o login do admin. Cada conversa recebe um token aleatório que permite acessar apenas aquela conversa. O admin identifica a empresa pelo login, nunca por um tenant enviado pela IA ou pelo navegador.

## Contagem do dashboard

Atendimentos conta conversas distintas que receberam mensagem do cliente no período selecionado, mesmo que tenham sido abertas antes. Várias mensagens na mesma conversa contam um atendimento; WhatsApp e Instagram são conversas independentes. Mensagens recebidas, divisão por canal e situação usam esse mesmo conjunto. Novos atendimentos conta conversas criadas no período, e Conversas armazenadas mostra o histórico completo do tenant. As datas usam o fuso America/Sao_Paulo.

## Dados e banco

SQLite continua disponível sem configuração. Os dados ficam em `%LOCALAPPDATA%\Lumi\lumi.db`; `LUMI_DATA_DIR` muda essa pasta. `DATABASE_URL` tem precedência e permite usar PostgreSQL. Para desenvolvimento com PostgreSQL 17, importação do backup sanitizado e configuração de IA, siga [o guia local](docs/desenvolvimento-local.md). O Compose usa um banco exclusivo na porta local 55439 e exige senha privada; não reutilize um volume de outro ambiente.

As tabelas são criadas na inicialização. Novas tabelas desta etapa são adicionadas sem apagar os dados anteriores. Ainda não há sistema de migrations para alterar colunas existentes. Os exemplos antigos permanecem no banco, mas não são exibidos nos novos logins.

`demo/tenants.json` contém somente os dados fictícios de instalação. O seed insere Rincão e Breve uma vez e não sobrescreve edições. Defina `LUMI_SEED_DEMO=false` para uma importação sanitizada não receber contas ou conteúdo de demonstração. Instruções, personalidade, conhecimento, contatos, conversas, usuários e contratos de funcionalidades são lidos do banco durante o uso. Não há lógica específica do Rincão no atendimento.

## Atendimento humano

Um pedido explícito como “quero falar com um humano” é detectado pelo código, mas passa pelo modelo para gerar a resposta com a personalidade do tenant. A fala é salva e colocada na fila do canal antes da chamada ao serviço de handover, sem aviso fixo nem pergunta de confirmação. Outras mensagens passam pelo modelo, que pode retornar a ação de handover somente para pedidos claros. O servidor valida a funcionalidade e o papel do contato. O handover tem seu fluxo próprio. Consultas externas usam contratos HTTP e parâmetros validados, conforme a seção de ferramentas abaixo.

O contrato fica em `tenant_features`, com descrição, endpoint e papéis autorizados. `services/handover.py` roda em processo separado e recebe chamadas HTTP autenticadas. `HANDOVER_SECRET` deve ter o mesmo valor nos dois processos; o padrão é uma credencial fictícia local. O serviço não importa código da Lumi. Cada chamada externa é registrada em `feature_calls` com tenant, conversa, parâmetros, resultado e duração.

Ao pedir atendimento, a conversa muda para `aguardando` antes da chamada externa. A notificação aparece no admin e a Lumi para imediatamente. O menu Conversas mostra a quantidade de pedidos aguardando atendimento do tenant, atualizada a cada 1,5 segundo em todas as telas. Ao assumir um pedido, ele sai dessa contagem; quando não há pedidos, o contador fica oculto. Se o serviço externo falhar, o pedido continua visível no admin e o erro fica registrado. Ao clicar em “Assumir atendimento”, o estado vira `humano`. A resposta usa o nome do usuário autenticado, mostrado em negrito ao cliente. A conversa permanece aberta. O cliente continua enviando mensagens, e a Lumi não responde. Uma resposta de IA que estava em andamento é descartada se o estado mudou antes de gravá-la.

O cliente recebe um aviso com o nome de quem assumiu. O botão “Sair e devolver à Lumi” avisa que o operador saiu e devolve as próximas mensagens à IA. Outro operador não pode responder ou liberar um atendimento já assumido. Uma revisão por conversa impede que respostas antigas sejam gravadas mesmo quando o humano assume e sai antes de a inferência terminar.

## Imagens

Em Configurações > Imagens, cadastre nome, descrição, instrução de quando usar e arquivo PNG, JPG ou WebP até 5 MB e 16 megapixels. As imagens são validadas, convertidas para JPEG sem metadados e armazenadas no banco por tenant. É possível editar a imagem ou os textos, ampliar e excluir. A exclusão desativa a imagem para novos envios, preservando o histórico.

O modelo recebe somente os identificadores, descrições e instruções das imagens habilitadas daquele tenant. Quando escolhe enviar, o código valida o identificador e grava a imagem na mensagem. O simulador e o admin exibem a imagem no histórico. A API do cliente exige o token da conversa e só libera imagens que já foram enviadas nela. Seleções de imagem ficam registradas em `feature_calls`. A mídia faz parte do canal de conversa; funcionalidades de negócio continuam usando seus serviços externos.

## Ordem das mensagens

O WhatsApp e o Instagram registram cada mensagem e reservam sua posição por contato antes de baixar imagens ou áudios. O processamento segue essa ordem, incluindo download, leitura da imagem, transcrição, ferramentas e gravação da resposta. Um texto seguinte aguarda a mídia anterior e recebe o histórico da resposta anterior. Outros contatos continuam independentes. Falhas liberam a próxima mensagem da fila; os limites de anti-spam continuam sendo aplicados na admissão, antes do trabalho lento. Esta fila de execução é local ao processo e não substitui uma fila distribuída para múltiplos workers.

## Anti-spam

O limite padrão é de três mensagens em andamento por contato, ajustável entre 1 e 10 nas configurações. As mensagens admitidas recebem respostas individualmente e são processadas uma de cada vez por contato. Enquanto o limite está ocupado, a primeira mensagem excedente gera um pedido para aguardar, a segunda avisa sobre o bloqueio e a terceira bloqueia. Depois disso, novas mensagens são ignoradas sem novas respostas. As três mensagens admitidas antes do bloqueio ainda terminam de ser respondidas.

Se a fila esvaziar antes do bloqueio, os avisos são zerados. O bloqueio persiste no banco até o admin usar “Desbloquear contato” na conversa. Reiniciar o servidor limpa a contagem de pedidos interrompidos, mas preserva os bloqueios. O simulador permite enviar mensagens enquanto espera, para testar a regra. “Nova conversa” no simulador cria outro contato fictício; no WhatsApp a identidade deverá vir do número do remetente. Esta execução local usa um único processo da aplicação; antes de múltiplos workers será necessário mover a fila e seus bloqueios de execução para um mecanismo compartilhado.

## Contexto e tempo de resposta

O prompt usa identidade e funcionalidades autorizadas, personalidade e conhecimento do tenant, seguidos do histórico recente. O conhecimento textual ainda é incluído como contexto completo, sem busca vetorial. Configurações permitem editar instruções, personalidade, conhecimento e imagens. O onboarding é configurável por tenant em Configurações > Onboarding; consulte a seção abaixo.

## WhatsApp de teste

O receptor da Cloud API, o vínculo por número e a entrega de textos e imagens estão implementados. A ativação depende de configurar o aplicativo e o número de teste na Meta. Consulte [a configuração do WhatsApp](docs/whatsapp.md). O receptor roda na porta 8002, separada do admin, e é o único serviço que deve ser exposto pelo túnel HTTPS.

O provider fica em `app/providers.py`. Provider, modelo e chave são escolhidos por tenant no painel Brevia; não há `OPENAI_API_KEY` nem seleção global. `codex` executa o CLI local, `codex_gateway` usa o gateway configurado no servidor, `openai` usa a Responses API e `demo` produz resposta fixa sem inferência. Tenant sem configuração falha fechado, sem usar credencial de outro. Ferramentas continuam validadas pelo núcleo. Leia [IA por tenant](docs/ia-por-tenant.md).

Este laboratório usa dados fictícios e serve apenas em localhost. O Codex CLI possui ferramentas locais; a pasta temporária e o modo de leitura não garantem isolamento completo do computador. Antes de dados reais, precisamos de um provider sem acesso ao sistema de arquivos ou um ambiente isolado para o processo, além de credenciais e operação adequadas à implantação.

## Verificar

```powershell
pip install -r requirements-dev.txt
python scripts/test-local.py
```

O teste confere login, acesso entre tenants, contexto, handover, avisos de entrada e saída, nome do atendente, descarte de respostas antigas, upload e envio de imagens e proibição de imagem de outro tenant. A regra de spam é verificada com três requisições simultâneas, dois avisos, bloqueio silencioso posterior e desbloqueio pelo admin. O Codex também foi testado com a saída estruturada de seleção de imagem. O serviço HTTP de handover foi verificado com os dois processos locais.


## Onboarding e perfil

Em Configurações > Onboarding, adicione objetivos com título, descrição, obrigatoriedade e, quando pertinente, a opção de atualizar o nome do contato. Os objetivos dizem quais informações descobrir; a personalidade e as preferências de tom, tamanho e estilo do tenant orientam como conduzir toda a conversa, inclusive acolhimento e perguntas. Títulos não são frases para copiar, não há pergunta curta obrigatória nem roteiro de apresentação. A Lumi aproveita informações espontâneas e integra o que falta ao atendimento, preservando o pedido original. Recusas e perguntas ignoradas não bloqueiam ajuda: não deve repetir a mesma pergunta em mensagens consecutivas e deixa de sugeri-la após duas tentativas.

O nome vindo do WhatsApp ou do simulador é apenas identificação do canal, nunca confirmação de nome para o onboarding. O perfil confirma informações fornecidas pela própria pessoa. O modelo sugere valores com citações da mensagem atual; o servidor exige que o valor apareça na evidência e que a evidência apareça na mensagem. Objetivos de outro tenant e valores sem evidência são descartados. Essa validação reduz invenções, mas a interpretação semântica ainda depende do modelo.

Objetivos ficam em `onboarding_objectives`, valores e tentativas em `profile_values`, e a conclusão persistente em `contact_profiles`. As tabelas são adicionadas sem alterar as existentes. O perfil aparece na conversa do admin. Uma vez concluído, não se reinicia automaticamente quando os objetivos são editados. Handover e anti-spam continuam tendo precedência. Clientes antigos sem perfil confirmado passam pelo onboarding no próximo contato; nenhum nome anterior é confirmado automaticamente.

Para instalar o exemplo do Rincão uma única vez, depois de iniciar a aplicação, execute `python -m app.onboarding_setup --tenant rincao --file demo/rincao-onboarding.json`. O comando recusa sobrescrever objetivos existentes. Esses exemplos ficam no banco e podem ser editados pelo admin. A regra de identidade do WhatsApp mantém o perfil no contato nas próximas mensagens; uma nova conversa do simulador cria um novo contato de teste.


## Ferramentas externas e papel do contato

A etapa local de consultas do Rincão está descrita em [docs/rincao-tools.md](docs/rincao-tools.md). O serviço independente consulta a agenda/preços do site de teste e o faturamento de eventos do buffet. Em Conversas, o admin pode alterar o papel entre Cliente, Gestor e Atendente; somente Gestor recebe a ferramenta financeira. Credenciais e consultas aos bancos ficam no serviço externo, fora do núcleo da Lumi. Esta etapa permanece local, sem commit/publicação até a revisão do usuário.


## Compra de ingressos (etapa local)

Cotação, pedido pelo CPF e página própria integrada à API E-commerce Cielo estão em [docs/rincao-commerce.md](docs/rincao-commerce.md). Pix, crédito e débito são oferecidos na página baseada no HTML fornecido, nunca no chat. Débito exige autenticação 3DS do banco e é à vista. A confirmação no gateway e o registro no sistema precedem a liberação dos vouchers. As credenciais fornecidas usam Cielo de produção, mesmo com o banco do site em teste. A conclusão segura de cadastro convidado está publicada somente no site HML. O checkout novo foi verificado em desktop e celular; testes bancários de débito usaram respostas simuladas, sem cobrança real.

## Pesquisa pública e previsão do tempo

O serviço externo em `services/web_tools/` roda em localhost:8004 e oferece pesquisa pública com leitura das páginas e previsão meteorológica por cidade/data. A Lumi responde com os dados encontrados; links públicos são complementares e URLs técnicas de meteorologia não entram na resposta da ferramenta. Está habilitado apenas para o Rincão nesta instalação, pelo mesmo fluxo usado no admin, WhatsApp e Instagram. Inicie com `scripts/start-web-tools.ps1 -PythonPath CAMINHO_DO_PYTHON`. Configuração, isolamento, limites e testes estão em [docs/web-tools.md](docs/web-tools.md). Não usa outra chamada de IA para fazer a busca.

## Receber imagem e áudio; medir consumo

O simulador permite anexar imagens e áudios e gravar pelo microfone. A Lumi entende a imagem ou a transcrição local e responde em texto. Os anexos ficam privados por tenant e conversa e aparecem no admin para o operador. Limites: imagens até 5 MB/16 MP; áudios até 12 MB/dois minutos. A transcrição usa faster-whisper local e não consome chamada ao Codex; o primeiro uso baixa/carrega o modelo. Detalhes e testes estão em [docs/incoming-media-and-cost.md](docs/incoming-media-and-cost.md).

A tela de `/chat/{tenant}` usa o visual do HTML de referência, sem respostas ou mensagens de demonstração. O clipe seleciona uma imagem ou áudio e mostra uma prévia; nada é enviado até clicar na seta. A legenda e a imagem seguem juntas na mesma mensagem. Também é possível colar ou arrastar a imagem, removê-la antes do envio e tentar novamente sem perder a legenda se o upload falhar. Sem texto ou anexo, o botão vira microfone; a gravação pode ser cancelada e termina em até dois minutos. “Nova conversa” inicia outro contato de teste, mantendo o histórico anterior no admin.

O HTML do simulador é servido sem cache, com URLs de CSS e JavaScript versionadas automaticamente pelo conteúdo. Assim, uma atualização do layout não reutiliza scripts antigos do navegador. O teste de interface cobre também essa situação e a retomada de uma sessão existente após recarregar.

**Consumo e velocidade** é uma página no menu do tenant, abaixo de Configurações, exclusiva da equipe Brevia. O usuário do cliente vê apenas Dashboard, Conversas e Configurações, e a API também bloqueia o relatório para esse login. A página tem filtros de período/modelo, gráficos diários, comparativo por modelo, chamadas recentes e resumo CSV. Ela mostra tokens medidos, modelo, tempo e custo de API em USD. Codex local e transcrição local aparecem com custo de API zero; um provider de API passará a contabilizar o custo quando utilizado. O consumo da assinatura Codex é separado desse valor. O padrão agora é GPT-6.1 Terra com esforço low e um perfil de atendimento mais enxuto, preservando o contexto completo do tenant. O modelo é escolhido por tenant no painel e passa a valer na próxima inferência, sem reinício. No gateway, ele também precisa estar na lista de modelos permitidos. A comparação e as limitações estão em [docs/provider-cost.md](docs/provider-cost.md). O fluxo de escola aguarda o formulário fornecido pelo usuário, e o WhatsApp continua pausado. O código desta etapa está incluído na sincronização das branches; a ativação dos canais depende da configuração e do aceite de cada ambiente.

## Gestão Brevia e instruções por papel

O admin Brevia também reúne clientes, projetos, contratos, histórico e horas de manutenção. A consulta pela Lumi usa uma ferramenta externa com escopo por papel; gestores consultam somente seus próprios projetos. As instruções por papel ficam em Configurações. Veja [gestão Brevia](docs/business-management.md) para permissões, execução e importação revisada do Notion.

## Instagram

O adaptador do Instagram e a preparação da conta na Meta estão descritos em [docs/instagram.md](docs/instagram.md). Configurar o vínculo no banco não significa que a conta já está autorizada ou recebendo mensagens; confirme o teste real antes de disponibilizá-la.

Simulações de cliente e gestor ficam na página Conversas do tenant; a Brevia também oferece a simulação de administrador. Papéis privilegiados exigem o login do operador durante toda a simulação. O administrador global consulta projetos e contratos de todos os clientes; o gestor fica restrito à própria empresa. Os registros de Estância e Abiquifi importados do Notion ficam no banco, com a Lumi desativada nesses clientes e sem novos logins. Consulte [gestão e simulações](docs/business-management.md).

Configurações → Comentários Instagram permite editar no banco as instruções das respostas públicas. Esse canal usa uma única inferência e nenhuma ferramenta de negócio. As respostas automáticas só podem ser ativadas depois de autorizar comentários e assinar esse evento na Meta. Consulte [integração do Instagram](docs/instagram.md).

## Tenant Estância

A configuração inicial e a integração do site de homologação estão documentadas em [docs/estancia.md](docs/estancia.md). Identidade, instruções e conhecimento ficam no banco do tenant; os contratos do e-commerce são externos e independentes dos dados do Rincão.

## Desenvolvimento de integrações em separado

O núcleo de atendimento permanece em `app/` e `web/`. O projeto separado para desenvolvimento de ferramentas pode ser preparado com `python scripts/export-integrations.py --output PASTA_VAZIA`; use `--estancia-site CAMINHO` para incluir os adaptadores disponíveis do site. Ele contém apenas os serviços independentes, contratos, exemplo e simulador HTTP, sem núcleo, banco ou credenciais. O serviço de gestão Brevia ainda depende de modelos internos e não é exportado como independente. A versão em execução não é substituída automaticamente. Leia [arquitetura e colaboração](docs/arquitetura-e-colaboracao.md) e o [contrato de integrações](docs/contrato-de-integracoes.md). A liberação ao cliente acontece somente após a revisão e os testes de Isaque; esta etapa não configura aprovação de branch no GitHub.
