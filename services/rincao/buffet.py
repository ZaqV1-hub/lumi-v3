import os
from datetime import timedelta
import pymysql
from .config import required


# Critério encontrado no buffet.repository.ts do serviço rincao-dados em homologação.
VALUE = """COALESCE(e.ValFixoBuffet, 0)
 + COALESCE(COALESCE(NULLIF(e.NumConvidadosRed, 0), e.NumConvidados), 0)
 * COALESCE(NULLIF(e.ValConvidadoRed, 0), e.ValConvidado, 0)
 - COALESCE(e.ValDesconto, 0)"""
DATE_COLUMNS = {"evento": "e.DatEvento", "contrato": "e.DatContrato"}


def query_revenue(start, end, date_base, representative):
    # Única interpolação estrutural: coluna escolhida por uma enumeração fixa.
    date_column = DATE_COLUMNS[date_base]
    where = f"{date_column} >= %s AND {date_column} < %s"
    params = [start, end + timedelta(days=1)]
    if representative:
        where += " AND LOCATE(UPPER(%s), UPPER(COALESCE(p.NomPessoa, ''))) > 0"
        params.append(representative)
    sql = f"""SELECT e.NidResponsavelEvento AS representative_id,
        NULLIF(TRIM(p.NomPessoa), '') AS representative,
        COUNT(*) AS events, ROUND(COALESCE(SUM({VALUE}), 0), 2) AS total
        FROM tevento e
        LEFT JOIN tpessoa p ON p.NidPessoa = e.NidResponsavelEvento
        WHERE {where}
        GROUP BY e.NidResponsavelEvento, p.NomPessoa
        ORDER BY total DESC, representative_id
        LIMIT 101"""
    connection = pymysql.connect(host=required("BUFFET_DB_HOST"),
        port=int(os.getenv("BUFFET_DB_PORT", "3306")), database=required("BUFFET_DB_NAME"),
        user=required("BUFFET_DB_USER"), password=required("BUFFET_DB_PASSWORD"),
        connect_timeout=5, read_timeout=8, write_timeout=8, charset="utf8",
        cursorclass=pymysql.cursors.DictCursor, autocommit=False)
    try:
        with connection.cursor() as cursor:
            cursor.execute(sql, params)
            rows = cursor.fetchall()
    finally:
        connection.rollback()
        connection.close()
    if len(rows) > 100:
        raise RuntimeError("Consulta ampla demais")
    return {"source": "buffet", "start_date": start, "end_date": end,
        "date_base": date_base, "representative_filter": representative,
        "events": sum(row["events"] for row in rows),
        "total": sum((row["total"] for row in rows), start=0), "currency": "BRL",
        "by_representative": rows,
        "criterion": "Valor fixo + convidados e preço ajustados (quando presentes) - desconto, conforme relatório de eventos existente. Inclui todos os status de evento, como esse relatório. Não representa dinheiro recebido nem fluxo de caixa."}
