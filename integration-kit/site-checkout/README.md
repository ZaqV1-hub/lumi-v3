# Página de pagamento Lumi no site HML

Este adaptador reutiliza o checkout visual da Lumi e a integração Cielo já existente no site. A página é `/pagar/TOKEN`; sua API é `/api/lumi-payment/TOKEN/state` e `/pay`. O pedido continua no banco de ingressos do próprio site. Não importa o núcleo da Lumi nem acessa o banco de outro cliente.

É uma integração para a cópia **local e isolada** do site Estância, não uma atualização do site publicado. O adaptador exige `lumiEnabled()`, banco com sufixo `_lumi_test`, segredo privado existente e `isLocalPaymentDemo()`: ambos os endpoints Cielo devem apontar ao simulador HTTP local. Ele recusa funcionar com gateway real. Débito aqui é simulado; ativação real requer implementar e validar 3DS antes de retirar essa restrição.

## Instalação revisada

No projeto separado do site, preserve uma cópia dos arquivos anteriores e confirme `.env.local`, banco e endpoints sem imprimir segredos. Copie `src/` e `public/` deste diretório para os diretórios correspondentes do site. Não copie arquivos privados para este pacote. O site precisa ter os módulos existentes de integração Lumi (`lumi-access`, `lumi-demo-payment`), Cielo e reconciliação.

Aplique `migration.sql` somente ao banco isolado. A migração é aditiva e transacional: cria `lumi_payment_attempts`, sem modificar pedidos existentes. A tabela guarda a reserva da operação e somente dados públicos da transação, nunca cartão, CVV ou resposta bruta do gateway. O token tem vínculo com `lumi_orders` e a consulta pública verifica tenant, compra, cancelamento e expiração.

Em `src/lib/lumi-commerce.ts`, altere as duas construções da URL de pagamento de `/lumi/checkout/${token}` para `/pagar/${token}`. Na página antiga `src/app/lumi/checkout/[token]/page.tsx`, mantenha um redirecionamento Next `redirect('/pagar/' + encodeURIComponent(token))`. Isso permite abrir links já enviados sem criar outra compra.

Execute `node node_modules/vitest/vitest.mjs run src/lib/lumi-payment-page.test.ts src/lib/lumi-access.test.ts`, TypeScript e build. Pare somente a instância local correta antes de substituir seu build; reinicie na porta privada já configurada. Não publique na VM ou produção. Confira no navegador o mesmo pedido, itens, valor e abas Pix, crédito e débito. Uma página aberta não comprova pagamento real.

## Repetição e resultado incerto

A primeira solicitação reserva o token atomicamente no Postgres antes de chamar o gateway. Cliques simultâneos ou repetição após timeout consultam o resultado existente. A consulta por referência da compra permite recuperar uma resposta perdida. Um pedido que já possui pagamento no escritor legado também não é reenviado. O estado pago depende da reconciliação do sistema de ingressos, nunca de mensagem do comprador. A proteção CSRF exige origem igual e token HMAC. Valor, CPF, comprador e ID são carregados do pedido, não aceitos do navegador.

Esta primeira versão não reinicia uma tentativa recusada: solicite uma nova compra ou faça recuperação operacional revisada. Não apague reservas para tentar novamente sem investigar o gateway. O endpoint de autenticação bancária real não é implementado por este adaptador de demonstração.

## Retorno

Restaure os arquivos anteriores, as construções da URL e o build anterior/recompilado. Preserve a tabela de tentativas para não perder a evidência de idempotência. Não remova pagamentos, pedidos ou ingressos para reverter a interface. A atualização do código não desfaz operações já executadas.
