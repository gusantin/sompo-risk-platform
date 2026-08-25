"""Cache simples em memória, adequado ao protótipo acadêmico."""

from copy import deepcopy
from datetime import datetime, timedelta, timezone
from threading import Lock


class CacheMemoria:
    def __init__(self):
        self._itens = {}
        self._lock = Lock()

    def obter(self, chave):
        agora = datetime.now(timezone.utc)
        with self._lock:
            item = self._itens.get(chave)
            if not item or item[0] <= agora:
                self._itens.pop(chave, None)
                return None
            return deepcopy(item[1])

    def salvar(self, chave, valor, ttl_segundos):
        expira_em = datetime.now(timezone.utc) + timedelta(seconds=ttl_segundos)
        with self._lock:
            self._itens[chave] = (expira_em, deepcopy(valor))


cache = CacheMemoria()


def chave_coordenada(prefixo, latitude, longitude, casas=3):
    return f"{prefixo}:{round(latitude, casas)}:{round(longitude, casas)}"

