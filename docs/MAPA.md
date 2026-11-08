# Personal Harness: mapa do projeto

> **Estado:** planejamento, sem código. **Atualizado em:** 2026-11-07.
> As decisões, com o porquê e as alternativas descartadas, ficam no Brain, em `01-PROJETOS/Personal Harness/`.
> A lista de tudo o que o Orca faz, com o que você usa, fica em [`PARIDADE-ORCA.md`](PARIDADE-ORCA.md).

---

## 1. Visão

Um **OS pessoal no Mac com cara de ADE** (ambiente de desenvolvimento com agentes). Ele substitui o **Orca** e o **Maestri**.

- **Régua:** tudo o que o Orca faz é o mínimo.
- **Diferencial:** o **Brain** como memória viva que deixa os projetos mais inteligentes, mais o lado **OS pessoal** (conectores, rotinas, kanban, captura rápida, avisos).
- **Para quê:** estudo, tarefas do trabalho, cotidiano e programação, tudo num lugar só.

## 2. Princípios (o que não muda)

| # | Princípio | Por quê |
|---|---|---|
| 1 | O Harness **não guarda login de IA**. Claude Code e Codex rodam **interativos em terminais**, logados pelo fluxo oficial | Única forma de usar o plano sem violar os termos ([página legal do Claude Code](https://code.claude.com/docs/en/legal-and-compliance)) |
| 2 | **O Brain é a memória.** O Harness lê e escreve seguindo as regras do vault: frontmatter, links, nunca apagar | Um só lugar para lembrar, para você e para os agentes |
| 3 | **Só local.** Nada exposto na internet. Avisos no celular saem pelo ClickUp e pelo Slack | Segurança, e o Harness para quando o Mac dorme |
| 4 | **Você aprova o que envolve outras pessoas.** A aprovação fica na central de conectores, porque os agentes rodam em modo sem confirmação (`--dangerously-skip-permissions` é o padrão no seu Orca) | O modo sem confirmação desliga a trava da CLI, então a trava precisa estar no Harness |
| 5 | **Um agente, uma tarefa.** Agente novo só com dor real | Regra já registrada no projeto Agentes Pessoais |
| 6 | **Só roda com o Mac acordado.** O que tem hora marcada é agendado fora (Slack, ClickUp) | Decisão sua: não é serviço 24h |

## 3. Módulos

Legenda: 🟦 a régua do Orca já tem · 🟩 diferencial do Harness · ⭐ você usa muito no Orca (ver seção 6)

| Módulo | O que faz | Origem |
|---|---|---|
| **Terminais e agentes** | Abas, divisão de tela, layouts salvos (automático, foco, grade), terminal flutuante, salto rápido (⌘J/⌘K), qualquer CLI de agente, hibernação de agente parado, sessões retomadas depois de reiniciar, histórico de sessões com busca e retomada, comandos e prompts salvos, agentes que sobrevivem a fechar o app, passar a conversa do Claude para o Codex e de volta | 🟦 ⭐ + Alethe |
| **Contas e uso** | Várias contas por CLI (`CLAUDE_CONFIG_DIR`, `CODEX_HOME`), comando `switch`, limites de 5 h e 7 dias com hora em que zeram, alerta em 80%, roteamento por cota: acima de 80%, sugere o mesmo nível (barato, padrão, forte) no outro provedor. A troca só é automática em rotina com regra explícita | 🟦 ⭐ + Alethe |
| **Barra de status** | Contexto e custo da sessão, cota de 5 h e 7 dias por provedor, memória usada pelo app | LearnHarness + Alethe |
| **Código** | Repositórios, worktree por agente, diff com notas por linha que voltam ao agente, commit e PR escritos por IA, checks falhos de volta ao agente, portas abertas, árvore de arquivos, visualizador de imagem, PDF e Markdown, grafo do código pelo graphify servido aos agentes por MCP, revisão de PR por IA só de leitura | 🟦 ⭐ + Alethe |
| **Navegador embutido** | Abas de navegador ao lado dos terminais, modo de design (clicar num elemento e mandar HTML e estilo ao agente) | 🟦 ⭐ |
| **Barra de entrada** | Sob cada terminal: 🎙️ voz em português, 📎 anexo (arrastar, colar, clipe), `@nota do Brain`, `/comando` | 🟦 + 🟩 |
| **Brain** | Grafo das notas, busca, leitura, janela de contexto da sessão, registro automático | 🟩 |
| **Precedentes** | Decisões, incidentes e aprendizados de outros projetos aparecendo na hora certa, também nas sessões fora do Harness | 🟩 |
| **Kanban de projetos** | Projetos do Brain como cartões, arrastar muda o estágio na nota, cartão abre tarefas, decisões e o espaço de trabalho; "Executar com agente" a partir de uma tarefa; os agentes movem os cartões de tarefa sozinhos pelo MCP do Harness (Pendente, Em andamento, Em teste, Concluído), com rótulos e subtarefas | 🟩 + CodeAgentSwarm (o Orca só tem tarefas do GitHub e do Linear) |
| **Conectores** | Galeria com botão "Conectar" (ClickUp, Slack, Notion, GitHub, Google…), várias contas por ferramenta, central de MCP com permissão por agente, aprovação e log, busca no catálogo oficial de MCP, teste de conexão, copiar um MCP entre Claude e Codex | 🟩 + Alethe |
| **Agentes com papel** | Galeria e botão "Novo agente" (por formulário ou descrevendo em uma frase), "testar antes de salvar", campo "qual dor resolve?", agentes padrão e concierge. Cada agente tem um **sprite em pixel art** gerado pelo Codex, que se anima conforme o estado (trabalhando, esperando você, dormindo, concluiu, erro) | 🟩 |
| **Skills** | Ver, instalar e compartilhar as skills do Claude e do Codex num lugar só | Alethe |
| **Orquestração** | Estratégias reutilizáveis num canvas (explorar e construir, planejar grande e executar pequeno, melhor de N, portão de revisão), com alternativa de provedor por cota | 🟦 + Alethe |
| **Estudo** | Modo de estudo do AI Engineer 2027: medir o que você sabe, planejar, ensinar com perguntas de previsão e grau de confiança, praticar; o que você aprende vira grafo no Brain; foco com Pomodoro. Casa do Sócrates e da Aurora | 🟩 LearnHarness + Alethe |
| **Rotinas e automações** | Prompt agendado que abre um terminal; recupera o que perdeu com o Mac dormindo | 🟦 + 🟩 |
| **Hoje** | Painel do dia: tarefas, rotinas, cota dos planos, sugestões do Brain | 🟩 |
| **Captura rápida** | Atalho global em qualquer app: "anota tarefa X", "me lembra de Y amanhã", que vai para o concierge | 🟩 |
| **Atividade** | O que cada agente fez nos conectores, as aprovações pendentes e os agentes em segundo plano com tempo e custo | 🟩 + LearnHarness |
| **Avisos** | Notificação do macOS com o app aberto; Slack (bot do Harness) e ClickUp para o celular | 🟦 + 🟩 |
| **Aparência** | Temas por tokens (Drácula azul como padrão, Grafite, Claro), **criar tema com prompt** (um agente gera os tokens, o Harness confere o contraste e mostra a prévia antes de aplicar), importar tema do Obsidian, VS Code ou Ghostty, fontes, tema do terminal, interface em português; direção visual em [`DESIGN.md`](DESIGN.md) | 🟦 + 🟩 + Alethe |
| **Perfis e backup** | Perfis isolados, exportar e importar a configuração | Alethe |

## 4. Arquitetura

```
 ┌──────────────────────────── App no Mac ─────────────────────────────┐
 │ Tela (React + xterm.js): terminais, código, navegador, Brain, kanban │
 ├──────────────────────────────────────────────────────────────────────┤
 │ Núcleo em Python (FastAPI)                                           │
 │  ├─ Terminais (PTY) com claude / codex / qualquer CLI                │
 │  │    └─ hooks + statusline + arquivos de sessão → contexto e cota   │
 │  ├─ Contas: uma pasta de configuração por conta                      │
 │  ├─ Agentes, rotinas, kanban                                         │
 │  ├─ Central de MCP: conectores, permissões, aprovação, log           │
 │  └─ Motor do Brain: índice, grafo, precedentes                       │
 └───────┬──────────────────────────────┬───────────────────────┬──────┘
         │ MCP                          │ lê e escreve          │ MCP e hooks
  ClickUp · Slack · Notion…      ~/Documents/Brain     Claude Code nos repositórios
         │ notificação nativa
       iPhone
```

| Peça | Como | Decidido? |
|---|---|---|
| Casca do app | Tauri (caminho A) ou o Electron do fork do Orca (caminho B) | ❓ pergunta 1 |
| Tela | React, xterm.js para terminais | ✅ em qualquer caminho |
| Núcleo | Python e FastAPI | ✅ |
| Terminais | Python controla o PTY (como o terminal do Jupyter) no caminho A; o Orca já faz no caminho B | depende da pergunta 1 |
| Ver dentro do terminal | Claude: statusline (contexto, custo, limites de 5 h e 7 dias), hooks e `transcript_path`, injetados por `--settings` na sessão para não brigar com outros apps. Codex: `hooks.json` dentro do `CODEX_HOME` da conta, `~/.codex/sessions/.../rollout-*.jsonl` (`token_count`) e limites por `codex app-server` → `account/rateLimits/read`. É o mesmo que o Orca faz, menos a leitura de token | ✅ (testar na Fase 0) |
| Agentes vivos | Um processo de fundo é dono dos terminais; fechar, travar ou atualizar a janela não mata os agentes (paridade com o Orca) | ✅ |
| Trava de aprovação | O hook PreToolUse do Claude espera a resposta do Harness antes de a ferramenta rodar, então funciona mesmo com o agente em Yolo | ✅ (testar na Fase 0) |
| Contas | `CLAUDE_CONFIG_DIR` e `CODEX_HOME`, login sempre pelo fluxo oficial | ✅ |
| Conectores | Central de MCP do Harness; cada terminal recebe um MCP só com as ferramentas liberadas para aquele agente (`--mcp-config` no Claude, `-c` no Codex). Tokens das ferramentas no Keychain | ✅ |
| Motor do Brain | Pacote Python usado de três formas: no app, como servidor MCP e nos hooks. Busca por palavra e por significado (embeddings locais), com o modelo julgando se o precedente se aplica | ✅ |
| Dados | SQLite (sessões, uso, log, cache do kanban). Projetos, tarefas e decisões continuam no Brain | ✅ |
| Versões | SemVer `MAIOR.MENOR.CORREÇÃO`, tag no git, commits `feat:`/`fix:`, `CHANGELOG.md` | ✅ |

## 5. Fluxos principais

1. **Abrir um projeto:** Kanban → cartão → "Abrir" → terminais na pasta do repositório com os precedentes do Brain no painel → statusline mostra contexto e cota.
2. **Lembrete:** captura rápida ("me lembra de pagar X sexta às 9h") → concierge → tarefa no ClickUp com prazo e mensagem agendada no Slack → o iPhone toca mesmo com o Mac fechado.
3. **Decisão com memória:** o agente vai decidir → consulta precedentes → o motor avisa "isso contradiz a decisão Y do projeto Z" → registro no Brain → sugestão aparece nos outros projetos quando você abri-los.
4. **Rotina:** 20h50 → o Harness abre um terminal com o prompt da Aurora → ela lê o Brain e atualiza o placar → aviso no Slack. Se o Mac estava dormindo, roda ao acordar ou pula, conforme a regra da rotina.
5. **Tarefa com agente:** Kanban → tarefa → "Executar com agente" → worktree nova → terminal com a tarefa como prompt → diff com notas → commit com mensagem escrita por IA.

## 6. Seu uso real do Orca

Levantado em 2026-11-07 a partir de `~/Library/Application Support/Orca`, só com contagens e configurações, sem conteúdo de conversa nem credenciais.

| Sinal | Valor |
|---|---|
| Uso desde | 2026-08-14 |
| Agentes iniciados | 2.758 |
| Tempo de agente | cerca de 680 horas |
| Repositórios | 14 |
| Worktrees com histórico | 25 |
| **Muito usado** | abas de terminal (500 a 999), navegador embutido (200 a 499), painel de uso e cota (200 a 499), divisão de abas (100 a 199), painéis de terminal (50 a 99), limpeza de worktrees (50 a 99), criação de espaços de trabalho (20 a 49), portas (10 a 19) |
| **Pouco usado** | troca de conta do Codex (3 a 4) e do Claude (2), terminal flutuante (3 a 4), tarefas (5 a 9), tarefas do GitHub (2), automações (3 a 4, nenhuma configurada hoje) |
| **Não usado** | tela de chat (desligada), celular (desligado), SSH (nenhum), máquinas na nuvem (desligado), sistema de plugins (desligado, só temas instalados), PR criado pelo Orca (0) |
| Agente padrão | `claude`, com `--dangerously-skip-permissions` |
| Visual | tema escuro, fonte Fira Code 14 peso 500, terminal "Ghostty Default Style Dark", barra lateral `#18181b` e divisórias `#3f3f46` (paleta zinco) |
| Voz | ligada, em modo alternar, **em inglês e sem modelo de voz baixado**, por isso não funcionava |
| Avisos | tarefa do agente concluída e sino do terminal, silenciados com a janela em foco |

**O que isso responde:** os três recursos do Orca que batiam com decisões nossas (celular, modo remoto e na nuvem, tela de chat) você não usa. Proposta: ficam fora da régua da `v1.0.0` e entram depois, se fizerem falta.

## 7. Decisões tomadas

Todas em `01-PROJETOS/Personal Harness/decisoes/` no Brain:

1. Usa os planos do Claude e do Codex só pelas CLIs oficiais já logadas
2. Não fala com o iPhone e avisa pelo ClickUp e pelo Slack
3. É um app de Mac em Python que só roda com o Mac acordado
4. Roda o Claude Code e o Codex em terminais dentro do app
5. Liga ferramentas por uma galeria de conectores com várias contas
6. O motor de precedentes atende também as sessões nos repositórios
7. Também é ambiente para programar (e substitui o Orca e o Maestri)
8. Tem como mínimo tudo o que o Orca faz
9. Segue o versionamento semântico

## 8. Perguntas abertas

| # | Pergunta | Recomendação |
|---|---|---|
| 1 | **Caminho:** do zero (A), fork do Orca (B) ou plugins no Orca (C)? | **Decidido em 2026-11-07: do zero (A)**, com Tauri, React e núcleo Python. O visual aprovado é uma moldura própria; num fork seria preciso redesenhar a interface do Orca e brigar com cada atualização dele |
| 2 | Tarefas do kanban moram no Brain, no ClickUp ou nos dois? | **Nos dois:** o Brain para planejar; uma cópia ligada no ClickUp só para o que tem prazo ou aviso |
| 3 | Transcrição de voz fora do Claude (Codex, captura rápida) | Whisper local, testando a velocidade no seu Mac Intel na Fase 0 |
| 4 | Editor de código completo dentro do app? | **O do Orca.** Ele já tem o Monaco (o editor do VS Code) e um markdown rico com `[[links]]` e callouts, que serve para editar as notas do Brain. No caminho B vem pronto; não construímos editor próprio |
| 5 | `v1.0.0` = "substituiu o Orca"? | Sim |
| 6 | Celular, modo remoto e tela de chat entram na régua? | **Depois da 1.0**, porque você não usa no Orca (seção 6) |
| 7 | Visual | Direção definida: Alethe + Orca + Obsidian, cinza e azul quase Drácula ([`DESIGN.md`](DESIGN.md), seção 0). As seis opções viraram módulos de um app só, num protótipo navegável de 9 telas (Hoje, Terminais, Estudo, Brain, Kanban, Quadros, Agentes, Conectores, Ajustes): https://claude.ai/artifact/LAFQ8F9HdM9XGpMpfA5KaG |
| 8 | Nome | Em aberto |

## 9. Roadmap por versão

Cada fase entregue sobe o número do meio. Os itens marcados com ⭐ são o seu uso diário e vêm primeiro.

| Versão | Entrega | Pronto quando |
|---|---|---|
| `v0.1.0` | **Fase 0, provas:** `claude` e `codex` num terminal do app; statusline, hooks e MCP do Harness chegando à sessão; troca de conta por pasta; Whisper no Mac Intel; anexo chegando às duas CLIs; bot do Slack tocando no iPhone, com mensagem agendada | Todas as provas passam ou têm plano B |
| `v0.2.0` | **Núcleo** ⭐: abas, divisões, terminal flutuante, salto rápido, contas e uso (5 h, 7 dias, alerta em 80%), barra de entrada com voz e anexo | Você passa um dia programando nele |
| `v0.3.0` | **Código** ⭐: agentes em arquivo (papel e prompt por agente), espaços de trabalho, worktrees (criar e limpar), diff com notas, commit escrito por IA, portas, árvore de arquivos, visualizadores | Você troca o Orca pelo Harness em um projeto |
| `v0.4.0` | **Navegador embutido** ⭐ com modo de design | Usa o navegador do Harness em vez do do Orca |
| `v0.5.0` | **Brain e kanban:** leitura, busca, precedentes v1 (consulta e início de sessão), kanban de projetos e tarefas | Abre os projetos pelo kanban |
| `v0.6.0` | **Conectores e avisos:** galeria, central de MCP, ClickUp e Slack, aprovações, atividade, Skills | Um lembrete pedido no Mac toca no iPhone |
| `v0.7.0` | **OS pessoal:** Hoje, captura rápida, concierge, rotinas com recuperação, criar agente por formulário e por descrição, sprites dos agentes com animação por estado, Estudo com Pomodoro | A rotina da Aurora roda pelo Harness |
| `v0.8.0` | **Brain vivo:** grafo, mini-mapa, janela de contexto, precedentes completos (os três momentos e o MCP para fora), sugestões entre projetos | Uma sugestão de precedente vira decisão aceita |
| `v0.9.0` | **Paridade restante:** orquestração em canvas e o que faltar da [`PARIDADE-ORCA.md`](PARIDADE-ORCA.md) para a régua da 1.0 | A checklist da 1.0 está toda marcada |
| **`v1.0.0`** | **Substituiu o Orca** | Uma semana sem abrir o Orca nem o Maestri |
| depois | Celular, SSH e remoto, tela de chat, catálogo de plugins, outros provedores | Quando fizer falta |

> **Caminho decidido (2026-11-07): do zero.** O roadmap acima vale como está. A `v0.1.0` é uma fatia vertical: moldura, terminal real do Claude Code, contexto e cota na barra de status.
>
> **`v0.2.0` (2026-11-07):** Codex, contas por pasta com `harness switch`, cota do Codex pelo `app-server`, abas, divisão em dois, flutuante, ⌘K, Ajustes, barra de entrada com ditado (Whisper local) e anexos. "Agentes em arquivo" foi para a `v0.3.0`, junto com o resto do trabalho de código.
>
> **`v0.3.0` (2026-11-07):** projetos e worktrees na barra lateral (criar com branch novo em `~/orca/workspaces`, copiando o `.env`; apagar com aviso de terminal aberto e de mudança sem commit, sem nunca apagar branch não juntado), painel da worktree com Mudanças, Arquivos e Portas, diff em aba com notas por linha que vão em lote para o agente, commit escrito pelo agente da worktree no terminal dele, visualizadores (Markdown, imagem, PDF, CSV, áudio, vídeo, HTML sem scripts, código), ⌘P e agentes em arquivo com tela de edição e sprite trocável (adiantado da `v0.7`), com os 8 agentes do Maestri importados. Ficou para depois: agentes por repositório (`.harness/agentes/` dentro do projeto), stage por trecho ou linha e comparar com qualquer ref.
>
> **`v0.4.0` (2026-11-07):** navegador embutido com WebKit nativo do macOS (o Tauri não traz Chromium): abas ao lado dos terminais, inspetor, aba anônima, downloads, novas janelas como abas, links do terminal com ⌘ + clique e as portas abrindo nele. Modo de design que manda o elemento (seletor, texto, HTML, estilo, componente e arquivo quando dá) para a barra de entrada do agente da worktree. Também entraram as sprites por prompt (Codex + pixelização) com estilo greco-romano por padrão. Ficou para depois: perfis com cookies importados do Chrome (o WebKit tem outro cofre de cookies) e o agente controlar o navegador pelo MCP.

> **`v0.4.1` (2026-11-07):** o navegador ficou fácil de achar: botão de globo na barra lateral, botão "Navegador" na tela vazia e rótulo "Design" no modo de design. Entrou o comando `metis web <endereço>`, que abre uma aba da MÊTIS a partir de qualquer terminal, inclusive o de um agente.

> **`v0.4.2` (2026-11-08):** correção do navegador. A página nativa podia ficar presa numa posição velha e cobrir a janela, e abrir uma aba dava o aviso "aba … não existe": o app reposicionava a página antes de ela nascer e marcava a posição como aplicada antes da confirmação. Agora é uma chamada nativa por vez, a posição só conta depois do sucesso e é reaplicada a cada segundo e no foco da janela. Entrou ⌘K → "Modo de design", e os botões da barra lateral pararam de ser cortados.

> **`v0.5.0` (2026-11-08):** Brain e kanban. Índice SQLite FTS5 do vault (cache em `~/.harness/brain.db`), tela do Brain com busca, filtros, leitor com `[[links]]`, callouts e "Citada por". Kanban de projetos pelo `estagio:` da nota e de tarefas pelas "Próximas ações", com o estado intermediário como etiqueta na linha (`#em-andamento`, `#em-teste`), escolha do Pedro para a tarefa seguir aberta no Obsidian e no `brain.py`. "Executar com agente" cria a worktree e abre o Claude com a tarefa. Precedentes v1 por palavra (título e resumo dos registros de outros projetos) no início de cada sessão do Claude e na aba Brain do painel. Os agentes usam o Brain e o kanban pelo `metis brain` e `metis tarefa`; o MCP do Harness fica para a `v0.6.0`, junto com a central de MCP. Ficou para depois: precedentes para o Codex no início da sessão (a MÊTIS ainda não instala hooks no Codex), tarefas no ClickUp (`v0.6.0`) e busca por significado (`v0.8.0`).

> **`v0.5.1` (2026-11-08):** o grafo do Brain, adiantado da `v0.8.0` a pedido do Pedro: notas e `[[links]]` resolvidos do índice, simulação de forças viva como a do Obsidian (d3-force: arrastar nó, painel com força de centro, repulsão, força e distância das ligações) com uma nuvem por área do projeto, ligações entre projetos em acento, filtros, legenda, zoom e a busca acendendo as notas achadas. Também voltou o botão do painel da worktree quando não há abas. Seguem para a `v0.8.0`: mini-mapa na sessão, janela de contexto e precedentes completos.

## 10. Riscos

| Risco | Como tratar |
|---|---|
| A Anthropic ou a OpenAI mudarem a regra de uso | Terminais interativos são o uso mais comum possível; um perfil de conta pode virar chave de API sem mudar o resto |
| O formato dos hooks, da statusline ou dos arquivos de sessão mudar | Um conector isolado por CLI; quebra um arquivo, não o sistema |
| Muitos terminais pesarem no Mac Intel | Limite de sessões ativas e hibernação de agente parado (o Orca usa 30 minutos) |
| Agentes sem confirmação mexendo em conectores | Aprovação na central de MCP, que não depende da CLI |
| Tamanho do projeto disputar tempo com o estudo | Entregas em fatias pequenas; o núcleo em Python e o motor de precedentes viram peça de portfólio |
| Conflito de configuração com o Orca durante a transição | Statusline e hooks do Harness por `--settings` na sessão, sem mexer no `~/.claude/settings.json` |

## 11. Glossário

| Termo | O que é |
|---|---|
| **ADE** | Ambiente de desenvolvimento com agentes: terminais, código e agentes num só app (Orca, Warp) |
| **CLI** | Programa de terminal, como `claude` e `codex` |
| **PTY** | O "terminal virtual" por onde o app conversa com a CLI como se fosse você digitando |
| **xterm.js** | O componente que desenha o terminal na tela (o mesmo do VS Code) |
| **Hook** | Script que a CLI chama sozinha em momentos certos (início de sessão, ferramenta chamada, fim de turno) |
| **Statusline** | Barra do Claude Code que recebe os dados da sessão (contexto, custo, limites) |
| **MCP** | Protocolo que liga ferramentas (ClickUp, Slack, Brain) aos agentes |
| **Worktree** | Uma cópia de trabalho do mesmo repositório git em outra pasta, para dois agentes não se atropelarem |
| **Fork** | Cópia de um projeto open source que você passa a evoluir por conta própria |
| **SemVer** | Versão `MAIOR.MENOR.CORREÇÃO` |
| **Embeddings** | Números que representam o significado de um texto; permitem achar "parecido" sem a mesma palavra |

## 12. Referências

| Referência | O que levamos |
|---|---|
| [Orca](https://github.com/stablyai/orca) (MIT, Electron) | A régua inteira: ver [`PARIDADE-ORCA.md`](PARIDADE-ORCA.md) |
| [LearnHarness](https://github.com/amosblomqvist/learnharness) | Terminal como dono do login, grafo de conhecimento, barra de entrada com ditado, modelo e esforço, contexto e custo sempre visíveis, modo de estudo |
| [Alethe Agents](https://github.com/Kc1t/alethe-agents) (AGPL, **Tauri + React + xterm.js**) | Prova de que Tauri aguenta um ADE com PTYs reais; aba de MCP e de Skills, graphify como MCP, passagem Claude ↔ Codex, layouts, sessões retomáveis, roteamento por cota, canvas de orquestração, Pomodoro, memória na barra, interface em português |
| [CodeAgentSwarm](https://www.codeagentswarm.com/en/guides/claude-code-task-management) | Kanban que os agentes atualizam sozinhos por MCP |

Lista original das referências: [`../refs.md`](../refs.md).
