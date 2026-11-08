# MÊTIS

**Inteligência em ação.** O ambiente pessoal onde agentes, projetos e memória trabalham juntos. Antes se chamava Personal Harness; a marca (símbolo, logotipo, cor e voz) está em [`docs/marca/`](docs/marca/) e na seção Marca de [`docs/DESIGN.md`](docs/DESIGN.md).

OS pessoal e ADE no Mac: os agentes (Claude Code, Codex) rodam em terminais de verdade, com o Brain como memória. O plano completo está em [`docs/MAPA.md`](docs/MAPA.md), o visual em [`docs/DESIGN.md`](docs/DESIGN.md) e a régua do Orca em [`docs/PARIDADE-ORCA.md`](docs/PARIDADE-ORCA.md).

## O que já faz (v0.4.1)

**Novo na 0.4:**

- **Navegador embutido**: abas de navegador ao lado dos terminais (botão de globo na barra lateral, ⌘K → "Abrir navegador", "Abrir" no painel Portas, `metis web <endereço>` em qualquer terminal, ou ⌘ + clique num link do terminal; com ⇧, abre no navegador do Mac). É o WebKit do macOS, com barra de endereço, voltar e avançar, recarregar, inspetor (devtools), aba anônima, downloads em `~/Downloads` e links `target=_blank` virando aba nova.
- **Modo de design**: ligado na barra da aba, realça o elemento sob o mouse; o clique manda para a barra de entrada do agente da worktree o seletor, o texto, o HTML, o estilo e, quando a página é React, Svelte ou Vue em desenvolvimento, o componente e o arquivo de origem. Esc sai.
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

## Comando `metis`

Dentro dos terminais do app (e em `core/` com `uv run metis`):

```sh
metis contas                       # contas de cada CLI e qual está em uso
metis switch codex pessoal         # as próximas sessões do Codex usam a conta "pessoal"
metis login claude trabalho        # cria a conta e abre o login oficial do Claude Code nela
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
