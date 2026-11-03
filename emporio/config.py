"""Configuração lida do ambiente (.env)."""

import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

RAIZ = Path(__file__).resolve().parent.parent
DIR_DADOS = RAIZ / "data"
DIR_POLITICAS = RAIZ / "knowledge" / "politicas"
DIR_HISTORICO = RAIZ / ".historico"

load_dotenv(RAIZ / ".env")


@dataclass(frozen=True)
class ConfigLLM:
    base_url: str
    api_key: str
    modelo: str
    temperatura: float


def config_llm() -> ConfigLLM:
    return ConfigLLM(
        base_url=os.getenv("LLM_BASE_URL", "http://localhost:11434/v1"),
        api_key=os.getenv("LLM_API_KEY", "ollama"),
        modelo=os.getenv("LLM_MODEL", "qwen3:14b"),
        temperatura=float(os.getenv("LLM_TEMPERATURE", "0.2")),
    )


def agora() -> datetime:
    """Data/hora de referência do agente.

    EMPORIO_DATA_REFERENCIA permite "congelar" o relógio, já que os dados
    da loja são um retrato que termina em março de 2026.
    """
    ref = os.getenv("EMPORIO_DATA_REFERENCIA", "").strip()
    if not ref:
        return datetime.now()
    if "T" not in ref:
        ref += "T10:00"
    return datetime.fromisoformat(ref)
