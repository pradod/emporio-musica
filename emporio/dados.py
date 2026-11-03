"""Carga, limpeza e regras de negócio sobre os CSVs da loja.

Tudo que envolve número (preço, desconto, parcela, prazo) é calculado aqui,
em Python, e nunca pelo LLM.
"""

from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from functools import lru_cache

import pandas as pd

from .config import DIR_DADOS

PREFIXO_CSV = "desafio_tecnico_ai_eng - "

# Regras do manual de políticas (seções 3, 4, 6 e 8).
DESCONTO_PIX = 0.05
FAIXAS_PARCELAMENTO = [(3, 50.0), (6, 80.0), (12, 100.0)]  # (até N parcelas, parcela mínima)
DIAS_ARREPENDIMENTO = 7
DIAS_TROCA_PREFERENCIA = 7
DIAS_TROCA_DEFEITO = 30
DIAS_GARANTIA_LEGAL = 90

PALAVRAS_VAZIAS = {"de", "da", "do", "com", "para", "um", "uma", "o", "a", "e", "em", "the"}

MARCAS = [
    "music man", "yamaha", "tagima", "giannini", "rozini", "shelby", "crafter",
    "martin", "taylor", "takamine", "kala", "ohana", "kalani", "fender", "gibson",
    "ibanez", "prs", "pearl", "tama", "korg", "nord", "roland",
]

STATUS_PEDIDO = {
    "pending": "aguardando confirmação do pagamento",
    "confirmed": "pagamento confirmado, em separação para envio",
    "shipped": "enviado (em transporte)",
    "delivered": "entregue",
    "cancelled": "cancelado",
}

PAGAMENTOS = {
    "pix": "PIX",
    "debit": "cartão de débito",
    "boleto": "boleto bancário",
}

DISPONIBILIDADE = {
    "disponivel": "disponível em estoque",
    "esgotado": "temporariamente esgotado",
    "fora_de_linha": "fora de linha (não faz mais parte do catálogo)",
    "em_breve": "em breve (ainda não disponível para venda)",
}


def normalizar(texto: str) -> str:
    """Minúsculas, sem acentos e sem pontuação, para buscas tolerantes."""
    texto = unicodedata.normalize("NFKD", str(texto)).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", " ", texto.lower()).strip()


def com_singulares(texto_normalizado: str) -> str:
    """Acrescenta formas no singular ("violoes" -> "violao", "teclados" -> "teclado")."""
    extras = []
    for palavra in texto_normalizado.split():
        if palavra.endswith("oes"):
            extras.append(palavra[:-3] + "ao")
        elif palavra.endswith("s") and len(palavra) > 3:
            extras.append(palavra[:-1])
    return " ".join([texto_normalizado, *extras])


def so_digitos(texto: str) -> str:
    return re.sub(r"\D", "", str(texto))


def _ler(nome: str) -> pd.DataFrame:
    return pd.read_csv(DIR_DADOS / f"{PREFIXO_CSV}{nome}.csv")


def _marca(texto_normalizado: str) -> str | None:
    for marca in MARCAS:
        if re.search(rf"\b{marca}\b", texto_normalizado):
            return marca
    return None


def _descricao_confiavel(nome: str, descricao: str, specs: dict) -> bool:
    """Detecta descrições que contradizem o próprio produto.

    Alguns itens (ex.: "Music Man Bass 1X", descrito como "Fender Jazz Bass")
    têm descrição de outro instrumento. Nesses casos o agente usa só os campos
    estruturados (nome, preço, estoque, specs).
    """
    marca_nome = _marca(normalizar(nome))
    desc = normalizar(descricao)
    outras = {m for m in MARCAS if re.search(rf"\b{m}\b", desc)} - {marca_nome}
    if outras:
        return False
    cordas = re.search(r"(\d+) cordas", desc)
    if cordas and str(specs.get("strings", "")).isdigit() and cordas.group(1) != specs["strings"]:
        return False
    return True


def _disponibilidade(status: str, estoque: int) -> str:
    if status == "discontinued":
        return "fora_de_linha"
    if status == "coming_soon":
        return "em_breve"
    return "disponivel" if estoque > 0 else "esgotado"


def parcelamento_maximo(valor: float) -> tuple[int, float]:
    """Maior número de parcelas sem juros respeitando a parcela mínima de cada faixa."""
    melhor = 1
    for n in range(2, 13):
        minimo = next(m for limite, m in FAIXAS_PARCELAMENTO if n <= limite)
        if valor / n >= minimo:
            melhor = n
    return melhor, round(valor / melhor, 2)


def descrever_pagamento(codigo: str) -> str:
    if codigo.startswith("credit_"):
        return f"cartão de crédito em {codigo.removeprefix('credit_')}"
    return PAGAMENTOS.get(codigo, codigo)


@dataclass
class Loja:
    produtos: pd.DataFrame
    categorias: pd.DataFrame
    pedidos: pd.DataFrame
    itens: pd.DataFrame
    clientes: pd.DataFrame
    promocoes: pd.DataFrame

    # ---------- produtos ----------

    def produto(self, produto_id: int) -> pd.Series | None:
        linhas = self.produtos[self.produtos.product_id == produto_id]
        return None if linhas.empty else linhas.iloc[0]

    def encontrar_produtos(self, consulta: str, limite: int = 5) -> pd.DataFrame:
        """Busca por nome tolerante a acento/caixa; ordena por nº de termos encontrados."""
        termos = [t for t in normalizar(consulta).split() if len(t) > 1 and t not in PALAVRAS_VAZIAS]
        if not termos:
            return self.produtos.head(0)
        nomes = self.produtos.nome_busca
        pontos = sum(nomes.str.contains(rf"\b{re.escape(t)}", regex=True).astype(int) for t in termos)
        achados = self.produtos.assign(_pontos=pontos)
        achados = achados[achados._pontos > 0]
        # Exige a maioria dos termos para não devolver qualquer "Yamaha" ao buscar "Yamaha C40".
        minimo = max(1, (len(termos) + 1) // 2)
        achados = achados[achados._pontos >= minimo]
        return achados.sort_values(["_pontos", "preco_final"], ascending=[False, True]).head(limite)

    def alternativas(self, produto: pd.Series, limite: int = 3) -> pd.DataFrame:
        """Itens vendáveis da mesma categoria com preço próximo."""
        candidatos = self.produtos[
            (self.produtos.category_id == produto.category_id)
            & (self.produtos.vendavel)
            & (self.produtos.product_id != produto.product_id)
        ]
        distancia = (candidatos.preco_final - produto.price_brl).abs()
        return candidatos.assign(_dist=distancia).sort_values("_dist").head(limite)

    # ---------- clientes e pedidos ----------

    def clientes_por_contato(self, contato: str) -> pd.DataFrame:
        contato = contato.strip()
        if "@" in contato:
            return self.clientes[self.clientes.email.str.lower() == contato.lower()]
        digitos = so_digitos(contato)
        if len(digitos) < 8:
            return self.clientes.head(0)
        return self.clientes[self.clientes.telefone_digitos.str.endswith(digitos[-9:] if len(digitos) >= 9 else digitos)]

    def pedido(self, pedido_id: int) -> pd.Series | None:
        linhas = self.pedidos[self.pedidos.order_id == pedido_id]
        return None if linhas.empty else linhas.iloc[0]

    def itens_do_pedido(self, pedido_id: int) -> pd.DataFrame:
        itens = self.itens[self.itens.order_id == pedido_id]
        return itens.merge(self.produtos[["product_id", "name"]], on="product_id", how="left")


def prazos_pos_venda(pedido: pd.Series, hoje: date) -> dict:
    """Prazos de devolução, troca e garantia de um pedido entregue.

    Suposição: não há data real de entrega nos dados; usamos a
    estimated_delivery como data de recebimento.
    """
    compra = pedido.order_date.date()
    recebimento = pedido.estimated_delivery.date()

    def prazo(inicio: date, dias: int, referencia: str) -> dict:
        limite = inicio + timedelta(days=dias)
        return {
            "conta_a_partir_de": f"{referencia} ({inicio:%d/%m/%Y})",
            "prazo_dias": dias,
            "valido_ate": f"{limite:%d/%m/%Y}",
            "dentro_do_prazo": hoje <= limite,
        }

    return {
        "data_recebimento_considerada": f"{recebimento:%d/%m/%Y}",
        "arrependimento_devolucao": prazo(recebimento, DIAS_ARREPENDIMENTO, "recebimento"),
        "troca_por_preferencia": prazo(recebimento, DIAS_TROCA_PREFERENCIA, "recebimento"),
        "troca_por_defeito_na_loja": prazo(compra, DIAS_TROCA_DEFEITO, "compra"),
        "garantia_legal_defeito": prazo(recebimento, DIAS_GARANTIA_LEGAL, "recebimento"),
    }


def status_loja(momento: datetime) -> dict:
    """Aberta/fechada agora e quando abre (seção 2 do manual; feriados não são conhecidos)."""
    horarios = {d: (9, 18) for d in range(5)} | {5: (9, 13)}
    dias = ["segunda", "terça", "quarta", "quinta", "sexta", "sábado", "domingo"]
    abre_fecha = horarios.get(momento.weekday())
    aberta = bool(abre_fecha) and abre_fecha[0] <= momento.hour < abre_fecha[1]
    if aberta:
        return {"aberta": True, "fecha_as": f"{abre_fecha[1]:02d}:00"}
    for delta in range(0, 8):
        dia = momento + timedelta(days=delta)
        faixa = horarios.get(dia.weekday())
        if faixa and (delta > 0 or momento.hour < faixa[0]):
            quando = "hoje" if delta == 0 else "amanhã" if delta == 1 else dias[dia.weekday()]
            return {"aberta": False, "proxima_abertura": f"{quando} às {faixa[0]:02d}:00"}
    return {"aberta": False}


@lru_cache(maxsize=1)
def carregar() -> Loja:
    categorias = _ler("categories")
    promocoes = _ler("promotions")
    clientes = _ler("customers")
    pedidos = _ler("orders")
    itens = _ler("order_items")
    produtos = _ler("products")

    # --- produtos ---
    produtos["specs"] = produtos.specs.apply(json.loads)
    produtos["created_at"] = pd.to_datetime(produtos.created_at)
    produtos = produtos.merge(
        categorias.rename(columns={"name": "categoria", "description": "categoria_descricao"}),
        on="category_id",
        how="left",
    )
    produtos["disponibilidade"] = [
        _disponibilidade(s, e) for s, e in zip(produtos.status, produtos.stock_quantity)
    ]
    produtos["vendavel"] = produtos.disponibilidade == "disponivel"
    produtos["descricao_confiavel"] = [
        _descricao_confiavel(n, d, s) for n, d, s in zip(produtos.name, produtos.description, produtos.specs)
    ]
    produtos["nome_busca"] = (produtos.name + " " + produtos.categoria).map(normalizar).map(com_singulares)

    # Promoção ativa: se houver mais de uma para o mesmo produto, vale a maior
    # (promoções não são cumulativas — seção 6.2).
    ativas = (
        promocoes[promocoes.is_active == 1]
        .sort_values("discount_percent", ascending=False)
        .drop_duplicates("product_id")
        .rename(columns={"discount_percent": "promo_percentual", "description": "promo_nome"})
    )
    produtos = produtos.merge(ativas[["product_id", "promo_percentual", "promo_nome"]], on="product_id", how="left")
    produtos["promo_percentual"] = produtos.promo_percentual.fillna(0).astype(int)
    produtos["preco_final"] = (produtos.price_brl * (1 - produtos.promo_percentual / 100)).round(2)

    # --- clientes e pedidos ---
    clientes["telefone_digitos"] = clientes.phone.map(so_digitos)
    for coluna in ("order_date", "estimated_delivery"):
        pedidos[coluna] = pd.to_datetime(pedidos[coluna])
    pedidos["tracking_code"] = pedidos.tracking_code.fillna("")
    pedidos["notes"] = pedidos.notes.fillna("")

    return Loja(produtos, categorias, pedidos, itens, clientes, promocoes)
