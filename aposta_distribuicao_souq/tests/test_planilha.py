"""Testes da planilha-mãe (export/import Excel de cenários).

`montar_cenario` usa dados sintéticos e monkeypatch dos cadastros de loja —
nenhum teste toca as bases reais.
"""
from io import BytesIO

import pandas as pd
import pytest

from core import planilha

CTX = {
    "subgrupos": {"VESTIDO", "REGATA"},
    "tecidos": {"Linho", "Algodão"},
    "tamanhos": {"36|XPP", "38|PP", "40|P", "42|M", "44|G", "46|GG", "U"},
    "perfis": {"A", "AB"},
    "climas": {"Quente", "Frio"},
    "ids": {"abc-123"},
}

PAYLOAD_V2 = {
    "versao": 2, "resumo": "x", "aposta_total": 90.0, "aposta_final": 120.0,
    "reserva_cd_pct": 0.20,
    "parque": {"perfis": ["A"], "climas": ["Quente"], "n_lojas_alvo": 10},
    "curva_tamanhos": {"38|PP": 0.1, "40|P": 0.25},
    "espelhos": ["04.25.11.001.002", "04.25.11.003.001"],
    "max_por_tamanho_loja": 4, "garantir_grade_completa": True,
    "inputs": {"sku_ref": "04.26.11.497", "subgrupo": "VESTIDO", "tecido": "Linho",
               "faixas": ["P2", "P3"], "cores": ["Azul", "Preto"],
               "grade": ["38|PP", "40|P"], "colecao": "INVERNO 2027",
               "dt_entrada": "2027-01-20", "aproveitamento": 0.70},
}


def _linha_base(**kw):
    linha = {"id": "", "sku_ref": "", "subgrupo": "VESTIDO", "tecido": "Linho",
             "faixas": "P1", "cores": "", "grade": "40|P;42|M",
             "colecao": "INVERNO 2027", "dt_entrada": "2027-01-20",
             "aproveitamento_pct": 70, "reserva_cd_pct": 20, "perfis": "",
             "climas": "", "aposta_final": 50, "espelhos": "",
             "curva_tamanhos": "", "max_por_tamanho_loja": "",
             "garantir_grade_completa": ""}
    linha.update(kw)
    return linha


def _df(*linhas):
    return pd.DataFrame(list(linhas), columns=[c for c in planilha.COLUNAS
                                               if c != "aposta_modelo"])


class TestRoundTrip:
    def test_exportar_e_validar_devolvem_os_mesmos_campos(self):
        xls = planilha.exportar([{"id": "abc-123", "payload": PAYLOAD_V2}])
        df = pd.read_excel(BytesIO(xls), sheet_name="cenarios")
        linhas, erros = planilha.validar(df, CTX)
        assert erros == []
        l = linhas[0]
        assert l["id"] == "abc-123"
        assert l["subgrupo"] == "VESTIDO" and l["tecido"] == "Linho"
        assert l["faixas"] == ["P2", "P3"]
        assert l["cores"] == ["Azul", "Preto"]
        assert l["grade"] == ["38|PP", "40|P"]      # '|' sobrevive ao ';'
        assert l["colecao"] == "INVERNO 2027" and l["dt_entrada"] == "2027-01-20"
        assert l["aproveitamento_pct"] == 70 and l["reserva_cd_pct"] == 20
        assert l["perfis"] == ["A"] and l["climas"] == ["Quente"]
        assert l["aposta_final"] == 120.0
        assert l["espelhos"] == ["04.25.11.001.002", "04.25.11.003.001"]
        assert l["curva_tamanhos"] == {"38|PP": pytest.approx(0.1),
                                       "40|P": pytest.approx(0.25)}
        assert l["max_por_tamanho_loja"] == 4
        assert l["garantir_grade_completa"] is True

    def test_leia_me_documenta_todas_as_colunas(self):
        xls = planilha.exportar([])
        leia = pd.read_excel(BytesIO(xls), sheet_name="leia-me")
        assert leia["Coluna"].tolist() == planilha.COLUNAS


class TestValidar:
    def test_obrigatorio_vazio(self):
        _, erros = planilha.validar(_df(_linha_base(subgrupo="")), CTX)
        assert erros == ["Linha 2: campo obrigatório 'subgrupo' vazio."]

    def test_dominios_invalidos_apontam_a_linha_certa(self):
        df = _df(_linha_base(),                                   # linha 2: ok
                 _linha_base(faixas="P1;P9"),                     # linha 3
                 _linha_base(grade="40|P;48|GGG"),                # linha 4
                 _linha_base(colecao="INV 27"),                   # linha 5
                 _linha_base(dt_entrada="31/02/2027"),            # linha 6
                 _linha_base(aposta_final=-5),                    # linha 7
                 _linha_base(perfis="AAA"),                       # linha 8
                 _linha_base(id="nao-existe"),                    # linha 9
                 _linha_base(subgrupo="VESTIDOO"))                # linha 10
        linhas, erros = planilha.validar(df, CTX)
        assert linhas == []                                       # all-or-nothing
        assert any(e.startswith("Linha 3: faixa 'P9'") for e in erros)
        assert any(e.startswith("Linha 4: tamanho '48|GGG'") for e in erros)
        assert any(e.startswith("Linha 5: coleção 'INV 27'") for e in erros)
        assert any(e.startswith("Linha 6: dt_entrada") for e in erros)
        assert any("Linha 7: aposta_final deve ser um número > 0" in e for e in erros)
        assert any(e.startswith("Linha 8: perfil 'AAA'") for e in erros)
        assert any(e.startswith("Linha 9: id 'nao-existe'") for e in erros)
        assert any(e.startswith("Linha 10: subgrupo 'VESTIDOO'") for e in erros)

    def test_curva_com_tamanho_fora_da_grade(self):
        _, erros = planilha.validar(
            _df(_linha_base(curva_tamanhos="46|GG=0.3")), CTX)
        assert any("curva_tamanhos tem o tamanho '46|GG'" in e for e in erros)

    def test_coluna_ausente_orienta_a_usar_o_export(self):
        df = _df(_linha_base()).drop(columns=["grade"])
        linhas, erros = planilha.validar(df, CTX)
        assert linhas == [] and "grade" in erros[0] and "export" in erros[0]

    def test_datas_em_tres_formatos(self):
        for dt in ("2027-01-20", "20/01/2027", pd.Timestamp("2027-01-20")):
            linhas, erros = planilha.validar(_df(_linha_base(dt_entrada=dt)), CTX)
            assert erros == [] and linhas[0]["dt_entrada"] == "2027-01-20"


# --------------------------------------------------------------------------- #
# montar_cenario (rateio) — cadastros de loja via monkeypatch
# --------------------------------------------------------------------------- #
LOJAS = pd.DataFrame([
    {"sk_localidade": 1.0, "desc_nome": "Loja Um", "Perfil": "A", "Temperatura": "Quente"},
    {"sk_localidade": 2.0, "desc_nome": "Loja Dois", "Perfil": "AB", "Temperatura": "Frio"},
])


def _lojas_fake(perfis=None, climas=None):
    df = LOJAS
    if perfis:
        df = df[df["Perfil"].isin(perfis)]
    if climas:
        df = df[df["Temperatura"].isin(climas)]
    return df.reset_index(drop=True)


@pytest.fixture(autouse=True)
def _cadastros_fake(monkeypatch):
    monkeypatch.setattr(planilha, "lojas_alvo_souq", _lojas_fake)
    monkeypatch.setattr(planilha, "cluster_por_loja",
                        lambda: {"1.0": ("A", "Quente"), "2.0": ("AB", "Frio")})
    monkeypatch.setattr(planilha, "espelhos_loja_nova", lambda: {})


PP = pd.DataFrame([
    {"cod_sku_pai": "E", "sk_produto": 1, "tamanho_grupo": "40|P",
     "desc_sub_grupo_wbg": "VESTIDO", "grupo_material": "Linho",
     "desc_fit": "RETO", "rank_colecao": 2023.0},
    {"cod_sku_pai": "E", "sk_produto": 2, "tamanho_grupo": "42|M",
     "desc_sub_grupo_wbg": "VESTIDO", "grupo_material": "Linho",
     "desc_fit": "RETO", "rank_colecao": 2023.0},
])
FP = pd.DataFrame([
    {"sk_produto": 1, "cod_sku_pai": "E", "qtd_produto": 6, "sk_localidade": 1.0},
    {"sk_produto": 2, "cod_sku_pai": "E", "qtd_produto": 3, "sk_localidade": 2.0},
])
CFG = {"desde_colecao": 2022.0, "max_por_tamanho_loja": 4, "ecom_locs": set()}


def _linha_valida(**kw):
    linha = {"id": None, "sku_ref": "REF1", "subgrupo": "VESTIDO", "tecido": "Linho",
             "faixas": ["P1"], "cores": [], "grade": ["40|P", "42|M"],
             "colecao": "INVERNO 2027", "dt_entrada": "2027-01-20",
             "aproveitamento_pct": 70, "reserva_cd_pct": 20,
             "perfis": None, "climas": None, "aposta_final": 50.0,
             "espelhos": ["E"], "curva_tamanhos": {},
             "max_por_tamanho_loja": None, "garantir_grade_completa": True}
    linha.update(kw)
    return linha


class TestMontarCenario:
    def test_payload_v2_com_matriz_e_total_fechando(self):
        payload, resultado = planilha.montar_cenario(_linha_valida(), PP, FP, CFG)
        assert payload["versao"] == 2 and payload["origem"] == "import"
        assert payload["resumo"] == "REF1 · VESTIDO/Linho · P1 · INVERNO 2027"
        assert payload["parque"]["n_lojas_alvo"] == 2
        matriz = payload["distribuicao_editada"]
        assert "Loja Um (A/Quente)" in matriz            # lojas com nome completo
        # invariante: lojas + CD = aposta final (com eventual acréscimo da grade)
        total = sum(sum(t.values()) for t in matriz.values())
        assert total == int(round(payload["aposta_final"]))
        assert payload["aposta_final"] == 50.0 + resultado.acrescimo_garantia

    def test_sem_espelhos_usa_o_segmento(self):
        payload, _ = planilha.montar_cenario(_linha_valida(espelhos=[]), PP, FP, CFG)
        assert payload["espelhos"] == []
        assert payload["participacoes_hist"]             # veio do pool do segmento
        assert set(payload["curva_tamanhos"]) == {"40|P", "42|M"}

    def test_parque_por_perfil_reduz_as_lojas(self):
        payload, _ = planilha.montar_cenario(_linha_valida(perfis=["A"]), PP, FP, CFG)
        assert payload["parque"]["n_lojas_alvo"] == 1
        assert all("Loja Dois" not in l for l in payload["distribuicao_editada"])

    def test_parque_vazio_levanta_erro_de_linha(self):
        with pytest.raises(ValueError, match="nenhuma loja ativa"):
            planilha.montar_cenario(
                _linha_valida(perfis=["A"], climas=["Frio"]), PP, FP, CFG)

    def test_curva_parcial_completada_e_calibrada_pelo_segmento(self):
        # planilha fixa 40|P=0.6; 42|M vem do segmento calibrado: a proporção
        # observada é 40|P: 6/9 e 42|M: 3/9 => 42|M = (3/9) × (0.6 ÷ (6/9)) = 0.3
        payload, _ = planilha.montar_cenario(
            _linha_valida(curva_tamanhos={"40|P": 0.6}), PP, FP, CFG)
        assert payload["curva_tamanhos"]["40|P"] == pytest.approx(0.6)
        assert payload["curva_tamanhos"]["42|M"] == pytest.approx(0.3)
        assert payload["curva_origem"] == {"40|P": "planilha", "42|M": "espelhos"}

    def test_curva_completa_da_planilha_prevalece(self):
        payload, _ = planilha.montar_cenario(
            _linha_valida(curva_tamanhos={"40|P": 0.7, "42|M": 0.3}), PP, FP, CFG)
        assert payload["curva_tamanhos"] == {"40|P": 0.7, "42|M": 0.3}
        assert set(payload["curva_origem"].values()) == {"planilha"}
