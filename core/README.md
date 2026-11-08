# harness-core

Núcleo da MÊTIS (antes Personal Harness). Roda em `127.0.0.1` e é dono dos terminais dos agentes.

- `pty_session.py`: um terminal real (PTY) por sessão, com histórico em memória.
- `sessions.py`: registro das sessões, status (trabalhando, esperando você, encerrada) e eventos.
- `claude_settings.py`: o `--settings` que cada sessão do Claude Code recebe, com statusline e hooks apontando para o núcleo.
- `relay.py`: o script que o Claude Code chama e que repassa o JSON ao núcleo.
- `statusline.py`: leitura do JSON da statusline (contexto, custo, limites de 5 horas e 7 dias).
- `accounts.py`: contas por CLI, cada uma numa pasta (`CLAUDE_CONFIG_DIR`, `CODEX_HOME`).
- `codex_usage.py`: cota do plano do Codex lida do `codex app-server` (JSON-RPC).
- `voice.py`: ditado com Whisper local (faster-whisper, modelo "small" em CPU).
- `attachments.py`: anexos salvos em `~/.harness/anexos`.
- `cli.py`: o comando `metis` (contas, switch, login, web, `brain` e `tarefa(s)`; `harness` segue como apelido).
- `projects.py`: projetos (repositórios git) cadastrados; a lista começa vazia.
- `gitops.py`: worktrees, status, diff, stage, commit, push e pull, sempre com o `git` da máquina e sem shell.
- `agents.py`: agentes em arquivo (`~/.harness/agentes/*.md`), sprite e importação do Maestri.
- `ports.py`: portas em escuta dos processos de cada terminal (`ps` + `lsof`).
- `files.py`: leitura de arquivos dentro da worktree, para o explorador e os visualizadores.
- `sprites.py`: sprites dos agentes por prompt (`codex exec` com a ferramenta de imagem, estilo greco-romano obrigatório) e a pixelização em 48 × 48.
- `vault.py`: o vault Brain (Obsidian): frontmatter, links, projetos de `01-PROJETOS` e a pasta de cada um (`diretorio:`); grava só o que muda, de forma atômica.
- `kanban.py`: estágio do projeto (`estagio:` no frontmatter) e tarefas das "Próximas ações" (`#em-andamento`, `#em-teste`, `[x]` com `✅ data`).
- `brain_index.py`: índice SQLite FTS5 em `~/.harness/brain.db` (cache, refeito do vault, com trava de escrita entre processos), busca, backlinks, vetores dos registros, precedentes híbridos (palavra + significado), conflitos antes de decidir, projetos vizinhos de um registro e o texto do hook de início de sessão.
- `semantic.py`: busca por significado com o potion-multilingual-128M (model2vec) em `~/.harness/modelos`: baixa, carrega sob demanda e solta parado; a régua é o z (quanto um vizinho se destaca da média da consulta).
- `suggestions.py`: sugestões entre projetos em `~/.harness/sugestoes.db`: registro novo → projetos vizinhos (z >= 3,3) → juiz (`claude -p --model haiku`, teto de 25 por dia) → aceitar pelo `brain.py registrar`.
- `brain_tools.py`: as ferramentas do Brain para agentes (buscar, ler, precedentes, conflitos, sugestões), as mesmas na central e no MCP de fora.
- `brain_mcp.py`: `metis brain mcp` (MCP por stdio para sessões fora da MÊTIS, vazio dentro dela) e `metis brain contexto` (hook SessionStart).
- `claude_print.py`: pedido pontual ao `claude -p` pela conta ativa (o juiz roda sem ferramentas, sem MCP e sem as configurações do usuário).
- `transcript.py`: janela de contexto de uma sessão do Claude, lida do transcript JSONL (total da API, divisão estimada por categoria desde a última compactação).
- `mcp_hub.py`: a central de MCP (`POST /mcp`): um servidor MCP por HTTP para cada terminal de agente, com as ferramentas do Brain (inclusive `brain_conflitos` e `brain_sugestoes`), do kanban, do lembrete e das contas de conector, aprovação de escrita, Atividade e as notas que cada sessão viu (mini-mapa).
- `connectors.py`: contas dos conectores (Slack por token do bot, ClickUp por OAuth), em `~/.harness/conectores.json` sem segredos.
- `keychain.py`: tokens dos conectores no Keychain do macOS (`keyring`).
- `slack.py`: Web API do Slack para o bot (DM, mensagem, mensagem agendada) e o manifesto do app.
- `mcp_client.py` e `oauth.py`: cliente MCP por HTTP e login OAuth com registro dinâmico e PKCE (retorno em `127.0.0.1`).
- `when.py`: datas em português para lembretes ("sexta 9h", "em 20 min").
- `capture.py`: a captura rápida (lembrete, tarefa, nota ou concierge), com a hora tirada só do fim da frase.
- `study.py`: blocos do Pomodoro em `~/.harness/estudo.db`, placar e a linha na nota do dia.
- `agent_draft.py`: rascunho de agente a partir de uma frase, pelo `claude -p` oficial.
- `routines.py`: rotinas (`~/.harness/rotinas/*.md`), a regra de rodar, recuperar ou pular com o Mac dormindo e o histórico em `~/.harness/rotinas.db`; o agendador roda no núcleo a cada 20 s.
- `boards.py`: os Quadros, `.canvas` do Obsidian (JSON Canvas 1.0) em `01-PROJETOS/<Projeto>/quadros/`: listar, criar, ler com as notas do Brain resolvidas e salvar recusando por cima do que o Obsidian salvou depois.
- `automations.py`: o arquivo das automações (`~/.harness/automacoes/<id>.yaml` = rascunho, `publicadas/<id>.yaml` = publicada, git local com as versões), a validação do desenho, as camadas, as expressões `{{Passo.campo}}` e a regra de uma linha da Condição (avaliada sem `eval`).
- `automation_engine.py`: o motor: execuções em `~/.harness/automacoes.db`, camadas que rodam juntas, ramos, ensaio no teste, ferramenta pela central, agente em terminal com a `saida`, aprovação, Brain, esperar, reexecutar daqui e o agendador (a mesma regra de recuperação das rotinas).
- `activity.py`: Atividade em `~/.harness/atividade.db`.
- `app.py`: API HTTP e WebSocket.

```sh
uv sync
uv run harness-core          # sobe em http://127.0.0.1:47830
uv run pytest
uv run harness contas        # contas e troca de conta pelo terminal
```

Variáveis: `HARNESS_PORT`, `HARNESS_TOKEN` (gerado se faltar), `HARNESS_HOME` (padrão `~/.harness`), `HARNESS_VOICE_MODEL` (padrão `small`), `HARNESS_WORKTREES_DIR` (padrão `~/orca/workspaces`), `BRAIN_VAULT` (padrão `~/Documents/Brain`, a mesma do `brain.py`).

No Mac Intel o `onnxruntime` não tem mais wheel; o `pyproject.toml` o desliga, porque só serve ao filtro de silêncio do Whisper, que o Harness não usa.
