import pandas as pd, config, engine
from data_source import carregar_excel
hoje = config.data_referencia()
print("hoje (data_referencia):", hoje)
dados = carregar_excel(hoje)
v = dados["vendas"]; print("vendas data min/max:", v["data"].min(), v["data"].max())
el = dados["estoque_loja"]; print("estoque_loja linhas:", len(el))
rec = dados["recebimento"]; print("recebimento linhas:", len(rec))
if not rec.empty:
    print("recebimento data min/max:", rec["data_recebimento"].min(), rec["data_recebimento"].max())

# Recalcula doadoras passo a passo
import numpy as np
dias_min = 14
hoje_ts = pd.Timestamp(hoje)
d = el[el["qtd"] > 0].copy()
d = d.merge(rec, on=["loja","sku_filho"], how="left")
d["dias_em_loja"] = (hoje_ts - d["data_recebimento"]).dt.days
uv = engine._ultima_venda(v)
d = d.merge(uv, on=["loja","sku_filho"], how="left")
ref = d["ultima_venda"].fillna(d["data_recebimento"])
d["dias_sem_venda"] = (hoje_ts - ref).dt.days
print("\ndias_sem_venda nulos:", d["dias_sem_venda"].isna().sum(), "de", len(d))
print("dias_sem_venda describe:\n", d["dias_sem_venda"].describe())
print("dias_em_loja describe:\n", d["dias_em_loja"].describe())
sv_ok = d["dias_sem_venda"].fillna(9999) >= dias_min
el_ok = d["dias_em_loja"].isna() | (d["dias_em_loja"] >= dias_min)
print("sem_venda_ok:", sv_ok.sum(), "| em_loja_ok:", el_ok.sum(), "| ambos:", (sv_ok & el_ok).sum())
