"""Testa o loop do agente com um LLM falso (sem rede)."""

import json
from types import SimpleNamespace

from emporio.agente import Agente


def _msg(conteudo=None, chamadas=None):
    tool_calls = [
        SimpleNamespace(id=f"c{i}", function=SimpleNamespace(name=n, arguments=json.dumps(a)))
        for i, (n, a) in enumerate(chamadas or [])
    ]
    return SimpleNamespace(content=conteudo, tool_calls=tool_calls or None)


class LLMFalso:
    def __init__(self, roteiro):
        self.roteiro = list(roteiro)
        self.recebidas = []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **kwargs):
        self.recebidas.append(kwargs["messages"])
        return SimpleNamespace(choices=[SimpleNamespace(message=self.roteiro.pop(0))])


def _agente(roteiro):
    agente = Agente()
    agente.cliente = LLMFalso(roteiro)
    return agente


def test_executa_ferramenta_e_responde():
    agente = _agente([
        _msg(chamadas=[("detalhes_produto", {"produto": "Takamine GD20"})]),
        _msg("<think>ok</think>O Takamine GD20 sai por R$ 2.199,00 😉"),
    ])
    r = agente.responder("Quanto custa o Takamine GD20?")
    assert r.texto == "O Takamine GD20 sai por R$ 2.199,00 😉"
    assert [c.nome for c in r.chamadas] == ["detalhes_produto"]
    assert [m["role"] for m in agente.historico] == ["user", "assistant", "tool", "assistant"]


def test_valor_inventado_dispara_revisao_e_some_do_historico():
    agente = _agente([
        _msg("O Takamine GD20 custa R$ 1.500,00."),  # sem consultar nada
        _msg(chamadas=[("detalhes_produto", {"produto": "Takamine GD20"})]),
        _msg("O Takamine GD20 custa R$ 2.199,00."),
    ])
    r = agente.responder("Quanto custa o Takamine GD20?")
    assert r.revisada and r.texto == "O Takamine GD20 custa R$ 2.199,00."
    conteudos = " ".join(str(m.get("content")) for m in agente.historico)
    assert "1.500,00" not in conteudos and "verificação automática" not in conteudos
    assert agente.historico[-1]["role"] == "assistant"


def test_prompt_de_sistema_traz_contexto_do_momento(monkeypatch):
    monkeypatch.setenv("EMPORIO_DATA_REFERENCIA", "2026-03-29T15:00")  # domingo
    agente = _agente([_msg("Oi! Como posso ajudar?")])
    agente.responder("oi")
    sistema = agente.cliente.recebidas[0][0]["content"]
    assert "domingo, 29/03/2026" in sistema and "FECHADA" in sistema
