"""Snapshots correntes indexáveis usados pelas rotas de status."""

from datetime import datetime, timezone

from services.firestore_service import consultar_documentos, obter_documento, upsert_documento
from services.propriedade_service import validar_id


PROPERTY_COLLECTION = "property_risk_current"
MACHINE_COLLECTION = "machine_state_current"


class SnapshotService:
    def __init__(self, firebase):
        self.firebase = firebase

    def _args(self):
        self.firebase.initialize()
        return self.firebase.firestore_url, self.firebase.obter_token

    def get_property(self, fazenda_id):
        validar_id(fazenda_id)
        return obter_documento(*self._args(), PROPERTY_COLLECTION, fazenda_id)

    def save_property(self, fazenda_id, document):
        validar_id(fazenda_id)
        payload = {key: value for key, value in document.items() if key != "id"}
        payload.update({"fazendaId": fazenda_id, "updatedAt": datetime.now(timezone.utc)})
        return upsert_documento(*self._args(), PROPERTY_COLLECTION, fazenda_id, payload)

    def list_properties(self, limit=100):
        return consultar_documentos(*self._args(), PROPERTY_COLLECTION, {}, "updatedAt", "DESCENDING", limit)

    def get_machine(self, fazenda_id, maquina_id):
        validar_id(fazenda_id); validar_id(maquina_id, "maquinaId")
        return obter_documento(*self._args(), MACHINE_COLLECTION, f"{fazenda_id}__{maquina_id}")

    def save_machine(self, fazenda_id, maquina_id, document):
        validar_id(fazenda_id); validar_id(maquina_id, "maquinaId")
        payload = {key: value for key, value in document.items() if key != "id"}
        payload.update({"fazendaId": fazenda_id, "maquinaId": maquina_id,
                        "updatedAt": datetime.now(timezone.utc)})
        return upsert_documento(*self._args(), MACHINE_COLLECTION, f"{fazenda_id}__{maquina_id}", payload)

    def list_machines(self, fazenda_id, limit=100):
        validar_id(fazenda_id)
        return consultar_documentos(*self._args(), MACHINE_COLLECTION, {"fazendaId": fazenda_id},
                                    "updatedAt", "DESCENDING", limit)

    def list_machines_attention(self, limit=100):
        return consultar_documentos(*self._args(), MACHINE_COLLECTION, {"attention": True},
                                    "updatedAt", "DESCENDING", limit)
