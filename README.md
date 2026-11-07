# Personal Harness

OS pessoal e ADE no Mac: os agentes (Claude Code, Codex) rodam em terminais de verdade, com o Brain como memória. O plano completo está em [`docs/MAPA.md`](docs/MAPA.md), o visual em [`docs/DESIGN.md`](docs/DESIGN.md) e a régua do Orca em [`docs/PARIDADE-ORCA.md`](docs/PARIDADE-ORCA.md).

## O que já faz (v0.2.0)

- **Claude Code e Codex de verdade em terminais**, com a sua conta, do mesmo jeito que no seu terminal. Também abre shell comum. O Harness não lê nem guarda login.
- **Abas, tela dividida em dois e terminal flutuante** (⌃\`). Os terminais ficam vivos ao trocar de aba, dividir ou abrir os Ajustes.
- **Salto rápido** (⌘K): pula para um terminal, abre um novo, divide a tela, troca de conta ou de tema.
- **Barra de entrada** embaixo dos terminais: escreva com calma, revise e mande para o terminal em foco (⏎ envia, ⌥⏎ só cola).
- **Ditado com o microfone**: o botão Ditar vira uma onda sonora ao vivo enquanto grava; ao parar, o Whisper transcreve no próprio Mac (sem internet, sem custo) e o texto cai na barra para revisar.
- **Anexos**: o botão Anexar ou arrastar arquivos do Finder. Solto num terminal, o caminho vai direto para ele; solto na barra, entra junto com o texto.
- **Contas e uso**: várias contas do Claude Code e do Codex, cada uma na própria pasta (`CLAUDE_CONFIG_DIR`, `CODEX_HOME`). Troca pelos Ajustes, pelo ⌘K ou com `harness switch`. A barra de status mostra as janelas de 5 horas e 7 dias da conta em uso de cada plano, em destaque a partir de 80%.
- **Status do agente** (trabalhando, esperando você) vindo dos hooks do Claude Code, e o contexto da sessão em foco.
- **Ajustes**: contas e uso, aparência (Drácula azul, Grafite, Claro), voz e atalhos.

As outras telas do protótipo aparecem na faixa de ícones e mostram em que versão chegam.

## Comando `harness`

Dentro dos terminais do app (e em `core/` com `uv run harness`):

```sh
harness contas                       # contas de cada CLI e qual está em uso
harness switch codex pessoal         # as próximas sessões do Codex usam a conta "pessoal"
harness login claude trabalho        # cria a conta e abre o login oficial do Claude Code nela
```

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
