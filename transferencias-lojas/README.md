# Remanejamento de Estoque entre Lojas

App web (Streamlit) que sugere transferências de produtos **entre lojas** quando
um SKU **filho** está em **ruptura** numa loja, o **CD não tem o item** e ele
**não está em trânsito** para aquela loja. As lojas com maior probabilidade de
venda (maior venda histórica do SKU pai) têm prioridade para receber.

## Como rodar (abrir o app)

1. Instale as dependências (uma vez):
   ```powershell
   pip install -r requirements.txt
   ```
2. **Dê dois cliques em `run.bat`** (ou rode `python -m streamlit run app.py`).
3. O app abre no navegador em **http://localhost:8501**.

> Não é um "mockup" estático — é um app interativo. Os filtros e parâmetros
> ficam na barra lateral e nas abas.

## Regras de negócio

- **Ruptura (não clusterização):** loja com estoque **zero** de um SKU filho,
  que **já carrega o SKU pai** (tem estoque de pelo menos outro filho/tamanho do
  mesmo pai) **e** vendeu o pai na janela. Se a loja **nunca recebeu** nenhum
  filho do pai, é **clusterização** (não entra como ruptura).
- **Só sugere** quando o CD (`CDES Vendas...`) está sem o filho **e** não há
  trânsito para a loja (trânsito vem do `status_estoque = Transito`).
- **Status permitidos para remanejar:** apenas **NOVIDADE, PERENE, LIQUIDAÇÃO,
  MIGRADO** (`desc_status_produto`). **OUTLET** e demais ficam de fora.
- **Lojas Outlet excluídas** como doadora e receptora (ex.: Outlet Alexânia →
  `EXCLUIR_MARCAS_LOJA = {"OUTLET"}`).
- **Doadora elegível:** só cede item parado há **≥ 2 semanas** (sem venda),
  contadas a partir do recebimento estimado.
- **Limite por doadora:** atende no **máximo 4 lojas** distintas por rodada.
- **Limite de peças por grupo (no SKU filho):** **Home = 10**, **Acessórios = 4**,
  **Roupa = 2** (de `desc_linha`; **BAZAR MATRIZ** e linhas fora do mapa são
  excluídas).
- **Prioridade de quem recebe:** venda histórica do SKU pai na loja (janela
  configurável).
- **Recebimento (premissa inicial):** sem histórico de estoque salvo, usamos
  `dt_envio + 7 dias` (lead time) da Base_Produtos; quando o histórico de
  snapshots amadurecer, ele assume.

Todos os parâmetros são ajustáveis na barra lateral.

## Cache e desempenho

A 1ª carga do dia lê as planilhas grandes (~35–45s) e grava um **cache diário**
em `data/cache/dados_AAAAMMDD.pkl`. As aberturas seguintes levam **< 1s**. O
`refresh_bases.py` apaga o cache do dia ao atualizar, forçando a releitura.

## Bases de dados (planilhas linkadas ao banco)

Ficam na pasta `Projetos\dados` (sobreponível pela variável de ambiente `PASTA_BASES`):

| Arquivo | Conteúdo | Atualização |
|---|---|---|
| `Base_Estoque.xlsx` | estoque por loja/CD/trânsito (`status_estoque`) | **diária** |
| `Base_2026.xlsx` | vendas do ano corrente | **diária** |
| `Base_Produtos.xlsx` | cadastro (SKU filho→pai, grupo via `desc_linha`) | **diária** |
| `Base_Lojas.xlsx` | cadastro de lojas (ativas, canal) | manual |
| `Base_2022..2025.xlsx` | histórico de vendas | manual |

### Atualização diária (Power Query → Excel)

Como as planilhas são alimentadas por Power Query, o **refresh real** precisa do
Excel. O `refresh_bases.py` abre Base_Estoque/Base_2026/Base_Produtos, faz
*Atualizar Tudo*, salva, fecha e limpa o cache do dia. Requer Excel instalado e:

```powershell
pip install pywin32
```

**Agendamento (já configurado):** existe a tarefa do Windows
`RemanejamentoRefreshBases` rodando **todo dia às 09:00**. Se o computador
estiver desligado/deslogado no horário, ela roda **assim que você logar**
(opção *StartWhenAvailable*). Para (re)criar a tarefa, rode `setup_agendador.ps1`.

```powershell
Start-ScheduledTask -TaskName RemanejamentoRefreshBases   # testar agora
Get-ScheduledTaskInfo -TaskName RemanejamentoRefreshBases # ver última/próxima execução
Unregister-ScheduledTask -TaskName RemanejamentoRefreshBases -Confirm:$false  # remover
```

> A tarefa é **manual de configurar uma única vez** (já feito). No dia a dia não
> precisa fazer nada — ela atualiza as planilhas sozinha antes de você abrir o app.

## Snapshot de estoque (tira o efeito ruptura no giro)

As bases não têm data de recebimento — só um snapshot do dia. A cada carga, o
app **grava o estoque do dia** em `data/hist_estoque.parquet`. Com o histórico
acumulando, passamos a:

- calcular **velocidade de venda por dias COM estoque** (sem viés de ruptura);
- estimar a **data de recebimento** (início da sequência atual com estoque),
  habilitando a regra das "2 semanas" com precisão.

Enquanto o histórico não amadurece (~2 semanas), a regra de doadora usa a
**última venda** como referência (*fallback*).

## Abas do app

1. **Sugestões de Remanejamento** — doadora → receptora por SKU (com grupo),
   filtros por grupo/loja, resumo de carga por doadora (confere o teto de 4) e
   export para Excel.
2. **Painel Loja × SKU** — lojas nas linhas, SKU pai nas colunas, com estoque,
   vendas e **giro** em heatmap. Filtro por grupo e top-N SKUs por venda.

## Sazonalidade (curva semanal de demanda)

`sazonalidade.py` monta uma **curva sazonal semanal** a partir do histórico
(Base_2022–2025, ~2,3M linhas, full price), por **grupo (merchandising) ×
subgrupo × matéria-prima** — com fallback para grupo×subgrupo e grupo.

- **Matéria-prima predominante**: extraída de `desc_material` por palavra-chave
  (1ª que aparece no texto); sem material → usa o total do grupo.
- A curva já captura **Natal** (semanas 50–51, índice 3–4×) e a **subida até o
  Dia das Mães** (semanas 17–19).
- `feriados.py`: calendário nacional + efeito de **emendas** (terça/quinta = 4
  dias; segunda/sexta = 3 dias → negativo; quarta = neutro) — fatores iniciais
  calibráveis.
- `prever(media_semanal, grupo, subgrupo, materia, ano, semana)` = média recente
  × índice sazonal × fator de feriado. Base para o cálculo de **cobertura**.

Reconstrua a curva quando atualizar o histórico:

```powershell
python sazonalidade.py
```

> A construção é pesada (~5 min) e fica em `data/curva_sazonal.parquet` (cache).

## Estrutura do código

| Arquivo | Responsabilidade |
|---|---|
| `app.py` | Interface Streamlit |
| `config.py` | Parâmetros, limites por grupo, matéria-prima, mapeamento das bases |
| `data_source.py` | Leitura das bases reais (e modo `mock` para teste) |
| `engine.py` | Regras: ruptura, elegibilidade, score, alocação |
| `painel.py` | Matrizes loja × SKU pai com heatmap |
| `snapshot.py` | Histórico diário de estoque (recebimento/velocidade) |
| `sazonalidade.py` | Curva sazonal semanal (previsão/cobertura) |
| `feriados.py` | Calendário nacional e efeito de emendas |
| `refresh_bases.py` | Refresh diário das planilhas via Excel (Power Query) |
