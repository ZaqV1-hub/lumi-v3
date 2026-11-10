# Transferência de número entre tenants

Antes de uma troca autorizada, confirme o Phone Number ID pela API Meta e o banco efetivamente usado. Pare somente o receptor do ambiente após verificar ausência de mensagens, respostas ou envios em andamento. Faça um backup consistente do banco e valide seu catálogo. Crie explicitamente a tabela nova whatsapp_archived_chats com ArchivedChat.__table__.create(engine, checkfirst=True), antes de ativar a versão que a consulta. Não há alteração de colunas existentes.

Dentro de Session.begin(), use app.whatsapp.transfer.transfer_channel(db, phone_id, target_tenant_id). A operação preserva contatos, mensagens, perfis, sessões e os vínculos anteriores em whatsapp_archived_chats. Cancela saídas pendentes da empresa anterior, pausa suas conversas e muda somente o tenant do canal, mantendo credenciais Meta. O novo atendimento cria contato e conversa no tenant de destino. Ao transferir de volta, a função restaura os vínculos arquivados dessa empresa e seus estados anteriores. Não reutilize token ou contato de uma empresa na outra.

Há proteções também no recebimento e envio: vínculo incompatível não é reutilizado e mensagem de tenant diferente do canal não é enviada. Os registros de histórico arquivado continuam identificados como WhatsApp no painel. Mensagens que já estavam em trânsito precisam de conferência antes da troca. Não dispare notificações nem crie compras para validar o roteamento.

O retorno usa a mesma função com o tenant anterior, após nova verificação de filas. Preserve os arquivos privados e as tabelas; não restaure o dump sobre mensagens novas. Arquivar um vínculo não equivale a apagar o histórico.
