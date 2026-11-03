"""Persistência simples do histórico de conversa (um JSON por sessão)."""

import json
import re

from .config import DIR_HISTORICO


def _arquivo(sessao: str):
    nome = re.sub(r"[^\w-]", "_", sessao)
    return DIR_HISTORICO / f"sessao_{nome}.json"


def carregar(sessao: str) -> list[dict]:
    caminho = _arquivo(sessao)
    if not caminho.exists():
        return []
    return json.loads(caminho.read_text(encoding="utf-8"))


def salvar(sessao: str, mensagens: list[dict]) -> None:
    DIR_HISTORICO.mkdir(exist_ok=True)
    _arquivo(sessao).write_text(json.dumps(mensagens, ensure_ascii=False, indent=1), encoding="utf-8")


def apagar(sessao: str) -> None:
    _arquivo(sessao).unlink(missing_ok=True)
