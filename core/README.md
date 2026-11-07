# harness-core

Núcleo do Personal Harness. Roda em `127.0.0.1` e é dono dos terminais dos agentes.

- `pty_session.py`: um terminal real (PTY) por sessão, com histórico em memória.
- `sessions.py`: registro das sessões, status (trabalhando, esperando você, encerrada) e eventos.
- `claude_settings.py`: o `--settings` que cada sessão do Claude Code recebe, com statusline e hooks apontando para o núcleo.
- `relay.py`: o script que o Claude Code chama e que repassa o JSON ao núcleo.
- `statusline.py`: leitura do JSON da statusline (contexto, custo, limites de 5 horas e 7 dias).
- `accounts.py`: contas por CLI, cada uma numa pasta (`CLAUDE_CONFIG_DIR`, `CODEX_HOME`).
- `codex_usage.py`: cota do plano do Codex lida do `codex app-server` (JSON-RPC).
- `voice.py`: ditado com Whisper local (faster-whisper, modelo "small" em CPU).
- `attachments.py`: anexos salvos em `~/.harness/anexos`.
- `cli.py`: o comando `metis` (contas, switch, login; `harness` segue como apelido).
- `projects.py`: projetos (repositórios git) cadastrados; a lista começa vazia.
- `gitops.py`: worktrees, status, diff, stage, commit, push e pull, sempre com o `git` da máquina e sem shell.
- `agents.py`: agentes em arquivo (`~/.harness/agentes/*.md`), sprite e importação do Maestri.
- `ports.py`: portas em escuta dos processos de cada terminal (`ps` + `lsof`).
- `files.py`: leitura de arquivos dentro da worktree, para o explorador e os visualizadores.
- `app.py`: API HTTP e WebSocket.

```sh
uv sync
uv run harness-core          # sobe em http://127.0.0.1:47830
uv run pytest
uv run harness contas        # contas e troca de conta pelo terminal
```

Variáveis: `HARNESS_PORT`, `HARNESS_TOKEN` (gerado se faltar), `HARNESS_HOME` (padrão `~/.harness`), `HARNESS_VOICE_MODEL` (padrão `small`), `HARNESS_WORKTREES_DIR` (padrão `~/orca/workspaces`).

No Mac Intel o `onnxruntime` não tem mais wheel; o `pyproject.toml` o desliga, porque só serve ao filtro de silêncio do Whisper, que o Harness não usa.
