import pandas as pd
import pytest

from core.dados import filtrar_colecoes, rank_colecao
from core.espelho import candidatos_espelho, projetar_aposta, velocidade_por_loja_desaz
from core.regra_distribuicao import participacao_com_loja_nova

CURVA_NEUTRA = pd.DataFrame({"semana": list(range(1, 54)), "indice": [100.0] * 53})


def _vendas(registros):
    """registros = [(data, loja, qtd, sku)]"""
    return pd.DataFrame(
        [{"dt_transacao": pd.Timestamp(d), "sk_localidade": l, "qtd_produto": q, "cod_sku_pai": s}
         for d, l, q, s in registros]
    )


class TestRankColecao:
    def test_inverno_e_verao(self):
        assert rank_colecao("INVERNO 2023") == 2023.0
        assert rank_colecao("VERÃO 2023-2024") == 2023.5

    def test_ordem_cronologica(self):
        assert rank_colecao("INVERNO 2023") < rank_colecao("VERÃO 2023-2024") < rank_colecao("INVERNO 2024")

    def test_colecoes_fora_do_escopo(self):
        # PERENE e ALTO VERÃO são sujeira de cadastro (definição do negócio)
        assert rank_colecao("PERENE") is None
        assert rank_colecao("PERENE IDA") is None
        assert rank_colecao("ALTO VERÃO") is None
        assert rank_colecao("ALTO VERÃO 2024 2025") is None
        assert rank_colecao("CANCELADO") is None
        assert rank_colecao(None) is None


class TestFiltrarColecoes:
    def test_descarta_fora_do_escopo_e_anteriores(self):
        df = pd.DataFrame({"desc_colecao": [
            "INVERNO 2023", "VERÃO 2023-2024", "INVERNO 2021",
            "PERENE", "ALTO VERÃO 2024 2025", "CANCELADO",
        ]})
        mantidas = filtrar_colecoes(df, desde=2022.0)["desc_colecao"].tolist()
        assert mantidas == ["INVERNO 2023", "VERÃO 2023-2024"]

    def test_coluna_ausente_nao_quebra(self):
        df = pd.DataFrame({"x": [1]})
        assert len(filtrar_colecoes(df)) == 1


def _catalogo(linhas):
    """linhas = [(cod_sku_pai, cor_grupo, manga, colecao)]"""
    return pd.DataFrame([
        {"cod_sku_pai": s, "desc_sub_grupo_wbg": "VESTIDO", "desc_grupo_wgb": "TECIDO PLANO",
         "faixa": "P1", "grupo_material": "Linho", "cor_grupo": c, "desc_manga": mg,
         "desc_comprimento": "MIDI", "desc_fit": "RETO", "desc_colecao": col,
         "rank_colecao": rank_colecao(col), "desc_item": s, "preco": 498.0}
        for s, c, mg, col in linhas
    ])


class TestCandidatosEspelho:
    def test_manga_comprimento_fit_nao_filtram(self):
        # dois vestidos idênticos que só diferem na manga: ambos são candidatos,
        # porque manga é consulta (eta² ~0), não filtro.
        cat = _catalogo([("A", "Azul", "MANGA LONGA", "INVERNO 2023"),
                         ("B", "Azul", "SEM MANGA", "INVERNO 2023")])
        cand, _ = candidatos_espelho(cat, subgrupo="VESTIDO", grupo="TECIDO PLANO",
                                     faixa="P1", tecido="Linho", cor_grupo="Azul")
        assert sorted(cand["cod_sku_pai"]) == ["A", "B"]

    def test_cor_filtra_mas_afrouxa_se_faltar_candidato(self):
        cat = _catalogo([("A", "Azul", "MANGA LONGA", "INVERNO 2023"),
                         ("B", "Preto", "MANGA LONGA", "INVERNO 2023")])
        # com min_candidatos=1 a cor segura o filtro
        cand, soft = candidatos_espelho(cat, subgrupo="VESTIDO", grupo="TECIDO PLANO",
                                        faixa="P1", tecido="Linho", cor_grupo="Azul",
                                        min_candidatos=1)
        assert cand["cod_sku_pai"].tolist() == ["A"] and soft == ["cor_grupo"]
        # exigindo 2, a cor é afrouxada e o Preto entra
        cand, soft = candidatos_espelho(cat, subgrupo="VESTIDO", grupo="TECIDO PLANO",
                                        faixa="P1", tecido="Linho", cor_grupo="Azul",
                                        min_candidatos=2)
        assert sorted(cand["cod_sku_pai"]) == ["A", "B"] and soft == []

    def test_colecao_fora_do_escopo_nao_vira_candidato(self):
        cat = _catalogo([("A", "Azul", "MANGA LONGA", "INVERNO 2023"),
                         ("P", "Azul", "MANGA LONGA", "PERENE"),
                         ("V", "Azul", "MANGA LONGA", "ALTO VERÃO 2024 2025"),
                         ("O", "Azul", "MANGA LONGA", "INVERNO 2019")])
        cand, _ = candidatos_espelho(cat, subgrupo="VESTIDO", grupo="TECIDO PLANO",
                                     faixa="P1", tecido="Linho", cor_grupo="Azul",
                                     min_candidatos=1)
        assert cand["cod_sku_pai"].tolist() == ["A"]


class TestVelocidadeEspelho:
    def test_sem_venda_retorna_none(self):
        assert velocidade_por_loja_desaz(_vendas([]), "X", CURVA_NEUTRA) is None

    def test_separa_ecom_do_fisico(self):
        # 2 lojas físicas com 10 cada + ecom (456) com 6, em 1 semana
        reg = [("2024-01-03", 1, 10, "X"), ("2024-01-03", 2, 10, "X"), ("2024-01-03", 456, 6, "X")]
        ve = velocidade_por_loja_desaz(_vendas(reg), "X", CURVA_NEUTRA, ecom_locs={456})
        assert ve.unidades == 26
        assert ve.unidades_ecom == 6
        assert ve.n_lojas == 2                      # ecom não conta como loja física
        assert ve.vel_por_loja_desaz == pytest.approx(10.0)   # 20 un / 1 sem / 2 lojas
        assert ve.vel_ecom_desaz == pytest.approx(6.0)

    def test_desazonaliza_janela_quente(self):
        # janela na semana 2 com índice 200 => velocidade observada é o dobro do normal
        curva = pd.DataFrame({"semana": [2], "indice": [200.0]})
        reg = [("2024-01-08", 1, 10, "X")]
        ve = velocidade_por_loja_desaz(_vendas(reg), "X", curva)
        assert ve.fator_janela == pytest.approx(200.0)
        assert ve.vel_por_loja_desaz == pytest.approx(5.0)  # 10 / 2.0


class TestProjetarAposta:
    def _vel(self, sku="X", vel_loja=1.0, vel_ecom=0.0):
        reg = [("2024-01-03", 1, 0, sku)]
        ve = velocidade_por_loja_desaz(_vendas(reg), sku, CURVA_NEUTRA)
        return ve

    def test_sem_espelho_levanta(self):
        with pytest.raises(ValueError):
            projetar_aposta([], CURVA_NEUTRA, "2024-01-01", 10)

    def test_extrapola_fisico_pela_frota_e_soma_ecom(self):
        reg = [("2024-01-03", 1, 10, "X"), ("2024-01-03", 456, 5, "X")]
        ve = velocidade_por_loja_desaz(_vendas(reg), "X", CURVA_NEUTRA, ecom_locs={456})
        # vel física = 10/loja/sem ; ecom = 5/sem ; 20 lojas ; 10 semanas neutras
        ap = projetar_aposta([ve], CURVA_NEUTRA, "2024-01-01", 20,
                             horizonte_semanas=10, aproveitamento=1.0, reserva_cd_pct=0.0)
        assert ap.venda_ecom == pytest.approx(50.0)             # 5 * 10
        assert ap.venda_projetada == pytest.approx(10 * 20 * 10 + 50)
        assert ap.aposta_sugerida == pytest.approx(2050.0)

    def test_aviso_de_moq(self):
        reg = [("2024-01-03", 1, 1, "X")]
        ve = velocidade_por_loja_desaz(_vendas(reg), "X", CURVA_NEUTRA)
        ap = projetar_aposta([ve], CURVA_NEUTRA, "2024-01-01", 1, horizonte_semanas=1, moq=100)
        assert any("MOQ" in a for a in ap.avisos)


class TestParticipacaoLojaNova:
    def test_loja_nova_herda_media_do_cluster(self):
        part_hist = {"1": 0.6, "2": 0.2, "3": 0.2}      # loja 1 = Ouro; 2 e 3 = Prata
        clusters = {"1": "Ouro", "2": "Prata", "3": "Prata", "9": "Prata"}
        out = participacao_com_loja_nova(part_hist, ["1", "2", "3", "9"], clusters)
        assert sum(out.values()) == pytest.approx(1.0)
        # loja 9 (nova, Prata) herda a média das Prata (0.2) antes de renormalizar
        assert out["9"] == pytest.approx(0.2 / 1.2)

    def test_cluster_sem_historico_usa_media_geral(self):
        part_hist = {"1": 0.5, "2": 0.5}
        clusters = {"1": "Ouro", "2": "Ouro", "9": "Bronze"}
        out = participacao_com_loja_nova(part_hist, ["1", "2", "9"], clusters)
        assert out["9"] == pytest.approx(0.5 / 1.5)

    def test_sem_historico_distribui_uniforme(self):
        out = participacao_com_loja_nova({}, ["1", "2"], {})
        assert out == {"1": 0.5, "2": 0.5}
