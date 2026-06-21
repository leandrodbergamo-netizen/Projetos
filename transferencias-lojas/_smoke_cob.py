import time, config, engine
from data_source import carregar_excel

hoje = config.data_referencia()
t0 = time.time()
dados = carregar_excel(hoje, usar_cache=False)  # rebuild com novo schema
print("Build %.0fs" % (time.time()-t0))

res = engine.calcular(dados, hoje)
nec, doa, sug = res["necessidades"], res["doadoras"], res["sugestoes"]
print("Necessidades:", len(nec), "| Doadoras:", len(doa), "| Sugestoes:", len(sug))

print("\nColunas necessidades:", list(nec.columns))
print(nec.head(8).to_string(index=False))

# validacoes
lim = {"Home":10,"Acessórios":4,"Roupa":2}
assert sug.empty or sug.apply(lambda r: r["qtd"] <= lim[r["grupo"]], axis=1).all()
chk = sug.groupby("loja_doadora")["loja_receptora"].nunique()
assert chk.max() <= 4
print("\nMax lojas/doadora:", int(chk.max()))
print("qtd_sugerida distrib:", nec["qtd_sugerida"].value_counts().sort_index().to_dict())
print("OK")
print("\nTop sugestoes:")
print(sug.head(6).to_string(index=False))
