import json
import unicodedata
from datetime import datetime, timedelta
from urllib.parse import urlencode
from zoneinfo import ZoneInfo
from .http import get
from .search import public_query

CONDITIONS = {0:"céu limpo", 1:"predominantemente limpo", 2:"parcialmente nublado", 3:"nublado",
    45:"nevoeiro", 48:"nevoeiro com geada", 51:"garoa leve", 53:"garoa moderada", 55:"garoa intensa",
    56:"garoa congelante leve", 57:"garoa congelante intensa", 61:"chuva leve", 63:"chuva moderada",
    65:"chuva forte", 66:"chuva congelante leve", 67:"chuva congelante forte", 71:"neve leve",
    73:"neve moderada", 75:"neve intensa", 77:"grãos de neve", 80:"pancadas leves de chuva",
    81:"pancadas moderadas de chuva", 82:"pancadas fortes de chuva", 85:"pancadas leves de neve",
    86:"pancadas fortes de neve", 95:"trovoadas", 96:"trovoadas com granizo", 99:"trovoadas com granizo forte"}


def today(timezone):
    return datetime.now(ZoneInfo(timezone)).date()


def forecast(arguments):
    place = public_query(arguments.place)
    params = {"name": place, "count": 4, "language": "pt"}
    if arguments.country_code: params["countryCode"] = arguments.country_code
    matches = json.loads(get("https://geocoding-api.open-meteo.com/v1/search", params)).get("results", [])
    def normalized(text):
        return "".join(c for c in unicodedata.normalize("NFD", text.casefold()) if not unicodedata.combining(c))
    city = normalized(place.split(",")[0].strip())
    exact = [m for m in matches if normalized(m["name"]) == city and m.get("feature_code", "PPL").startswith("PPL")]
    if exact:
        unique = {}
        for match in sorted(exact, key=lambda m: m.get("population", 0), reverse=True):
            key = (normalized(match["name"]), match.get("admin1"), match.get("country_code"))
            unique.setdefault(key, match)
        matches = list(unique.values())
    if not matches:
        return {"ok": False, "error": "cidade_nao_encontrada", "instruction": "Peça a cidade e o estado/região. Não invente coordenadas."}
    if len(matches) > 1:
        return {"ok": False, "error": "localizacao_ambigua", "candidates": [
            {"city": m["name"], "region": m.get("admin1"), "country": m.get("country")} for m in matches[:4]],
            "instruction": "Confirme a cidade e o estado/região antes de consultar. Use um nome qualificado, como Cidade, Estado."}
    location = matches[0]; timezone = location.get("timezone", "UTC")
    start = arguments.start_date; end = arguments.end_date or start
    current = today(timezone); maximum = current + timedelta(days=15)
    if start < current or end > maximum:
        return {"ok": False, "error": "data_fora_da_previsao", "available_from": current.isoformat(),
                "available_until": maximum.isoformat(),
                "instruction": "Não há previsão disponível para essa data nesta fonte. Informe o limite retornado e sugira consultar mais perto da visita. Nunca invente a previsão ou substitua por média histórica."}
    if end < start or (end-start).days > 6:
        return {"ok": False, "error": "periodo_invalido", "instruction": "Consulte um período em ordem crescente, de até sete dias."}
    query = {"latitude": location["latitude"], "longitude": location["longitude"], "timezone": timezone,
             "start_date": start.isoformat(), "end_date": end.isoformat(),
             "daily": "weather_code,temperature_2m_min,temperature_2m_max,precipitation_probability_max,precipitation_sum"}
    url = "https://api.open-meteo.com/v1/forecast"
    data = json.loads(get(url, query)); daily = data.get("daily", {})
    days = []
    for i, day in enumerate(daily.get("time", [])):
        def value(key):
            values = daily.get(key, [])
            return values[i] if i < len(values) else None
        code = value("weather_code")
        days.append({"date": day, "condition": CONDITIONS.get(code, "condição não informada"),
                     "temperature_min_c": value("temperature_2m_min"), "temperature_max_c": value("temperature_2m_max"),
                     "rain_probability_percent": value("precipitation_probability_max"), "rain_mm": value("precipitation_sum")})
    return {"ok": bool(days), "provider": "Open-Meteo", "location": {"city": location["name"],
                "region": location.get("admin1"), "country": location.get("country"), "timezone": timezone},
            "days": days, "source": {"title": "Open-Meteo"},
            "instruction": "Responda com os dados meteorológicos retornados e as datas; mencione o nome da fonte sem URL técnica. Previsão pode mudar: chance de chuva não é garantia. Não deduza políticas de abertura ou funcionamento da empresa. Campo null significa informação indisponível."}
