"""Explicit official weather ingestion; dashboard reads never create notifications."""
import json


def run():
    from server import propriedades, snapshots, alerts, consultar_avisos_inmet
    feed = consultar_avisos_inmet()
    if feed.get("status") != "ok":
        raise RuntimeError("weather_feed_unavailable")
    count = 0
    for prop in propriedades.listar(100):
        if prop.get("demoData") or str(prop.get("fazendaId", "")).startswith("demo_"):
            continue
        results = alerts.evaluate_weather(prop, (feed.get("dados") or {}).get("items", []),
                                          snapshots.get_property(prop["fazendaId"]))
        count += len(results)
    return {"matchedAlerts": count, "scope": "up to 100 properties; exact municipality/UF only", "delivered": False}


if __name__ == "__main__":
    try:
        print(json.dumps(run()))
    except Exception:
        raise SystemExit("Weather ingestion unavailable; check server configuration and official feed.") from None
