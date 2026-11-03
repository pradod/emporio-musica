"""Manual de políticas, curado em markdown e dividido por tópico.

O PDF original tem 8 páginas: em vez de RAG com embeddings, o agente escolhe
o tópico explicitamente via ferramenta (ver README).
"""

from functools import lru_cache

from .config import DIR_POLITICAS

TOPICOS = {
    "loja_contato_horario": "Sobre a loja, o que vendemos (e o que não vendemos), endereço, telefone, e-mail e horário de funcionamento",
    "pagamento_parcelamento": "Formas de pagamento, desconto no PIX, parcelamento no cartão, combinação de pagamentos",
    "trocas_devolucoes": "Direito de arrependimento, devolução, troca por defeito, troca por preferência, itens sem troca",
    "frete_entrega": "Frete, prazos de entrega, Correios/Jadlog, rastreamento, produto avariado",
    "promocoes": "Campanhas promocionais, regras de desconto, cumulatividade, promoção expirada",
    "garantia": "Garantia legal e de fabricante, o que a garantia não cobre",
    "privacidade_dados": "LGPD, uso e exclusão de dados pessoais",
}


@lru_cache(maxsize=None)
def ler(topico: str) -> str:
    if topico not in TOPICOS:
        raise ValueError(f"tópico desconhecido: {topico}. Opções: {', '.join(TOPICOS)}")
    return (DIR_POLITICAS / f"{topico}.md").read_text(encoding="utf-8")
