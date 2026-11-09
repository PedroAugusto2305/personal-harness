# Paridade com o Orca

> **Estado:** em execução, um bloco por versão desde a `v0.9.2`. **Levantamento:** 2026-11-07, sobre o Orca 1.4.248 a 1.4.253. **Situação:** 2026-11-09.
> **Fontes:** as 58 páginas de `onorca.dev/docs`, o changelog, as releases de 1.4.247 a 1.4.253 e as referências de plugin em `github.com/stablyai/orca/docs/reference`. Em [`MAPA.md`](MAPA.md#6-seu-uso-real-do-orca), o seu uso real, lido de `~/Library/Application Support/Orca`.

**Como ler a tabela:**
- **Uso:** ⭐ muito · ◐ pouco · ○ nunca ou desligado · ? sem sinal.
- **Meta:**
  - **1.0** é a régua obrigatória para desligar o Orca.
  - **Depois** entra após a 1.0.
  - **Fora** contraria um princípio do Harness.
- A meta é uma **proposta**: mova o que quiser.

## Situação da régua 1.0 (2026-11-09, `v0.9.8`)

| Bloco | Situação |
|---|---|
| Contas, uso e limites, hooks e memória, servidores MCP (central de conectores), status do agente, barra de entrada com anexo e ditado em português, terminal flutuante, links e arrastar para o terminal | ✅ da `v0.2` à `v0.6` |
| Worktrees (criar, copiar `.env`, apagar sem perder branch), abas, divisão em dois, painel de mudanças, diff com notas, commit pelo agente, arquivos, visualizadores, ⌘P, portas | ✅ `v0.3` |
| Navegador por worktree com modo de design | ✅ `v0.4` |
| Status do workspace e tarefas no kanban, Atividade, automações agendadas | ✅ `v0.5` a `v0.9.0` |
| **A. Sessões e agentes:** sobreviver a fechar o app, histórico e retomar, reiniciar e continuar, passar o trabalho Claude ↔ Codex, modo de permissão, confiar na pasta, Mac acordado, página de Skills | ✅ `v0.9.2` |
| **E. Avisos e sistema:** aviso do macOS e som, sino com não lidos e badge no Dock, ajustes de aviso, gerenciador de recursos, scripts de setup e arquivamento, CLI com `--json` e leitura e escrita em terminais | ✅ `v0.9.2` |
| **B. Terminal e navegação:** busca no terminal, comandos salvos, divisão aninhada salva por worktree (com arrastar a aba para a borda), ⌘J, atalhos remapeáveis, busca nas configurações, importar tema do Ghostty | ✅ `v0.9.3` |
| **Uso diário:** app instalado de uma versão marcada, atualização pelo app e pelo `metis`, MÊTIS de desenvolvimento separada | ✅ `v0.9.4` |
| **C. Git e GitHub:** stage por trecho ou linha, comparar com qualquer ref, conflitos, criar PR, issues e PRs no kanban, receitas de IA por ação | ✅ `v0.9.6` (merge em 3 vias com edição livre vem com os editores) |
| **D. Editores:** editar arquivos da worktree, editar notas do Brain com `[[links]]` e callouts | ✅ `v0.9.7` (Monaco nos arquivos, CodeMirror nas notas) |
| Fora da `v0.9.2` no bloco A: configuração por agente (binário e argumentos próprios), CLI genérica, hibernação, MCP próprio pela central | ✅ `v0.9.8` parte 1 (argumentos, variáveis, outra CLI, hibernação) e parte 3 (MCP próprio pela central) |
| Fora da `v0.9.3` no bloco B: temas do Warp e do Kitty, copiar o contexto e o ID da sessão, teclado kitty e OSC 52 no terminal | ✅ `v0.9.8` parte 1 (temas, copiar, OSC 52); ⏳ teclado kitty espera o xterm 6.1 estável (só existe na beta) |
| Itens 1.0 fora dos blocos: navegador pelo MCP, perfis e emulação, barra lateral (filtros, fixar, renomear, cores), worktree a partir de branch ou SHA, painel de agentes, tarefas unificadas, abrir em VS Code, fontes e zoom, Skills da MÊTIS | ✅ `v0.9.8` partes 1 a 3 (navegador pelo MCP, perfis, emulação, barra lateral, worktree de branch ou commit, fontes e zoom, Skills, painel de agentes, tarefas do Brain, do GitHub e do ClickUp no kanban); abrir em VS Code na `v0.9.6` |
| Fora da `v0.9.6` no bloco C e diferenciais da MÊTIS: checks falhos de volta ao agente, revisão de PR por IA, grafo do código pela central, Estudo completo, perfis da MÊTIS e backup, instalar e compartilhar Skills | ✅ `v0.9.8` parte 5 (PRs empilhados ficam para depois da 1.0) |
| Correções e detalhes do Pedro, revisão das telas | ⏳ `v0.9.9` |

## Agentes e contas

| Recurso | O que faz | Uso | Meta |
|---|---|---|---|
| Catálogo de agentes | 41 CLIs com instalação em um clique; qualquer CLI roda num terminal | ⭐ (claude) | 1.0: Claude e Codex com tudo; outras como "CLI genérica" |
| Configuração por agente | Ligar e desligar CLIs; binário, comando, argumentos e variáveis próprios | ? | 1.0 |
| Modo de permissão | Manual, Auto ou Yolo para sessões novas | ⭐ (Yolo) | 1.0 |
| Confiar na pasta automaticamente | Pula o "trust this folder" | ? | 1.0 |
| Claude Code a fundo | Subagentes e colegas de equipe como linhas filhas, transcript do filho | ? | Depois |
| Claude Agent Teams | Painel nativo por colega de equipe | ○ (desligado) | Depois |
| Codex a fundo | Servidor isolado por aba, subagentes como filhos | ? | Depois |
| Várias contas e troca rápida | Troca a conta ativa num clique; vale para sessões novas | ◐ | 1.0 |
| Uso e limites | Janelas de 5 h, diária, semanal; aviso em 80%; compacto ou detalhado | ⭐ | 1.0 |
| Custo estimado | Por família de modelo, pela tabela de preços | ? | 1.0 |
| Histórico de sessões | Transcripts de cerca de 22 CLIs, busca, retomar (`claude --resume`, `codex resume`) | ? | **1.0** |
| Hibernação | Pausa agente parado e retoma depois (padrão de 30 min) | ○ (experimental) | 1.0 |
| Agentes sobrevivem a fechar o app | Um processo de fundo segura os terminais; fechar, travar ou atualizar o app não mata o agente | ? | **1.0** (vira peça da arquitetura) |
| Reiniciar agente | Relança o agente que saiu, na mesma pasta e conta | ? | 1.0 |
| Passar o trabalho | Sessão nova em outro agente, com um resumo tirado do transcript | ? | 1.0 (Claude ↔ Codex) |
| Hooks e memória | Respeita `.claude/`, `.codex/`, `CLAUDE.md`, `AGENTS.md` | ⭐ | 1.0 |
| Skills | Instalar, atualizar, página de skills, compartilhar por link | ○ (botão oculto) | 1.0 (página de skills); compartilhar por link: Fora (exige conta Orca) |
| Servidores MCP | Registrar MCP para os agentes, por máquina | ? | 1.0 (central de conectores) |
| Manter o Mac acordado | Ligado, só com agente ativo, desligado | ○ | 1.0 |
| Modelos alternativos | Ex.: GLM pelo env do Claude | ○ | Depois |
| Créditos de reset do Codex | Gasta um crédito de reset de limite | ? | Depois |

## Terminal e chat

| Recurso | O que faz | Uso | Meta |
|---|---|---|---|
| Terminal | xterm.js, teclado kitty, OSC 52, busca com regex, copiar contexto e ID da sessão | ⭐ | 1.0 |
| Links no terminal | Abrir no navegador do app ou do sistema, copiar | ? | 1.0 |
| Shells e temas | Shell padrão, argumentos, contraste; importa temas do Ghostty, Warp e Kitty | ⭐ (tema Ghostty) | 1.0 |
| Status do agente | Girando, "?" âmbar, verde, vermelho, cinza | ⭐ | 1.0 (alimenta os sprites) |
| Arrastar para o terminal | Arquivo vira caminho; captura de tela vira arquivo | ? | 1.0 |
| Comandos salvos | Comandos e prompts salvos, globais ou por projeto | ? | 1.0 |
| Terminal flutuante | Terminal, navegador e markdown fora de worktree (`Cmd+Opt+A`) | ◐ | 1.0 |
| Tela de chat | Transcript estruturado com caixa de mensagem | ○ (desligada) | Depois (roda pelo Agent SDK com o login do plano, a zona cinzenta que evitamos) |
| Caixa de mensagem do chat | Anexos, `@arquivo`, `/` comandos, fila, parar, voltar | ○ | 1.0 como **barra de entrada sob o terminal** |
| Pílulas de modelo e anel de contexto | Modelo, esforço, modo rápido, uso do contexto | ○ | 1.0 na barra de status |
| Visuais no chat | Gráficos e diagramas na resposta | ○ | Depois |
| Continuar após reset do limite | Reenvia sozinho quando o limite zera | ○ | Depois |
| Ditado | Voz para o prompt ou o terminal; modelos locais (Whisper Tiny, Parakeet…) ou OpenAI | ◐ (ligado sem modelo) | **1.0**, em português |

## Worktrees e layout

| Recurso | O que faz | Uso | Meta |
|---|---|---|---|
| Worktree por tarefa | `git worktree` de verdade, a partir de branch, SHA ou remota, criação em segundo plano | ⭐ | 1.0 |
| Diálogo de criação | Projeto, agente inicial, ligação com PR ou tarefa, nome do branch, emoji | ⭐ | 1.0 |
| Arquivos ignorados | Compartilhar ou copiar `node_modules`, `.env` etc. para a worktree | ? | 1.0 |
| Scripts de setup e de arquivamento | Rodam ao criar e ao apagar a worktree (`orca.yaml`) | ? | 1.0 |
| Apagar worktree | Pasta e branch, forçar, revisar branches preservados | ⭐ (50 a 99) | 1.0 |
| Worktrees filhas | Aninhamento, dormir ou apagar com descendentes | ? | Depois |
| Barra lateral | Por projeto, filtros, fixar, seleção múltipla, renomear, cores por repositório | ⭐ | 1.0 |
| Trabalho ligado | Vários PRs e tarefas por workspace | ? | Depois |
| Worktrees externas | Descobre worktrees criadas pelo Claude Code | ? | 1.0 |
| Grupos de projetos | Vários repositórios num grupo | ○ | Depois |
| Gerenciador de recursos | CPU, memória, sessões, disco, limpeza | ? | 1.0 (importa no Mac Intel) |
| Status do workspace | a fazer, em andamento, em revisão, concluído, com comentário | ? | 1.0 (vira o kanban de tarefas) |
| Abas | Terminal, editor, navegador, diff, PR, simulador, chat | ⭐ (500 a 999) | 1.0 |
| Divisão de tela | Arrastar para a borda, aninhada, salva por worktree | ⭐ (100 a 199) | 1.0 |
| Painel de agentes | Kanban "precisa de você, trabalhando, feito, parado" | ○ (experimental) | 1.0, fundido ao kanban do Harness |
| Feed de atividade | Eventos dos agentes com prévia | ○ | 1.0 (módulo Atividade) |

## Navegação e atalhos

| Recurso | O que faz | Uso | Meta |
|---|---|---|---|
| Abrir arquivo (`Cmd-P`) | Busca de arquivos no worktree | ? | 1.0 |
| Omnibox | Busca abas, arquivos, URLs, agentes, histórico | ? | 1.0 |
| Pular para (`Cmd-J`) | Recentes, worktrees, projetos, `#PR`, abas | ? | 1.0 |
| Atalhos remapeáveis | Todos, em arquivo de configuração | ? | 1.0 |
| Busca nas configurações | `Cmd-,` com termos em vários idiomas | ? | 1.0 |

## Revisão e git

| Recurso | O que faz | Uso | Meta |
|---|---|---|---|
| Visualizador de diff | Combinado, de imagem, merge em 3 vias, stage por trecho ou linha, comparar com qualquer ref | ? | 1.0 |
| Notas no diff da IA | Nota por linha ou faixa, mandar em lote ao agente | ? | 1.0 |
| Notas em markdown | Anotar o texto renderizado | ? | Depois |
| Autoria | Marca se a linha é humana ou da IA | ? | Depois |
| Commit | Mensagem por IA, pre-commit na tela, "consertar com IA", amend | ⭐ (IA ligada) | 1.0 |
| Push, pull, sync | Botão que muda com o estado; force com `--force-with-lease` | ? | 1.0 |
| Criar PR | GitHub, GitLab, Bitbucket; texto por IA; rascunho; PRs empilhados | ○ (0 PRs) | 1.0 só GitHub; o resto Depois |
| Receitas de IA por ação | Agente, modelo e template para commit, PR, branch | ? | 1.0 |
| Painel de source control | Contexto do branch, resolver conflito com IA, abortar merge | ? | 1.0 |
| Revisões hospedadas | Checks, comentários, auto-merge, "consertar checks" | ○ | Depois |
| Configurações de git | Assinatura de commit, editor externo | ? | 1.0 |

## Arquivos e editor

| Recurso | O que faz | Uso | Meta |
|---|---|---|---|
| Editor Monaco | O editor do VS Code: salvar sozinho, formatar ao salvar, vários cursores | ? | 1.0 (vem pronto no caminho B; no A, Monaco embutido) |
| Markdown rico | Menu `/`, callouts, **`[[links]]`**, tabelas, frontmatter | ? | **1.0**: serve para editar as notas do Brain dentro do Harness |
| Visualizadores | HTML, Mermaid, PDF, imagem, áudio e vídeo, CSV editável, Jupyter com kernel | ? | 1.0 (Jupyter com kernel Depois) |
| Explorador de arquivos | Tempo real, cores de git, copiar caminho, revelar | ? | 1.0 |
| Arrastar de fora | Cai onde você aponta | ? | 1.0 |
| Publicar artefato | HTML e MD como link público | ○ (desligado) | Fora (exige conta Orca; o Harness é só local) |

## Navegador

| Recurso | O que faz | Uso | Meta |
|---|---|---|---|
| Navegador por worktree | Chromium com histórico, devtools, downloads; cursor do agente visível | ⭐ (200 a 499) | **1.0** |
| Modo de design | Clicar num elemento manda HTML, CSS e arquivo:linha ao agente | ? | 1.0 |
| Perfis | Partições isoladas, importar cookies do Chrome | ? | 1.0 |
| Senhas e extensões | Gerenciador de senhas, extensões do Chrome (experimental) | ? | Depois |
| Emulação | Viewport, roteamento de links | ? | 1.0 |
| Automação do navegador | snapshot, clicar, preencher, screenshot, console, rede | ◐ (configurado 1 vez) | 1.0 (pelo MCP do Harness) |
| Uso do computador | Controlar apps nativos pela acessibilidade | ◐ (configurado 1 vez) | Depois |
| Emulador de celular | Simulador de iOS em aba, Android por adb | ○ | Depois |

## Integrações

| Recurso | O que faz | Uso | Meta |
|---|---|---|---|
| GitHub | PRs, checks, issues, Projects como kanban | ◐ (2) | 1.0 (issues e PRs); Projects Depois |
| GitLab, Bitbucket, Azure, Gitea | Outros hosts de git | ○ | Depois |
| Linear | Ver, editar, criar, sincronizar status | ○ | Depois (vira conector) |
| Jira | Cloud ou Server, JQL, transições | ○ | Depois (vira conector) |
| Tarefas unificadas | GitHub, Linear, Jira e GitLab numa lista; criar worktree de um item | ◐ (5 a 9) | 1.0, fundido ao kanban (Brain, ClickUp, GitHub) |
| Abrir em, importar | VS Code, importar `~/.claude`, `~/.codex`, Ghostty | ? | 1.0 |

## Automação e CLI

| Recurso | O que faz | Uso | Meta |
|---|---|---|---|
| CLI do Orca | `orca` com saída `--json` para os agentes usarem o app | ? | 1.0 (CLI `harness`) |
| Comandos principais | worktree, iniciar agente com modelo, esforço e prompt, ler e escrever em terminais | ? | 1.0 |
| Orquestração | Runs, tarefas em grafo, workers em worktree filha, mensagens, portões | ◐ (1 run) | Depois (canvas de orquestração) |
| Automações agendadas | Cron, RRULE, fuso, recuperação dentro de uma tolerância | ◐ (nenhuma ativa) | 1.0 (Rotinas) |
| Skills do Orca | Guias para o agente usar o app | ? | 1.0 (skills do Harness) |

## Remoto, nuvem e celular

| Recurso | O que faz | Uso | Meta |
|---|---|---|---|
| SSH | Importa `~/.ssh/config`, MFA, jump host | ○ (0 alvos) | Depois |
| Servidor gerenciado via SSH | O Orca instala o próprio runtime no host | ○ | Depois |
| Portas | Aba de portas, portas detectadas, encaminhamento | ⭐ (10 a 19) | **1.0** (local) |
| Servidor remoto do Orca | Outra máquina roda tudo; laptop, web e celular viram clientes | ○ | Depois |
| Cliente web | A interface no navegador | ○ | Depois |
| Máquina na nuvem | Ambiente por workspace (Fly, Modal, Vercel Sandbox, Docker) | ○ (desligado) | Depois |
| App de celular | Pareamento, terminal, chat, ações, push | ○ (desligado) | Depois (hoje: avisos por ClickUp e Slack) |

## Avisos, aparência e configurações

| Recurso | O que faz | Uso | Meta |
|---|---|---|---|
| Avisos de agente | Notificação, som e chip quando termina ou precisa de você | ⭐ (ligados) | 1.0 |
| Caixa de avisos | Sino, badge no Dock, não lido | ? | 1.0 |
| Ajustes de aviso | Som, volume, silenciar por máquina | ⭐ | 1.0 |
| Plugins | 151 no catálogo, instalar por Git, atualização automática | ○ (desligado, só temas) | Depois (o catálogo); temas 1.0 |
| Temas e aparência | Temas do app e do terminal, ícones, fontes, acento, densidade, zoom, 10 idiomas | ⭐ | 1.0 com a [`DESIGN.md`](DESIGN.md) |
| Atualizações | Automáticas, canal RC, atraso configurável | ? | 1.0: ✅ `v0.9.4` (aviso de versão nova e atualizar num clique; o núcleo passa ao reiniciar) |
| Telemetria | PostHog anônimo | ⭐ (ligada) | Fora (o Harness não manda dados para fora) |
| Segredos | No Keychain | ? | 1.0 |

## O que o Orca faz e o Harness **não** vai fazer

| Mecanismo do Orca | Por que fica fora |
|---|---|
| Ler o uso do Claude pela API com o token OAuth da conta, como reserva da statusline | Fere o princípio 1: o Harness nunca lê credencial. Fica só a statusline, que é o caminho principal do próprio Orca |
| Tela de chat do Claude pelo Agent SDK com o login do plano | É o modo sem tela que decidimos evitar; você também não usa |
| Hooks gravados no `~/.claude/settings.json` global | O Harness injeta os dele por sessão (`--settings`), para não brigar com outros apps |
| Conta Orca, Relay, artefatos públicos, compartilhar skills por link | O Harness é só local |
| Telemetria | Idem |

## Como o Orca faz por dentro (útil para nós)

- **Uso do Claude:** a statusline repassa o `rate_limits` que o Claude Code já entrega, por `curl`, para o servidor local de hooks. É exatamente o plano do Harness.
- **Uso do Codex:** ele abre um `codex app-server` de curta duração e chama `account/rateLimits/read`. Usa o login da própria CLI, então serve ao Harness também.
- **Contas:** `CLAUDE_CONFIG_DIR` por conta do Claude (o Keychain separa por pasta) e `CODEX_HOME` por conta do Codex. Trocar de conta é só mudar o ponteiro, sem login de novo. Confirma o nosso desenho.
- **Hooks do Claude:** SessionStart, UserPromptSubmit, Stop, StopFailure, SubagentStop, Pre e PostToolUse, PermissionRequest e PostCompact.
  - O **PreToolUse espera a resposta**, então serve de trava de aprovação do Harness mesmo com o agente em Yolo.
- **Hooks do Codex:** `hooks.json` dentro do `CODEX_HOME`.
- **Agentes vivos:** um processo de fundo é dono dos terminais, e a interface só se reconecta a ele.
- **Automações:** um relógio interno de 60 segundos, com recuperação do que passou dentro de uma tolerância. Não usa cron nem launchd. Precisa do Orca rodando.
- **Plugins:** a API **é documentada** (`docs/reference/plugin-authoring.md`, `plugin-host-api.md`, `plugin-manifest.md`). Ela tem:
  - painéis em iframe isolado e plugins com acesso total num processo Node próprio;
  - eventos de status de agente;
  - interceptação de `agent.prompt.before`, de `agent.tool.before/after` e da criação de workspace;
  - itens na barra de status, comandos, editores, temas.

  Ainda reservados para o futuro: `mcpServers`, `connections`, `taskSources` e `skills`.

## Ideias de plugins da comunidade que valem para o Harness

- Rotação de conta quando a janela de uso está no fim.
- Caixa de pendências dos agentes.
- Cliente de banco de dados.
- WakaTime.
