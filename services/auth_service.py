"""Autenticação modular da API de aplicação."""

import hashlib
import hmac


class ApplicationAuthService:
    """Provider simples de API key, substituível futuramente por JWT/Firebase Auth."""

    def authenticate(self, authorization, api_keys):
        if not authorization or not authorization.startswith("Bearer "):
            return None
        candidate = authorization[7:]
        if not candidate:
            return None
        for expected in api_keys:
            if hmac.compare_digest(candidate.encode("utf-8"), expected.encode("utf-8")):
                actor = hashlib.sha256(candidate.encode("utf-8")).hexdigest()[:16]
                return {"kind": "application", "actorId": f"api_key:{actor}"}
        return None
