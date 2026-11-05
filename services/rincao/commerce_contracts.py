from .contracts import CONTRACTS

ROLES = ["cliente", "gestor", "atendente"]
CONTRACTS.extend([
    {"name": "consultar_compra_ingressos", "description": "Consultar o estado atual ou recuperar o link de pagamento de uma compra desta conversa usando seu quote_id. Use também quando pedirem o pedido anterior ou o link novamente: o serviço informa o endereço atual ou que o prazo expirou; não reutilize links e diagnósticos antigos do histórico. Mesmo se o cliente disser que pagou, só confirme após o serviço verificar a Cielo e registrar os ingressos. Não consulte compras de outras pessoas por CPF.",
     "path": "/commerce/status", "roles": ROLES, "parameters": {"type": "object", "properties": {
        "quote_id": {"type": "string", "minLength": 20, "maxLength": 80}}, "required": ["quote_id"], "additionalProperties": False}},
    {"name": "cotar_ingressos", "description": "Calcular internamente o total da compra solicitada de ingressos Day Use, com data e quantidades de adultos, infantis e isentos. Quando a pessoa já pediu a compra e as escolhas estão definidas, faça esse cálculo sem perguntar se ela quer uma cotação. Cotação é uma etapa técnica, não um serviço adicional a oferecer ao cliente. Não precisa de CPF para calcular. O serviço fornece preços atuais, total e quote_id. Evite confirmações repetidas das mesmas escolhas e valores; depois da escolha, peça apenas nome, CPF e WhatsApp que ainda faltarem. Não peça cartão nem senha.",
     "path": "/commerce/quote", "roles": ROLES, "parameters": {
        "type": "object", "properties": {
            "visit_date": {"type": "string", "pattern": "^[0-9]{4}-[0-9]{2}-[0-9]{2}$"},
            "ticket_type": {"type": "string", "enum": ["padrao", "promo"]},
            **{key: {"type": "integer", "minimum": 0, "maximum": 100} for key in ["adults", "children", "exempt"]}},
        "required": ["visit_date", "ticket_type", "adults", "children", "exempt"], "additionalProperties": False}},
    {"name": "criar_compra_ingressos", "description": "Preparar compra escolhida explicitamente após cotação: quote_id, nome e CPF válido. Somente no canal WhatsApp o telefone vem automaticamente; no Instagram e simulador peça o WhatsApp com DDD se ainda não foi informado pelo comprador. Não deduza telefone de nome ou identificador do Instagram. Se houver dados_invalidos, peça novamente somente o campo rejeitado sem alterar os demais dados ou escolhas. O preço vem do sistema; registra pedido pendente pelo CPF e devolve link Cielo. Não afirme que está pago nem gere ingressos pelo chat. Se o checkout estiver indisponível, explique e não invente link.",
     "path": "/commerce/purchase", "roles": ROLES, "parameters": {
        "type": "object", "properties": {
            "quote_id": {"type": "string", "minLength": 20, "maxLength": 80},
            "name": {"type": "string", "minLength": 2, "maxLength": 120},
            "cpf": {"type": "string", "minLength": 11, "maxLength": 14},
            "phone": {"type": ["string", "null"], "maxLength": 20},
            "email": {"type": ["string", "null"], "maxLength": 120}},
        "required": ["quote_id", "name", "cpf", "phone", "email"], "additionalProperties": False}},
])
