# Concluir cadastro de comprador convidado — preparação para o site HML

Estes arquivos são a preparação original da integração para o site Next.js. A implementação revisada foi publicada somente no HML na release lumi-guest-claim-20261030-03, em 30/10/2026. A emissão dos links foi ativada na configuração privada local da Lumi após conferir compatibilidade das chaves. O projeto do site contém proteções adicionais para conta paralela do painel e concorrência; não substituir a versão publicada por esta preparação sem revisão.

Copiar `lumi-guest-token.mjs`, sua declaração `.d.mts` e `lumi-guest-registration.ts` para `src/lib/` do site de homologação e revisar/aplicar `registration.patch`. O patch mantém o cadastro normal e envia o token do link da Lumi no formulário. Não modifica o login de contas existentes.

Usar a mesma chave aleatória de 32 bytes em base64 na variável privada `RINCAO_GUEST_CLAIM_KEY` do serviço externo e do site, sem prefixo NEXT_PUBLIC. A chave nunca entra no código, HTML ou Git. Só depois de validar o site, configurar `RINCAO_GUEST_ACCOUNT_URL` para sua página HTTPS de cadastro e `RINCAO_GUEST_CLAIM_ENABLED=true` no serviço externo.

O link só é emitido após o pagamento ser confirmado no provedor e os ingressos registrados, para compras cujo WhatsApp veio do canal autenticado. O token usa AES-256-GCM, CPF e telefone ficam cifrados e expira em uma hora. O site verifica token, CPF, telefone do cadastro, pedido pago com origem Lumi e ausência de senha/e-mail antes do UPDATE. A condição é repetida no próprio UPDATE: uma conta que já tenha senha ou e-mail não pode ser substituída. A senha passa pelo mesmo hash utilizado no site; o CPF e as compras permanecem iguais. Depois do primeiro uso, a senha preenchida impede reutilização.

Não liberar cadastro de um CPF existente apenas por alguém informar o número. No simulador o telefone digitado não comprova posse do WhatsApp, por isso não produz link para concluir conta.

Na publicação do HML passaram build, TypeScript, ESLint e 27 testes específicos no projeto do site. A rota HTTPS foi verificada e rejeitou comprovante inválido. A simulação completa com pagamento real e conclusão da conta ainda cabe ao titular. Produção não foi alterada.
