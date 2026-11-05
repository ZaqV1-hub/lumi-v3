"""Contrato público para correção de dados, sem incluir valores enviados."""
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.responses import JSONResponse

BUYER_FIELDS = {"name", "cpf", "phone", "email", "quote_id"}
BUSINESS_FIELDS = {"whatsapp_necessario": "phone", "cpf_precisa_ser_informado_pelo_comprador": "cpf"}


def invalid_data(fields):
    return {"ok": False, "error": "dados_invalidos", "invalid_fields": fields}


async def buyer_validation(request, exc):
    if request.url.path != "/commerce/purchase":
        return await request_validation_exception_handler(request, exc)
    fields = []
    for error in exc.errors():
        loc = error.get("loc", ())
        if len(loc) != 3 or tuple(loc[:2]) != ("body", "arguments") or loc[2] not in BUYER_FIELDS:
            return JSONResponse(status_code=422, content={"error": "parametros_invalidos"})
        item = {"field": loc[2], "reason": "required" if error["type"] == "missing" else "invalid"}
        if item not in fields:
            fields.append(item)
    return JSONResponse(status_code=422, content=invalid_data(fields))
