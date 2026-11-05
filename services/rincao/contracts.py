DATE_RANGE = {
    "type": "object", "properties": {
        "start_date": {"type": ["string", "null"], "pattern": "^[0-9]{4}-[0-9]{2}-[0-9]{2}$", "description": "Data inicial inclusiva YYYY-MM-DD; null usa hoje."},
        "end_date": {"type": ["string", "null"], "pattern": "^[0-9]{4}-[0-9]{2}-[0-9]{2}$", "description": "Data final inclusiva YYYY-MM-DD; null usa o padrão da consulta."}},
    "required": ["start_date", "end_date"], "additionalProperties": False,
}

CONTRACTS = [
    {"name": "consultar_agenda", "description": "Consultar no site as datas abertas e os preços atuais de ingressos para visitas em família. Use quando o cliente perguntar quando abre, datas disponíveis ou preços por data. Se a pessoa já pediu uma compra e informou quantidades ou critérios de data, aproveite essas escolhas: não peça autorização para fazer uma cotação técnica nem repita o preço como uma nova etapa. Esclareça somente escolhas ou informações realmente pendentes e confirme o resumo da compra quando necessário.",
     "path": "/agenda", "roles": ["cliente", "gestor", "atendente"], "parameters": DATE_RANGE},
    {"name": "consultar_faturamento", "description": "Consultar faturamento de eventos do buffet por período e representante, somente para gestores. date_base=evento para faturamento pelas datas dos eventos; contrato para vendas contratadas pelas datas dos contratos. Não representa recebimentos de caixa.",
     "path": "/faturamento", "roles": ["gestor"], "parameters": {
         **DATE_RANGE, "properties": {**DATE_RANGE["properties"],
             "representative": {"type": ["string", "null"], "maxLength": 120, "description": "Nome do representante solicitado ou null para todos."},
             "date_base": {"type": "string", "enum": ["evento", "contrato"], "description": "Use evento para faturamento; contrato quando perguntarem vendas ou contratos fechados."}},
         "required": ["start_date", "end_date", "representative", "date_base"]}},
]
