import os
import psycopg
from psycopg.rows import dict_row
from .config import required


# Mesmas tabelas de preço e tipos públicos do catálogo do site de homologação.
AGENDA_SQL = """SELECT a.dtagenda AS date, a.stagenda AS status, a.tpagenda AS type,
       t.vlnormal AS adult_online, t.vlinfant AS child_online,
       t.vlnormalbil AS adult_gate, t.vlinfantbil AS child_gate
FROM agenda a
LEFT JOIN tabpreco t ON t.idtabpreco = a.idtabpreco
WHERE a.dtagenda >= %s AND a.dtagenda <= %s
  AND a.tpagenda IN ('padra', 'promo')
ORDER BY a.dtagenda, a.idagenda
LIMIT 101
"""


def query_agenda(start, end):
    with psycopg.connect(host=required("INGRESSO_SISTEMA_DB_HOST"),
        port=int(os.getenv("INGRESSO_SISTEMA_DB_PORT", "5432")),
        dbname=required("INGRESSO_SISTEMA_DB_NAME"), user=required("INGRESSO_SISTEMA_DB_USER"),
        password=required("INGRESSO_SISTEMA_DB_PASSWORD"),
        sslmode="require" if os.getenv("INGRESSO_SISTEMA_DB_SSL") == "true" else "disable",
        connect_timeout=5, options="-c default_transaction_read_only=on -c statement_timeout=5000",
        row_factory=dict_row) as connection:
        rows = connection.execute(AGENDA_SQL, (start, end)).fetchall()
    items = []
    for row in rows[:100]:
        status = {"abe": "aberta", "fec": "fechada", "lot": "lotada"}.get(row["status"], "desconhecida")
        items.append({"date": row["date"], "status": status,
            "type": "promocional" if row["type"] == "promo" else "padrão",
            "prices": {key: row[key] for key in ("adult_online", "child_online", "adult_gate", "child_gate")}
                      if status == "aberta" else None})
    return {"source": "site de ingressos", "start_date": start, "end_date": end,
            "currency": "BRL", "items": items, "truncated": len(rows) > 100,
            "scope": "Datas públicas padrão/promocionais; passeios escolares privados não incluídos. Sem registro não significa aberto. Preço ausente não significa gratuito."}
