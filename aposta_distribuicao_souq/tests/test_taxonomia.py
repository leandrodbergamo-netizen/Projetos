import pytest

from core.taxonomia import (agrupar_cor, agrupar_material, agrupar_tamanho, norm,
                            normalizar_subgrupo, ordem_tamanhos, rotulo_grade)


class TestAgruparTamanho:
    def test_numerario_e_letra_caem_no_mesmo_bucket(self):
        # regra do negócio: 36|XPP, 38|PP, 40|P, 42|M, 44|G, 46|GG
        assert agrupar_tamanho("36") == agrupar_tamanho("XPP") == "36|XPP"
        assert agrupar_tamanho("38") == agrupar_tamanho("PP") == "38|PP"
        assert agrupar_tamanho("40") == agrupar_tamanho("P") == "40|P"
        assert agrupar_tamanho("42") == agrupar_tamanho("M") == "42|M"
        assert agrupar_tamanho("44") == agrupar_tamanho("G") == "44|G"
        assert agrupar_tamanho("46") == agrupar_tamanho("GG") == "46|GG"

    def test_unico_e_desconhecido(self):
        assert agrupar_tamanho("U") == "U"
        assert agrupar_tamanho("59") is None
        assert agrupar_tamanho(None) is None

    def test_ordem_do_menor_para_o_maior(self):
        o = ordem_tamanhos()
        assert o.index("38|PP") < o.index("42|M") < o.index("46|GG")

    def test_rotulo_compacto(self):
        assert rotulo_grade({"38|PP", "40|P", "42|M", "44|G", "46|GG"}) == "PP–GG"
        assert rotulo_grade({"36|XPP", "38|PP", "40|P", "42|M", "44|G", "46|GG"}) == "XPP–GG"
        assert rotulo_grade({"U"}) == "U"
        assert rotulo_grade({"38|PP", "44|G"}) == "PP/G"     # não contígua: lista
        assert rotulo_grade(set()) == "—"


class TestNormalizarSubgrupo:
    def test_remove_espaco_que_duplicava_a_opcao(self):
        # o cadastro tem 'JAQUETA ' e 'JAQUETA' -> viravam 2 itens no dropdown
        assert normalizar_subgrupo("JAQUETA ") == normalizar_subgrupo("JAQUETA") == "JAQUETA"
        assert normalizar_subgrupo("BODY ") == "BODY"

    def test_sinonimo_de_plural(self):
        assert normalizar_subgrupo("SHORTS") == "SHORT"
        assert normalizar_subgrupo("SHORT") == "SHORT"

    def test_preserva_acento_e_caixa(self):
        assert normalizar_subgrupo("CALÇA") == "CALÇA"
        assert normalizar_subgrupo("CAMISÃO") == "CAMISÃO"

    def test_nao_quebra_com_nulo(self):
        assert normalizar_subgrupo(None) is None


class TestNorm:
    def test_remove_acento_e_maiuscula(self):
        assert norm("Algodão") == "ALGODAO"
        assert norm("  poliéster  / viscose ") == "POLIESTER / VISCOSE"

    def test_nulo_vira_vazio(self):
        assert norm(None) == ""


class TestAgruparMaterial:
    def test_grupo_tricot_e_jeans_vencem_material(self):
        assert agrupar_material("TRICOT", "VISCOSE / ELASTANO") == "Tricot"
        assert agrupar_material("JEANS", "ALGODÃO") == "Jeans"

    def test_linho_predomina_mesmo_nao_sendo_primeiro(self):
        # regra de negócio: qualquer coisa com linho é classificada como Linho
        assert agrupar_material("TECIDO PLANO", "VISCOSE / LINHO") == "Linho"
        assert agrupar_material("TECIDO PLANO", "LINHO JIMMY") == "Linho"

    def test_primeira_fibra_citada_define_o_bucket(self):
        assert agrupar_material("TECIDO PLANO", "VISCOSE / ELASTANO") == "Viscose"
        assert agrupar_material("TECIDO PLANO", "POLIÉSTER / VISCOSE") == "Poliéster"
        assert agrupar_material("TECIDO PLANO", "ALGODÃO / ELASTANO") == "Algodão"

    def test_fibra_explicita_vence_termo_de_tecelagem(self):
        assert agrupar_material("TECIDO PLANO", "ALGODÃO ( JACQUARD ZEBRA )") == "Algodão"

    def test_termo_de_tecelagem_quando_nao_ha_fibra(self):
        assert agrupar_material("TECIDO PLANO", "TAFETTA INDIA - TEXPRIMA") == "Poliéster"
        assert agrupar_material("TECIDO PLANO", "LAISE LEQUE") == "Algodão"
        assert agrupar_material("TECIDO PLANO", "TENCEL 63") == "Viscose"

    def test_fornecedor_usa_a_composicao_informada(self):
        assert agrupar_material("TECIDO PLANO", "CHLOÉ") == "Algodão"      # 70,5% algodão
        assert agrupar_material("TECIDO PLANO", "PARISE ESTAMPADO") == "Viscose"
        assert agrupar_material("TECIDO PLANO", "PARISE ESTAMP. G8522") == "Viscose"
        assert agrupar_material("TECIDO PLANO", "BETA") == "Poliéster"
        assert agrupar_material("TECIDO PLANO", "NILO TRIPOLI") == "Linho"  # 55% linho

    def test_composicao_do_fornecedor_vence_tecelagem_generica(self):
        # crochê genérico seria Algodão, mas a composição da Beta é 100% poliéster
        assert agrupar_material("TECIDO PLANO", "CROCHE ZOE - BETA") == "Poliéster"

    def test_fibra_explicita_vence_fornecedor(self):
        assert agrupar_material("TECIDO PLANO", "ALGODÃO / VISCOSE / ELASTANO ( CHLOÉ )") == "Algodão"

    def test_fornecedor_sem_composicao_segue_outros(self):
        assert agrupar_material("TECIDO PLANO", "NILO LEVE") == "Outros"   # NILO TRIPOLI != NILO LEVE
        assert agrupar_material("TECIDO PLANO", "JACK STRETCH") == "Outros"
        assert agrupar_material("TECIDO PLANO", "TECIDO XL") == "Outros"

    def test_material_vazio(self):
        assert agrupar_material("TECIDO PLANO", None) == "Outros"


class TestAgruparCor:
    def test_excecoes_do_usuario(self):
        assert agrupar_cor("AZUL DENIM") == "Azul"
        assert agrupar_cor("AZUL CLARO") == "Azul"
        assert agrupar_cor("PINK") == "Rosa"
        assert agrupar_cor("PRATA") == "Cinza"

    def test_azul_marinho_fica_separado(self):
        # exceção explícita: relevância própria, não pode virar "Azul"
        assert agrupar_cor("AZUL MARINHO") == "Azul Marinho"

    def test_qualificador_claro_escuro_cai_na_cor_base(self):
        assert agrupar_cor("MARROM ESCURO") == "Marrom"
        assert agrupar_cor("AZUL MÉDIO") == "Azul"
        assert agrupar_cor("OFF WHITE ESCURO") == "Off White"

    def test_off_white_separado_de_branco(self):
        # decisão do negócio: off white tem venda própria, não funde com Branco
        assert agrupar_cor("OFF WHITE") == "Off White"
        assert agrupar_cor("BRANCO") == "Branco"

    def test_padronagem_vai_para_estampado(self):
        assert agrupar_cor("LISTRADO") == "Estampado"
        assert agrupar_cor("XADREZ") == "Estampado"

    def test_cor_desconhecida_passa_direto(self):
        assert agrupar_cor("CHARTREUSE") == "Chartreuse"

    def test_cor_vazia(self):
        assert agrupar_cor(None) == "Indefinido"


class TestFaixasDoSubgrupo:
    @pytest.fixture()
    def pasta_faixas(self, tmp_path):
        import pandas as pd

        from core.taxonomia import _tabela_faixas
        df = pd.DataFrame({
            "Grupo": ["MALHA"] * 4 + ["TECIDO PLANO"] * 4,
            "Subgrupo": ["REGATA"] * 8,
            "Faixa de Preço": ["P1", "P2", "P3", "P4"] * 2,
            "MOQ": [50] * 8,
            "De": [148, 178, 198, 298, 298, 398, 498, 598],
            "Até": [177.99, 197.99, 297.99, 397.99,
                    397.99, 497.99, 597.99, 697.99],
        })
        df.to_excel(tmp_path / "Faixas de Preco TESTE.xlsx", index=False)
        _tabela_faixas.cache_clear()
        yield str(tmp_path)
        _tabela_faixas.cache_clear()

    def test_reguas_por_construcao(self, pasta_faixas):
        from core.taxonomia import faixas_do_subgrupo
        r = faixas_do_subgrupo("REGATA", caminho=pasta_faixas)
        assert sorted(r["grupo"].unique()) == ["MALHA", "TECIDO PLANO"]
        assert len(r) == 8
        # cenário "Regata Berna": o mesmo intervalo em R$ tem rótulos diferentes
        malha_p4 = r[(r["grupo"] == "MALHA") & (r["faixa"] == "P4")].iloc[0]
        plano_p1 = r[(r["grupo"] == "TECIDO PLANO") & (r["faixa"] == "P1")].iloc[0]
        assert (malha_p4["de"], malha_p4["ate"]) == (plano_p1["de"], plano_p1["ate"]) \
            == (298.0, 397.99)

    def test_subgrupo_inexistente_retorna_vazio(self, pasta_faixas):
        from core.taxonomia import faixas_do_subgrupo
        assert faixas_do_subgrupo("VESTIDO", caminho=pasta_faixas).empty


# --------------------------------------------------------------------------- #
# De-para de material por SKU (cadastro sem desc_material)
# --------------------------------------------------------------------------- #
def test_preparar_produtos_completa_material_pelo_depara(monkeypatch):
    import pandas as pd
    from core import espelho, taxonomia

    monkeypatch.setattr(espelho, "material_por_sku",
                        lambda: {"04.26.02.777.054": "100% VISCOSE"})
    monkeypatch.setattr(taxonomia, "material_por_sku",
                        lambda: {"04.26.02.777.054": "100% VISCOSE"})
    prod = pd.DataFrame({
        "sk_produto": [1, 2, 3],
        "cod_sku_pai": ["04.26.02.777.054", "04.26.02.777.054", "04.26.02.999.001"],
        "desc_item": ["BLUSA DEVA", "BLUSA DEVA", "BLUSA X"],
        "desc_linha": ["ROUPA"] * 3,
        "desc_sub_grupo_wbg": ["BLUSA"] * 3,
        "desc_grupo_wgb": ["TECIDO PLANO"] * 3,
        "desc_material": [None, "LINHO PURO", None],   # 2ª linha: cadastro prevalece
        "desc_cor": ["PRETO"] * 3,
        "desc_tamanho": ["P", "M", "P"],
        "desc_colecao": ["INVERNO 2026"] * 3,
        "dt_envio": [pd.NaT] * 3,
        "preco_tabela": [100.0] * 3,
        "desc_status_produto": ["ATIVO"] * 3,
    })
    out = espelho.preparar_produtos(prod)
    por_sk = out.set_index("sk_produto")
    assert por_sk.loc[1, "grupo_material"] == "Viscose"     # veio do de-para
    assert por_sk.loc[2, "grupo_material"] == "Linho"       # cadastro prevalece
    assert por_sk.loc[3, "grupo_material"] == "Outros"      # sem de-para segue Outros


def test_material_por_sku_sem_arquivo(monkeypatch, tmp_path):
    from core import taxonomia

    monkeypatch.setattr(taxonomia, "CONFIG_DIR", tmp_path)
    taxonomia.material_por_sku.cache_clear()
    assert taxonomia.material_por_sku() == {}
    (tmp_path / "material_por_sku.yaml").write_text(
        "04.26.02.777.054: 100% VISCOSE\n04.26.02.778.054:\n", encoding="utf-8")
    taxonomia.material_por_sku.cache_clear()
    assert taxonomia.material_por_sku() == {"04.26.02.777.054": "100% VISCOSE"}
    taxonomia.material_por_sku.cache_clear()
