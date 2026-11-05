# Compra de ingressos pela Lumi — teste local

## Fluxo

O cliente escolhe data e quantidades. A ferramenta cotar_ingressos consulta o catálogo de homologação e retorna preço, disponibilidade, total e uma cotação identificada. Não precisa de CPF para cotar. Depois da escolha, a Lumi coleta nome e CPF válido; no WhatsApp o telefone vem do canal, no simulador é informado pela pessoa. A personalidade continua orientando as mensagens.

A ferramenta criar_compra_ingressos revalida o preço, vincula a compra pendente ao CPF e cria uma URL da nossa própria página. Criar o link não cria uma transação financeira na Cielo. O cliente abre a página HTTPS e escolhe Pix ou cartão. O checkout usa a API E-commerce Cielo com MerchantId/MerchantKey, sem depender dos produtos Checkout hospedado ou Link de Pagamento da Cielo.

O total vem da cotação do servidor; navegador e modelo não podem enviar outro preço. Cartão e CVV ficam somente na requisição ao checkout e na chamada HTTPS ao gateway. Não entram no chat, Codex, banco de tentativas ou logs. O CPF é mascarado no registro da chamada da Lumi; cadastro e compra no sistema contêm o CPF completo.

## Registro no site

O serviço externo reutiliza os contratos de comércio do projeto rincao-dados na VM: cotação, pedido pendente e pedido aprovado. A fonte atual foi compilada isoladamente, sem substituir o serviço/site existente. O adaptador executa esses contratos por SSH com chave e host verificado, sem abrir novas portas na VM. A Lumi continua acessando apenas os endpoints HTTP do serviço externo.

O adaptador confere tenant de homologação, banco com sufixo _test e RINCAO_TICKET_API_USE_TEST_DB=true antes de operar. O convidado é inserido sem senha/e-mail, com nome e telefone. CPF existente não tem seu cadastro substituído. A compra fica na tabela compra, com origem Lumi e sessão idempotente. Somente a confirmação do gateway aciona o contrato que grava pagamento e vouchers.

Foi criado o pedido de teste 900000050, nome “Teste Lumi V3 Ecommerce”, com cadastro incompleto e nenhum voucher: estado pendente. Repetir a mesma sessão manteve o mesmo pedido. O CPF está somente no registro privado de QA, fora deste repositório.

## Confirmação e duplicidade

A página usa token aleatório e mostra somente seu pedido, nome e CPF mascarado. Há validação de origem, CSRF, tamanho de corpo e campos permitidos. Dados inválidos de cartão não são ecoados na validação. Duplo clique reutiliza a tentativa em andamento. Depois de resposta incerta, o serviço consulta o pedido sem repetir automaticamente a cobrança. Nova tentativa explícita após recusa/cancelamento usa outra referência, limitada a cinco.

O serviço consulta pagamentos pendentes a cada 15 segundos. Só aceita Status=2 da API E-commerce, com PaymentId, referência, valor e CPF correspondentes. Status=1, apenas autorizado, não libera ingressos. Um “paguei” no chat ou status enviado pelo navegador não confirma nada. A ferramenta consultar_compra_ingressos também verifica o provedor. O registro idempotente no sistema acontece antes de mostrar a compra concluída.

A confirmação externa agora inclui metadata.payment_method com pix, credit_card ou debit_card, derivado exclusivamente do tipo verificado na Cielo. O escritor atual do rincao-dados ainda precisa consumir esse campo e preencher a forma de pagamento legada; o painel do site também precisa exibir/filtrar origem_checkout=lumi sem trocar o tipo técnico da compra. O pedido 900000052 já pago não foi reenviado nem alterado; corrigir a forma histórica apenas com evidência verificada, sem duplicar pagamentos ou ingressos.

O banco auxiliar rincao-commerce.db, fora do Git, guarda cotações, pedidos e tentativas. A tabela payment_attempts contém identificador, estado e dados públicos do Pix; não guarda cartão nem resposta bruta da Cielo. A tabela tool_contexts na Lumi mantém a última cotação por conversa, tenant e permissão, para recuperar a cotação na mensagem seguinte sem mostrar seu identificador ao cliente.

## Configuração

Credenciais ficam em %LOCALAPPDATA%\Lumi\cielo.env. INGRESSO_CIELO_API_ENDPOINT e INGRESSO_CIELO_QUERY_ENDPOINT determinam o ambiente financeiro. Os endereços fornecidos são de produção: banco do site de teste não torna o pagamento simulado. A página informa quando existe cobrança real. Nenhuma cobrança de cartão ou pagamento Pix foi feita durante a implementação.

O serviço usa RINCAO_CHECKOUT_PUBLIC_URL do arquivo privado cielo.env, carregado antes de rincao-tools.env para evitar que cópias antigas nesse arquivo prevaleçam. Mantenha essa variável somente em cielo.env. O receptor 8002 expõe apenas as rotas permitidas do checkout, além dos webhooks. Admin e contratos externos não são expostos. O Quick Tunnel precisa ficar ativo; ao trocar seu endereço, atualizar a variável, reiniciar o serviço 8003 e recuperar os links dos mesmos pedidos, sem criar novas compras.

Para simular neste computador, RINCAO_CHECKOUT_SIMULATOR_URL=http://127.0.0.1:8000 faz a página abrir pelo servidor local do admin, sem depender do Quick Tunnel. O servidor 8000 também encaminha somente as rotas permitidas do checkout ao serviço externo; LUMI_CHECKOUT_SERVICE_URL configura o destino (padrão localhost:8003). O núcleo informa o canal a partir do vínculo da conversa no banco, nunca de uma escolha do modelo. Somente o canal `simulator` usa endereço local; WhatsApp e Instagram recebem `RINCAO_CHECKOUT_PUBLIC_URL`, independentemente de o telefone do comprador ter sido informado no chat. Essa escolha não altera a verificação do telefone nem a permissão de concluir cadastro. Ao recuperar um pedido existente, o endereço é reconstruído com a configuração atual, preservando pedido, prazo e pagamentos. Ao trocar o túnel público, atualize essa variável no arquivo privado `cielo.env` e reinicie o serviço 8003. A origem do pagamento deve corresponder exatamente a uma das duas URLs configuradas, além de exigir o comprovante CSRF. No chat, o link local aparece como “Abrir página de pagamento”.

Pix usa o provedor Cielo2. A expiração é limitada à validade restante do checkout. Crédito segue o limite de três parcelas e o mínimo por parcela informado, exceto à vista. Débito é à vista (Visa, Mastercard ou Elo) e exige autenticação 3DS antes da autorização. As credenciais existentes no HML foram copiadas por SSH para o arquivo privado local, sem exibir valores. A obtenção de token foi validada sem cobrança; os ambientes de autenticação e pagamento precisam coincidir.

RINCAO_COMMERCE_REMOTE_ROOT aponta para a configuração de homologação; RINCAO_COMMERCE_REMOTE_DEPENDENCIES, para as dependências da fonte atual; RINCAO_COMMERCE_REMOTE_BUILD, para a compilação isolada. Os caminhos ficam no arquivo privado. Antes de usar outro servidor, recompilar os contratos revisados e validar o banco de teste. Nenhum SQL vem do modelo.

## Concluir a conta no site

O vínculo dos ingressos ao CPF independe de login. A conclusão segura de cadastro incompleto foi publicada somente no HML em 30/10/2026, na release lumi-guest-claim-20261030-03. O site valida comprovante cifrado, telefone, pedido pago e ausência de conta completa ou privilegiada. Os arquivos em integrations/rincao-site/ são a preparação original; a implementação revisada está no projeto do site.

A emissão foi ativada na configuração privada local após conferir que as chaves da Lumi e do HML coincidem. Após pagamento confirmado e ingressos registrados, o checkout oferece o botão para concluir o cadastro em https://cluberincao.questione.ai/cadastro. A consulta da compra pela Lumi também retorna esse link. Ele não é emitido para pedido pendente nem para telefone digitado no simulador. A compra real completa, incluindo pagamento e conclusão do cadastro, ainda precisa ser simulada pelo titular; nenhum pagamento foi realizado pelo agente.

## Verificar

Executar python -m unittest discover -s tests. O gateway simulado verifica estados, valores, CPF, duplicidade, proteção de cartão, permissões e emissão de ingressos. Leitura e pedido pendente também foram testados no banco de homologação. O teste financeiro final deve ser feito pelo titular na página; o ambiente Cielo de produção pode cobrar de verdade.

Referências: [API E-commerce](https://docs.cielo.com.br/ecommerce-cielo/docs/caracteristicas-api-ecommerce) e [integração Pix](https://docs.cielo.com.br/ecommerce-cielo/docs/pix-cielo).

## Checkout visual e débito

O visual usa o HTML Checkout Rincão Ingressos fornecido em 30/10/2026: fontes Poppins/Inter, cores, resumo responsivo, cartão ilustrado e logotipos. Dados de exemplo, cartões automáticos, confirmação simulada, QR ilustrativo e vouchers fictícios foram removidos. Nome, CPF mascarado, data, valores, transação e confirmação vêm do servidor. Pedido pago continua abrindo o comprovante depois de expirar o prazo de pagamento; pedido expirado mostra uma tela para voltar à Lumi, sem tentar cobrar novamente.

A autenticação usa MPI V2 por script, compatível com o fluxo existente do site, carregado diretamente da Cielo para usar a versão atual. Um token de uso específico 3DS é obtido no servidor; client secret e credenciais do gateway não vão ao navegador. O comprovante da sessão dura cinco minutos e vincula pedido, valor e hash protegido do cartão. Falha, recusa, ausência de autenticação ou troca de cartão interrompem o débito. Apenas autenticação bem sucedida segue como DebitCard/ExternalAuthentication à API, que verifica os dados do banco. Débito nunca vira crédito automaticamente.

Os testes de navegador em tests/checkout-ui.cjs interceptam todas as requisições POST. Verificam desktop/celular, validação, Pix, consulta sem nova cobrança e o fluxo completo de débito com banco simulado. As imagens de QA ficam fora do Git. Não foi feita transação bancária real de débito pelo agente; falta a simulação final do titular. As credenciais 3DS foram aceitas no teste de obtenção de token.

Referências: [débito Cielo](https://docs.cielo.com.br/ecommerce-cielo/docs/cart%C3%A3o-de-debito), [MPI V2 por script](https://docs.cielo.com.br/gateway/docs/3-implementando-o-script).
# Recuperação de pedidos

A ferramenta `consultar_compra_ingressos` também serve para recuperar o link de um pedido da própria conversa. Para pedidos pendentes sem tentativa de pagamento, o retorno inclui o endereço calculado com a configuração atual do checkout. Se o prazo expirou, informa `expired` e não apresenta o link como válido. Nenhum desses caminhos cria outro pedido, cobrança ou ingresso. O contrato orienta consultar o estado atual em vez de repetir diagnósticos antigos do histórico. A compra continua exigindo cotação, escolha da pessoa e CPF informado pelo comprador; cartão e senha ficam somente na página de pagamento.


## Correção de dados do comprador

Validações de nome, CPF e e-mail retornam `dados_invalidos` com `invalid_fields`, sem ecoar dados pessoais ou erros técnicos. A Lumi pede apenas a informação rejeitada, preservando as demais escolhas, e valida novamente antes de criar o pedido. Telefone ausente também é um campo a coletar: só o WhatsApp fornece o número automaticamente; Instagram e simulador precisam do telefone informado pelo comprador. O núcleo aceita somente campos e motivos de validação seguros no HTTP 422; outros erros continuam tratados como indisponibilidade. Não há resposta pronta para o cliente.
