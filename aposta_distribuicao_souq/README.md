# Aposta & Distribuição — Souq Roupa

App local em Python + Streamlit para planejar aposta e distribuição inicial de produtos novos da linha Roupa.

## Estrutura proposta

- `app/` = páginas Streamlit
- `core/` = regras puras e pipeline
- `config/` = parâmetros e cadastros auxiliares
- `docs/` = documentação e exemplos
- `tests/` = testes unitários

## Como rodar

```powershell
cd c:\Users\LeandroDias\Projetos\aposta_distribuicao_souq
pip install -r requirements.txt
streamlit run app.py
```

A 1ª carga lê as vendas de 2022–2026 (~20s) e fica em cache. Mexeu nos Excel?
Use o botão **🔄 Recarregar bases** na barra lateral.

## Publicar na nuvem (Supabase + Streamlit Cloud)

Mesmo desenho do app de transferências: o Excel **não** vai para a nuvem. O seu PC
prepara os dados e publica no Supabase; o app hospedado lê as tabelas prontas.

```
SEU PC (Excel)  →  publica_supabase.py  →  SUPABASE (Postgres)  →  Streamlit Cloud
```

As tabelas usam o prefixo **`aposta_`** (`aposta_produtos`, `aposta_vendas`,
`aposta_lojas`, `aposta_faixas`) para conviver, no mesmo banco, com as do app de
transferências — que tem uma tabela `produtos` e a recria a cada publicação.
**Sem o prefixo, um app apagaria a tabela do outro.**

### 1. No PC (uma vez)
1. Copie `.env.example` para `.env` e preencha `DATABASE_URL` com a string do
   **Pooler** do Supabase (Settings → Database → Connection pooling). É o mesmo
   banco do app de transferências.
2. Publique:
   ```powershell
   python publica_supabase.py
   ```

### 2. No Streamlit Cloud
- **Main file:** `aposta_distribuicao_souq/app.py`
- **Secrets:**
  ```toml
  FONTE_DADOS = "supabase"
  DATABASE_URL = "postgresql+psycopg2://..."
  ```
- Deixe o app **privado**, restrito aos e-mails do time.

### 3. Manutenção
Rode `python publica_supabase.py` sempre que quiser atualizar os dados da nuvem
(ex.: depois de atualizar as planilhas ou de um cadastro novo entrar).
