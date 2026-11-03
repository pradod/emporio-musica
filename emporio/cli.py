"""Interface de linha de comando para conversar com o agente."""

import argparse
import json

import openai

from . import historico
from .agente import Agente
from .config import agora, config_llm

CINZA, NEGRITO, FIM = "\033[2m", "\033[1m", "\033[0m"

AJUDA = """Comandos: /nova (apaga o histórico desta sessão), /rastreio (liga/desliga as chamadas de ferramenta), /sair"""


def _resumir(resultado: dict, limite: int = 140) -> str:
    texto = json.dumps(resultado, ensure_ascii=False)
    return texto if len(texto) <= limite else texto[:limite] + "…"


def main() -> None:
    parser = argparse.ArgumentParser(description="Toni — assistente virtual da Empório da Música")
    parser.add_argument("--sessao", default="padrao", help="nome da sessão; o histórico é salvo em .historico/")
    parser.add_argument("--sem-rastreio", action="store_true", help="não mostra as chamadas de ferramentas")
    args = parser.parse_args()

    cfg = config_llm()
    agente = Agente(historico.carregar(args.sessao))
    rastreio = not args.sem_rastreio

    print(f"{NEGRITO}Empório da Música — Sua música começa aqui.{FIM}")
    print(f"{CINZA}modelo: {cfg.modelo} @ {cfg.base_url} | data de referência: {agora():%d/%m/%Y %H:%M} | sessão: {args.sessao}")
    if agente.historico:
        print(f"histórico retomado ({len(agente.historico)} mensagens)")
    print(f"{AJUDA}{FIM}\n")

    while True:
        try:
            mensagem = input(f"{NEGRITO}Você:{FIM} ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not mensagem:
            continue
        if mensagem == "/sair":
            break
        if mensagem == "/nova":
            historico.apagar(args.sessao)
            agente.historico = []
            print(f"{CINZA}(histórico apagado){FIM}\n")
            continue
        if mensagem == "/rastreio":
            rastreio = not rastreio
            print(f"{CINZA}(rastreio {'ligado' if rastreio else 'desligado'}){FIM}\n")
            continue

        tamanho = len(agente.historico)
        try:
            resposta = agente.responder(mensagem)
        except openai.APIConnectionError:
            print(f"\n[erro] Não consegui conectar em {cfg.base_url}. O servidor do modelo está rodando? (ex.: `ollama serve`)\n")
            del agente.historico[tamanho:]
            continue
        except openai.APIStatusError as exc:
            print(f"\n[erro] O provedor respondeu {exc.status_code}: {exc.message}\n")
            del agente.historico[tamanho:]
            continue

        if rastreio:
            for c in resposta.chamadas:
                print(f"{CINZA}  ↳ {c.nome}({json.dumps(c.argumentos, ensure_ascii=False)}) → {_resumir(c.resultado)}{FIM}")
            if resposta.revisada:
                print(f"{CINZA}  ↳ (resposta revisada pelo verificador de valores){FIM}")
        print(f"{NEGRITO}Toni:{FIM} {resposta.texto}\n")
        historico.salvar(args.sessao, agente.historico)


if __name__ == "__main__":
    main()
