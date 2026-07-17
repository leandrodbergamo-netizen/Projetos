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
        assert agrupar_cor("OFF WHITE ESCURO") == "Branco"

    def test_padronagem_vai_para_estampado(self):
        assert agrupar_cor("LISTRADO") == "Estampado"
        assert agrupar_cor("XADREZ") == "Estampado"

    def test_cor_desconhecida_passa_direto(self):
        assert agrupar_cor("CHARTREUSE") == "Chartreuse"

    def test_cor_vazia(self):
        assert agrupar_cor(None) == "Indefinido"
