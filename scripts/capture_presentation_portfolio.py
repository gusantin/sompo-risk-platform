"""Capture real providers for three fictional fixed properties; no Firebase or Telegram writes."""
import argparse
import json
from config import Config
from services.presentation_portfolio_service import configured_portfolio
from services.live_case_service import LiveCaseService

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()
    service = configured_portfolio()
    payload = service.capture(service.read(Config.PRESENTATION_PORTFOLIO_PATH))
    if args.write:
        LiveCaseService.save_snapshot(payload, Config.PRESENTATION_PORTFOLIO_PATH)
    print(json.dumps({"mode": payload["mode"], "cases": [{"property": c["property"], "riskType": c["riskType"], "risk": c["risk"], "provenance": c["provenance"]} for c in payload["cases"]]}, ensure_ascii=False, indent=2))
