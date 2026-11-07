# harness-core

Núcleo do Personal Harness. Roda em `127.0.0.1` e é dono dos terminais dos agentes.

- `pty_session.py`: um terminal real (PTY) por sessão, com histórico em memória.
- `sessions.py`: registro das sessões, status (trabalhando, esperando você, encerrada) e eventos.
- `claude_settings.py`: o `--settings` que cada sessão do Claude Code recebe, com statusline e hooks apontando para o núcleo.
- `relay.py`: o script que o Claude Code chama e que repassa o JSON ao núcleo.
- `statusline.py`: leitura do JSON da statusline (contexto, custo, limites de 5 horas e 7 dias).
- `app.py`: API HTTP e WebSocket.

```sh
uv sync
uv run harness-core          # sobe em http://127.0.0.1:47830
uv run pytest
```

Variáveis: `HARNESS_PORT`, `HARNESS_TOKEN` (gerado se faltar), `HARNESS_HOME` (padrão `~/.harness`).
