"""Refresh canonical evidence and choose first valid municipality, never by risk."""
import json
from copy import deepcopy
from config import Config
from services.live_case_service import LiveCaseService
from services.presentation_portfolio_service import configured_portfolio, PORTFOLIO, SECOND_PROPERTY


def capture():
    service = configured_portfolio()
    previous = service.read(Config.PRESENTATION_PORTFOLIO_PATH)
    identities = list(PORTFOLIO) + [c["property"] for c in previous.get("cases", [])
        if c["id"] not in {p["fazendaId"] for p in PORTFOLIO} and c["id"] != SECOND_PROPERTY["fazendaId"]]
    result = service.capture(previous, identities=identities)
    attempts = []
    second = None
    for city, code in [("Sorriso", "5107925"), ("Lucas do Rio Verde", "5105259"), ("Rondonópolis", "5107602")]:
        identity = {**SECOND_PROPERTY, "municipio": city, "ibgeCode": code}
        candidate = service.capture(identities=[identity])["cases"][0]
        usable = candidate.get("dataCoverage", {}).get("weatherAvailable") and candidate["risk"].get("score") is not None
        attempts.append({"municipality": city, "valid": bool(usable)})
        if second is None:
            second = deepcopy(candidate)
        if usable:
            second = candidate
            break
    result["cases"].append(second)
    result["secondPropertyAcquisition"] = attempts
    LiveCaseService.save_snapshot(result, Config.PRESENTATION_PORTFOLIO_PATH)
    print(json.dumps({"attempts": attempts, "cases": [{"property": c["property"], "risk": c["risk"],
        "provenance": c["provenance"], "sourceHealth": c["sourceHealth"]} for c in result["cases"]]}, ensure_ascii=False))


if __name__ == "__main__":
    capture()
