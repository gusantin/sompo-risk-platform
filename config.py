"""Configuração central da aplicação, carregada do ambiente e de .env local."""

import os
from pathlib import Path

from dotenv import load_dotenv


BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")


def _float_env(nome, padrao):
    try:
        return float(os.getenv(nome, padrao))
    except ValueError as erro:
        raise ValueError(f"{nome} deve ser numérico.") from erro


def _bool_env(nome, padrao="false"):
    return os.getenv(nome, padrao).strip().lower() == "true"


class Config:
    API_CONTRACT_VERSION = os.getenv("API_CONTRACT_VERSION", "1")
    ENVIRONMENT = os.getenv("ENVIRONMENT", "development")
    HOST = os.getenv("HOST", "0.0.0.0")
    PORT = int(os.getenv("PORT", "5000"))
    CORS_ALLOWED_ORIGINS = tuple(x.strip() for x in os.getenv("CORS_ALLOWED_ORIGINS", "").split(",") if x.strip())
    APP_API_KEYS = tuple(x.strip() for x in os.getenv("APP_API_KEYS", "").split(",") if x.strip())
    ALLOW_DEV_AUTH_BYPASS = _bool_env("ALLOW_DEV_AUTH_BYPASS")
    ALLOW_DEV_DEVICE_BYPASS = _bool_env("ALLOW_DEV_DEVICE_BYPASS")
    FIREBASE_KEY_PATH = os.getenv("FIREBASE_KEY_PATH", str(BASE_DIR / "firebase-key.json"))
    TEMPERATURA_MIN_C = _float_env("TEMPERATURA_MIN_C", "-40")
    TEMPERATURA_MAX_C = _float_env("TEMPERATURA_MAX_C", "85")
    IDENTIFICADOR_MAX_LENGTH = int(os.getenv("IDENTIFICADOR_MAX_LENGTH", "100"))
    JSON_MAX_BYTES = int(os.getenv("JSON_MAX_BYTES", "16384"))
    MAX_MEASUREMENTS = int(os.getenv("MAX_MEASUREMENTS", "50"))
    DEVICE_TOKEN_HASH_ITERATIONS = int(os.getenv("DEVICE_TOKEN_HASH_ITERATIONS", "120000"))
    DEVICE_STALE_AFTER_SECONDS = int(os.getenv("DEVICE_STALE_AFTER_SECONDS", "300"))
    DEVICE_OFFLINE_AFTER_SECONDS = int(os.getenv("DEVICE_OFFLINE_AFTER_SECONDS", "1800"))
    IOT_RATE_LIMIT_REQUESTS = int(os.getenv("IOT_RATE_LIMIT_REQUESTS", "120"))
    IOT_RATE_LIMIT_WINDOW_SECONDS = int(os.getenv("IOT_RATE_LIMIT_WINDOW_SECONDS", "60"))
    EXPENSIVE_RATE_LIMIT_REQUESTS = int(os.getenv("EXPENSIVE_RATE_LIMIT_REQUESTS", "10"))
    EXPENSIVE_RATE_LIMIT_WINDOW_SECONDS = int(os.getenv("EXPENSIVE_RATE_LIMIT_WINDOW_SECONDS", "60"))
    ALERT_COOLDOWN_SECONDS = int(os.getenv("ALERT_COOLDOWN_SECONDS", "3600"))
    ALERT_HOTSPOT_DISTANCE_KM = _float_env("ALERT_HOTSPOT_DISTANCE_KM", "5")
    ALERT_HOTSPOT_CRITICAL_DISTANCE_KM = _float_env("ALERT_HOTSPOT_CRITICAL_DISTANCE_KM", "1")
    HOTSPOT_MAX_AGE_HOURS = _float_env("HOTSPOT_MAX_AGE_HOURS", "24")
    OPERATIONAL_HOTSPOT_DISTANCE_KM = _float_env("OPERATIONAL_HOTSPOT_DISTANCE_KM", "10")
    EVENT_SIGNIFICANT_SCORE_DELTA = _float_env("EVENT_SIGNIFICANT_SCORE_DELTA", "15")
    IOT_MAX_AGE_MINUTES = int(os.getenv("IOT_MAX_AGE_MINUTES", "15"))
    IOT_MAX_AGE_SECONDS = int(os.getenv("IOT_MAX_AGE_SECONDS", str(IOT_MAX_AGE_MINUTES * 60)))
    MACHINE_LOCATION_MAX_AGE_SECONDS = int(os.getenv("MACHINE_LOCATION_MAX_AGE_SECONDS", "900"))
    TELEMETRY_DEFAULT_LIMIT = int(os.getenv("TELEMETRY_DEFAULT_LIMIT", "20"))
    TELEMETRY_MAX_LIMIT = int(os.getenv("TELEMETRY_MAX_LIMIT", "100"))
    PROPERTY_TELEMETRY_QUERY_LIMIT = int(os.getenv("PROPERTY_TELEMETRY_QUERY_LIMIT", "1000"))
    RISK_HISTORY_DEFAULT_LIMIT = int(os.getenv("RISK_HISTORY_DEFAULT_LIMIT", "20"))
    RISK_HISTORY_MAX_LIMIT = int(os.getenv("RISK_HISTORY_MAX_LIMIT", "100"))
    REGIONAL_CACHE_TTL_SECONDS = int(os.getenv("REGIONAL_CACHE_TTL_SECONDS", "1800"))
    REGIONAL_MAX_CONCURRENCY = int(os.getenv("REGIONAL_MAX_CONCURRENCY", "4"))
    REGIONAL_MAX_LOCATIONS = int(os.getenv("REGIONAL_MAX_LOCATIONS", "20"))
    REGIONAL_JOB_MAX_LOCATIONS = int(os.getenv("REGIONAL_JOB_MAX_LOCATIONS", "300"))
    REGIONAL_READ_MAX_LIMIT = int(os.getenv("REGIONAL_READ_MAX_LIMIT", "200"))
    REGIONAL_STALE_AFTER_SECONDS = int(os.getenv("REGIONAL_STALE_AFTER_SECONDS", "7200"))
    EXTERNAL_API_BUDGET_SECONDS = _float_env("EXTERNAL_API_BUDGET_SECONDS", "25")
    LIVE_CASE_SNAPSHOT_PATH = os.getenv("LIVE_CASE_SNAPSHOT_PATH", str(BASE_DIR / "data" / "live_showcase_cases.json"))
    LIVE_CASE_MAX_AGE_SECONDS = int(os.getenv("LIVE_CASE_MAX_AGE_SECONDS", "21600"))
    LIVE_CASE_MONITORED_STATES = tuple(x.strip().upper() for x in os.getenv(
        "LIVE_CASE_MONITORED_STATES", "MT,MS,GO,MG,PR").split(",") if x.strip())
    LIVE_CASE_MAX_WORKERS = int(os.getenv("LIVE_CASE_MAX_WORKERS", "3"))
    LLM_PROVIDER = os.getenv("LLM_PROVIDER", "ollama").strip().lower()
    OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434").strip()
    OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3.2:3b").strip()
    SOMPO_AGENT_TIMEOUT_SECONDS = _float_env("SOMPO_AGENT_TIMEOUT_SECONDS", "120")
    ENABLE_FIREBASE_TEST_ROUTE = _bool_env("ENABLE_FIREBASE_TEST_ROUTE")


if Config.DEVICE_STALE_AFTER_SECONDS > Config.DEVICE_OFFLINE_AFTER_SECONDS:
    raise ValueError("DEVICE_STALE_AFTER_SECONDS deve ser menor ou igual a DEVICE_OFFLINE_AFTER_SECONDS.")
if Config.ALERT_HOTSPOT_CRITICAL_DISTANCE_KM > Config.ALERT_HOTSPOT_DISTANCE_KM:
    raise ValueError("ALERT_HOTSPOT_CRITICAL_DISTANCE_KM deve ser menor ou igual a ALERT_HOTSPOT_DISTANCE_KM.")
if Config.HOTSPOT_MAX_AGE_HOURS <= 0:
    raise ValueError("HOTSPOT_MAX_AGE_HOURS deve ser positivo.")
if Config.JSON_MAX_BYTES <= 0 or not 1 <= Config.MAX_MEASUREMENTS <= 100:
    raise ValueError("Limites de payload inválidos.")
if Config.DEVICE_TOKEN_HASH_ITERATIONS < 100_000:
    raise ValueError("DEVICE_TOKEN_HASH_ITERATIONS deve ser pelo menos 100000.")
if any(len(key) < 16 for key in Config.APP_API_KEYS):
    raise ValueError("Cada APP_API_KEY deve ter pelo menos 16 caracteres.")
if Config.LIVE_CASE_MAX_AGE_SECONDS <= 0 or not 1 <= Config.LIVE_CASE_MAX_WORKERS <= 4:
    raise ValueError("Configuração de casos reais inválida.")
if (Config.SOMPO_AGENT_TIMEOUT_SECONDS <= 0 or not Config.LLM_PROVIDER
        or not Config.OLLAMA_URL or not Config.OLLAMA_MODEL):
    raise ValueError("Configuração do agente contextual inválida.")
