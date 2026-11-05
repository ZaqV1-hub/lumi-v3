"""Contratos do e-commerce próprio da Estância, executados pelo site HML."""
ROLES = ["cliente", "gestor", "atendente"]
TOKEN = {"type": "string", "minLength": 43, "maxLength": 43}
ITEMS = {"type": "array", "minItems": 1, "maxItems": 30, "items": {"type": "object", "properties": {
    "product_id": {"type": "string", "minLength": 1, "maxLength": 120},
    "quantity": {"type": "integer", "minimum": 1, "maximum": 100}}, "required": ["product_id", "quantity"], "additionalProperties": False}}
CONTRACTS = [
    {"name": "consultar_catalogo", "path": "/api/lumi/catalog", "roles": ROLES,
     "description": "Consultar passaportes e adicionais ativos no catálogo atual do site de homologação da Estância, com preços, descrições e product_id. Quando souber a data, informe visit_date para filtrar os produtos disponíveis nesse dia. Consulte antes de propor ou cotar produtos; não reutilize os preços e nomes do material antigo. Respeite as condições e faixas etárias descritas em cada produto. Não cria compra.",
     "parameters": {"type": "object", "properties": {"visit_date": {"type": ["string", "null"], "format": "date"}}, "required": ["visit_date"], "additionalProperties": False}},
    {"name": "cotar_ingressos", "path": "/api/lumi/quote", "roles": ROLES,
     "description": "Calcular internamente a compra de passaportes e adicionais escolhidos para uma data. Use os product_id reais do catálogo e as quantidades informadas. Precisa de pelo menos um passaporte. Não precisa de CPF nem autorização adicional para fazer o cálculo da compra solicitada. Depois, apresente total e colete apenas dados faltantes, sem oferecer cotação como uma etapa extra.",
     "parameters": {"type": "object", "properties": {"visit_date": {"type": "string", "format": "date"}, "items": ITEMS}, "required": ["visit_date", "items"], "additionalProperties": False}},
    {"name": "criar_compra_ingressos", "path": "/api/lumi/purchase", "roles": ROLES,
     "description": "Preparar o pedido escolhido após cotação, com nome completo, CPF válido informado pelo comprador e telefone. Somente no WhatsApp o número vem automaticamente; no Instagram e simulador peça o telefone com DDD quando faltar. Se houver dados_invalidos, peça novamente apenas o campo rejeitado. Registra pedido pendente no site de homologação da Estância e retorna o link de checkout. Envie esse link como retornado, inclusive local durante a simulação. Pagamento acontece na página Cielo, nunca no chat. Não afirme que está pago sem consulta.",
     "parameters": {"type": "object", "properties": {"quote_id": TOKEN, "name": {"type": "string", "minLength": 2, "maxLength": 120},
        "cpf": {"type": "string", "minLength": 11, "maxLength": 14}, "phone": {"type": ["string", "null"], "maxLength": 20},
        "email": {"type": ["string", "null"], "maxLength": 120}}, "required": ["quote_id", "name", "cpf", "phone", "email"], "additionalProperties": False}},
    {"name": "consultar_compra_ingressos", "path": "/api/lumi/status", "roles": ROLES,
     "description": "Consultar o estado do pedido desta conversa e recuperar seu link atual. Só confirme pagamento se o estado for paid. Não consulta pedidos de outras conversas nem por CPF.",
     "parameters": {"type": "object", "properties": {"quote_id": TOKEN}, "required": ["quote_id"], "additionalProperties": False}},
]
