import pytest

from emporio import ferramentas as f


@pytest.fixture(autouse=True)
def data_fixa(monkeypatch):
    monkeypatch.setenv("EMPORIO_DATA_REFERENCIA", "2026-03-25T10:30")


def test_busca_violoes_ate_mil_reais_so_traz_disponiveis():
    r = f.buscar_produtos(categoria="Violões", preco_max=1000, limite=15)
    nomes = [p["nome"] for p in r["produtos"]]
    assert r["total_encontrado"] == 12
    assert "Giannini GF-3D Dreadnought Sunburst" not in nomes  # esgotado
    assert "Shelby SN-7C 7 Cordas Nylon Natural" not in nomes  # fora de linha


def test_busca_categoria_sem_produtos_nao_inventa():
    r = f.buscar_produtos(categoria="Cordas Orquestrais")
    assert r["total_encontrado"] == 0 and "Não invente" in r["observacao"]


def test_detalhes_takamine_gd20_com_pix_e_parcelas():
    r = f.detalhes_produto("Takamine GD20")
    assert r["preco"] == "R$ 2.199,00"
    assert r["pagamento"]["pix"].startswith("R$ 2.089,05")
    assert r["pagamento"]["cartao_credito"] == "até 12x de R$ 183,25 sem juros"


def test_pix_nao_acumula_com_promocao():
    r = f.detalhes_produto("Crafter HT-100")
    assert r["preco_original"] == "R$ 2.399,00" and r["preco"] == "R$ 1.967,18"
    assert r["pagamento"]["pix"].startswith("R$ 1.967,18")


def test_produto_esgotado_sugere_alternativas():
    r = f.detalhes_produto("Giannini GF-3D")
    assert r["disponibilidade"] == "temporariamente esgotado"
    assert r["alternativas_disponiveis"]


def test_pedido_exige_contato_correto():
    assert "erro" in f.consultar_pedido(7, "outra.pessoa@jmail.com")
    assert "erro" in f.consultar_pedido(999, "(67) 99789-0123")
    assert f.consultar_pedido(7, "99789-0123")["numero_pedido"] == 7


def test_prazos_de_pos_venda_calculados():
    prazos = f.consultar_pedido(7, "leticia.rocha@jmail.com")["prazos_pos_venda"]
    assert not prazos["arrependimento_devolucao"]["dentro_do_prazo"]
    assert prazos["garantia_legal_defeito"]["dentro_do_prazo"]
    assert prazos["garantia_legal_defeito"]["valido_ate"] == "18/05/2026"


def test_pedido_enviado_atrasado_gera_alerta():
    r = f.consultar_pedido(8, "anacarol.ferreira@coldmail.com")
    assert "atrasada" in r["alerta_interno"]


def test_email_compartilhado_nao_lista_pedidos():
    assert "mais de um cadastro" in f.listar_pedidos_do_cliente("bruno.martins@jmail.com")["erro"]


def test_executar_trata_argumento_invalido():
    assert "erro" in f.executar("detalhes_produto", {"nome": "x"})
    assert "erro" in f.executar("nao_existe", {})


def test_schemas_e_funcoes_consistentes():
    assert {s["function"]["name"] for s in f.SCHEMAS} == set(f.FUNCOES)
