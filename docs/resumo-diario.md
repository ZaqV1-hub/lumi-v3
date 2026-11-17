# Resumo diário de atendimento

Com a configuração do banco do ambiente carregada, gere o resumo do tenant com `python -m app.daily_report --tenant SLUG --date AAAA-MM-DD --output CAMINHO.txt`. Sem `--date`, o comando usa o dia anterior em São Paulo. Informe um caminho novo em uma pasta privada.

O relatório conta conversas e mensagens no dia, atendimentos com resposta humana, conversas atualmente atribuídas a operadores e custo estimado de API. Atribuições atuais são uma foto do momento da consulta. O custo pode ser parcial, conforme o indicador de mensagens sem custo completo. O arquivo contém totais por tenant e nenhum texto de conversa.

A publicação automática no Drive ainda depende da autorização OAuth de cada empresa e do vínculo com a pasta que ela vai compartilhar com seus colaboradores. Use o escopo [drive.file](https://developers.google.com/workspace/drive/api/guides/api-specific-auth) para limitar o acesso aos arquivos da integração. Antes de ampliar o resumo para incluir mensagens, defina quais trechos podem ser compartilhados. Para visitas e conversões, use confirmações registradas pelos serviços de agendamento e checkout, com data e identificação da operação para deduplicar.
