# Serviço externo de ingressos no HML

O componente services.rincao é independente do núcleo e valida credencial, tenant e papel em cada operação. RINCAO_COMMERCE_TRANSPORT=local permite executar o adaptador Node já instalado na mesma máquina, sem copiar chave SSH. O padrão continua ssh para instalações locais. A guarda do RPC exige nome de banco terminado em _test e o modo de teste habilitado; cotações usam sessão PostgreSQL somente leitura.

Na instalação autorizada de HML, o serviço fica em loopback, com ambiente privado próprio, dados de checkout próprios e versão de código registrada. O núcleo chama apenas os endpoints de agenda, cotação, criação e consulta aprovados para o tenant. Contratos de faturamento não são habilitados por essa preparação. A página pública de pagamento passa pelo proxy /checkout já existente; admin e contratos continuam privados. Nunca use app.tool_setup apenas para inspecionar contratos, pois ele habilita todo o conjunto.

A configuração de IA é por tenant, mesmo quando o responsável autoriza compartilhar a mesma credencial: decifre com o tenant de origem e cifre novamente com o tenant de destino. Não copie o valor cifrado entre tenants. Segredos não pertencem a commits ou relatórios.

O componente de ingressos tem instalação e liberação próprias. Depois de alterar services/rincao, publique seu código no Git, valide com mocks e atualize a release versionada desse serviço, reiniciando somente o serviço correspondente. O deploy do núcleo não substitui a validação nem a atualização dessa integração separada. Preserve checkouts, registros de idempotência e resultados incertos. Faça backup consistente do SQLite antes de atualização de schema ou retorno. Não faça cobranças para testar infraestrutura.

Ambiente de site HML não implica sandbox da Cielo: a tela deve refletir o gateway efetivamente configurado. Validação de infraestrutura não efetua cobrança, aprovação manual nem emissão de ingresso. O pagamento real depende de ação explícita do comprador e confirmação do gateway.

A entrada services.rincao.hml:app inclui confirmação de handover no formato legado, com credencial própria e verificação de tenant. A pausa da IA, fila humana e avisos continuam sendo responsabilidade do núcleo.

A entrada também monta o serviço público existente em /public-tools, mantendo seus próprios contratos, limites e autorização por tenant. A consulta de faturamento usa o endpoint existente /faturamento, com papel gestor validado no servidor e consulta SQL fixa em transação sem gravação. Credenciais de buffet e buscador são provisionadas no ambiente privado do componente. Ativar a integração não concede o papel gestor a contatos.
