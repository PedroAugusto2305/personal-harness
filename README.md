# Personal Harness

OS pessoal e ADE no Mac: os agentes (Claude Code, Codex) rodam em terminais de verdade, com o Brain como memória. O plano completo está em [`docs/MAPA.md`](docs/MAPA.md), o visual em [`docs/DESIGN.md`](docs/DESIGN.md) e a régua do Orca em [`docs/PARIDADE-ORCA.md`](docs/PARIDADE-ORCA.md).

## v0.1.0: fatia vertical

- A janela abre com a moldura aprovada: barra de título própria, faixa de ícones, sessões, terminal e barra de status.
- **Claude Code de verdade num terminal**, logado com a sua conta, do mesmo jeito que no seu terminal. O Harness não guarda nenhum login.
- A **barra de status** mostra o uso do plano (janelas de 5 horas e 7 dias, com a hora em que zeram) e o contexto da sessão ativa.
- **Status do agente** (trabalhando, esperando você) vindo dos hooks do Claude Code.
- Também abre um shell comum.
- Três temas por tokens: Drácula azul, Grafite e Claro (clique no chip "tema" da barra de título).

As outras telas do protótipo aparecem na faixa de ícones e mostram em que versão chegam.

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
```

- O núcleo é dono dos terminais. Cada sessão do Claude recebe um `--settings` com a statusline e os hooks apontando para o núcleo. Esse `--settings` tem precedência sobre `~/.claude/settings.json`, então o Orca e o seu Claude Code de sempre não são afetados.
- O núcleo só escuta em `127.0.0.1` e exige um token novo a cada execução.
- Variáveis do Orca e marcadores da sessão que abriu o núcleo não passam para os agentes.

## Estrutura

```
core/   núcleo em Python (uv): sessões, PTY, relay, API
app/    janela Tauri e tela React
docs/   mapa, design e paridade com o Orca
scripts/ dev.sh e dev-web.sh
```
