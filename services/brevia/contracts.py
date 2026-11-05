CONTRACT = {
    "name": "consultar_projetos_contratos",
    "description": "Consultar um relatório atual dos projetos, contratos, horas contratadas, horas consumidas, atividades e situação da Lumi. Use quando pedirem andamento ou relatório de um cliente. O servidor restringe o cliente consultável pelo papel cadastrado. Não substitui o faturamento do negócio do cliente.",
    "path": "/reports/projects",
    "roles": ["gestor", "administrador"],
    "parameters": {"type": "object", "additionalProperties": False,
        "properties": {"client": {"type": ["string", "null"], "maxLength": 160},
            "start_date": {"type": ["string", "null"], "format": "date"},
            "end_date": {"type": ["string", "null"], "format": "date"}},
        "required": ["client", "start_date", "end_date"]},
}
