# Inteligência artificial por tenant

Em Configurações → Inteligência artificial, a equipe Brevia escolhe provider e modelo para a empresa selecionada. Opções: Codex CLI no servidor (`codex`), Codex remoto pelo gateway (`codex_gateway`), OpenAI API (`openai`) ou demonstração sem inferência (`demo`). Alterações valem na próxima inferência, sem reiniciar. Contatos e clientes não podem escolher o tenant ou mudar credenciais pela conversa. A mudança não ativa uma empresa pausada nem configura seus canais.

Provider e modelo ficam em `tenant_ai_settings`. A chave OpenAI é cifrada com Fernet antes da gravação e seu conteúdo é vinculado ao ID do tenant; mover o ciphertext para outra empresa é rejeitado. A aplicação retorna apenas presença da chave e estado de configuração. A API nunca devolve segredo, nem mesmo para Brevia. Campo em branco preserva a chave; a opção explícita de remover apaga a chave daquele tenant. Manter uma chave cadastrada ao escolher Codex permite voltar à API; Codex não recebe essa chave.

Não existe fallback para `OPENAI_API_KEY`, `LUMI_PROVIDER`, `LUMI_OPENAI_MODEL` ou `LUMI_CODEX_MODEL`: essas variáveis não selecionam IA nem credencial. Um tenant novo precisa ser configurado. Falta de chave/modelo, chave cifrada inválida ou indisponibilidade do provider gera erro sem trocar de fornecedor. O modelo precisa existir e estar acessível na conta escolhida. Salvar configuração não faz chamada paga nem comprova disponibilidade da API.

## Configuração privada do servidor

`LUMI_AI_SECRET_KEY` guarda a chave Fernet de criptografia, separada do banco e diferente de uma chave OpenAI. Gere uma única vez por ambiente com `cryptography.fernet.Fernet.generate_key()` e grave diretamente no arquivo privado carregado pelo serviço, sem imprimir nem colocar em Git. Reinicie painel e receptor depois de configurar essa variável. Não substitua a chave de criptografia ao reiniciar/deployar: perder ou trocar esse valor impede ler as credenciais já gravadas. Guarde backup privado separado do dump de banco; rotação exige recifrar as credenciais, não apenas mudar a variável.

Para Codex local, mantenha o CLI autenticado no servidor que executa a inferência. Para gateway, o servidor usa `LUMI_CODEX_GATEWAY_URL` e `LUMI_CODEX_GATEWAY_TOKEN` como infraestrutura compartilhada, mas a escolha e o modelo são do tenant. A chave OpenAI de um tenant nunca é enviada ao gateway. Não envie segredos em prompts, mensagens, arquivos de conhecimento ou URLs.

## Migração e retorno

Antes de publicar: salve backup do banco e da configuração privada; prepare a nova release e a chave de criptografia; carregue a configuração correta do ambiente antes de importar os módulos. Execute `python -m app.migrate_tenant_ai --provider codex_gateway --model gpt-6.1-terra` no ambiente da VM, ou `--provider codex` no Mac. `--tenant SLUG` limita a um tenant. O comando cria a tabela nova e inicializa somente registros ausentes, em transação. Não altera dados, canais ou escolhas existentes; não copia uma chave global. Nova tabela aditiva não substitui migrations para alterações futuras de colunas.

Depois, configure pelo painel a chave e o modelo dos tenants que usam OpenAI. Remova as quatro variáveis globais antigas do arquivo ativo. Publique painel e receptor juntos para que todos os canais usem a mesma seleção. Verifique o tenant e o provider no relatório Consumo e velocidade; não use banco ativo para testes unitários. Em caso de retorno, preserve a tabela, o dump e a chave de criptografia. Código anterior não entende a seleção por tenant: não volte a ele distribuindo a chave de um cliente globalmente. Retorno não desfaz chamadas ou mensagens já realizadas.

## Validação

Testes cobrem dois tenants com chaves/modelos distintos em paralelo, ausência de fallback global, falta de configuração, tentativa de trocar ciphertext entre tenants, permissão de login e tenant, preservação/remoção da chave, ausência de segredo na resposta/auditoria e migração idempotente. OpenAI nesses testes usa transporte HTTP simulado e dados fictícios. O fluxo do painel também é validado no navegador; inferência real é registrada separadamente na operação do ambiente.

## Operação e consumo

O estado implantado, as inferências reais e os limites dos canais estão em [produção na VM](producao-vm.md) e [homologação na VM](homologacao-vm.md). HML e PROD podem usar providers diferentes para o mesmo tenant; a escolha pertence ao banco de cada ambiente, não ao nome do tenant no código.

OpenAI registra consumo e estima custo somente quando modelo, tier e metadados permitem aplicar a tarifa completa verificada. Leitura e escrita de cache têm tratamento próprio; raciocínio já integra os tokens de saída e não é cobrado duas vezes na estimativa. Custo ausente permanece desconhecido, com total parcial indicado no relatório. A apresentação usa seis casas decimais para não exibir pequenas chamadas como zero. As referências de tarifa ficam no registro da chamada; a estimativa não substitui a fatura da OpenAI. Codex CLI/gateway e transcrição local continuam com custo de API zero, separado da assinatura e da infraestrutura.
