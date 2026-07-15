# Que variáveis realmente explicam a velocidade de venda?

## Pergunta
Quais atributos do produto devem **filtrar** a seleção de espelhos e quais são
apenas **consulta**? Filtrar por um atributo irrelevante custa caro: encolhe (ou
zera) o conjunto de espelhos sem ganho de previsão.

## Método
- Base: vendas full price, escopo Souq (linha ROUPA + lojas Souq/Ecom), 2022–2026.
- Produtos no escopo real do app: coleção ≥ Inverno 2022, grão vendável → **2.492 modelos**.
- Velocidade por modelo (`cod_sku_pai`) = unidades ÷ semanas ativas (mín. 2 semanas).
- **eta²** = fração da variância da velocidade explicada pela variável, medida
  **dentro de cada subgrupo** (níveis com n ≥ 5). Referência (Cohen): 0,01 pequeno,
  0,06 médio, 0,14 grande.

## Resultado (eta² por subgrupo)

| Subgrupo | n | manga | comprimento | fit | **cor** | **tecido** | **faixa** |
|----------|--:|------:|------------:|----:|--------:|-----------:|----------:|
| BLUSA    | 652 | 0,06 | 0,01 | 0,01 | 0,13 | 0,05 | 0,05 |
| CALÇA    | 383 | —    | 0,01 | 0,01 | 0,06 | 0,07 | 0,02 |
| CAMISA   | 227 | 0,11 | 0,04 | 0,00 | 0,11 | 0,01 | 0,08 |
| CAMISÃO  | 72  | 0,01 | 0,03 | 0,00 | 0,03 | 0,09 | 0,07 |
| KAFTAN   | 147 | 0,04 | 0,01 | 0,01 | 0,07 | 0,13 | 0,18 |
| REGATA   | 271 | 0,02 | 0,02 | 0,03 | 0,10 | 0,08 | 0,08 |
| SAIA     | 199 | —    | 0,01 | 0,02 | 0,08 | 0,04 | 0,03 |
| VESTIDO  | 272 | 0,02 | 0,02 | 0,01 | 0,12 | 0,09 | 0,05 |
| **MÉDIA** | | **0,04** | **0,02** | **0,01** | **0,09** | **0,07** | **0,07** |

O próprio subgrupo, medido entre subgrupos, dá eta² = 0,07.

## Conclusão
- **Cor (agrupada) é a variável mais preditiva** (0,09) — efeito médio. Justifica o
  agrupamento de cor e o uso como filtro.
- **Tecido (0,07) e faixa de preço (0,07)** sustentam-se como filtro rígido.
- **Manga (0,04), comprimento (0,02) e fit (0,01)** têm poder explicativo
  praticamente nulo: saber a manga de uma blusa explica ~4% de por que ela vende
  mais ou menos que outra; o restante é modelagem, estampa, preço, timing e acerto
  do produto.
- Exceções que valem registro: **KAFTAN** é muito sensível a faixa (0,18) e tecido
  (0,13); **CAMISA** é o único subgrupo em que manga importa (0,11).

## Decisão de desenho (match de espelho)
- **Filtro rígido:** subgrupo + grupo (construção) + faixa de preço + tecido.
- **Filtro afrouxável:** cor — solta automaticamente se sobrarem poucos candidatos.
- **Apenas consulta (não filtram):** manga, comprimento, fit — aparecem como colunas
  na tabela de candidatos para o comprador bater o olho ao escolher o espelho.
- **Data não entra no match** — serve só para posicionar a janela sazonal.

## Nota sobre cobertura de material
No escopo real (coleção ≥ Inverno 2022), o bucket "Outros" de tecido é de **6,6%**
(1.283 de 19.385 produtos), sendo **949 com `desc_material` em branco** e o restante
nomes de fornecedor — destes, 12 foram resolvidos pela composição informada pelo
negócio (ver `config/material_grupos.yaml`), restando ~11 produtos sem classificação.
O material em branco concentra-se em coleções pré-2022 (já fora do escopo) e em
produtos 2026 ainda em cadastro; o impacto em unidades vendidas é de **0,87%**.

## Ressalvas
A velocidade usada é bruta (não desazonalizada) e sofre de outros confundidores
(coleção, timing de entrada, acerto do produto). O sinal uniformemente baixo de
manga/comprimento/fit, porém, é robusto o bastante para a decisão de desenho.
