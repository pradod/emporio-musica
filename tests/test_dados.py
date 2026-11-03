from datetime import datetime

from emporio.dados import carregar, parcelamento_maximo, status_loja


def test_parcelamento_respeita_parcela_minima_por_faixa():
    assert parcelamento_maximo(429.90) == (5, 85.98)   # 6x daria R$ 71,65 < R$ 80
    assert parcelamento_maximo(2199.00) == (12, 183.25)
    assert parcelamento_maximo(140.00) == (2, 70.00)   # 3x daria R$ 46,67 < R$ 50
    assert parcelamento_maximo(90.00) == (1, 90.00)


def test_disponibilidade_segue_status_e_estoque():
    produtos = carregar().produtos.set_index("product_id")
    assert produtos.loc[96, "disponibilidade"] == "esgotado"        # active, estoque 0
    assert produtos.loc[136, "disponibilidade"] == "fora_de_linha"  # discontinued com estoque 13
    assert produtos.loc[130, "disponibilidade"] == "em_breve"       # coming_soon com estoque 2
    assert produtos.loc[95, "vendavel"]


def test_descricoes_inconsistentes_sao_marcadas():
    produtos = carregar().produtos.set_index("product_id")
    for pid in (135, 137, 139, 140, 142, 144):
        assert not produtos.loc[pid, "descricao_confiavel"], pid
    assert produtos.loc[145, "descricao_confiavel"]  # Fender Stratocaster descrito como Stratocaster
    assert produtos.loc[95, "descricao_confiavel"]


def test_apenas_promocoes_ativas_alteram_preco():
    produtos = carregar().produtos.set_index("product_id")
    assert produtos.loc[90, "preco_final"] == 1967.18  # 18% sobre R$ 2.399
    assert produtos.loc[95, "preco_final"] == 2199.00  # promoção 12% inativa


def test_horario_de_funcionamento():
    assert status_loja(datetime(2026, 3, 25, 10, 30))["aberta"]           # quarta
    assert not status_loja(datetime(2026, 3, 28, 13, 0))["aberta"]        # sábado 13h
    domingo = status_loja(datetime(2026, 3, 29, 15, 0))
    assert domingo == {"aberta": False, "proxima_abertura": "amanhã às 09:00"}
