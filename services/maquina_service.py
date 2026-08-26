"""Domínio de máquinas e perfis semânticos de sensores."""

import math
from datetime import datetime, timezone

from services.firestore_service import atualizar_documento, consultar_documentos, criar_documento, obter_documento
from services.propriedade_service import validar_id
from services.unit_service import (
    KNOWN_UNITS, UnitValidationError, validate_metadata, validate_sensor_metadata, validate_sensor_unit,
)


COLECAO = "maquinas"
SCOPES = {"ambient_local", "machine_internal", "machine_component", "soil", "other", "unknown"}
UNIDADES = KNOWN_UNITS
CAMPOS = {"nome", "tipo", "fabricante", "modelo", "ano", "status", "possuiGps", "latitude", "longitude",
          "lastLocationAt", "sensoresConfigurados", "metadata"}


class ValidacaoMaquinaError(ValueError):
    pass


def _texto(dados, campo, obrigatorio=False, maximo=200):
    valor = dados.get(campo)
    if valor is None and not obrigatorio:
        return None
    if not isinstance(valor, str) or not valor.strip() or len(valor.strip()) > maximo:
        raise ValidacaoMaquinaError(f"'{campo}' deve ser texto não vazio com até {maximo} caracteres.")
    return valor.strip()


def _instante(valor, campo):
    if valor is None:
        return None
    if isinstance(valor, datetime):
        if valor.tzinfo is None:
            raise ValidacaoMaquinaError(f"'{campo}' deve ter fuso horário.")
        return valor.astimezone(timezone.utc)
    if isinstance(valor, str):
        try:
            instante = datetime.fromisoformat(valor.replace("Z", "+00:00"))
            if instante.tzinfo is None:
                raise ValueError
            return instante.astimezone(timezone.utc)
        except ValueError as erro:
            raise ValidacaoMaquinaError(f"'{campo}' deve ser timestamp ISO 8601 com fuso horário.") from erro
    raise ValidacaoMaquinaError(f"'{campo}' deve ser timestamp válido.")


def _sensor(item):
    if not isinstance(item, dict):
        raise ValidacaoMaquinaError("Cada sensor deve ser um objeto.")
    permitidos = {"sensorId", "type", "scope", "target", "unit", "thresholds", "metadata"}
    if set(item) - permitidos:
        raise ValidacaoMaquinaError("Sensor contém campos inesperados.")
    try:
        sensor_id = validar_id(item.get("sensorId"), "sensorId")
    except ValueError as erro:
        raise ValidacaoMaquinaError(str(erro)) from erro
    tipo = _texto(item, "type", True, 80)
    scope = item.get("scope", "unknown")
    unidade = item.get("unit", "unknown")
    if scope not in SCOPES:
        raise ValidacaoMaquinaError("'scope' do sensor é inválido.")
    if unidade not in UNIDADES:
        raise ValidacaoMaquinaError("'unit' do sensor é inválida.")
    try:
        validate_sensor_unit(tipo, unidade)
    except UnitValidationError as erro:
        raise ValidacaoMaquinaError(str(erro)) from erro
    thresholds = item.get("thresholds")
    valores = []
    if thresholds is not None:
        if not isinstance(thresholds, dict) or set(thresholds) - {"warning", "high", "critical"}:
            raise ValidacaoMaquinaError("'thresholds' deve conter apenas warning, high e critical.")
        valores = [thresholds.get(chave) for chave in ("warning", "high", "critical") if thresholds.get(chave) is not None]
        if any(not isinstance(v, (int, float)) or isinstance(v, bool) or not math.isfinite(v) for v in valores):
            raise ValidacaoMaquinaError("Thresholds devem ser números finitos.")
        if valores != sorted(valores):
            raise ValidacaoMaquinaError("Thresholds devem estar em ordem crescente.")
    metadata = item.get("metadata", {})
    try:
        validate_sensor_metadata(metadata)
    except UnitValidationError as erro:
        raise ValidacaoMaquinaError(str(erro)) from erro
    valid_range = metadata.get("validRange")
    if valid_range and any(not valid_range["min"] <= value <= valid_range["max"] for value in valores):
        raise ValidacaoMaquinaError("Thresholds devem estar dentro de metadata.validRange.")
    return {"sensorId": sensor_id, "type": tipo, "scope": scope,
            "target": _texto(item, "target", False, 100), "unit": unidade,
            "thresholds": thresholds, "metadata": metadata}


def validar_maquina(dados):
    if not isinstance(dados, dict) or set(dados) - CAMPOS:
        raise ValidacaoMaquinaError("Payload de máquina inválido ou contém campos inesperados.")
    possui_gps = dados.get("possuiGps", False)
    if not isinstance(possui_gps, bool):
        raise ValidacaoMaquinaError("'possuiGps' deve ser booleano.")
    latitude, longitude = dados.get("latitude"), dados.get("longitude")
    for nome, valor, minimo, maximo in (("latitude", latitude, -90, 90), ("longitude", longitude, -180, 180)):
        if valor is not None and (not isinstance(valor, (int, float)) or isinstance(valor, bool) or not math.isfinite(valor) or not minimo <= valor <= maximo):
            raise ValidacaoMaquinaError(f"'{nome}' está fora da faixa válida.")
    if (latitude is None) != (longitude is None):
        raise ValidacaoMaquinaError("Latitude e longitude devem ser informadas juntas.")
    ano = dados.get("ano")
    if ano is not None and (not isinstance(ano, int) or isinstance(ano, bool) or not 1900 <= ano <= 2200):
        raise ValidacaoMaquinaError("'ano' é inválido.")
    sensores = dados.get("sensoresConfigurados", [])
    if not isinstance(sensores, list) or len(sensores) > 100:
        raise ValidacaoMaquinaError("'sensoresConfigurados' deve ser lista com até 100 itens.")
    sensor_profiles = [_sensor(item) for item in sensores]
    sensor_ids = [item["sensorId"] for item in sensor_profiles]
    if len(sensor_ids) != len(set(sensor_ids)):
        raise ValidacaoMaquinaError("sensorId deve ser único dentro da máquina.")
    metadata = dados.get("metadata", {})
    try:
        validate_metadata(metadata)
    except UnitValidationError as erro:
        raise ValidacaoMaquinaError(str(erro)) from erro
    return {"nome": _texto(dados, "nome", True), "tipo": _texto(dados, "tipo", True, 100),
            "fabricante": _texto(dados, "fabricante"), "modelo": _texto(dados, "modelo"), "ano": ano,
            "status": _texto(dados, "status", True, 50), "possuiGps": possui_gps,
            "latitude": latitude, "longitude": longitude,
            "lastLocationAt": _instante(dados.get("lastLocationAt"), "lastLocationAt"),
            "sensoresConfigurados": sensor_profiles, "metadata": metadata}


class MaquinaService:
    def __init__(self, firebase, propriedade_service):
        self.firebase, self.propriedades = firebase, propriedade_service

    def _args(self):
        self.firebase.initialize()
        return self.firebase.firestore_url, self.firebase.obter_token

    @staticmethod
    def _doc_id(fazenda_id, maquina_id):
        validar_id(fazenda_id); validar_id(maquina_id, "maquinaId")
        return f"{fazenda_id}__{maquina_id}"

    def criar(self, fazenda_id, maquina_id, dados):
        if self.propriedades.obter(fazenda_id) is None:
            return None
        validado = validar_maquina(dados); agora = datetime.now(timezone.utc)
        validado.update({"fazendaId": fazenda_id, "maquinaId": maquina_id, "createdAt": agora, "updatedAt": agora})
        return criar_documento(*self._args(), COLECAO, self._doc_id(fazenda_id, maquina_id), validado)

    def obter(self, fazenda_id, maquina_id):
        return obter_documento(*self._args(), COLECAO, self._doc_id(fazenda_id, maquina_id))

    def listar(self, fazenda_id):
        validar_id(fazenda_id)
        return consultar_documentos(*self._args(), COLECAO, {"fazendaId": fazenda_id}, "updatedAt", limite=100)

    def atualizar(self, fazenda_id, maquina_id, alteracoes):
        atual = self.obter(fazenda_id, maquina_id)
        if atual is None: return None
        base = {k: v for k, v in atual.items() if k in CAMPOS}; base.update(alteracoes)
        validado = validar_maquina(base)
        if atual.get("demoData") is True:
            validado["demoData"] = True
        validado.update({"fazendaId": fazenda_id, "maquinaId": maquina_id,
            "createdAt": atual["createdAt"], "updatedAt": datetime.now(timezone.utc)})
        return atualizar_documento(*self._args(), COLECAO, self._doc_id(fazenda_id, maquina_id), validado)
