"""Trilha de auditoria separada de logs técnicos e telemetria."""

from datetime import datetime, timezone

from services.firestore_service import salvar_documento


class AuditService:
    def __init__(self, firebase):
        self.firebase = firebase

    def _args(self):
        self.firebase.initialize()
        return self.firebase.firestore_url, self.firebase.obter_token

    def record(self, action, resource_type, resource_id, actor, request_id, changes=None):
        return salvar_documento(*self._args(), "audit_log", {
            "action": action, "resourceType": resource_type, "resourceId": resource_id,
            "actor": actor or {"kind": "system", "actorId": "system"},
            "requestId": request_id, "changes": changes or {}, "createdAt": datetime.now(timezone.utc),
        })
