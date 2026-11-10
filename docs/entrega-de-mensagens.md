# Respostas em partes e indicador de processamento

A configuração é por tenant, em tenant_reply_delivery. Empresas sem registro continuam com o comportamento anterior. A resposta gerada é dividida em frases/parágrafos de até aproximadamente 450 caracteres; palavras e URLs não são cortadas. A divisão não faz novas chamadas ao modelo. Mídia fica na última parte, sem duplicação. Cada parte recebe os mesmos vínculos de autorização de ferramentas. O histórico e os canais mostram mensagens reais, não uma quebra apenas visual.

Antes de atualizar, identifique DATABASE_URL e LUMI_DATA_DIR, faça backup consistente do banco e preserve o código anterior. Com o ambiente correto configurado, execute `python scripts/configure-reply-delivery.py --tenant SLUG --max-chars 450`. A migração aditiva cria explicitamente apenas tenant_reply_delivery e reply_parts, sem modificar colunas nem conteúdo existente. O comando é idempotente. Não apague mensagens diretamente sem respeitar os vínculos de reply_parts; a chave estrangeira usa ON DELETE CASCADE para exclusões SQL.

O WhatsApp recebe um POST /PHONE_ID/messages com status=read, message_id do evento recebido e typing_indicator.type=text. O aviso é enviado no início do processamento da vez do contato, depois da fila. Não é emitido para duplicatas, conversas humanas ou contatos bloqueados. Uma falha gera aviso operacional sem conteúdo privado e não interrompe a resposta. O sinal nativo tem duração limitada pela Meta e não representa texto enviado. Não há atraso artificial entre as partes.

Partes ainda pendentes são canceladas quando muda a revisão da conversa, a IA é desativada ou um humano assume. Um envio já em trânsito não pode ser desfeito. A fila atual continua com um worker de entrega por processo. Não aumente workers sem coordenação compartilhada.

Para desativar novos fracionamentos e sinais, execute o mesmo comando com --disable. Preserve as tabelas para manter a referência das mensagens já geradas. Para retornar o código, pare somente os serviços do ambiente, restaure a release anterior e reinicie; não restaure um banco antigo sobre novas conversas. Nenhuma credencial ou assinatura de canal é alterada.

## Integração com a versão compartilhada

A atualização desta tarefa foi aplicada como release de hotfix somente no HML, preservando a release anterior e o banco. A implementação está versionada na branch develop e deve ser preservada nas próximas integrações. Atualizações futuras devem partir da ponta atual de develop, sem publicar uma cópia antiga por cima dela. Não copiar o checkout pessoal inteiro sobre o HML. Produção não foi alterada. Os testes de HTTP da Meta são simulados; a exibição nativa depende de confirmação no aparelho.
