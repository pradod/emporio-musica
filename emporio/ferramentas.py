"""Ferramentas expostas ao LLM (function calling) e seus schemas.

Cada ferramenta devolve um dict já pronto para o modelo: valores em reais
formatados, rótulos em português e regras de negócio aplicadas.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime

import pandas as pd

from . import politicas
from .config import DIR_HISTORICO, agora
from .dados import (
    DESCONTO_PIX,
    DISPONIBILIDADE,
    STATUS_PEDIDO,
    carregar,
    descrever_pagamento,
    normalizar,
    parcelamento_maximo,
    prazos_pos_venda,
)

LIMITE_ESTOQUE_BAIXO = 2

ROTULOS_SPECS = {
    "top": "tampo", "back_sides": "fundo e laterais", "neck": "braço", "strings": "cordas",
    "scale": "escala", "electronics": "captação/eletrônica", "color": "cor", "body": "corpo",
    "shells": "cascos", "pieces": "peças", "hardware": "ferragens", "keys": "teclas",
    "type": "tipo", "polyphony": "polifonia",
}
VALORES_SPECS = {"steel": "aço", "yes": "sim", "no": "não", "included": "inclusas"}


def brl(valor: float) -> str:
    texto = f"{valor:,.2f}".replace(",", "_").replace(".", ",").replace("_", ".")
    return f"R$ {texto}"


def _resumo_produto(p: pd.Series) -> dict:
    item = {
        "id": int(p.product_id),
        "nome": p["name"],
        "categoria": p.categoria,
        "preco": brl(p.preco_final),
        "disponibilidade": DISPONIBILIDADE[p.disponibilidade],
    }
    if p.promo_percentual:
        item["preco_original"] = brl(p.price_brl)
        item["promocao"] = f"{p.promo_nome}: {p.promo_percentual}% de desconto"
    return item


# ---------------------------------------------------------------- produtos

def buscar_produtos(
    texto: str | None = None,
    categoria: str | None = None,
    preco_min: float | None = None,
    preco_max: float | None = None,
    tipo_corda: str | None = None,
    com_captacao: bool | None = None,
    apenas_disponiveis: bool = True,
    ordenar_por: str = "menor_preco",
    limite: int = 8,
) -> dict:
    loja = carregar()
    produtos = loja.produtos
    if texto:
        produtos = loja.encontrar_produtos(texto, limite=len(produtos))
    if categoria:
        produtos = produtos[produtos.categoria.map(normalizar) == normalizar(categoria)]
    if preco_min is not None:
        produtos = produtos[produtos.preco_final >= preco_min]
    if preco_max is not None:
        produtos = produtos[produtos.preco_final <= preco_max]
    if tipo_corda:
        alvo = "steel" if normalizar(tipo_corda) in {"aco", "steel"} else "nylon"
        produtos = produtos[produtos.specs.map(lambda s: s.get("strings") == alvo)]
    if com_captacao is not None:
        alvo = "yes" if com_captacao else "no"
        produtos = produtos[produtos.specs.map(lambda s: s.get("electronics") == alvo)]
    if apenas_disponiveis:
        produtos = produtos[produtos.vendavel]

    if not texto or ordenar_por != "relevancia":
        produtos = produtos.sort_values("preco_final", ascending=ordenar_por != "maior_preco")
    total = len(produtos)
    limite = max(1, min(int(limite), 15))
    resultado = {
        "total_encontrado": total,
        "produtos": [_resumo_produto(p) for _, p in produtos.head(limite).iterrows()],
    }
    if total > limite:
        resultado["observacao"] = f"Mostrando {limite} de {total}. Refine a busca se necessário."
    if total == 0:
        resultado["observacao"] = (
            "Nenhum produto encontrado com esses filtros. Não invente produtos: "
            "informe o cliente e ofereça buscar com outros critérios."
        )
    return resultado


def detalhes_produto(produto: str) -> dict:
    loja = carregar()
    produto = str(produto).strip()
    if produto.isdigit():
        p = loja.produto(int(produto))
        if p is None:
            return {"erro": f"Produto de id {produto} não existe no catálogo."}
    else:
        achados = loja.encontrar_produtos(produto, limite=5)
        if achados.empty:
            return {"erro": f"Nenhum produto com nome parecido com '{produto}' no catálogo."}
        melhores = achados[achados._pontos == achados._pontos.max()]
        if len(melhores) > 1:
            return {
                "ambiguo": True,
                "mensagem": "Mais de um produto corresponde ao nome. Pergunte ao cliente qual deles.",
                "candidatos": [_resumo_produto(c) for _, c in melhores.iterrows()],
            }
        p = melhores.iloc[0]

    info = _resumo_produto(p)
    info["preco_de_tabela"] = brl(p.price_brl)
    info["especificacoes"] = {
        ROTULOS_SPECS.get(k, k): VALORES_SPECS.get(v, v) for k, v in p.specs.items()
    }
    if p.descricao_confiavel:
        info["descricao"] = p.description
    else:
        info["descricao"] = None
        info["aviso_interno"] = (
            "A descrição cadastrada deste item é inconsistente com o produto. "
            "Use apenas nome, preço e especificações."
        )

    if p.vendavel:
        info["estoque"] = "últimas unidades" if p.stock_quantity <= LIMITE_ESTOQUE_BAIXO else "disponível"
        n, parcela = parcelamento_maximo(p.preco_final)
        pagamento = {"cartao_credito": f"até {n}x de {brl(parcela)} sem juros" if n > 1 else "à vista"}
        if p.promo_percentual:
            pagamento["pix"] = (
                f"{brl(p.preco_final)} (o desconto de 5% do PIX não se soma à promoção)"
            )
        else:
            pagamento["pix"] = f"{brl(p.price_brl * (1 - DESCONTO_PIX))} (5% de desconto à vista)"
        info["pagamento"] = pagamento
    else:
        info["alternativas_disponiveis"] = [
            _resumo_produto(a) for _, a in loja.alternativas(p).iterrows()
        ]
        if p.disponibilidade == "em_breve":
            info["aviso_interno"] = "Não há data de chegada no sistema: não prometa prazo."

    # Promoções encerradas ajudam a responder "ainda está na promoção X?".
    encerradas = loja.promocoes[(loja.promocoes.product_id == p.product_id) & (loja.promocoes.is_active == 0)]
    if not encerradas.empty:
        info["promocoes_encerradas"] = [
            f"{r.description} ({r.discount_percent}%)" for r in encerradas.itertuples()
        ]
    return info


# ---------------------------------------------------------------- pedidos

def _contato_confere(cliente: pd.Series, contato: str) -> bool:
    loja = carregar()
    return cliente.customer_id in set(loja.clientes_por_contato(contato).customer_id)


def _detalhar_pedido(pedido: pd.Series) -> dict:
    loja = carregar()
    hoje = agora().date()
    itens = loja.itens_do_pedido(int(pedido.order_id))
    info = {
        "numero_pedido": int(pedido.order_id),
        "data_do_pedido": f"{pedido.order_date:%d/%m/%Y}",
        "status": STATUS_PEDIDO.get(pedido.status, pedido.status),
        "itens": [f"{int(i.quantity)}x {i['name']}" for _, i in itens.iterrows()],
        "valor_total": brl(pedido.total_brl),
        "forma_de_pagamento": descrever_pagamento(pedido.payment_method),
    }
    if pedido.tracking_code:
        info["codigo_rastreamento"] = pedido.tracking_code
    if pd.notna(pedido.estimated_delivery):
        info["previsao_de_entrega"] = f"{pedido.estimated_delivery:%d/%m/%Y}"
    if pedido.notes:
        info["observacao"] = pedido.notes

    dias = (hoje - pedido.order_date.date()).days
    if pedido.status == "pending" and dias > 3:
        info["alerta_interno"] = (
            f"Pedido pendente há {dias} dias (boleto compensa em até 3 dias úteis). "
            "Ofereça encaminhar para a equipe verificar o pagamento."
        )
    if pedido.status == "shipped" and pd.notna(pedido.estimated_delivery) and hoje > pedido.estimated_delivery.date():
        atraso = (hoje - pedido.estimated_delivery.date()).days
        info["alerta_interno"] = (
            f"Entrega atrasada em {atraso} dias em relação à previsão. "
            "Peça desculpas e ofereça encaminhar para a equipe acionar a transportadora."
        )
    if pedido.status == "delivered" and pd.notna(pedido.estimated_delivery):
        info["prazos_pos_venda"] = prazos_pos_venda(pedido, hoje)
        info["data_de_hoje"] = f"{hoje:%d/%m/%Y}"
    return info


def consultar_pedido(numero_pedido: int, contato: str) -> dict:
    loja = carregar()
    pedido = loja.pedido(int(numero_pedido))
    falha = {
        "erro": "Não foi possível validar o pedido com esses dados. Peça ao cliente para "
        "conferir o número do pedido e o telefone ou e-mail usado na compra."
    }
    if pedido is None:
        return falha
    cliente = loja.clientes[loja.clientes.customer_id == pedido.customer_id].iloc[0]
    if not _contato_confere(cliente, contato):
        return falha
    return {"cliente": cliente["name"].split()[0], **_detalhar_pedido(pedido)}


def listar_pedidos_do_cliente(contato: str) -> dict:
    loja = carregar()
    clientes = loja.clientes_por_contato(contato)
    if clientes.empty:
        return {"erro": "Nenhum cadastro encontrado com esse telefone/e-mail."}
    if len(clientes) > 1:
        return {
            "erro": "Esse contato está associado a mais de um cadastro. "
            "Peça o número do pedido ou o telefone do cliente para identificá-lo com segurança."
        }
    cliente = clientes.iloc[0]
    pedidos = loja.pedidos[loja.pedidos.customer_id == cliente.customer_id].sort_values("order_date", ascending=False)
    if pedidos.empty:
        return {"cliente": cliente["name"].split()[0], "pedidos": [], "observacao": "Cliente sem pedidos."}
    return {
        "cliente": cliente["name"].split()[0],
        "pedidos": [_detalhar_pedido(p) for _, p in pedidos.iterrows()],
    }


# ---------------------------------------------------------------- políticas e equipe

def consultar_politica(topico: str) -> dict:
    return {"topico": topico, "conteudo": politicas.ler(topico)}


def encaminhar_para_equipe(motivo: str, resumo: str, numero_pedido: int | None = None, contato: str | None = None) -> dict:
    protocolo = f"EM-{agora():%Y%m%d}-{uuid.uuid4().hex[:4].upper()}"
    registro = {
        "protocolo": protocolo,
        "registrado_em": datetime.now().isoformat(timespec="seconds"),
        "motivo": motivo,
        "resumo": resumo,
        "numero_pedido": numero_pedido,
        "contato": contato,
    }
    DIR_HISTORICO.mkdir(exist_ok=True)
    with open(DIR_HISTORICO / "encaminhamentos.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps(registro, ensure_ascii=False) + "\n")
    return {"protocolo": protocolo, "prazo_de_retorno": "até 24 horas úteis"}


# ---------------------------------------------------------------- registro

CATEGORIAS = ["Guitarras", "Baixos", "Baterias e Percussão", "Teclados e Pianos", "Violões",
              "Instrumentos de Sopro (Madeiras)", "Instrumentos de Sopro (Metais)",
              "Cordas Orquestrais", "Ukuleles"]

SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "buscar_produtos",
            "description": (
                "Busca instrumentos no catálogo com filtros. Use para perguntas como 'quais violões até R$1000', "
                "'tem ukulele tenor?', 'opções de guitarra'. Retorna preço atual (já com promoção ativa) e disponibilidade."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "texto": {"type": "string", "description": "Marca, modelo ou termo livre (ex.: 'Yamaha', 'tenor', '7 cordas')."},
                    "categoria": {"type": "string", "enum": CATEGORIAS},
                    "preco_min": {"type": "number", "description": "Preço mínimo em reais."},
                    "preco_max": {"type": "number", "description": "Preço máximo em reais."},
                    "tipo_corda": {"type": "string", "enum": ["nylon", "aço"], "description": "Só para violões e ukuleles."},
                    "com_captacao": {"type": "boolean", "description": "true = elétrico/eletroacústico (com captação)."},
                    "apenas_disponiveis": {"type": "boolean", "description": "Padrão true. Use false só se o cliente perguntar por item esgotado/fora de linha."},
                    "ordenar_por": {"type": "string", "enum": ["menor_preco", "maior_preco", "relevancia"]},
                    "limite": {"type": "integer", "description": "Máximo de itens (padrão 8, máx. 15)."},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "detalhes_produto",
            "description": (
                "Detalhes de UM produto: preço, promoção, preço no PIX, parcelamento, estoque, especificações "
                "e alternativas se estiver indisponível. Use quando o cliente citar um modelo (ex.: 'quanto custa o Takamine GD20?')."
            ),
            "parameters": {
                "type": "object",
                "properties": {"produto": {"type": "string", "description": "Nome/modelo do produto ou id numérico."}},
                "required": ["produto"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "consultar_pedido",
            "description": (
                "Status, itens, rastreio e prazos de troca/devolução/garantia de um pedido. Exige o número do pedido "
                "E o telefone ou e-mail do cadastro (LGPD). Se o cliente não informou ambos, peça antes de chamar."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "numero_pedido": {"type": "integer"},
                    "contato": {"type": "string", "description": "Telefone ou e-mail informado pelo cliente."},
                },
                "required": ["numero_pedido", "contato"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "listar_pedidos_do_cliente",
            "description": "Lista os pedidos de um cliente a partir do telefone ou e-mail do cadastro (quando ele não sabe o número do pedido).",
            "parameters": {
                "type": "object",
                "properties": {"contato": {"type": "string", "description": "Telefone ou e-mail informado pelo cliente."}},
                "required": ["contato"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "consultar_politica",
            "description": "Lê o manual oficial da loja sobre um tópico. Use SEMPRE antes de responder sobre regras, horários, endereço, pagamento, frete, trocas, garantia ou promoções.",
            "parameters": {
                "type": "object",
                "properties": {
                    "topico": {
                        "type": "string",
                        "enum": list(politicas.TOPICOS),
                        "description": "; ".join(f"{k}: {v}" for k, v in politicas.TOPICOS.items()),
                    }
                },
                "required": ["topico"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "encaminhar_para_equipe",
            "description": (
                "Registra o caso para a equipe humana e gera um protocolo. Use para reclamações, pedidos de troca/devolução "
                "elegíveis, defeitos, cotação de frete, pedidos atrasados ou quando o cliente pedir para falar com um atendente. "
                "Confirme com o cliente antes de registrar."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "motivo": {"type": "string", "enum": ["reclamacao", "troca_ou_devolucao", "defeito_garantia", "pedido_atrasado", "cotacao_frete", "falar_com_atendente", "outro"]},
                    "resumo": {"type": "string", "description": "Resumo objetivo do caso para a equipe."},
                    "numero_pedido": {"type": "integer"},
                    "contato": {"type": "string"},
                },
                "required": ["motivo", "resumo"],
            },
        },
    },
]

FUNCOES = {
    "buscar_produtos": buscar_produtos,
    "detalhes_produto": detalhes_produto,
    "consultar_pedido": consultar_pedido,
    "listar_pedidos_do_cliente": listar_pedidos_do_cliente,
    "consultar_politica": consultar_politica,
    "encaminhar_para_equipe": encaminhar_para_equipe,
}

FERRAMENTAS_DE_DADOS = {"buscar_produtos", "detalhes_produto", "consultar_pedido", "listar_pedidos_do_cliente"}


def executar(nome: str, argumentos: dict) -> dict:
    """Executa uma ferramenta e transforma qualquer falha em mensagem para o modelo."""
    funcao = FUNCOES.get(nome)
    if funcao is None:
        return {"erro": f"Ferramenta '{nome}' não existe."}
    try:
        return funcao(**argumentos)
    except (TypeError, ValueError) as exc:
        return {"erro": f"Argumentos inválidos para {nome}: {exc}"}
