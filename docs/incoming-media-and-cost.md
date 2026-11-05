# Imagem, áudio e medição de consumo

## Uso no simulador

Abra o simulador do cliente pelo dashboard do admin ou por `/chat/SLUG`. Use **Enviar imagem ou áudio** para anexar um arquivo, com legenda opcional. **Gravar áudio** solicita o microfone ao navegador; o segundo clique para e envia a gravação. A gravação para automaticamente após dois minutos. A Lumi responde em texto. As imagens prontas que a empresa cadastrou continuam podendo ser enviadas pela ferramenta existente; esta etapa não gera imagens nem fala sintética.

Imagens aceitas: JPEG, PNG e WebP, até 5 MB e 16 megapixels. O servidor verifica o arquivo real, corrige orientação, remove metadados e reduz para até 1600 pixels antes de enviar ao modelo. São enviados no máximo os dois anexos visuais mais recentes dentro das últimas oito mensagens; isso dá contexto curto para perguntas de continuidade e limita o custo.

Áudios aceitos: WAV, MP3, M4A/MP4, OGG e WebM, até 12 MB e dois minutos. A leitura verifica o contêiner e limita a duração decodificada, sem permitir protocolos de rede ou playlists. O arquivo original e a transcrição aparecem na conversa. Se não houver fala compreensível ou o arquivo for inválido, a interface informa o erro, sem inventar transcrição. Imagem e áudio são dados do cliente, não instruções que possam alterar permissões ou revelar informações internas.

## Fluxo e isolamento

`incoming_attachments` associa mensagem, conversa e tenant. Os acessos são autenticados pelo token da conversa no simulador e pelo login do tenant no admin. Outro contato, inclusive do mesmo tenant, não consegue abrir um anexo que não pertence à sua conversa. Não há diretório público de uploads nem caminho de arquivo enviado pelo usuário ao provider.

O anexo é salvo antes da inferência. Se a conversa estiver com atendimento humano, ele aparece para o operador, mas a Lumi não faz inferência nem transcreve automaticamente. Spam continua sendo controlado por contato antes da IA. A transcrição usa o mesmo ciclo de geração e permite intervenção humana durante o processamento. Os dados reconhecidos alimentam o perfil apenas pelas mesmas regras de evidência do onboarding.

O receptor WhatsApp também aceita eventos `image` e `audio`, com download autenticado da Meta, limite de tamanho, origem HTTPS permitida e a mesma validação do simulador. Esse adaptador foi testado com transporte simulado. O WhatsApp continua pausado; o teste real pelo número será feito quando o usuário decidir retomá-lo. Esta etapa não alterou a configuração da Meta nem enviou mensagens.

## Providers

Imagem usa `codex exec --image` na chamada normal, com arquivos temporários apagados ao final. Não existe uma chamada separada para descrever cada imagem. A primeira medição abaixo usava `gpt-6.1-sol`. Após a comparação de custo, o padrão passou a `gpt-6.1-terra`, raciocínio `low`, com perfil enxuto de atendimento; veja [provider-cost.md](provider-cost.md). `LUMI_CODEX_MODEL` permite trocar o modelo sem alterar regras de tenant ou ferramentas.

Áudio usa `app/audio.py` com faster-whisper local, modelo multilíngue `base`, CPU int8 e até quatro threads. O modelo é carregado uma vez por processo. O primeiro uso pode demorar mais para carregar os pesos. A instalação baixa os pesos públicos para `%LOCALAPPDATA%\Lumi\speech-models`; depois a transcrição não envia áudio a uma API. `LUMI_AUDIO_MODEL` e `LUMI_AUDIO_LANGUAGE` configuram modelo/idioma (padrões base/pt). Há uma transcrição ativa por processo para não saturar a máquina; não há tarifa de API pela transcrição local, mas infraestrutura e energia têm custo.

## Consumo e velocidade

Atualização: o painel exibe custo de API zero para o Codex local e a transcrição local. Tokens e tempos continuam medidos. Os valores equivalentes de API apresentados nas amostras históricas abaixo servem para planejamento, não são cobranças do CLI nem valores somados no admin atual.

Com o login Brevia, entre no tenant e abra **Consumo e velocidade** no menu lateral, abaixo de Configurações. Essa página não aparece no painel do cliente, e a API exige o papel Brevia. As medições começam nesta versão; não existe contagem retroativa dos atendimentos antigos. `model_calls` guarda provider, modelo solicitado, tokens de entrada/cache/saída/raciocínio quando disponíveis, duração, status e referência de preço. Não guarda prompt, imagem, áudio, transcrição ou saída bruta. `response_runs` mede o tempo total da mensagem, incluindo fila, transcrição, consultas e inferência. Chamadas com ferramenta contam separadamente, vinculadas à mesma mensagem, para calcular a média por mensagem.

O Codex emite uso por `--json`; números ausentes ficam desconhecidos, não viram zero para o cálculo de preço. A estimativa é um equivalente de API em USD com preços Standard para contexto curto verificados em 30/10/2026. Não é uma cobrança adicional do plano Codex, não converte porcentagem da franquia em dinheiro e não inclui outros fornecedores/infraestrutura. Não estima modelos sem preço conhecido. Cache é descontado da entrada total antes de aplicar a tarifa específica, sem dupla cobrança. Os preços ficam em `app/usage.py`; revise-os quando o provedor mudar a tabela.

## Testes e amostras de custo

Foram testados upload, leitura, gravação por microfone simulado, reprodução, transcrição local, isolamento de anexos/consumo, handover sem inferência, arquivos inválidos e limite de duração. `tests/media-ui.cjs` intercepta uploads e não chama a IA. Testes reais com Codex foram feitos numa cópia temporária do banco, sem inserir contatos de QA no histórico do usuário nem enviar mensagens ao WhatsApp.

Uma imagem pública de QA com o texto “TESTE VISUAL 4729” foi lida corretamente. Um áudio sintético em português de 4,8 segundos foi transcrito corretamente em aproximadamente 2,3–2,9 segundos. Duas mensagens com GPT-6.1 Sol, usando o contexto atual do tenant na cópia de QA, deram 44.224 tokens de entrada, 305 de saída, sem cache, tempo total médio de 7,44 segundos e equivalente médio de US$ 0,045749 por mensagem. O processo CLI inclui instruções do agente além do contexto da Lumi; isso pesa mesmo em respostas curtas.

Um teste adicional da mesma leitura visual com GPT-6 Luna também identificou o texto corretamente: 20.512 tokens de entrada, 117 de saída, 5,728 segundos e equivalente de US$ 0,0021097. É apenas uma amostra, não uma avaliação completa de qualidade, ferramentas, onboarding ou vendas. O modelo padrão do usuário não foi trocado. A comparação serve para planejar um benchmark de um provider de atendimento mais econômico, preferencialmente com API direta e contexto enxuto. O preço real futuro só pode ser confirmado medindo essa configuração final.

O e-commerce escolar permanece pendente do formulário e das regras do usuário. Nenhum campo, escola, série ou turma foi fixado em código nesta etapa.

O fluxo solicitado para a próxima etapa é buscar escolas/clientes com passeios futuros no sistema do Rincão, apresentar nomes e endereços para distinguir homônimos, confirmar a escola e a data, coletar nome do aluno e as opções reais de ensino/série/turma do formulário, apresentar resumo com possibilidade de correção e somente então gerar o pagamento. A compra e o pagamento devem aparecer vinculados ao passeio e à escola no sistema existente. As opções virão do serviço externo e do banco, sem listas de escolas ou formulário escolar fixados no núcleo da Lumi. Os campos adicionais e as regras finais aguardam o documento do usuário.

Referências: [Codex não interativo e uso JSON](https://learn.chatgpt.com/docs/non-interactive-mode), [preços de API](https://developers.openai.com/api/docs/pricing), [faster-whisper](https://github.com/SYSTRAN/faster-whisper).
