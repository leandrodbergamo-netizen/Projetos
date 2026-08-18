# Completeness · E-commerce Souq

Auditoria diária do catálogo publicado em souqstore.com.br, cruzada com as bases
internas de produto e estoque. Responde três perguntas por dia:

1. **O que está no site está bem cadastrado?** (14 campos de completeness)
2. **O que tem estoque já está no site?** (disponibilidade dos SKUs elegíveis)
3. **O que tem foto pronta e ainda não foi publicado?** (fila de publicação)

O app é lido pelo time de E-commerce em `streamlit`; a coleta e o cruzamento
rodam no PC do Leandro e publicam o resultado no Supabase, de onde a versão
hospedada lê.

---

## Como rodar

```bash
pip install -r requirements.txt
python atualiza_completeness.py --coleta     # baixa o catálogo do site
python atualiza_completeness.py --processa   # cruza com as bases e grava tudo
streamlit run app.py                         # abre o painel (porta 8502)
```

No Windows dá para usar `run.bat` (abre o app) e `rodar_diario.bat` (roda a
rotina completa e loga em `logs/`).

## Rotina diária

`tarefa_diaria.py` executa as quatro etapas em sequência e isola as falhas — um
erro na publicação não impede a notificação:

| Etapa | O que faz |
|---|---|
| coleta | percorre `products.json` até a primeira página vazia |
| processa | aplica as regras, grava séries, snapshots e miniaturas |
| publica | manda as tabelas `comp_*` e as miniaturas novas para o Supabase |
| notifica | posta o resumo no canal **Ecom + CRM** do Teams |

Agendar no Windows: `powershell -File setup_agendador.ps1` (cria a tarefa
`CompletenessSouqDiario` às 09:30, depois do refresh das bases).

## Estrutura

| Arquivo | Papel |
|---|---|
| `config.py` | caminhos das fontes, parâmetros de negócio e limiares de alerta |
| `coleta.py` | coleta do `products.json` e cache do catálogo |
| `analise.py` | **as regras de negócio** — as 14 flags e a elegibilidade dos SKUs |
| `relatorio.py` | gravação das séries, dos snapshots, do `data.js` e das miniaturas |
| `metricas.py` | cálculos de apresentação: séries, % por campo, alertas |
| `data_source.py` | leitura para o app: CSVs locais ou tabelas `comp_*` do Supabase |
| `imagens.py` | cascata de imagem por SKU (miniatura → cadastro → Shopify) |
| `storage.py` | miniaturas no bucket privado do Supabase (URLs assinadas) |
| `visual.py` | estilo, cartões de indicador, gráficos e exportação em Excel |
| `app.py` | o painel: completeness, disponibilidade e alertas |
| `atualiza_completeness.py` | CLI da auditoria (`--coleta` / `--processa`) |
| `publica_supabase.py` | publicação no Postgres + Storage |
| `notifica_teams.py` | resumo diário no Teams |
| `tarefa_diaria.py` | orquestra a rotina completa |
| `dashboard.html` | dashboard estático legado (lê `data.js`; substituído pelo app) |

## Fontes de dados

| Fonte | Caminho padrão | Variável de ambiente |
|---|---|---|
| Bases de produto e estoque | `C:\Users\LeandroDias\Projetos\dados` | `SOUQ_DADOS_DIR` |
| SKUs exceção (desabilitados) | OneDrive `…\Ecommerce…\2026\Produto` | `SOUQ_PRODUTO_DIR` |
| Fotos de e-commerce | OneDrive, toda pasta `Marketing - COLEÇÃO *` | `SOUQ_FOTOS_DIR` |

As bases em `Projetos\dados` são atualizadas diariamente por um fluxo do Power
Automate; a planilha de SKUs exceção é mantida pelo time de Produto.

Configuração fica no `.env` (veja `.env.example`). Nada de credencial ou dado de
negócio vai para o repositório.

## Regras de negócio

Estas regras definem a série histórica e **não mudam sem quebrar a
comparabilidade** dos números:

- **Candidato** = SKU pai com estoque ≥ 2 unidades, somando as localidades
  válidas (fora: Iguatemi SP, CDES Defeitos e CDES Recebimento).
- Ficam de fora os **SKUs exceção** (desabilitados de propósito) e os produtos
  **sem `dt_envio`** na Base_Produtos — não deveriam estar ativos.
- **Combined listings** (opção Cor com mais de um valor) saem do dashboard por
  serem duplicidade interna, mas seus SKUs contam como "no site".
- **SKU pai** = SKU sem o último segmento, quando há mais de 3 pontos.
- **Alt-text** é coletado mas fica fora da média de completeness.
- **Paginação da coleta: só para em página vazia.** A plataforma devolve páginas
  parciais (menos de 250 itens) no meio da série — foi o que zerou a coleta em
  17/08/2026, quando a página 1 veio com 247 itens.

### Quebra de série

Em **14/07/2026** entraram os filtros de SKU exceção e de `dt_envio`: candidatos
caíram de ~1686 para ~1495 e a disponibilidade subiu de ~80,7% para ~83%. Os
gráficos do app começam nessa data (`config.DATA_INICIO_SERIE`) para não
comparar critérios diferentes. O histórico anterior continua nos CSVs.

## Alertas

Configurados em `config.ALERTAS`:

| Checagem | Limiar |
|---|---|
| Volume da coleta | menos de 1.500 produtos lidos |
| SKUs elegíveis | menos de 700 candidatos |
| Produtos sem cadastro | mais de 100 sem match na Base_Produtos |
| Queda de disponibilidade | queda de 5 p.p. ou mais vs a carga anterior |
| Foto pronta e fora do site | qualquer SKU com foto e 50+ unidades no CD |

## Nuvem

O app hospedado lê o Postgres do Supabase (tabelas prefixadas `comp_`, com RLS
habilitado para bloquear a Data API pública) e as miniaturas do bucket privado
`comp-thumbs`, por URL assinada. Nos Secrets do Streamlit Cloud:

```toml
FONTE_DADOS = "supabase"
DATABASE_URL = "postgresql+psycopg2://..."
SUPABASE_URL = "https://SEU_REF.supabase.co"
SUPABASE_SERVICE_KEY = "..."
```
