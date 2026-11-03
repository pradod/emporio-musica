"""Loop do agente: LLM via API compatível com OpenAI + execução de ferramentas."""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field

from openai import OpenAI

from . import ferramentas
from .config import agora, config_llm
from .prompt import montar_prompt

MAX_RODADAS_FERRAMENTAS = 6
MAX_MENSAGENS_HISTORICO = 40
RE_PENSAMENTO = re.compile(r"<think>.*?</think>", re.DOTALL)
RE_VALOR = re.compile(r"R\$\s?\d[\d.]*,\d{2}")


@dataclass
class ChamadaFerramenta:
    nome: str
    argumentos: dict
    resultado: dict


@dataclass
class Resposta:
    texto: str
    chamadas: list[ChamadaFerramenta] = field(default_factory=list)
    revisada: bool = False


def _limpar(texto: str | None) -> str:
    return RE_PENSAMENTO.sub("", texto or "").strip()


def _valores_sem_origem(texto: str, historico: list[dict]) -> list[str]:
    """Valores em R$ citados na resposta que não aparecem em nenhum resultado de ferramenta."""
    fontes = " ".join(m["content"] for m in historico if m["role"] == "tool")
    return [v for v in RE_VALOR.findall(texto) if v.replace(" ", "") not in fontes.replace(" ", "")]


def _recortar(historico: list[dict]) -> list[dict]:
    """Mantém as mensagens mais recentes, começando sempre numa mensagem do usuário."""
    if len(historico) <= MAX_MENSAGENS_HISTORICO:
        return historico
    recorte = historico[-MAX_MENSAGENS_HISTORICO:]
    while recorte and recorte[0]["role"] != "user":
        recorte = recorte[1:]
    return recorte


class Agente:
    def __init__(self, historico: list[dict] | None = None):
        cfg = config_llm()
        self.cfg = cfg
        self.cliente = OpenAI(base_url=cfg.base_url, api_key=cfg.api_key)
        self.extra_body = json.loads(os.getenv("LLM_EXTRA_BODY", "") or "{}")
        self.historico: list[dict] = historico or []

    def _completar(self) -> object:
        mensagens = [{"role": "system", "content": montar_prompt(agora())}, *_recortar(self.historico)]
        resposta = self.cliente.chat.completions.create(
            model=self.cfg.modelo,
            messages=mensagens,
            tools=ferramentas.SCHEMAS,
            temperature=self.cfg.temperatura,
            extra_body=self.extra_body or None,
        )
        return resposta.choices[0].message

    def responder(self, mensagem_usuario: str) -> Resposta:
        self.historico.append({"role": "user", "content": mensagem_usuario})
        resultado = Resposta(texto="")
        indice_rascunho: int | None = None

        for _ in range(MAX_RODADAS_FERRAMENTAS):
            msg = self._completar()
            if msg.tool_calls:
                self.historico.append({
                    "role": "assistant",
                    "content": _limpar(msg.content),
                    "tool_calls": [
                        {"id": c.id, "type": "function", "function": {"name": c.function.name, "arguments": c.function.arguments}}
                        for c in msg.tool_calls
                    ],
                })
                for chamada in msg.tool_calls:
                    try:
                        argumentos = json.loads(chamada.function.arguments or "{}")
                        saida = ferramentas.executar(chamada.function.name, argumentos)
                    except json.JSONDecodeError:
                        argumentos, saida = {}, {"erro": "Argumentos não são JSON válido."}
                    resultado.chamadas.append(ChamadaFerramenta(chamada.function.name, argumentos, saida))
                    self.historico.append({
                        "role": "tool",
                        "tool_call_id": chamada.id,
                        "content": json.dumps(saida, ensure_ascii=False),
                    })
                continue

            texto = _limpar(msg.content)
            # Guarda-corpo: valor em R$ que não veio de nenhuma ferramenta = possível alucinação.
            # Pede uma revisão (uma vez só) antes de entregar ao cliente.
            suspeitos = _valores_sem_origem(texto, self.historico)
            if suspeitos and indice_rascunho is None:
                resultado.revisada = True
                indice_rascunho = len(self.historico)
                self.historico.append({"role": "assistant", "content": texto})
                self.historico.append({
                    "role": "user",
                    "content": (
                        "[verificação automática do sistema, não é o cliente] Os valores "
                        f"{', '.join(suspeitos)} não vieram de nenhuma ferramenta. Consulte as ferramentas "
                        "e reescreva a resposta ao cliente usando apenas valores retornados por elas."
                    ),
                })
                continue

            if indice_rascunho is not None:
                # Remove o rascunho e a nota de verificação; o histórico guarda só a versão final.
                del self.historico[indice_rascunho:indice_rascunho + 2]
            self.historico.append({"role": "assistant", "content": texto})
            resultado.texto = texto
            return resultado

        resultado.texto = (
            "Desculpa, me enrolei aqui pra encontrar essa informação. "
            "Pode reformular a pergunta ou, se preferir, te passo para um atendente da equipe."
        )
        self.historico.append({"role": "assistant", "content": resultado.texto})
        return resultado
