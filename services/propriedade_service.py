"""Domínio e persistência de propriedades rurais."""

import math
import re
from datetime import datetime, timezone

from services.firestore_service import (
    atualizar_documento, criar_documento, listar_documentos, obter_documento,
)


COLECAO = "fazendas"
ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,99}$")
ESTADOS = {
    "AC", "AL", "AP", "AM", "BA", "CE", "DF", "ES", "GO", "MA", "MT",
    "MS", "MG", "PA", "PB", "PR", "PE", "PI", "RJ", "RN", "RS", "RO",
    "RR", "SC", "SP", "SE", "TO",
}
PROPERTY_FIELDS = {
    "nome", "municipio", "estado", "latitude", "longitude", "poligonoGeoJson", "areaHectares",
    "atividadePrincipal", "culturas", "irrigacao", "tipoSolo", "texturaSolo", "riscoEncharcamento",
    "riscoAtolamento", "decliveAcentuado", "riscoErosao", "presencaPalhadaVegetacaoSeca",
    "historicoIncendio", "historicoPrincipioIncendioMaquinas", "pontosAreasCriticas",
    "descricaoPontosCriticos", "quantidadeMaquinas", "tiposMaquinas", "maquinasComGps",
    "riscosPrioritarios", "acaoAlertaCritico",
}


class ValidacaoPropriedadeError(ValueError):
    pass


def validar_id(valor, nome="fazendaId"):
    if not isinstance(valor, str) or not ID_PATTERN.fullmatch(valor):
        raise ValidacaoPropriedadeError(
            f"{nome} deve ter 1 a 100 caracteres alfanuméricos, '_' ou '-'."
        )
    return valor


def _texto(dados, campo, obrigatorio=False, maximo=300):
    valor = dados.get(campo)
    if valor is None and not obrigatorio:
        return None
    if not isinstance(valor, str) or not valor.strip():
        raise ValidacaoPropriedadeError(f"'{campo}' deve ser texto não vazio.")
    valor = valor.strip()
    if len(valor) > maximo:
        raise ValidacaoPropriedadeError(f"'{campo}' excede {maximo} caracteres.")
    return valor


def _booleano(dados, campo):
    valor = dados.get(campo)
    if valor is not None and not isinstance(valor, bool):
        raise ValidacaoPropriedadeError(f"'{campo}' deve ser booleano.")
    return valor


def _lista_textos(dados, campo, max_itens=50):
    valor = dados.get(campo, [])
    if not isinstance(valor, list) or len(valor) > max_itens:
        raise ValidacaoPropriedadeError(f"'{campo}' deve ser uma lista com até {max_itens} itens.")
    if any(not isinstance(item, str) or not item.strip() or len(item) > 100 for item in valor):
        raise ValidacaoPropriedadeError(f"'{campo}' contém item inválido.")
    return [item.strip() for item in valor]


def _culturas(valor):
    if valor is None:
        return []
    if not isinstance(valor, list) or len(valor) > 50:
        raise ValidacaoPropriedadeError("'culturas' deve ser uma lista com até 50 itens.")
    resultado = []
    for item in valor:
        if isinstance(item, str):
            item = {"nome": item}
        if not isinstance(item, dict):
            raise ValidacaoPropriedadeError("Cada cultura deve ser texto ou objeto.")
        allowed = {"nome", "areaHectares", "estagioSafra", "observacoes", "safra",
                   "vigenteDesde", "vigenteAte", "atual"}
        if set(item) - allowed:
            raise ValidacaoPropriedadeError("Cultura contém campos inesperados.")
        nome = _texto(item, "nome", obrigatorio=True, maximo=100)
        cultura = {"nome": nome}
        if item.get("areaHectares") is not None:
            area = item["areaHectares"]
            if not isinstance(area, (int, float)) or isinstance(area, bool) or area < 0:
                raise ValidacaoPropriedadeError("'areaHectares' da cultura deve ser não negativa.")
            cultura["areaHectares"] = area
        for campo in ("estagioSafra", "observacoes", "safra", "vigenteDesde", "vigenteAte"):
            if item.get(campo) is not None:
                cultura[campo] = _texto(item, campo, maximo=500)
        if item.get("atual") is not None:
            if not isinstance(item["atual"], bool):
                raise ValidacaoPropriedadeError("'atual' da cultura deve ser booleano.")
            cultura["atual"] = item["atual"]
        resultado.append(cultura)
    return resultado


def validar_propriedade(dados):
    if not isinstance(dados, dict) or set(dados) - PROPERTY_FIELDS:
        raise ValidacaoPropriedadeError("Corpo JSON inválido.")
    latitude = dados.get("latitude")
    longitude = dados.get("longitude")
    if not isinstance(latitude, (int, float)) or isinstance(latitude, bool) or not math.isfinite(latitude) or not -90 <= latitude <= 90:
        raise ValidacaoPropriedadeError("'latitude' deve estar entre -90 e 90.")
    if not isinstance(longitude, (int, float)) or isinstance(longitude, bool) or not math.isfinite(longitude) or not -180 <= longitude <= 180:
        raise ValidacaoPropriedadeError("'longitude' deve estar entre -180 e 180.")
    area = dados.get("areaHectares")
    if not isinstance(area, (int, float)) or isinstance(area, bool) or not math.isfinite(area) or area <= 0:
        raise ValidacaoPropriedadeError("'areaHectares' deve ser maior que zero.")
    estado = _texto(dados, "estado", obrigatorio=True, maximo=2).upper()
    if estado not in ESTADOS:
        raise ValidacaoPropriedadeError("'estado' deve ser uma UF brasileira válida.")
    quantidade = dados.get("quantidadeMaquinas", 0)
    if not isinstance(quantidade, int) or isinstance(quantidade, bool) or quantidade < 0:
        raise ValidacaoPropriedadeError("'quantidadeMaquinas' deve ser inteiro não negativo.")
    poligono = dados.get("poligonoGeoJson")
    if poligono is not None and (
        not isinstance(poligono, dict)
        or poligono.get("type") not in ("Polygon", "MultiPolygon")
        or not isinstance(poligono.get("coordinates"), list)
    ):
        raise ValidacaoPropriedadeError("'poligonoGeoJson' deve ser Polygon ou MultiPolygon GeoJSON.")
    if poligono is not None:
        poligonos = [poligono["coordinates"]] if poligono["type"] == "Polygon" else poligono["coordinates"]
        try:
            for pol in poligonos:
                if not pol: raise ValueError
                for anel in pol:
                    if len(anel) < 4 or anel[0] != anel[-1]: raise ValueError
                    for ponto in anel:
                        if (len(ponto) < 2 or not all(isinstance(v, (int, float)) and not isinstance(v, bool)
                                and math.isfinite(v) for v in ponto[:2])): raise ValueError
                        if not -180 <= ponto[0] <= 180 or not -90 <= ponto[1] <= 90: raise ValueError
        except (TypeError, ValueError):
            raise ValidacaoPropriedadeError("'poligonoGeoJson' contém geometria inválida.")
    resultado = {
        "nome": _texto(dados, "nome", obrigatorio=True, maximo=200),
        "municipio": _texto(dados, "municipio", obrigatorio=True, maximo=150),
        "estado": estado, "latitude": latitude, "longitude": longitude,
        "pontoCentral": {"latitude": latitude, "longitude": longitude},
        "poligonoGeoJson": poligono, "areaHectares": area,
        "atividadePrincipal": _texto(dados, "atividadePrincipal", obrigatorio=True, maximo=150),
        "culturas": _culturas(dados.get("culturas")),
        "irrigacao": _booleano(dados, "irrigacao"),
        "tipoSolo": _texto(dados, "tipoSolo", maximo=100),
        "texturaSolo": _texto(dados, "texturaSolo", maximo=100),
        "riscoEncharcamento": _booleano(dados, "riscoEncharcamento"),
        "riscoAtolamento": _booleano(dados, "riscoAtolamento"),
        "decliveAcentuado": _booleano(dados, "decliveAcentuado"),
        "riscoErosao": _booleano(dados, "riscoErosao"),
        "presencaPalhadaVegetacaoSeca": _booleano(dados, "presencaPalhadaVegetacaoSeca"),
        "historicoIncendio": _booleano(dados, "historicoIncendio"),
        "historicoPrincipioIncendioMaquinas": _booleano(dados, "historicoPrincipioIncendioMaquinas"),
        "pontosAreasCriticas": _lista_textos(dados, "pontosAreasCriticas"),
        "descricaoPontosCriticos": _texto(dados, "descricaoPontosCriticos", maximo=2000),
        "quantidadeMaquinas": quantidade,
        "tiposMaquinas": _lista_textos(dados, "tiposMaquinas"),
        "maquinasComGps": _booleano(dados, "maquinasComGps"),
        "riscosPrioritarios": _lista_textos(dados, "riscosPrioritarios"),
        "acaoAlertaCritico": _texto(dados, "acaoAlertaCritico", maximo=1000),
    }
    return resultado


class PropriedadeService:
    def __init__(self, firebase):
        self.firebase = firebase

    def _args(self):
        self.firebase.initialize()
        return self.firebase.firestore_url, self.firebase.obter_token

    def criar(self, fazenda_id, dados):
        validar_id(fazenda_id)
        validado = validar_propriedade(dados)
        agora = datetime.now(timezone.utc)
        validado.update({"fazendaId": fazenda_id, "createdAt": agora, "updatedAt": agora})
        return criar_documento(*self._args(), COLECAO, fazenda_id, validado)

    def obter(self, fazenda_id):
        validar_id(fazenda_id)
        return obter_documento(*self._args(), COLECAO, fazenda_id)

    def listar(self, limite=100):
        limite = int(limite)
        if not 1 <= limite <= 100:
            raise ValidacaoPropriedadeError("limit deve estar entre 1 e 100.")
        return listar_documentos(*self._args(), COLECAO, limite)

    def atualizar(self, fazenda_id, alteracoes):
        atual = self.obter(fazenda_id)
        if atual is None:
            return None
        base = {chave: valor for chave, valor in atual.items() if chave in PROPERTY_FIELDS}
        base.update(alteracoes)
        validado = validar_propriedade(base)
        if atual.get("demoData") is True:
            validado["demoData"] = True
        validado["fazendaId"] = fazenda_id
        validado["createdAt"] = atual["createdAt"]
        validado["updatedAt"] = datetime.now(timezone.utc)
        return atualizar_documento(*self._args(), COLECAO, fazenda_id, validado)
