import pandas as pd
import pytest

from core.dados import filtrar_colecoes, rank_colecao
from core.espelho import (candidatos_espelho, curva_tamanhos_grade, pool_suavizacao,
                          projetar_aposta, velocidade_por_loja_desaz)
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
                                     faixas="P1", tecido="Linho", cor_grupo="Azul")
        assert sorted(cand["cod_sku_pai"]) == ["A", "B"]

    def test_cor_filtra_mas_afrouxa_se_faltar_candidato(self):
        cat = _catalogo([("A", "Azul", "MANGA LONGA", "INVERNO 2023"),
                         ("B", "Preto", "MANGA LONGA", "INVERNO 2023")])
        # com min_candidatos=1 a cor segura o filtro
        cand, soft = candidatos_espelho(cat, subgrupo="VESTIDO", grupo="TECIDO PLANO",
                                        faixas="P1", tecido="Linho", cor_grupo="Azul",
                                        min_candidatos=1)
        assert cand["cod_sku_pai"].tolist() == ["A"] and soft == ["cor_grupo"]
        # exigindo 2, a cor é afrouxada e o Preto entra
        cand, soft = candidatos_espelho(cat, subgrupo="VESTIDO", grupo="TECIDO PLANO",
                                        faixas="P1", tecido="Linho", cor_grupo="Azul",
                                        min_candidatos=2)
        assert sorted(cand["cod_sku_pai"]) == ["A", "B"] and soft == []

    def test_grade_nao_filtra_espelhos(self):
        # decisão de 08/2026: a grade é insumo da DISTRIBUIÇÃO (colunas da
        # matriz); espelho que não vendeu todos os tamanhos continua candidato.
        def linhas(sku, tams):
            return [{"cod_sku_pai": sku, "desc_sub_grupo_wbg": "VESTIDO",
                     "desc_grupo_wgb": "TECIDO PLANO", "faixa": "P1",
                     "grupo_material": "Linho", "cor_grupo": "Azul",
                     "desc_manga": None, "desc_comprimento": None, "desc_fit": None,
                     "desc_colecao": "INVERNO 2023", "rank_colecao": 2023.0,
                     "desc_item": sku, "preco": 498.0, "tamanho_grupo": t}
                    for t in tams]
        cat = pd.DataFrame(
            linhas("A", ["38|PP", "40|P", "42|M", "44|G", "46|GG"])
            + linhas("B", ["40|P", "42|M", "44|G"]))
        cand, soft = candidatos_espelho(cat, subgrupo="VESTIDO", grupo="TECIDO PLANO",
                                        faixas="P1", tecido="Linho", min_candidatos=1)
        assert sorted(cand["cod_sku_pai"].unique()) == ["A", "B"]
        assert soft == []

    def test_multiplas_faixas_cada_produto_na_regua_da_propria_construcao(self):
        # cenário "Regata Berna": mesmo preço é P4 na régua de MALHA e P1 na de
        # TECIDO PLANO. Selecionando as faixas direto, cada produto responde pela
        # faixa calculada na régua da própria construção.
        cat = _catalogo([("PLANO", "Azul", None, "INVERNO 2023"),
                         ("BERNA", "Azul", None, "INVERNO 2023")])
        cat.loc[cat["cod_sku_pai"] == "BERNA", "desc_grupo_wgb"] = "MALHA"
        cat.loc[cat["cod_sku_pai"] == "BERNA", "faixa"] = "P4"
        cand, _ = candidatos_espelho(cat, subgrupo="VESTIDO", faixas=["P1", "P4"],
                                     tecido="Linho", min_candidatos=1)
        assert sorted(cand["cod_sku_pai"]) == ["BERNA", "PLANO"]
        cand, _ = candidatos_espelho(cat, subgrupo="VESTIDO", faixas=["P4"],
                                     tecido="Linho", min_candidatos=1)
        assert cand["cod_sku_pai"].tolist() == ["BERNA"]

    def test_faixas_vazia_ou_none_nao_filtra(self):
        cat = _catalogo([("A", "Azul", None, "INVERNO 2023"),
                         ("B", "Azul", None, "INVERNO 2023")])
        cat.loc[cat["cod_sku_pai"] == "B", "faixa"] = "P3"
        for faixas in (None, []):
            cand, _ = candidatos_espelho(cat, subgrupo="VESTIDO", faixas=faixas,
                                         tecido="Linho", min_candidatos=1)
            assert sorted(cand["cod_sku_pai"]) == ["A", "B"]

    def test_grupo_construcao_e_opcional(self):
        # a aba de aposta não pergunta mais a construção: sem `grupo`, modelos de
        # construções diferentes (mesmo tecido) são todos candidatos.
        cat = _catalogo([("A", "Azul", None, "INVERNO 2023"),
                         ("B", "Azul", None, "INVERNO 2023")])
        cat.loc[cat["cod_sku_pai"] == "B", "desc_grupo_wgb"] = "MALHA"
        cand, _ = candidatos_espelho(cat, subgrupo="VESTIDO", faixas="P1",
                                     tecido="Linho", cor_grupo="Azul")
        assert sorted(cand["cod_sku_pai"]) == ["A", "B"]
        # informando o grupo, ele volta a filtrar
        cand, _ = candidatos_espelho(cat, subgrupo="VESTIDO", grupo="MALHA",
                                     faixas="P1", tecido="Linho", cor_grupo="Azul")
        assert cand["cod_sku_pai"].tolist() == ["B"]

    def test_colecao_fora_do_escopo_nao_vira_candidato(self):
        cat = _catalogo([("A", "Azul", "MANGA LONGA", "INVERNO 2023"),
                         ("P", "Azul", "MANGA LONGA", "PERENE"),
                         ("V", "Azul", "MANGA LONGA", "ALTO VERÃO 2024 2025"),
                         ("O", "Azul", "MANGA LONGA", "INVERNO 2019")])
        cand, _ = candidatos_espelho(cat, subgrupo="VESTIDO", grupo="TECIDO PLANO",
                                     faixas="P1", tecido="Linho", cor_grupo="Azul",
                                     min_candidatos=1)
        assert cand["cod_sku_pai"].tolist() == ["A"]


class TestPoolSuavizacao:
    def test_mesmo_subgrupo_tecido_e_escopo(self):
        cat = _catalogo([("A", "Azul", None, "INVERNO 2023"),
                         ("B", "Preto", None, "INVERNO 2023"),      # cor diferente entra
                         ("V", "Azul", None, "INVERNO 2019")])      # fora do escopo sai
        cat.loc[cat["cod_sku_pai"] == "B", "grupo_material"] = "Linho"
        outro = _catalogo([("T", "Azul", None, "INVERNO 2023")])
        outro["grupo_material"] = "Tricot"
        import pandas as pd
        pool = pool_suavizacao(pd.concat([cat, outro]), subgrupo="VESTIDO", tecido="Linho")
        assert pool == {"A", "B"}

    def test_fit_restringe_quando_informado(self):
        cat = _catalogo([("A", "Azul", None, "INVERNO 2023"),
                         ("B", "Azul", None, "INVERNO 2023")])
        cat.loc[cat["cod_sku_pai"] == "B", "desc_fit"] = "AMPLO"
        pool = pool_suavizacao(cat, subgrupo="VESTIDO", tecido="Linho", fits=["RETO"])
        assert pool == {"A"}
        pool = pool_suavizacao(cat, subgrupo="VESTIDO", tecido="Linho", fits=None)
        assert pool == {"A", "B"}


def _cat_tamanhos(linhas):
    """linhas = [(cod_sku_pai, sk_produto, tamanho_grupo, tecido, fit)]"""
    return pd.DataFrame([
        {"cod_sku_pai": s, "sk_produto": sk, "tamanho_grupo": t,
         "desc_sub_grupo_wbg": "VESTIDO", "grupo_material": tec, "desc_fit": fit,
         "rank_colecao": 2023.0}
        for s, sk, t, tec, fit in linhas
    ])


def _vendas_tamanhos(linhas):
    """linhas = [(sk_produto, cod_sku_pai, qtd)]"""
    return pd.DataFrame([{"sk_produto": sk, "cod_sku_pai": s, "qtd_produto": q}
                         for sk, s, q in linhas])


class TestCurvaTamanhosGrade:
    GRADE = ["40|P", "42|M", "46|GG"]

    def test_corta_tamanhos_fora_da_grade_e_preserva_proporcao(self):
        # espelho E vendeu P=2, M=1 e U=7 (U fora da grade [P, M]): U é cortado
        # e a proporção P:M (2:1) é preservada; tudo origem "espelhos".
        cat = _cat_tamanhos([("E", 1, "40|P", "Linho", "RETO"),
                             ("E", 2, "42|M", "Linho", "RETO"),
                             ("E", 3, "U", "Linho", "RETO")])
        ven = _vendas_tamanhos([(1, "E", 2), (2, "E", 1), (3, "E", 7)])
        curva, origem, avisos = curva_tamanhos_grade(
            ven, cat, ["E"], ["40|P", "42|M"], subgrupo="VESTIDO", tecido="Linho")
        assert list(curva) == ["40|P", "42|M"]
        assert curva["40|P"] / curva["42|M"] == pytest.approx(2.0)
        assert set(origem.values()) == {"espelhos"}
        assert avisos == []

    def test_faltante_projetado_com_calibracao_pelos_comuns(self):
        # espelhos E: P=1, M=1 (sem GG). Pool = {E, Z}; Z: P=3, M=3, GG=4.
        # Vendas do pool: P=4, M=4, GG=4 -> curva 1/3 cada; comuns P+M somam 1.0
        # no espelho e 2/3 no pool => escala 1.5 => GG = (1/3)*1.5 = 0.5.
        cat = _cat_tamanhos([("E", 1, "40|P", "Linho", "RETO"),
                             ("E", 2, "42|M", "Linho", "RETO"),
                             ("Z", 4, "40|P", "Linho", "RETO"),
                             ("Z", 5, "42|M", "Linho", "RETO"),
                             ("Z", 6, "46|GG", "Linho", "RETO")])
        ven = _vendas_tamanhos([(1, "E", 1), (2, "E", 1),
                                (4, "Z", 3), (5, "Z", 3), (6, "Z", 4)])
        curva, origem, avisos = curva_tamanhos_grade(
            ven, cat, ["E"], self.GRADE, subgrupo="VESTIDO", tecido="Linho")
        assert origem == {"40|P": "espelhos", "42|M": "espelhos", "46|GG": "pool_tecido"}
        assert curva["46|GG"] == pytest.approx(0.5)
        assert any("46|GG" in a and "subgrupo+tecido" in a for a in avisos)

    def test_cadeia_de_pools_fit_depois_tecido_depois_subgrupo(self):
        # pool do fit RETO não tem GG; quem tem é o AMPLO (mesmo tecido) -> o
        # nível fit é pulado e o tamanho vem do pool subgrupo+tecido.
        cat = _cat_tamanhos([("E", 1, "40|P", "Linho", "RETO"),
                             ("F", 2, "40|P", "Linho", "RETO"),
                             ("A", 3, "40|P", "Linho", "AMPLO"),
                             ("A", 4, "46|GG", "Linho", "AMPLO")])
        ven = _vendas_tamanhos([(1, "E", 4), (2, "F", 2), (3, "A", 1), (4, "A", 1)])
        curva, origem, _ = curva_tamanhos_grade(
            ven, cat, ["E"], ["40|P", "46|GG"], subgrupo="VESTIDO", tecido="Linho",
            fits=["RETO"])
        assert origem["46|GG"] == "pool_tecido"
        # e se nem o tecido tiver o tamanho, afrouxa para o subgrupo inteiro
        cat.loc[cat["cod_sku_pai"] == "A", "grupo_material"] = "Tricot"
        curva, origem, _ = curva_tamanhos_grade(
            ven, cat, ["E"], ["40|P", "46|GG"], subgrupo="VESTIDO", tecido="Linho",
            fits=["RETO"])
        assert origem["46|GG"] == "pool_subgrupo"

    def test_sem_pool_com_o_tamanho_usa_piso(self):
        cat = _cat_tamanhos([("E", 1, "40|P", "Linho", "RETO"),
                             ("E", 2, "42|M", "Linho", "RETO")])
        ven = _vendas_tamanhos([(1, "E", 4), (2, "E", 2)])
        curva, origem, avisos = curva_tamanhos_grade(
            ven, cat, ["E"], self.GRADE, subgrupo="VESTIDO", tecido="Linho")
        assert origem["46|GG"] == "piso"
        # piso = menor peso presente / 2 (M = 2/6) -> GG = 1/6
        assert curva["46|GG"] == pytest.approx(min(curva["40|P"], curva["42|M"]) / 2)
        assert any("piso" in a for a in avisos)

    def test_espelho_sem_venda_na_grade_usa_pool_direto(self):
        # espelho E só vendeu U (fora da grade): a curva do pool entra direto.
        cat = _cat_tamanhos([("E", 1, "U", "Linho", "RETO"),
                             ("Z", 2, "40|P", "Linho", "RETO"),
                             ("Z", 3, "42|M", "Linho", "RETO")])
        ven = _vendas_tamanhos([(1, "E", 5), (2, "Z", 3), (3, "Z", 1)])
        curva, origem, _ = curva_tamanhos_grade(
            ven, cat, ["E"], ["40|P", "42|M"], subgrupo="VESTIDO", tecido="Linho")
        assert set(origem.values()) == {"pool_tecido"}
        assert curva["40|P"] / curva["42|M"] == pytest.approx(3.0)

    def test_resultado_na_ordem_da_grade(self):
        cat = _cat_tamanhos([("E", 1, "40|P", "Linho", "RETO"),
                             ("E", 2, "42|M", "Linho", "RETO"),
                             ("E", 3, "46|GG", "Linho", "RETO")])
        ven = _vendas_tamanhos([(1, "E", 1), (2, "E", 2), (3, "E", 3)])
        grade = ["46|GG", "40|P", "42|M"]     # ordem proposital fora do padrão
        curva, _, _ = curva_tamanhos_grade(
            ven, cat, ["E"], grade, subgrupo="VESTIDO", tecido="Linho")
        assert list(curva) == grade


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

    def test_parque_reduzido_reduz_o_fisico_e_preserva_o_ecom(self):
        # semântica do REDUTOR Perfil/Clima da etapa Projeção: menos lojas no
        # parque => venda física cai proporcional; o Ecom não é loja e não muda.
        reg = [("2024-01-03", 1, 10, "X"), ("2024-01-03", 456, 5, "X")]
        ve = velocidade_por_loja_desaz(_vendas(reg), "X", CURVA_NEUTRA, ecom_locs={456})
        cheio = projetar_aposta([ve], CURVA_NEUTRA, "2024-01-01", 20,
                                horizonte_semanas=10, aproveitamento=1.0, reserva_cd_pct=0.0)
        reduzido = projetar_aposta([ve], CURVA_NEUTRA, "2024-01-01", 5,
                                   horizonte_semanas=10, aproveitamento=1.0, reserva_cd_pct=0.0)
        assert reduzido.venda_ecom == cheio.venda_ecom == pytest.approx(50.0)
        assert (reduzido.venda_projetada - reduzido.venda_ecom) == pytest.approx(
            (cheio.venda_projetada - cheio.venda_ecom) * 5 / 20)

    def test_avisa_que_ecom_entra_na_aposta(self):
        reg = [("2024-01-03", 1, 10, "X"), ("2024-01-03", 456, 5, "X")]
        ve = velocidade_por_loja_desaz(_vendas(reg), "X", CURVA_NEUTRA, ecom_locs={456})
        ap = projetar_aposta([ve], CURVA_NEUTRA, "2024-01-01", 5, horizonte_semanas=1)
        assert any("Ecom" in a for a in ap.avisos)


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

    def test_perfil_e_clima_par_exato(self):
        part_hist = {"1": 0.5, "2": 0.3, "3": 0.2}
        chaves = {"1": ("A", "Quente"), "2": ("A", "Quente"),
                  "3": ("AB", "Frio"), "9": ("A", "Quente")}
        out = participacao_com_loja_nova(part_hist, ["1", "2", "3", "9"], chaves)
        # loja 9 herda a média de (A, Quente) = (0.5+0.3)/2 = 0.4, antes de renormalizar
        assert out["9"] == pytest.approx(0.4 / 1.4)

    def test_combinacao_inexistente_afrouxa_para_o_perfil(self):
        # no parque real não existe loja Perfil AB com clima Frio: sem o
        # afrouxamento a loja nova cairia na média geral, que é pior.
        part_hist = {"1": 0.2, "2": 0.2, "3": 0.6}
        chaves = {"1": ("A", "Frio"), "2": ("A", "Quente"),
                  "3": ("AB", "Quente"), "9": ("AB", "Frio")}
        out = participacao_com_loja_nova(part_hist, ["1", "2", "3", "9"], chaves)
        # (AB, Frio) não existe -> usa a média de AB = 0.6
        assert out["9"] == pytest.approx(0.6 / 1.6)


class TestLojaEspelhoNova:
    """Regra do negócio: loja nova sem dado próprio usa fator × loja espelho
    (ex.: Casa Jardins = 75% do Iguatemi SP)."""

    ESPELHOS = {"casa": ("igua", 0.75, "Casa Jardins", "Iguatemi SP")}

    def test_sem_dado_proprio_usa_fator_da_loja_espelho(self):
        part_hist = {"igua": 0.4, "2": 0.6}
        out = participacao_com_loja_nova(
            part_hist, ["igua", "2", "casa"], {}, lojas_espelho=self.ESPELHOS,
            com_dado_proprio=set())
        # a renormalização preserva as proporções: casa = 75% do iguatemi
        assert out["casa"] / out["igua"] == pytest.approx(0.75)

    def test_com_venda_do_espelho_selecionado_o_dado_real_prevalece(self):
        part_hist = {"igua": 0.4, "2": 0.5, "casa": 0.1}
        out = participacao_com_loja_nova(
            part_hist, ["igua", "2", "casa"], {}, lojas_espelho=self.ESPELHOS,
            com_dado_proprio={"casa"})
        assert out["casa"] == pytest.approx(0.1)       # já soma 1, não muda

    def test_participacao_subestimada_e_substituida_pela_regra(self):
        # loja aberta ha pouco aparece no historico com share minusculo (janela
        # curta); sem venda dos espelhos selecionados, a regra corrige.
        part_hist = {"igua": 0.4, "2": 0.58, "casa": 0.02}
        out = participacao_com_loja_nova(
            part_hist, ["igua", "2", "casa"], {}, lojas_espelho=self.ESPELHOS,
            com_dado_proprio=set())
        assert out["casa"] / out["igua"] == pytest.approx(0.75)

    def test_sem_com_dado_proprio_mantem_comportamento_antigo(self):
        # default (None): a regra só cobre quem está fora do histórico
        part_hist = {"igua": 0.4, "2": 0.5, "casa": 0.1}
        out = participacao_com_loja_nova(
            part_hist, ["igua", "2", "casa"], {}, lojas_espelho=self.ESPELHOS)
        assert out["casa"] == pytest.approx(0.1)

    def test_espelho_sem_historico_cai_no_cluster(self):
        part_hist = {"2": 1.0}
        clusters = {"2": "Prata", "casa": "Prata"}
        out = participacao_com_loja_nova(
            part_hist, ["2", "casa"], clusters, lojas_espelho=self.ESPELHOS,
            com_dado_proprio=set())
        assert out["casa"] == pytest.approx(1.0 / 2.0)   # média das Prata


class TestJanelaFullPrice:
    def test_janela_alarga_e_derruba_a_velocidade(self):
        # vendeu 10 un em 1 semana, mas ficou exposto 10 semanas ate liquidar:
        # a velocidade real e diluida pelas semanas em que nao vendeu.
        reg = [("2024-01-03", 1, 10, "X")]
        sem = velocidade_por_loja_desaz(_vendas(reg), "X", CURVA_NEUTRA)
        com = velocidade_por_loja_desaz(_vendas(reg), "X", CURVA_NEUTRA,
                                        janela=(pd.Timestamp("2024-01-01"), pd.Timestamp("2024-03-11")))
        assert com.semanas_ativas > sem.semanas_ativas
        assert com.vel_por_loja_desaz < sem.vel_por_loja_desaz
        assert com.unidades == sem.unidades          # nunca perde venda

    def test_janela_nunca_encurta_nem_descarta_venda(self):
        # venda full price DEPOIS da liquidacao (status do catalogo x flag da
        # transacao) e ANTES da entrada presumida (dt_envio+7 e premissa):
        # vale a venda real, a janela nao pode cortar.
        reg = [("2024-01-03", 1, 5, "X"), ("2024-06-05", 1, 5, "X")]
        com = velocidade_por_loja_desaz(_vendas(reg), "X", CURVA_NEUTRA,
                                        janela=(pd.Timestamp("2024-02-01"), pd.Timestamp("2024-03-01")))
        assert com.unidades == 10
        assert com.semanas_ativas >= 22               # cobre ate a ultima venda

    def test_sem_janela_conhecida_usa_primeira_e_ultima_venda(self):
        reg = [("2024-01-03", 1, 10, "X")]
        a = velocidade_por_loja_desaz(_vendas(reg), "X", CURVA_NEUTRA, janela=(None, None))
        b = velocidade_por_loja_desaz(_vendas(reg), "X", CURVA_NEUTRA)
        assert a.semanas_ativas == b.semanas_ativas

    def test_sem_liquidacao_mas_ainda_vendendo_vai_ate_hoje(self):
        # produto da safra corrente: vendeu ha 5 dias e nao tem liquidacao =>
        # segue a full price, entao as semanas paradas contam ate hoje.
        reg = [("2026-05-01", 1, 10, "X"), ("2026-07-10", 1, 1, "X")]
        ve = velocidade_por_loja_desaz(_vendas(reg), "X", CURVA_NEUTRA,
                                       janela=(pd.Timestamp("2026-05-01"), None),
                                       ativo_ate=pd.Timestamp("2026-07-15"))
        assert ve.semanas_ativas == pytest.approx(11.7, abs=0.2)   # 01/05 -> 15/07

    def test_sem_liquidacao_e_parado_ha_meses_para_na_ultima_venda(self):
        # produto antigo que sumiu sem registrar liquidacao: esticar ate hoje
        # diluiria a velocidade em anos de prateleira que nunca existiram.
        reg = [("2023-01-02", 1, 10, "X"), ("2023-03-06", 1, 5, "X")]
        ve = velocidade_por_loja_desaz(_vendas(reg), "X", CURVA_NEUTRA,
                                       janela=(pd.Timestamp("2023-01-02"), None),
                                       ativo_ate=pd.Timestamp("2026-07-15"))
        assert ve.semanas_ativas < 15          # ~9 semanas, nao ~180

    def test_liquidacao_conhecida_ignora_a_regra_de_hoje(self):
        reg = [("2026-05-01", 1, 10, "X"), ("2026-07-10", 1, 1, "X")]
        ve = velocidade_por_loja_desaz(_vendas(reg), "X", CURVA_NEUTRA,
                                       janela=(pd.Timestamp("2026-05-01"), pd.Timestamp("2026-07-12")),
                                       ativo_ate=pd.Timestamp("2026-12-31"))
        assert ve.semanas_ativas == pytest.approx(11.3, abs=0.2)   # para na liquidacao


class TestGradeCompleta:
    CURVA5 = {"PP": 1, "P": 2, "M": 2, "G": 1, "GG": 1}

    def _distribui(self, garantir, aposta=30, reserva=0.0):
        from core.regra_distribuicao import distribuir
        return distribuir(aposta_total=aposta, participacoes={"L1": 0.9, "L2": 0.1},
                          curva_tamanhos=self.CURVA5, reserva_cd_pct=reserva,
                          max_por_tamanho_loja=None, garantir_grade_completa=garantir)

    def test_garantida_toda_loja_recebe_1_de_cada_tamanho(self):
        # sem reserva nem sobra, o CD esta zerado: o deficit e SOMADO a aposta e
        # o rateio das demais lojas nao muda.
        r = self._distribui(True)
        for loja, tams in r.matriz.items():
            assert sum(tams.values()) >= 5, f"{loja} nao recebeu a grade"
            assert all(q >= 1 for q in tams.values()), f"{loja} ficou com tamanho zerado"
        assert r.acrescimo_garantia > 0
        assert r.total_distribuido() == 30 + r.acrescimo_garantia
        assert any("SOMADAS" in a for a in r.avisos)

    def test_garantia_usa_o_cd_antes_de_somar(self):
        # loja pequena (10% de 10 un) fica sem varios tamanhos; a reserva do CD
        # (4 un) cobre o deficit inteiro -> nada e somado a aposta.
        r = self._distribui(True, aposta=10, reserva=0.40)
        for loja, tams in r.matriz.items():
            assert all(q >= 1 for q in tams.values()), f"{loja} com tamanho zerado"
        assert r.acrescimo_garantia == 0
        assert r.reserva_cd < 4.0                       # reserva foi consumida
        assert any("usou" in a and "do CD" in a for a in r.avisos)
        assert r.total_distribuido() == 10 - int(r.reserva_cd)   # aposta nao cresceu

    def test_soma_apenas_depois_de_esgotar_o_cd(self):
        # reserva de 1 un nao cobre o deficit: 1 sai do CD (zera) e o resto e
        # SOMADO a aposta, com os dois avisos.
        r = self._distribui(True, aposta=10, reserva=0.10)
        for loja, tams in r.matriz.items():
            assert all(q >= 1 for q in tams.values()), f"{loja} com tamanho zerado"
        assert r.reserva_cd == pytest.approx(0.0)       # CD esgotou primeiro
        assert r.acrescimo_garantia > 0
        assert any("usou" in a and "do CD" in a for a in r.avisos)
        assert any("CD esgotado" in a for a in r.avisos)

    def test_aposta_pequena_nenhuma_loja_fica_sem_grade(self):
        # aposta 7 < piso 10: mesmo assim TODAS as lojas levam a grade completa
        # (nunca "ficaram sem grade").
        r = self._distribui(True, aposta=7)
        for loja, tams in r.matriz.items():
            assert all(q >= 1 for q in tams.values()), f"{loja} com tamanho zerado"
        assert not any("ficaram sem grade" in a for a in r.avisos)
        assert r.total_distribuido() == 7 + r.acrescimo_garantia

    def test_desligada_permite_grade_incompleta(self):
        r = self._distribui(False)
        assert r.acrescimo_garantia == 0
        assert sum(r.matriz["L2"].values()) > 0        # loja pequena permanece
        assert any(q == 0 for q in r.matriz["L2"].values())   # com tamanho faltando


class TestTetosDaDistribuicao:
    def test_teto_de_pecas_por_sku_tamanho(self):
        from core.regra_distribuicao import distribuir
        r = distribuir(aposta_total=100, participacoes={"L1": 0.5, "L2": 0.5},
                       curva_tamanhos={"M": 1.0}, reserva_cd_pct=0.0,
                       max_por_tamanho_loja=4)
        assert r.matriz["L1"]["M"] == 4 and r.matriz["L2"]["M"] == 4
        assert r.sobra_para_cd == 92          # o excedente volta ao CD
        assert any("teto de 4" in a for a in r.avisos)

    def test_teto_de_cobertura_usa_a_velocidade_da_loja(self):
        from core.regra_distribuicao import distribuir
        r = distribuir(aposta_total=200, participacoes={"L1": 0.5, "L2": 0.5},
                       curva_tamanhos={"P": 1, "M": 1, "G": 1}, reserva_cd_pct=0.0,
                       velocidades_semanais={"L1": 2.0, "L2": 10.0},
                       cobertura_max_semanas=6, max_por_tamanho_loja=None)
        assert sum(r.matriz["L1"].values()) == 12    # 2/sem * 6 semanas
        assert sum(r.matriz["L2"].values()) == 60    # 10/sem * 6 semanas

    def test_sem_teto_por_tamanho_quando_desligado(self):
        from core.regra_distribuicao import distribuir
        r = distribuir(aposta_total=100, participacoes={"L1": 1.0},
                       curva_tamanhos={"M": 1.0}, reserva_cd_pct=0.0,
                       max_por_tamanho_loja=None)
        assert r.matriz["L1"]["M"] == 100


class TestColecaoEHorizonte:
    def test_fim_de_periodo_por_estacao(self):
        from core.dados import fim_periodo_saudavel
        from datetime import date
        assert fim_periodo_saudavel("INVERNO 2027") == date(2027, 6, 14)
        assert fim_periodo_saudavel("VERÃO 2026-2027") == date(2027, 1, 2)

    def test_horizonte_da_entrada_ate_o_fim(self):
        from core.dados import semanas_ate
        assert semanas_ate("2027-01-20", "2027-06-14") == 21
        assert semanas_ate("2027-06-01", "2027-06-14") == 2

    def test_horizonte_tem_piso_de_1_semana(self):
        from core.dados import semanas_ate
        assert semanas_ate("2027-06-20", "2027-06-14") == 1   # entrada após o fim

    def test_colecoes_projetaveis_em_ordem_cronologica(self):
        from core.dados import colecoes_projetaveis
        assert colecoes_projetaveis(2026)[:3] == ["INVERNO 2026", "VERÃO 2026-2027", "INVERNO 2027"]
