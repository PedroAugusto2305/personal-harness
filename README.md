# MÊTIS

**Inteligência em ação.** O ambiente pessoal onde agentes, projetos e memória trabalham juntos. Antes se chamava Personal Harness; a marca (símbolo, logotipo, cor e voz) está em [`docs/marca/`](docs/marca/) e na seção Marca de [`docs/DESIGN.md`](docs/DESIGN.md).

OS pessoal e ADE no Mac: os agentes (Claude Code, Codex) rodam em terminais de verdade, com o Brain como memória. O plano completo está em [`docs/MAPA.md`](docs/MAPA.md), o visual em [`docs/DESIGN.md`](docs/DESIGN.md) e a régua do Orca em [`docs/PARIDADE-ORCA.md`](docs/PARIDADE-ORCA.md).

## O que já faz (v0.7.1)

**Novo na 0.7.1, o resto do OS pessoal:**

- **Captura rápida** (⌥Espaço de qualquer app, ou ⌘K → "Captura rápida"): uma caixinha por cima de tudo. "me lembra de pagar o boleto sexta 9h" vira lembrete no Slack; "tarefa revisar o PR no Personal Harness" vira linha nas Próximas ações do projeto; "tarefa…" ou "anota…" sem projeto vai para as Capturas do dia no Brain; o resto vai para o **Hermes**, o concierge, num terminal da MÊTIS, que age pela central de MCP.
- **Hermes**: agente novo, concierge da captura rápida.
- **Agente por descrição**: em "Novo agente", descreva numa frase e o Claude rascunha nome, papel, dor, cor e pasta; "Testar sem salvar" abre um terminal com o rascunho. Todo agente ganhou o campo "Qual dor resolve?".
- **Sprites animadas** por estado na barra lateral e nas abas: respira parado, balança trabalhando, "!" esperando você, pulinho ao concluir, treme no erro.
- **Estudo** (ícone de livro): Pomodoro (25/5, 50/10 ou 15/3) que continua ao trocar de tela, com o relógio na barra de título; cada foco vira uma linha em "📚 Estudo" na nota do dia do Brain. Placar com o piso de 20 minutos, a semana, a sequência e o aviso de dois dias seguidos sem estudar; botões para a Aurora e o Sócrates.

**Desde a 0.7.0:**

**Novo na 0.7, rotinas e Hoje:**

- **Rotinas**: um agente que abre sozinho num terminal na hora marcada, com um pedido como primeira mensagem (`claude "<pedido>"`, interativo e pelo plano). Dias da semana, hora, aviso no Slack (toca no iPhone) e janela de recuperação: se o Mac dormia na hora e acordou dentro dela, roda; depois, pula e fica registrado. Cada rotina é um `.md` em `~/.harness/rotinas/`.
- **Hoje** (ícone de casa): as rotinas do dia com o que rodou, pulou ou espera, o que está em andamento nos projetos do Brain, o que aguarda a sua aprovação e um lembrete rápido. À direita, todas as rotinas com a próxima execução e o editor (nome, agente, dias, hora, recuperação, pedido, aviso).
- Já vêm duas: **Check-in de estudo** com a Aurora (seg a sáb, 20h50, aviso no Slack, recupera até 21h50) e **Consolidação semanal do Brain** com a Alexandria (sexta, 22h10, recupera até o dia seguinte).

**Desde a 0.6:**

**Novo na 0.6, conectores e avisos:**

- **Central de MCP**: todo Claude e todo Codex aberto na MÊTIS já vem com o MCP "metis" (por `--mcp-config` no Claude e `mcp_servers` no Codex, com um token por terminal). Ele traz as ferramentas do Brain e do kanban (`brain_buscar`, `brain_ler`, `brain_precedentes`, `tarefas`, `tarefa_mover`, `tarefa_nova`), o `lembrete` e as ferramentas de cada conta conectada, com o id da conta na frente.
- **Conectores** (ícone de tomada): **Slack** por um bot da MÊTIS em cada workspace (o passo a passo e o manifesto estão na tela; você cola o token do bot) e **ClickUp** pelo MCP oficial, com login no navegador. Várias contas por ferramenta; tokens no Keychain do Mac.
- **Lembretes**: `metis lembrete "pagar o boleto" sexta 9h` (ou "amanhã 14:30", "em 20 min", "13/11 9h") agenda a mensagem do bot na sua DM do Slack; o iPhone toca na hora, mesmo com o Mac dormindo. Os agentes fazem o mesmo pela ferramenta `lembrete`.
- **Aprovação**: mensagem para outras pessoas e escrita no ClickUp esperam o seu "Aprovar" num cartão que aparece em qualquer tela (dá para desligar por conta). Em 10 minutos sem resposta, a ação não acontece.
- **Atividade**: tudo o que os agentes fizeram pela central, com quem, o quê e o resultado.
- **Conectores por agente**: no editor de agentes, escolha quais contas cada um pode usar (todas, nenhuma ou algumas).

**Desde a 0.5:**

**Novo na 0.5, Brain e kanban:**

- **Grafo do Brain** (v0.5.1): sem nota aberta, o Brain mostra o grafo das notas, com uma nuvem por área do projeto (vinda do `area:` da nota) e as ligações entre projetos na cor de acento. Os nomes ficam escondidos e aparecem passando o mouse; o botão "Nomes" mostra os dos projetos. As forças ficam vivas, como no Obsidian: o grafo se acomoda animando, arrastar um nó puxa os vizinhos, e o painel "Forças" tem força de centro, repulsão, força e distância das ligações (guardados entre aberturas). Pinça aproxima, dois dedos andam, passar o mouse acende as ligações, clicar abre a nota; a busca acende as notas achadas. Filtros por tipo, "Precedentes entre projetos", "Notas sem ligação" e a legenda liga e desliga cada área.
- **Brain** (ícone de grafo na faixa, ou ⌘K → "Buscar no Brain"): busca por palavra em todo o vault, sem acento e por começo de palavra, com filtro por tipo (decisões, incidentes, aprendizados, entregas, projetos, conhecimento) e por projeto. A nota abre ao lado, com `[[links]]` clicáveis (link para nota que não existe fica tracejado), callouts, "Citada por" e "Abrir no Obsidian".
- **Kanban** (ícone de colunas, ou ⌘K → "Kanban de projetos"): os projetos de `01-PROJETOS` como cartões nas colunas Ideia, Planejando, Construindo, Em produção e Pausado. Arrastar grava `estagio:` na nota. O cartão abre as tarefas, que são as "Próximas ações" da nota, em Pendente, Em andamento, Em teste e Concluído. Arrastar troca a etiqueta na linha (`#em-andamento`, `#em-teste`) ou marca `[x]` com a data; "+ Adicionar" escreve uma linha nova.
- **Executar com agente**: numa tarefa, cria uma worktree com o nome dela, abre o Claude, põe a tarefa em "Em andamento" e deixa o pedido na barra de entrada para você revisar.
- **Precedentes v1**: toda sessão do Claude aberta na pasta de um projeto do Brain começa com decisões, incidentes, aprendizados e entregas de **outros** projetos que batem com as tarefas abertas. No painel da worktree, a aba **Brain** mostra o projeto, as tarefas abertas e os mesmos precedentes.
- **Para os agentes**: `metis brain buscar|ler|precedentes`, `metis tarefas` e `metis tarefa nova|mover`, em qualquer terminal da MÊTIS.

**Desde a 0.4:**

- **Navegador embutido**: abas de navegador ao lado dos terminais (botão de globo na barra lateral, ⌘K → "Abrir navegador", "Abrir" no painel Portas, `metis web <endereço>` em qualquer terminal, ou ⌘ + clique num link do terminal; com ⇧, abre no navegador do Mac). É o WebKit do macOS, com barra de endereço, voltar e avançar, recarregar, inspetor (devtools), aba anônima, downloads em `~/Downloads` e links `target=_blank` virando aba nova.
- **Modo de design**: botão Design na barra da aba (ou ⌘K → "Modo de design", que abre uma aba já no modo se nenhuma estiver em foco), realça o elemento sob o mouse; o clique manda para a barra de entrada do agente da worktree o seletor, o texto, o HTML, o estilo e, quando a página é React, Svelte ou Vue em desenvolvimento, o componente e o arquivo de origem. Esc sai.
- **Sprites por prompt**: na tela de Agentes, um chat da sprite. Você descreve, o Codex desenha e a MÊTIS pixeliza em 48 × 48. Todo agente é **greco-romano** por padrão; sem sprite escolhida, ganha um busto greco-romano gerado do nome.
- O app escolhe uma porta livre para o núcleo e o núcleo se encerra se o app morrer, então recompilar ou travar não deixa a MÊTIS "sem núcleo".

**Desde a 0.3, para programar:**

- **Projetos e worktrees**: a barra lateral é organizada por projeto (repositório git), depois as worktrees, depois os terminais de cada uma. Cria worktree com branch novo (em `~/orca/workspaces/<repo>/<nome>`, a mesma pasta do Orca, copiando o `.env`) e já abre o Claude nela. Apagar avisa se há terminal aberto ou mudança sem commit, e nunca apaga um branch com commits que não foram juntados.
- **Painel da worktree** (⌘⇧B): **Mudanças** (marcar, desmarcar, commit, pull e push), **Arquivos** (árvore com as cores do git) e **Portas** (os servidores que os terminais subiram, com um clique para abrir).
- **Revisão com notas**: o diff de cada arquivo abre numa aba; uma nota por linha, e "Mandar ao agente" junta todas na barra de entrada do agente da worktree.
- **Commit pelo agente**: "Pedir ao agente" manda o agente da worktree escrever a mensagem e commitar, no terminal dele (se não houver agente aberto, abre um Claude).
- **Visualizadores**: Markdown, imagem, PDF, CSV, áudio, vídeo, HTML (sem scripts) e código. ⌘P abre qualquer arquivo da worktree.
- **Agentes em arquivo**: cada agente é um `.md` em `~/.harness/agentes/` (nome, descrição, CLI, modelo, conta, pasta, cor e o papel). A tela de Agentes edita tudo, inclusive a sprite (PNG em pixel art) e os importados do Maestri. O papel vai como `--append-system-prompt` no Claude e `developer_instructions` no Codex.

**Desde a 0.2:**

- **Claude Code e Codex de verdade em terminais**, com a sua conta, do mesmo jeito que no seu terminal. Também abre shell comum. A MÊTIS não lê nem guarda login.
- **Abas, tela dividida em dois e terminal flutuante** (⌃\`). Os terminais ficam vivos ao trocar de aba, dividir ou abrir os Ajustes.
- **Salto rápido** (⌘K): pula para um terminal, abre um novo, divide a tela, troca de conta ou de tema.
- **Barra de entrada** embaixo dos terminais: escreva com calma, revise e mande para o terminal em foco (⏎ envia, ⌥⏎ só cola).
- **Ditado com o microfone**: o botão Ditar vira uma onda sonora ao vivo enquanto grava; ao parar, o Whisper transcreve no próprio Mac (sem internet, sem custo) e o texto cai na barra para revisar.
- **Anexos**: o botão Anexar ou arrastar arquivos do Finder. Solto num terminal, o caminho vai direto para ele; solto na barra, entra junto com o texto.
- **Contas e uso**: várias contas do Claude Code e do Codex, cada uma na própria pasta (`CLAUDE_CONFIG_DIR`, `CODEX_HOME`). Troca pelos Ajustes, pelo ⌘K ou com `metis switch`. A barra de status mostra as janelas de 5 horas e 7 dias da conta em uso de cada plano, em destaque a partir de 80%.
- **Status do agente** (trabalhando, esperando você) vindo dos hooks do Claude Code, e o contexto da sessão em foco.
- **Ajustes**: contas e uso, aparência (Drácula azul, Grafite, Claro), voz e atalhos.

As outras telas do protótipo aparecem na faixa de ícones e mostram em que versão chegam.

O projeto do Brain de uma pasta vem do `diretorio:` no frontmatter da nota do projeto (o mesmo vínculo do `brain.py`); uma worktree conta como o repositório principal dela.

## Comando `metis`

Dentro dos terminais do app (e em `core/` com `uv run metis`):

```sh
metis contas                       # contas de cada CLI e qual está em uso
metis switch codex pessoal         # as próximas sessões do Codex usam a conta "pessoal"
metis login claude trabalho        # cria a conta e abre o login oficial do Claude Code nela
metis web 5173                     # abre uma aba do navegador da MÊTIS
metis brain buscar webhook guru    # busca no Brain (--tipo decisao, --projeto "Nome")
metis brain ler "Título da nota"   # mostra a nota e quem cita ela
metis brain precedentes            # registros de outros projetos parecidos com o desta pasta
metis tarefas                      # Próximas ações do projeto desta pasta, com o id
metis tarefa mover 4ea9e8ea em-teste
```

O nome antigo, `harness`, continua funcionando como apelido. Os dados seguem em `~/.harness`.

## Rodar

Precisa de `uv`, Node 22+, Rust e o Xcode Command Line Tools.

```sh
./scripts/dev.sh        # abre a janela; o app sobe o núcleo sozinho
./scripts/dev-web.sh    # só no navegador, em http://localhost:1420
```

Testes do núcleo:

```sh
cd core && uv run pytest
```

## Como funciona

```
app/ (Tauri + React + xterm.js)  ──HTTP/WebSocket em 127.0.0.1──►  core/ (Python, FastAPI)
                                                                     │  PTY por sessão
                                                                     ▼
                                                       claude --settings {statusLine + hooks}
                                                                     │  relay.sh (curl + token)
                                                                     └──► núcleo: contexto, cota, status
                                                       codex app-server ──► cota do Codex (a cada 3 min)
                                                       Whisper local    ──► ditado (WAV 16 kHz)
```

- O núcleo é dono dos terminais. Cada sessão do Claude recebe um `--settings` com a statusline e os hooks apontando para o núcleo. Esse `--settings` tem precedência sobre `~/.claude/settings.json`, então o Orca e o seu Claude Code de sempre não são afetados.
- O núcleo só escuta em `127.0.0.1` e exige um token novo a cada execução.
- Variáveis do Orca, marcadores da sessão que abriu o núcleo e o Python do próprio núcleo não passam para os agentes.
- Cada conta é uma pasta de configuração. A conta "padrão" usa o `~/.claude` e o `~/.codex` de sempre.
- O modelo de voz (Whisper "small", cerca de 460 MB) fica em `~/.harness/modelos`; os anexos, em `~/.harness/anexos`.

## Estrutura

```
core/   núcleo em Python (uv): sessões, PTY, relay, API
app/    janela Tauri e tela React
docs/   mapa, design e paridade com o Orca
scripts/ dev.sh e dev-web.sh
```
