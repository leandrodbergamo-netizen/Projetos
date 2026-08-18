# Guia — Transformar a Auditoria Completeness Souq em App + Publicar no GitHub (via Claude Code)

Documento de referência para abrir este projeto no Claude Code e evoluí-lo de script para app versionado no GitHub.

---

## 1. O que o projeto é hoje

Pasta: `C:\Users\LeandroDias\Claude\Projects\completeness`

| Arquivo | Papel |
|---|---|
| `atualiza_completeness.py` | Script único: coleta o catálogo do site (`souqstore.com.br/products.json`), cruza com as bases internas e gera os acumulados |
| `dashboard.html` | Dashboard estático (abre direto no navegador; lê `data.js`) |
| `data.js` | Payload gerado a cada processamento (`window.DADOS = {...}`) |
| `historico.csv` / `historico_disponibilidade.csv` | Séries acumuladas diárias — **nunca apagar** |
| `detalhe_atual.csv` / `disponibilidade_atual.csv` | Snapshots do dia |
| `_cache_catalogo.json` | Cache da coleta (etapa `--coleta`) |
| `fotos_thumb/` | Miniaturas das fotos dos candidatos |

**Fluxo:** `python atualiza_completeness.py --coleta` → `python atualiza_completeness.py --processa` → abrir `dashboard.html`.

### Dependências externas (fora da pasta)

O script localiza sozinho via caminhos Windows ou variáveis de ambiente:

| Fonte | Caminho padrão | Variável de ambiente |
|---|---|---|
| Bases de leitura (`Base_Produtos.xlsx`, `Base_Estoque.xlsx`) | `C:\Users\LeandroDias\Projetos\dados` | `SOUQ_DADOS_DIR` |
| SKUs exceção (`SOUQ_CONTROLE DESABILITADOS .xlsx`) | OneDrive `...\Ecommerce...\2026\Produto` | `SOUQ_PRODUTO_DIR` |
| Fotos de e-commerce (nomeadas por SKU) | OneDrive `...\Marketing - COLEÇÃO 28 - INVERNO 26 - MONDO` | `SOUQ_FOTOS_DIR` |

Dependências Python: `pandas`, `openpyxl`, `Pillow` (opcional, só para miniaturas).

### Regras de negócio já implementadas (não perder na migração)

- Candidatos = estoque ≥ 2, excluindo SKUs exceção e produtos sem `dt_envio` na Base_Produtos.
- Combined listings (opção Cor com >1 valor) saem do dashboard, mas seus SKUs contam como "no site".
- Contraprova de fotos: candidatos com foto e fora do site + produtos no site sem imagem.
- SKU pai = SKU sem o último segmento quando há mais de 3 pontos.
- **Paginação da coleta: só parar em página vazia** — a plataforma devolve páginas parciais (<250) no meio da série (bug corrigido em 17/08/2026; página 1 devolvia 247 e o loop parava).
- Quebra de série em 14/07/2026 (entrada dos filtros exceção/dt_envio): candidatos ~1686→~1495, disponibilidade ~80,7%→~83%.

---

## 2. Publicar no GitHub

### Pré-requisitos (uma vez)

1. Instalar [Git para Windows](https://git-scm.com/download/win) e [GitHub CLI](https://cli.github.com/) (`winget install Git.Git GitHub.cli`).
2. `gh auth login` (autenticar na sua conta GitHub).
3. Instalar Claude Code: `npm install -g @anthropic-ai/claude-code` (requer Node.js) e rodar `claude` na pasta do projeto para logar.

### O que NÃO deve ir para o repositório

Criar `.gitignore` com:

```gitignore
# Dados de negócio (sensíveis / grandes)
_cache_catalogo.json
data.js
*.csv
fotos_thumb/
# Bases nunca ficam aqui, mas por garantia
*.xlsx
__pycache__/
```

> Decisão a tomar: versionar ou não os `historico*.csv`. Recomendação: **não versionar** (dados de negócio em repo, mesmo privado, é exposição desnecessária; e o histórico já vive no OneDrive/máquina). Se quiser backup, melhor uma cópia agendada para o OneDrive.

### Passos (o Claude Code faz tudo isso se você pedir)

```bash
cd C:\Users\LeandroDias\Claude\Projects\completeness
git init
git add atualiza_completeness.py dashboard.html GUIA_APP_GITHub.md .gitignore requirements.txt README.md
git commit -m "Auditoria de completeness do catálogo Souq"
gh repo create souq-completeness --private --source=. --push
```

**Repositório deve ser PRIVADO** — o código contém caminhos internos da WBG e lógica de negócio.

---

## 3. Transformar em app — opções

| Opção | Esforço | Quando escolher |
|---|---|---|
| **A. App local (Streamlit)** | Baixo | Uso pessoal/time pequeno, dados ficam na máquina. `streamlit run app.py` vira um site local; o dashboard.html atual pode ser portado ou embutido |
| **B. Dashboard estático + GitHub Pages** | Baixo | Só visualização. Problema: `data.js` teria que ir ao repo (dado de negócio público em Pages — **não recomendado** sem repo privado + Pages privado, que exige plano pago) |
| **C. App web hospedado (Streamlit Community Cloud / Render)** | Médio | Acesso de qualquer lugar. Problema: as bases xlsx e fotos estão no OneDrive local — precisaria migrar leitura para API do Graph/SharePoint ou upload manual |
| **D. Executável Windows (agendado)** | Baixo | Manter como está, mas com Task Scheduler rodando coleta+processa diariamente sem depender do Cowork |

**Recomendação pragmática:** A + D. Streamlit para a interface (mantém tudo local, sem expor dados) e Task Scheduler para automatizar a rotina diária. B/C só se precisar de acesso externo — e aí o passo crítico é trocar a leitura das bases locais por SharePoint API.

---

## 4. Prompt sugerido para o Claude Code

Abra o terminal na pasta do projeto, rode `claude` e cole:

```
Este projeto audita diariamente o catálogo do e-commerce Souq. Leia GUIA_APP_GITHUB.md
e atualiza_completeness.py antes de qualquer mudança.

Tarefas:
1. Criar .gitignore (conforme o guia), requirements.txt e um README.md conciso.
2. Refatorar atualiza_completeness.py em módulos (coleta.py, analise.py, relatorio.py)
   SEM alterar nenhuma regra de negócio — os outputs (historico.csv, data.js etc.)
   devem sair byte-idênticos ao script atual. Validar comparando antes/depois.
3. Criar app Streamlit (app.py) replicando as visões do dashboard.html:
   série histórica de completeness, disponibilidade, detalhe por produto com filtros,
   e a contraprova de fotos com as miniaturas de fotos_thumb/.
4. Criar script agendável (rodar_diario.bat) que executa --coleta e --processa e
   loga o resultado em logs/, para eu registrar no Task Scheduler do Windows.
5. Publicar como repositório PRIVADO no GitHub (gh repo create souq-completeness --private).

Restrições: não apagar historico*.csv; não commitar csv/xlsx/data.js;
a paginação da coleta só para em página vazia (nunca em página com <250 itens).
```

---

## 5. Rotina diária depois da migração

1. Task Scheduler roda `rodar_diario.bat` (ex.: 9h, dias úteis).
2. Você abre o app Streamlit (ou o dashboard.html, que continua funcionando).
3. Alertas a observar (hoje verificados manualmente; vale pedir ao Claude Code para colocá-los no script): coleta < 1500, candidatos < 700, sem match > 100, queda de disponibilidade > 5 p.p., novidade com foto + CD ≥ 50 fora do site.

---

*Gerado em 17/08/2026. Bug de paginação corrigido nesta data — se a coleta voltar a cair de repente para poucas centenas, suspeite primeiro do endpoint products.json.*
