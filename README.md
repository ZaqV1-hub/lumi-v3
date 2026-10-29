# Lumi v3

Laboratório local multi-tenant com admin autenticado e simulador de cliente separado. O admin usa o HTML e o CSS originais enviados como referência, incluindo as fontes Poppins e Inter. Login, conversas e formulários de personalidade, conhecimento e imagens estão conectados ao banco. O dashboard mostra contagens reais do simulador; estatísticas fictícias do protótipo foram substituídas. As fontes usam o mesmo Google Fonts do HTML original e precisam de conexão para o primeiro carregamento.

## Rodar no Windows

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

## Dados e banco

SQLite permite rodar sem Docker. Os dados ficam em `%LOCALAPPDATA%\Lumi\lumi.db`; `LUMI_DATA_DIR` muda essa pasta. Para Postgres, inicie Docker Desktop, rode `docker compose up -d db` e configure `DATABASE_URL=postgresql+psycopg://lumi:lumi_local@localhost:5432/lumi` antes de iniciar a Lumi. O Postgres ainda precisa ser validado neste computador.

As tabelas são criadas na inicialização. Novas tabelas desta etapa são adicionadas sem apagar os dados anteriores. Ainda não há sistema de migrations para alterar colunas existentes. Os exemplos antigos permanecem no banco, mas não são exibidos nos novos logins.

`demo/tenants.json` contém somente os dados fictícios de instalação. O seed insere Rincão e Breve uma vez e não sobrescreve edições. Instruções, personalidade, conhecimento, contatos, conversas, usuários e contratos de funcionalidades são lidos do banco durante o uso. Não há lógica específica do Rincão no atendimento.

## Atendimento humano

Um pedido explícito como “quero falar com um humano” segue diretamente para o contrato de handover, sem gastar uma inferência. Outras mensagens passam pelo modelo, que pode retornar a ação de handover somente para pedidos claros. O servidor valida a funcionalidade e o papel do contato. Há um contrato específico de handover nesta primeira versão; ainda não é um executor genérico de ferramentas ou MCP.

O contrato fica em `tenant_features`, com descrição, endpoint e papéis autorizados. `services/handover.py` roda em processo separado e recebe chamadas HTTP autenticadas. `HANDOVER_SECRET` deve ter o mesmo valor nos dois processos; o padrão é uma credencial fictícia local. O serviço não importa código da Lumi. Cada chamada externa é registrada em `feature_calls` com tenant, conversa, parâmetros, resultado e duração.

Ao pedir atendimento, a conversa muda para `aguardando` antes da chamada externa. A notificação aparece no admin e a Lumi para imediatamente. Se o serviço externo falhar, o pedido continua visível no admin e o erro fica registrado. Ao clicar em “Assumir atendimento”, o estado vira `humano`. A resposta usa o nome do usuário autenticado, mostrado em negrito ao cliente. A conversa permanece aberta. O cliente continua enviando mensagens, e a Lumi não responde. Uma resposta de IA que estava em andamento é descartada se o estado mudou antes de gravá-la.

O cliente recebe um aviso com o nome de quem assumiu. O botão “Sair e devolver à Lumi” avisa que o operador saiu e devolve as próximas mensagens à IA. Outro operador não pode responder ou liberar um atendimento já assumido. Uma revisão por conversa impede que respostas antigas sejam gravadas mesmo quando o humano assume e sai antes de a inferência terminar.

## Imagens

Em Configurações > Imagens, cadastre nome, descrição, instrução de quando usar e arquivo PNG, JPG ou WebP até 5 MB e 16 megapixels. As imagens são validadas, convertidas para JPEG sem metadados e armazenadas no banco por tenant. É possível editar a imagem ou os textos, ampliar e excluir. A exclusão desativa a imagem para novos envios, preservando o histórico.

O modelo recebe somente os identificadores, descrições e instruções das imagens habilitadas daquele tenant. Quando escolhe enviar, o código valida o identificador e grava a imagem na mensagem. O simulador e o admin exibem a imagem no histórico. A API do cliente exige o token da conversa e só libera imagens que já foram enviadas nela. Seleções de imagem ficam registradas em `feature_calls`. A mídia faz parte do canal de conversa; funcionalidades de negócio continuam usando seus serviços externos.

## Anti-spam

O limite padrão é de três mensagens em andamento por contato, ajustável entre 1 e 10 nas configurações. As mensagens admitidas recebem respostas individualmente e são processadas uma de cada vez por contato. Enquanto o limite está ocupado, a primeira mensagem excedente gera um pedido para aguardar, a segunda avisa sobre o bloqueio e a terceira bloqueia. Depois disso, novas mensagens são ignoradas sem novas respostas. As três mensagens admitidas antes do bloqueio ainda terminam de ser respondidas.

Se a fila esvaziar antes do bloqueio, os avisos são zerados. O bloqueio persiste no banco até o admin usar “Desbloquear contato” na conversa. Reiniciar o servidor limpa a contagem de pedidos interrompidos, mas preserva os bloqueios. O simulador permite enviar mensagens enquanto espera, para testar a regra. “Nova conversa” no simulador cria outro contato fictício; no WhatsApp a identidade deverá vir do número do remetente. Esta execução local usa um único processo da aplicação; antes de múltiplos workers será necessário mover a fila e seus bloqueios de execução para um mecanismo compartilhado.

## Contexto e tempo de resposta

O prompt usa identidade e funcionalidades autorizadas, personalidade e conhecimento do tenant, seguidos do histórico recente. O conhecimento textual ainda é incluído como contexto completo, sem busca vetorial. Configurações permitem editar instruções, personalidade, conhecimento e imagens. O onboarding é configurável por tenant em Configurações > Onboarding; consulte a seção abaixo.

## WhatsApp de teste

O receptor da Cloud API, o vínculo por número e a entrega de textos e imagens estão implementados. A ativação depende de configurar o aplicativo e o número de teste na Meta. Consulte [a configuração do WhatsApp](docs/whatsapp.md). O receptor roda na porta 8002, separada do admin, e é o único serviço que deve ser exposto pelo túnel HTTPS.

O provider fica em `app/providers.py` e usa Codex CLI com pasta temporária, ambiente reduzido e esforço de raciocínio baixo. No teste local, uma resposta simples levou aproximadamente 6 segundos, contra aproximadamente 29 segundos na versão anterior; a duração varia com o modelo e o serviço. O handover explícito levou cerca de 0,4 segundo. O CLI ainda inicia um processo a cada inferência; uma API de modelo ou conexão persistente poderá reduzir esse custo depois. Defina `LUMI_PROVIDER=demo` para resposta fixa sem usar o Codex.

Este laboratório usa dados fictícios e serve apenas em localhost. O Codex CLI possui ferramentas locais; a pasta temporária e o modo de leitura não garantem isolamento completo do computador. Antes de dados reais, precisamos de um provider sem acesso ao sistema de arquivos ou um ambiente isolado para o processo, além de credenciais e operação adequadas à implantação.

## Verificar

```powershell
pip install -r requirements-dev.txt
python -m unittest discover -s tests
```

O teste confere login, acesso entre tenants, contexto, handover, avisos de entrada e saída, nome do atendente, descarte de respostas antigas, upload e envio de imagens e proibição de imagem de outro tenant. A regra de spam é verificada com três requisições simultâneas, dois avisos, bloqueio silencioso posterior e desbloqueio pelo admin. O Codex também foi testado com a saída estruturada de seleção de imagem. O serviço HTTP de handover foi verificado com os dois processos locais.


## Onboarding e perfil

Em Configurações > Onboarding, adicione objetivos com título, descrição, obrigatoriedade e, quando pertinente, a opção de atualizar o nome do contato. Não há perguntas fixas nem informações de empresas na lógica do atendimento. A Lumi pode registrar o motivo do contato na primeira mensagem e perguntar somente como a pessoa prefere ser chamada. Ao receber o nome, retoma o pedido original. Recusas e perguntas ignoradas não bloqueiam ajuda: não deve repetir a mesma pergunta em mensagens consecutivas e deixa de sugeri-la após duas tentativas.

O nome vindo do WhatsApp ou do simulador é apenas identificação do canal, nunca confirmação de nome para o onboarding. O perfil confirma informações fornecidas pela própria pessoa. O modelo sugere valores com citações da mensagem atual; o servidor exige que o valor apareça na evidência e que a evidência apareça na mensagem. Objetivos de outro tenant e valores sem evidência são descartados. Essa validação reduz invenções, mas a interpretação semântica ainda depende do modelo.

Objetivos ficam em `onboarding_objectives`, valores e tentativas em `profile_values`, e a conclusão persistente em `contact_profiles`. As tabelas são adicionadas sem alterar as existentes. O perfil aparece na conversa do admin. Uma vez concluído, não se reinicia automaticamente quando os objetivos são editados. Handover e anti-spam continuam tendo precedência. Clientes antigos sem perfil confirmado passam pelo onboarding no próximo contato; nenhum nome anterior é confirmado automaticamente.

Para instalar o exemplo do Rincão uma única vez, depois de iniciar a aplicação, execute `python -m app.onboarding_setup --tenant rincao --file demo/rincao-onboarding.json`. O comando recusa sobrescrever objetivos existentes. Esses exemplos ficam no banco e podem ser editados pelo admin. A regra de identidade do WhatsApp mantém o perfil no contato nas próximas mensagens; uma nova conversa do simulador cria um novo contato de teste.
