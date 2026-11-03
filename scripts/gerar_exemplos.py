"""Roda conversas roteirizadas contra o modelo configurado e grava em exemplos/*.md.

Uso:  python scripts/gerar_exemplos.py            (todos)
      python scripts/gerar_exemplos.py 2 4        (só os cenários 2 e 4)
"""

import json
import os
import sys
from pathlib import Path

import openai

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Os dados terminam em 22/03/2026; congelamos "hoje" logo depois para os exemplos fazerem sentido.
os.environ.setdefault("EMPORIO_DATA_REFERENCIA", "2026-03-25T10:30")

from emporio.agente import Agente  # noqa: E402
from emporio.config import RAIZ, agora, config_llm  # noqa: E402

CENARIOS = [
    (
        "catalogo_violoes",
        "Busca no catálogo com filtro de preço",
        [
            "Oi! Quais opções de violões disponíveis custando até R$1000?",
            "Legal! Desses, qual você indicaria pra um iniciante que quer tocar MPB?",
        ],
    ),
    (
        "preco_pagamento_promocao",
        "Preço, PIX, parcelamento e promoção encerrada",
        [
            "Quanto custa o Takamine GD20?",
            "Vi que ele tinha uma oferta especial de 12%, ainda tá valendo?",
            "E se eu pagar no PIX? Dá pra parcelar no cartão também?",
        ],
    ),
    (
        "loja_e_fora_de_escopo",
        "Informações da loja, acessórios e pergunta fora do escopo",
        [
            "Qual o endereço da loja? Sábado vocês abrem até que horas?",
            "Vocês vendem encordoamento e amplificador?",
            "Beleza. Aproveitando, me ajuda a resolver uma equação do segundo grau?",
        ],
    ),
    (
        "devolucao_e_garantia",
        "Arrependimento fora do prazo, aplicação das políticas e encaminhamento",
        [
            "Me arrependi da minha compra, posso devolver meu pedido?",
            "É o pedido 7, meu telefone é (67) 99789-0123",
            "Na verdade o ukulele começou a trastejar sozinho, acho que é defeito",
            "Pode registrar sim, por favor",
        ],
    ),
    (
        "pedido_atrasado",
        "Rastreio de pedido atrasado com validação de identidade",
        [
            "Boa tarde, cadê meu pedido? Já era pra ter chegado",
            "Pedido 8, e-mail anacarol.ferreira@coldmail.com",
            "Pode sim, obrigada",
        ],
    ),
]


def rodar(indice: int, slug: str, titulo: str, falas: list[str]) -> Path:
    cfg = config_llm()
    agente = Agente()
    linhas = [
        f"# Exemplo {indice} — {titulo}",
        "",
        f"> Gerado por `scripts/gerar_exemplos.py` · modelo `{cfg.modelo}` · "
        f"data de referência {agora():%d/%m/%Y %H:%M} (quarta-feira)",
        "",
    ]
    for fala in falas:
        resposta = agente.responder(fala)
        linhas += [f"**Cliente:** {fala}", ""]
        if resposta.chamadas:
            linhas += ["<details><summary>🔧 ferramentas chamadas</summary>", ""]
            for c in resposta.chamadas:
                linhas += [
                    f"- `{c.nome}({json.dumps(c.argumentos, ensure_ascii=False)})`",
                    "",
                    "  ```json",
                    *(f"  {l}" for l in json.dumps(c.resultado, ensure_ascii=False, indent=1).splitlines()),
                    "  ```",
                ]
            if resposta.revisada:
                linhas.append("- _resposta revisada pelo verificador de valores_")
            linhas += ["", "</details>", ""]
        linhas += [f"**Toni:** {resposta.texto}", "", "---", ""]
        print(f"[{indice}] cliente: {fala}\n[{indice}] toni: {resposta.texto}\n")

    destino = RAIZ / "exemplos" / f"{indice:02d}_{slug}.md"
    destino.write_text("\n".join(linhas), encoding="utf-8")
    return destino


def main() -> None:
    escolhidos = {int(a) for a in sys.argv[1:]} or set(range(1, len(CENARIOS) + 1))
    for i, (slug, titulo, falas) in enumerate(CENARIOS, start=1):
        if i in escolhidos:
            try:
                print(f"→ {rodar(i, slug, titulo, falas)}")
            except openai.APIConnectionError:
                sys.exit(f"Não consegui conectar em {config_llm().base_url}. O servidor do modelo está rodando?")


if __name__ == "__main__":
    main()
