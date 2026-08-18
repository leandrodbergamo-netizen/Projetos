# Passo a passo da configuração

Roteiro único para colocar a auditoria de completeness no ar: dados na nuvem,
app publicado para o time, notificação no Teams e rotina agendada.

Faça na ordem. Cada bloco funciona sozinho — se parar no meio, o que já foi
configurado continua valendo.

---

## Bloco 0 · Antes de qualquer coisa (5 min)

### 0.1 Conferir se o repositório é privado

O código tem caminhos internos da WBG e a lógica de negócio da auditoria.

1. Abra numa janela anônima: `https://github.com/leandrodbergamo-netizen/Projetos`
2. **Carregou sem login?** O repo é público — torne-o privado antes de seguir:
   Settings → General → Danger Zone → *Change repository visibility* → Private.
3. **Deu 404?** Está privado. Pode seguir.

### 0.2 Olhar o app rodando

```
run.bat
```

Abre em `http://localhost:8502`. É a mesma tela que o time vai ver.

---

## Bloco 1 · Supabase (15 min)

Use o **mesmo projeto** do reabastecimento. As tabelas da completeness têm
prefixo `comp_`, então não colidem com as dele.

### 1.1 Pegar as três credenciais

No painel do Supabase, projeto do reabastecimento:

| Credencial | Onde achar |
|---|---|
| `DATABASE_URL` | Já está no `.env` do reabastecimento — copie a linha inteira |
| `SUPABASE_URL` | Project Settings → API → **Project URL** |
| `SUPABASE_SERVICE_KEY` | Project Settings → API → Project API keys → **service_role** (clique em Reveal) |

> A `service_role` key ignora todas as permissões. Ela só pode existir em dois
> lugares: no `.env` da sua máquina e nos Secrets do Streamlit Cloud. Nunca em
> mensagem, planilha ou commit.

### 1.2 Criar o arquivo `.env`

Na pasta do projeto, copie `.env.example` para `.env` e preencha:

```
FONTE_DADOS=local
DATABASE_URL=postgresql+psycopg2://postgres.SEU_REF:SENHA@aws-0-REGIAO.pooler.supabase.com:6543/postgres
SUPABASE_URL=https://SEU_REF.supabase.co
SUPABASE_SERVICE_KEY=eyJ...
```

`FONTE_DADOS=local` é o certo aqui: no seu PC o app lê os CSVs. Quem usa
`supabase` é a versão hospedada.

### 1.3 Primeira publicação

```
python publica_supabase.py
```

Cria as tabelas `comp_detalhe`, `comp_disponibilidade`, `comp_historico`,
`comp_hist_disp` e `comp_meta`, liga o RLS em todas (bloqueia a API pública do
Supabase) e cria o bucket privado `comp-thumbs` com as miniaturas.

Confira no Supabase → Table Editor: as cinco tabelas `comp_*` devem aparecer.

---

## Bloco 2 · Notificação no Teams (10 min)

### 2.1 Criar o fluxo

No Teams, canal **Ecom + CRM**:

1. Clique nos `⋯` do canal → **Fluxos de trabalho** (Workflows)
2. Escolha o modelo **"Postar em um canal quando uma solicitação de webhook for recebida"**
3. Confirme a conta, o Time e o Canal
4. Copie a **URL** gerada no final (só aparece uma vez — guarde)

### 2.2 Ligar no projeto

Acrescente ao `.env`:

```
TEAMS_WEBHOOK_URL=https://prod-XX.westus.logic.azure.com:443/workflows/...
TEAMS_FORMATO=cartao
```

### 2.3 Testar

```
python notifica_teams.py            (só mostra o texto, não envia)
python notifica_teams.py --enviar   (posta de verdade no canal)
```

Rode o primeiro, leia a mensagem, e só então o segundo. **O segundo posta para
todo o grupo.**

> Se a mensagem chegar como um bloco de JSON em vez de texto formatado, troque
> para `TEAMS_FORMATO=texto` no `.env` e teste de novo.

---

## Bloco 3 · Publicar o app para o time (15 min)

### 3.1 Subir o código

Eu faço o commit. Você só confirma o push depois do passo 0.1.

### 3.2 Criar o app no Streamlit Cloud

1. Entre em `https://share.streamlit.io` com a conta GitHub
2. **Create app** → escolha implantar a partir de um repositório do GitHub
   (o app nasce privado porque o repositório é privado)
3. Preencha:
   - Repository: `leandrodbergamo-netizen/Projetos`
   - Branch: `main`
   - Main file path: `completeness/app.py`
4. **Advanced settings** → **Secrets**, cole:

```toml
FONTE_DADOS = "supabase"
DATABASE_URL = "postgresql+psycopg2://..."
SUPABASE_URL = "https://SEU_REF.supabase.co"
SUPABASE_SERVICE_KEY = "eyJ..."
APP_URL = "https://SEU-APP.streamlit.app"
```

5. **Deploy**

`APP_URL` é opcional: preenchida, a mensagem do Teams ganha um link para o painel.

### 3.3 Liberar o acesso do time

No app publicado: **Settings** → **Sharing** → adicione os e-mails do time de
E-commerce. Cada pessoa entra com a conta Microsoft/Google do e-mail cadastrado.

---

## Bloco 4 · Rotina diária (5 min)

### 4.1 Agendar

Clique com o botão direito em `setup_agendador.ps1` → **Executar com PowerShell**.

Cria a tarefa `CompletenessSouqDiario` às **09:30** — depois do Power Automate
atualizar as bases e da tarefa do reabastecimento (09:00). Se o PC estiver
desligado no horário, roda assim que você logar.

### 4.2 Testar de ponta a ponta

```
Start-ScheduledTask -TaskName CompletenessSouqDiario
```

Depois de uns minutos:

```
Get-Content logs\completeness_*.log -Tail 40
```

Você deve ver: coleta ok → o resumo do dia → linhas do `comp_*` → miniaturas →
"Rotina concluída". E a mensagem chega no Teams.

> **Atenção:** essa execução posta no canal de verdade. Se preferir testar mudo:
> `python tarefa_diaria.py --sem-teams`

---

## Bloco 5 · Verificar se a Souq já não está pagando um problema

Duas coisas que apareceram na análise e valem uma olhada sua:

1. **A disponibilidade caiu 4,7 p.p.** entre 12/08 e 17/08 (83,2% → 78,5%), com
   304 SKUs elegíveis fora do site contra 234 antes. Não é ruído de cálculo —
   são produtos com estoque que saíram do ar.
2. **A tarefa agendada do reabastecimento roda `refresh_bases.py`**, não
   `tarefa_diaria.py`. Se for o caso, a publicação diária dele no Supabase não
   está acontecendo e o app na nuvem pode estar com dados velhos.

---

## Depois, no dia a dia

Nada. A tarefa roda sozinha, o time abre o link e o resumo cai no Teams todo dia.

Quando quiser mexer nos limiares de alerta, é em `config.ALERTAS`. Quando uma
coleção nova de fotos chegar no OneDrive, o app varre sozinho — não precisa
mudar caminho.
