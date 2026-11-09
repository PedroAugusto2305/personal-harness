# Personal Harness: mapa do projeto

> **Estado:** em construção, na `v0.9.7` (lista de mudanças em [`../CHANGELOG.md`](../CHANGELOG.md)). **Atualizado em:** 2026-11-08.
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
| **Orquestração** | Estratégias reutilizáveis num canvas (explorar e construir, planejar grande e executar pequeno, melhor de N, portão de revisão), com alternativa de provedor por cota. Na `v0.9.2`, no mesmo canvas e motor das Automações | 🟦 + Alethe |
| **Estudo** | Modo de estudo do AI Engineer 2027: medir o que você sabe, planejar, ensinar com perguntas de previsão e grau de confiança, praticar; o que você aprende vira grafo no Brain; foco com Pomodoro. Casa do Sócrates e da Aurora | 🟩 LearnHarness + Alethe |
| **Rotinas e automações** | Rotinas (`v0.7`): prompt agendado que abre um terminal; recupera o que perdeu com o Mac dormindo. **Automações (`v0.9.0`, núcleo; o resto na `0.9.x`):** o "n8n da MÊTIS", canvas visual de passos com ferramenta pela central de MCP, agente em terminal pelo plano, versões, teste com ensaio, aprovação e execuções; as rotinas viram automações de um gatilho e um agente. Especificação na seção 13 | 🟦 + 🟩 |
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
| Casca do app | Tauri (caminho A) | ✅ do zero, 2026-11-07 |
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

Cada fase entregue sobe o número do meio. Os itens marcados com ⭐ são o seu uso diário e vêm primeiro. Exceções combinadas com o Pedro em 2026-11-08: os Quadros entraram como `v0.9.1` (a paridade passou para a `v0.9.2` em diante); as Automações entraram como `v0.9.0` e a paridade restante, que era a `v0.9.0`, passou a ser a `v0.9.1`.

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
| `v0.9.0` | **Automações**, o "n8n da MÊTIS": canvas visual de passos, ferramenta pela central de MCP sem gastar cota, agente em terminal pelo plano, arquivo com rascunho e publicada, testar com ensaio, aprovação antes de falar com outras pessoas, histórico de execuções. Especificação na seção 13 | O briefing comercial da manhã (ou outra automação real do Pedro) roda pela MÊTIS por uma semana, com teste em ensaio, aprovação e histórico |
| `v0.9.1` | **Quadros:** quadro livre por projeto, `.canvas` do Obsidian na pasta do projeto no Brain, com notas do Brain, sessões vivas (estado, últimas mensagens e campo de mensagem), tarefas, links, notas suas, grupos e ligações; ligar uma nota a uma sessão manda a nota como contexto | Um projeto andando com o quadro aberto ao lado dos terminais |
| `v0.9.2` | **Paridade, sessões, agentes e avisos (blocos A e E):** agentes que sobrevivem a fechar o app, histórico e retomar, reiniciar e continuar, passar o trabalho entre Claude e Codex, modo de permissão e confiar na pasta, Mac acordado, Skills, avisos do macOS e sino, recursos, scripts da worktree, `metis` com `--json` | Fechar e reabrir a MÊTIS com agentes trabalhando, sem perder nenhum |
| `v0.9.3` | **Paridade, terminal e navegação (bloco B):** divisão da tela em árvore salva por worktree (dividir à direita e para baixo, arrastar a aba para a borda, divisórias), busca no terminal, comandos salvos, ⌘J, atalhos remapeáveis, busca nos Ajustes, tema do terminal importado do Ghostty | Um dia de trabalho com a tela dividida em três, trocando de worktree sem perder a divisão |
| `v0.9.4` | **Uso diário:** MÊTIS de uso instalada a partir de uma tag (`scripts/instalar.sh`, cópia por versão em `~/.harness/versoes`), atualização pelo app e por `metis atualizar`, MÊTIS de desenvolvimento com dados próprios (`~/.harness-dev`), arrastar cartão do kanban na janela, aviso do Codex pelo `notify`, código de saída do agente, `CHANGELOG.md` | A MÊTIS instalada no lugar do `tauri dev` no uso do dia a dia |
| `v0.9.5` | **Correção:** a MÊTIS instalada aberta pelo Finder ou pelo Launchpad adota o PATH do shell de login (antes não achava o `uv`, o `claude` nem o `codex`) | A MÊTIS aberta pelo Launchpad sobe o núcleo e abre o Claude |
| `v0.9.6` | **Paridade, bloco C:** git e GitHub (marcar por trecho, comparar com ref, conflitos, push/pull na tela, criar PR, issues e PRs no kanban, receitas de IA por ação) | Um PR aberto e juntado sem sair da MÊTIS |
| `v0.9.7` | **Paridade, bloco D:** editores (arquivos da worktree e notas do Brain com `[[links]]` e callouts), depois de decidir o editor | Uma nota do Brain e um arquivo de código editados na MÊTIS |
| `v0.9.8` | **O que o MAPA prometeu e ainda não saiu:** as sobras da régua do Orca (navegador pelo MCP e perfis, barra lateral com filtros, fixar e renomear, hibernação, CLI genérica, configuração por agente, painel de agentes) e os diferenciais da MÊTIS (o resto das Automações, roteamento por cota, `@nota` e `/comando` na barra, rótulos e subtarefas no kanban, mais conectores e o catálogo de MCP, checks e revisão de PR por IA, graphify por MCP, Estudo completo, tema por prompt, perfis e backup, Skills) | A checklist da 1.0 está toda marcada |
| `v0.9.9` | **Correções e detalhes do Pedro:** os bugs achados no uso e os ajustes que ele passar, junto da revisão das telas | O apanhado do Pedro está todo resolvido |
| **`v1.0.0`** | **Substituiu o Orca** | Uma semana sem abrir o Orca nem o Maestri |
| depois | Celular, SSH e remoto, tela de chat, catálogo de plugins, outros provedores | Quando fizer falta |

**Ideias na fila (sem versão ainda, provavelmente depois da 1.0):**

- **Tokens gastos por projeto** (ideia do Pedro, 2026-11-08): estimativa do total de tokens que cada projeto já consumiu, somando as sessões do Claude e do Codex do projeto e de todas as worktrees dele. Fonte provável: o `usage` de cada resposta nos transcripts, que a MÊTIS já lê para a janela de contexto (`transcript.py`). Mostrar entrada, saída e cache separados, porque a leitura de cache domina a soma.
- **Terminal próprio com conteúdo rico** (ideia do Pedro, 2026-11-08): a conversa com o Claude Code e com o Codex mostra imagens, fluxogramas, diagramas e afins direto no chat, como o app do Codex faz, valendo para as duas CLIs. É a versão mais completa da "tela de chat" da linha "depois", que foi deixada de lado na `v0.7.2`. Caminho provável, sem mudar o jeito de rodar a CLI: o terminal interativo continua por baixo (pelo plano, com a barra de baixo como entrada) e a tela desenha a conversa a partir do transcript, que a MÊTIS já lê (Claude em `~/.claude/projects`, Codex nas sessões dele), trocando blocos `mermaid`, imagens e arquivos gerados pela versão desenhada.

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

> **`v0.6.0` (2026-11-08):** conectores e avisos. Central de MCP no núcleo (`POST /mcp`, JSON-RPC escrito à mão, um token por terminal) entregue a todo Claude e Codex; ferramentas do Brain, do kanban, `lembrete` e das contas conectadas, com aprovação de escrita e Atividade. Galeria com Slack (bot da MÊTIS por workspace, token colado pelo Pedro, pessoal e Seller Pro) e ClickUp (MCP oficial, OAuth com registro dinâmico e PKCE feito pela MÊTIS, pessoal e Seller Pro); tokens no Keychain. `metis lembrete` agenda a mensagem do bot na DM do Slack. Conectores por agente no editor. Ficou para a 0.6.x: tela de Skills, "Adicionar MCP" genérico, Notion, GitHub e Google.

> **`v0.7.0` (2026-11-08):** rotinas e Hoje, a primeira parte do OS pessoal, escolha do Pedro para chegar logo ao "a rotina da Aurora roda pela MÊTIS". Rotina = agente aberto num terminal na hora marcada com o pedido como primeira mensagem (interativo, pelo plano), aviso no Slack e janela de recuperação para o Mac dormindo. Tela Hoje com as rotinas do dia, tarefas em andamento, aprovações e lembrete; editor de rotinas. Aurora (seg a sáb, 20h50) e Alexandria (sexta, 22h10, trazida do Maestri) já cadastradas. Ficou para a 0.7.x: captura rápida, concierge, criar agente por descrição, sprites animadas por estado e Estudo com Pomodoro.

> **`v0.7.1` (2026-11-08):** o resto do OS pessoal da v0.7. Captura rápida no ⌥Espaço (plugin de atalho global do Tauri e uma janela pequena por cima de tudo): lembrete, tarefa e anotação na hora, o resto para o Hermes, concierge novo. Agente por descrição (`claude -p` rascunha, o Pedro revisa) com "Testar sem salvar" e o campo "Qual dor resolve?". Sprites animadas por estado. Estudo com Pomodoro, placar das regras da Aurora e uma linha por bloco na nota do dia. Escolhas do Pedro: ⌥Espaço, ações diretas mais concierge, nome Hermes, minutos na MÊTIS e na nota do dia.

> **`v0.7.2` (2026-11-08):** a barra de baixo vira a única entrada dos agentes, pedido do Pedro. O Claude Code não deixa esconder a caixa de entrada dele, e a entrada por fluxo de mensagens só existe no modo sem tela; mantivemos o terminal interativo, só para ler: teclas e colagem vão para a barra, a caixa vazia do Claude é coberta (achada na tela: linha "❯" entre traços, com o resto apagado) e, com a barra vazia, ↑↓, Enter, Esc, ⇧Tab e ⌃C passam para o agente. A caixa do Codex ainda não é coberta. Uma tela de chat própria foi a alternativa descartada por enquanto.

> **`v0.8.0` (2026-11-08):** Brain vivo. Escolhas do Pedro: embeddings locais com o julgamento do modelo; sugestão a cada registro novo; MCP e início de sessão também fora da MÊTIS; aceitar a sugestão vira decisão no projeto pelo `brain.py`. Busca por significado com o [potion-multilingual-128M](https://huggingface.co/minishlab/potion-multilingual-128M) (model2vec, estático, numpy no Mac Intel, ~260 MB em float16). Medido no vault: carregado ocupa ~1,5 GB (630 MB são o tokenizador), então só o núcleo carrega, sob demanda, e solta após 20 min; o MCP de fora e o hook usam os vetores guardados no `brain.db` e pedem ao núcleo o vetor de texto livre. A régua é o z sobre a população de registros (o cosseno cru tem piso diferente por nota): precedentes do projeto com z >= 2,4, texto livre >= 2,0, decisões do mesmo projeto >= 1,8, candidato a sugestão >= 3,3 (cerca de 30% dos registros, uns 9 julgamentos por dia). Os três momentos: início de sessão (híbrido palavra + significado), antes de decidir (`brain_conflitos`, o próprio agente julga) e a cada registro novo (juiz Haiku sem ferramentas, teto de 25 por dia, primeira passada só marca o que já existe). Também: mini-mapa no canto do terminal e janela de contexto lida do transcript (aba Contexto). Testado: 120 testes; no vault real, conflito e hook em menos de 0,5 s; aceitar com o `brain.py` de verdade numa cópia do vault. Fica para depois: julgar sugestões com a cota do Codex, a janela de contexto do Codex, e contexto no início de sessão do Codex fora da MÊTIS (o Codex não tem hook).

> **`v0.9.0` (2026-11-08):** Automações, o núcleo da seção 13, escolha do Pedro: fatia "núcleo na 0.9.0, resto na 0.9.x", e as automações reais ele monta conforme precisar. Arquivo YAML com rascunho e publicada (git local, versões = commits da publicada), canvas do protótipo ligado ao núcleo, gatilhos manual, `metis rodar` e agendado (regra de recuperação das rotinas), passos Ferramenta (central de MCP, sem cota, aprovação de quem fala com outras pessoas), Agente (terminal interativo com MCP só das ferramentas liberadas e a ferramenta `saida`, conferida contra o formato, até 2 correções, pedido de novo no terminal pelo hook Stop), Condição (regra de uma linha, sem `eval`), Aprovação, Brain e Esperar; testar com ensaio; execuções com entrada e saída de cada passo; Pedir conserto e Reexecutar daqui. Ficam para a `0.9.x`: Código, criar por frase, gatilhos por evento e sondagem, troca de provedor por cota e rotinas virando automações.

> **`v0.9.1` (2026-11-08):** Quadros, pedido do Pedro antes da paridade ("sairia na 0.9 também"); a paridade passou para a `v0.9.2`. Escolhas do Pedro: o quadro mora no vault como `.canvas` do Obsidian (JSON Canvas 1.0) em `01-PROJETOS/<Projeto>/quadros/`, abre no Obsidian também; o cartão de sessão é leve (estado, últimas mensagens pelo transcript ou o fim do terminal, campo de mensagem, abrir o terminal); ligar uma nota do Brain a uma sessão manda à sessão o pedido de ler a nota (vira contexto e entra no mini-mapa). Cartões da MÊTIS (sessão, tarefa) são nós de texto com `%%metis {...}%%` no fim, que o Obsidian esconde e guarda; salvar recusa se o Obsidian salvou depois (a tela recarrega).

> **`v0.9.8` (em andamento, 2026-11-08):** tudo o que o MAPA prometeu e não saiu, sem corte, em cinco partes, cada uma com o próprio PR na main e a tag `v0.9.8` no fim: (1) agentes e terminal: argumentos, variáveis e outra CLI por agente, hibernação, copiar ID e contexto, OSC 52, temas do Warp e do Kitty, `@nota` e `/comando` na barra, `metis worktree nova` e `metis agente`, skill da MÊTIS; (2) navegador e tela: navegador pelo MCP com o cursor do agente, perfis, emulação, ⌘K com endereços e histórico, barra lateral (filtros, fixar, renomear, cores), worktree a partir de branch ou commit, fontes, densidade e zoom, tema por prompt, importar tema do Obsidian e do VS Code; (3) conectores e kanban: MCP próprio, catálogo, testar conexão, copiar MCP entre Claude e Codex, Notion, GitHub e Google, ClickUp no kanban, rótulos e subtarefas, painel de agentes, Atividade dos agentes, cota no Hoje; (4) automações: passo Código, criar por frase, gatilhos por evento e sondagem, troca por cota (e sugestão nos terminais), rotinas como automações, importar do n8n, orquestração em canvas; (5) código e estudo: checks falhos ao agente, revisão de PR por IA, graphify por MCP, Estudo completo, perfis e backup, instalar e compartilhar Skills.

> **`v0.9.7` (2026-11-08):** paridade com o Orca, bloco D (editores), escolha do Pedro: os dois editores, dentro da MÊTIS ("se abrir fora não faz sentido"). **Monaco** (`monaco-editor` 0.57, empacotado com os workers pelo Vite, carregado só ao abrir um arquivo) nos arquivos da worktree, no lugar do texto só para ler; tema tirado dos tokens CSS; sem validação semântica do TypeScript (o projeto inteiro não é carregado). **CodeMirror 6** nas notas do Brain, com visualização ao vivo própria (`app/src/lib/noteEditor.ts`): marcas escondidas fora da linha do cursor pela árvore do Lezer, `[[links]]` por expressão (com a checagem de nota existente pelo `/brain/known`), callouts do Obsidian, frontmatter como caixa de propriedades (decoração de bloco num StateField), tarefas com caixinha, `[[` pelo `/brain/titulos` e `/` com blocos. **Gravar** só com o hash de quando abriu (`PUT /fs/text`, `PUT /brain/note/texto`, 409 com o hash atual); a nota recusa texto vazio (o Brain nunca apaga) e reindexa ao gravar. O editor de arquivo recarrega quando o agente muda o arquivo sem edição pendente e mostra o diff lado a lado quando há. Com o foco num editor, ⌘D, ⌘F, ⌘L e ⌘⌥ e as setas são do editor. Fora: criar arquivo ou nota pelo editor, LSP (ir para a definição entre arquivos) e merge em 3 vias com edição dos três lados (o arquivo em conflito abre no Monaco, com os marcadores).

> **`v0.9.8` parte 1 (2026-11-08): agentes e terminal.** **Agente:** `args` (sintaxe de shell, `shlex`) e `env` (`CHAVE=valor` por linha, sem mexer no `PATH` nem nas variáveis da MÊTIS) no `.md` do agente; `cli: outra` com `command` vira uma sessão `shell` que roda o comando, sem a central de MCP, sem modelo, conta nem papel. Sessão nova aceita modelo, esforço e pedido (o `metis agente` usa). **Hibernar:** a cada 30 s o núcleo para com `SIGSTOP` o Claude ou o Codex em "esperando" sem entrada nem saída há `hibernar_min` minutos (automações e rotinas fora); escrever ou focar o terminal manda `SIGCONT` (`/sessions/{id}/acordar`). **Contexto da sessão:** `/sessions/{id}/contexto` devolve o ID da conversa, o transcript e as últimas mensagens; o menu ⋯ copia. **OSC 52** pelo `ClipboardAddon` do xterm. **Temas** do Kitty (`.conf`) e do Warp (YAML) em `themes.py`, junto dos do Ghostty; o texto colado tem o formato descoberto sozinho. **Barra:** `@` busca títulos no índice do Brain e insere `[[Título]] (caminho)`; `/` lê os `.md` de `commands` do projeto e da conta, as skills (`description` do frontmatter, inclusive em bloco `>` e `|`) e uma lista fixa dos comandos de cada CLI. **Skill da MÊTIS** gravada em `<pasta da conta>/skills/metis/SKILL.md` de cada conta. Ficou para depois: o teclado do kitty, que o xterm só tem na 6.1 ainda em beta (com a barra de baixo como única entrada dos agentes, o ganho é pequeno; entra quando a 6.1 sair estável).

> **`v0.9.6` (2026-11-08):** paridade com o Orca, bloco C (Git e GitHub). **Marcar por trecho e por linha:** a tela monta um patch só com as linhas escolhidas (`app/src/lib/patch.ts`: linha não escolhida vira contexto do lado em que existe) e o núcleo aplica com `git apply --recount` no índice (marcar), no índice ao contrário (desmarcar) ou na árvore ao contrário (descartar). **Comparar com ref:** contra o merge-base da ref com o HEAD, contando o que não foi commitado; imagem com `/git/blob`. **Sincronizar:** sem upstream, `push -u`; com upstream, `pull --rebase --autostash` e push; forçar só com `--force-with-lease`. **Operação em andamento** pelo git-dir (MERGE_HEAD, rebase-merge…), continuar com `-c core.editor=true`; conflito bloco a bloco reescreve o arquivo e marca quando não sobra marcador. **GitHub pelo `gh` já logado** (sem token na MÊTIS), com cache de 60 s; juntar sem `--delete-branch` (numa worktree ele tentaria trocar de branch). **Receitas** em `~/.harness/ajustes.json` (commit, commit do marcado, PR com `{base}` e `{branch}`), seguindo a decisão de o commit por IA ser feito pelo agente da worktree; descartar não rastreado vai para a Lixeira. Ficaram de fora: merge em 3 vias com edição livre (vem com os editores, na `v0.9.7`), PRs empilhados, checks falhos de volta ao agente (`v0.9.8`).

> **`v0.9.5` (2026-11-08):** correção achada na primeira instalação de verdade: aberto pelo Finder, pelo Launchpad ou pelo Dock, o app recebe só o PATH mínimo do macOS (`launchctl getenv PATH` vazio) e não acharia o `uv` para subir o núcleo, nem o núcleo o `claude` e o `codex` (em `~/.local/bin`). Sem `TERM`, o app pergunta o PATH ao shell de login (`$SHELL -l -i -c`, entre marcas, até 5 s) e o adota antes de subir o núcleo. A sequência até a 1.0 andou uma casa e o Pedro a corrigiu no mesmo dia: bloco C (git e GitHub) na `v0.9.6`, D (editores) na `v0.9.7`, tudo o que o MAPA prometeu e não saiu (sobras da régua e diferenciais) na `v0.9.8`, e correções e detalhes dele na `v0.9.9`.

> **`v0.9.4` (2026-11-08):** uso diário, primeira versão da sequência até a 1.0 combinada com o Pedro (v0.9.4 uso diário, v0.9.5 bloco C, v0.9.6 bloco D, v0.9.7 sobras da régua, v0.9.8 diferenciais escolhidos). **MÊTIS de uso:** `scripts/instalar.sh [versão]` clona o repositório em `~/.harness/versoes/<tag>`, faz o checkout da tag, `uv sync`, `npm ci` e `tauri build` (alvo do Rust compartilhado em `~/.harness/build`), e põe o `MÊTIS.app` em `/Applications`; o app empacotado roda o núcleo da cópia dele (o caminho vem do `CARGO_MANIFEST_DIR` da compilação), então o núcleo em uso nunca troca de arquivo. A instalada procura tag nova no repositório a cada 6 horas (`/sistema/versao`) e avisa no sino; Ajustes → Sobre e `metis atualizar` rodam o `instalar.sh` da versão nova num terminal. **MÊTIS de desenvolvimento:** `scripts/dev.sh` com `HARNESS_HOME=~/.harness-dev`, porta 47840, identificador `dev.pedroaquino.metis.dev` e sem o ⌥Espaço (`METIS_DEV=1`). **Codex:** a sessão recebe `-c notify=[relay, "codex", <notify que já estava no config.toml>]`; o relay avisa o núcleo (`agent-turn-complete` = `Stop`) e chama o `notify` anterior; Enter num Codex parado vira "trabalhando". **Kanban:** arrasto com o ponteiro, capturado já no clique. **Código de saída** no evento `session.status`. **Terminal ao recarregar:** o núcleo devolve o histórico inteiro (até 2 MB); quando a largura muda, as linhas do `%` do zsh (`PROMPT_SP`) sobram como linhas em branco, e o sumiço da saída visto num teste não se reproduziu.

> **`v0.9.3` (2026-11-08):** paridade com o Orca, bloco B (terminal e navegação). **Divisão em árvore por worktree:** cada worktree (e "fora dos projetos") guarda a própria divisão, salva entre aberturas; escolher uma worktree na barra lateral, ou uma aba dela, mostra a divisão de lá, e as abas das outras ficam em cinza. Dividir à direita (⌘D) e para baixo (⌘⇧D), quantas vezes quiser; arrastar uma aba para a borda de um painel divide ali, e para o meio troca; divisórias arrastáveis (dois cliques voltam ao meio); ⌘⇧W tira o painel; ⌘⌥ e as setas andam entre painéis; aba fechada some da divisão e o vizinho cresce. O arrasto é feito com o ponteiro, porque o arrastar do HTML não chega na janela do Tauri. **Busca no terminal** (⌘F, com o addon de busca do xterm): maiúsculas, regex e contagem, também no histórico de rolagem. **Comandos salvos** em `~/.harness/comandos.json`, globais ou de um projeto: comando roda no shell em foco (ou no mais recente da worktree, ou num novo); prompt vai para a barra de entrada; rodam por ⌘⇧K ou ⌘K. **⌘J (pular para):** abas pelas mais recentes, worktrees e telas. **Atalhos remapeáveis** em Ajustes → Atalhos e em `~/.harness/atalhos.json` (só o que mudou), pela tecla física (`KeyboardEvent.code`), com aviso de conflito e dos atalhos do macOS. **Busca nos Ajustes** (⌘, já abre com o foco nela), com termos em inglês e espanhol, que abre a seção e acende a linha. **Tema do terminal** do Ghostty: os temas do Ghostty.app, da pasta do usuário e do config, colar um tema, e o Ghostty Default Style Dark (o do Orca do Pedro) vem junto, porque o Ghostty não está instalado. Ficaram de fora: o tema do Warp e do Kitty, e copiar o contexto e o ID da sessão.

> **`v0.9.2` (2026-11-08):** paridade com o Orca, blocos A (sessões e agentes) e E (avisos e sistema), escolha do Pedro: um bloco por versão, A+E primeiro. O núcleo passou a rodar por conta própria: a janela sobe o núcleo fora do grupo de processos dela (`process_group(0)`, saída em `~/.harness/nucleo.log`) e, ao abrir, se liga ao que já está no ar pelo `runtime.json`; fechar, recarregar ou recompilar a janela não fecha mais os terminais, e as rotinas e automações seguem com a janela fechada. Versão do núcleo diferente da do app: a tela oferece reiniciar o núcleo (fecha os terminais). Desligar de vez: Ajustes ou `metis desligar`. Também: histórico das conversas do Claude e do Codex de todas as contas, com busca e retomar (`claude --resume`, `codex resume`); reiniciar e continuar o agente que saiu; passar o trabalho entre Claude e Codex com o transcript; modo de permissão por CLI (padrão, manual, auto, yolo) e pastas dos projetos e worktrees como confiáveis; Mac acordado com `caffeinate`; avisos do macOS e sino com não lidos; recursos por sessão; Skills; scripts de setup e arquivamento por projeto; `metis sessoes`, `metis sessao ler|escrever` e `--json`. Os avisos do agente seguem o nome do hook do Claude Code (`Stop` = terminou, `Notification` = espera você), porque pela troca de estado toda resposta pronta virava "espera você"; o Codex, sem hooks, fica sem aviso por enquanto. Reiniciar um agente que saiu tira a sessão antiga da lista, e a nova nasce com o mesmo nome e no mesmo lugar da tela.

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

## 13. Automações (`v0.9.0`)

> **Decidido em 2026-11-08.** O Pedro avaliou o protótipo e aprovou: entra na `v0.9.0`, e a paridade restante passa para a `v0.9.1`. Decisão no Brain: `[[MÊTIS ganha automações visuais próprias para o uso pessoal e o n8n fica com a produção 24 h]]`.

**O que é.** Um "n8n" dentro da MÊTIS: um canvas de passos ligados em que **ferramenta é determinística e não gasta cota**, **agente é um terminal de verdade do Claude ou do Codex pelo plano**, e tudo mora num **arquivo versionado**, com rascunho e publicada sempre explícitos. Escopo: automações pessoais e afins, só com o Mac acordado, com acesso a tudo do Brain e dos repositórios dos outros projetos. Não substitui o n8n da empresa, que continua com a produção 24 h com webhook (Manu 2.0, funil de leads, Guru e Hotmart); se precisar, a ponte é a ferramenta do MCP do n8n e o Slack.

**Por que não só o n8n.** As dores já registradas no Brain: sub-fluxo que só roda publicado e devolve o erro calado ao AI Agent (Manu 2.0), edição de workflow ativo que publica na hora (Base de Leads), API que não enxerga pastas, IA como nó avulso pago por API e teste que manda de verdade.

### 13.1 Protótipo de referência

- Branch `ideia/automacoes`, worktree `~/orca/workspaces/personal-harness/ideia-automacoes`. Tela só de frente, com dados de exemplo na memória: `app/src/components/AutomationsView.tsx` e `app/src/components/automations.css`. A ligação no app é a View `automations`, o ícone `flow` em `icons.tsx` e o item "Automações" na faixa (`Chrome.tsx`). A proposta completa está em `docs/AUTOMACOES.md` do mesmo branch.
- O branch saiu da `v0.5.1` (commit `6dc428f`). **Não junte o branch:** leve a tela e o CSS para a versão atual e ligue no núcleo de verdade. O protótipo é a referência do visual e das interações, não do código final.
- Para ver: `cd ~/orca/workspaces/personal-harness/ideia-automacoes/app && npx vite --port 1430 --host 127.0.0.1` e abrir `http://127.0.0.1:1430`. Use `127.0.0.1`: os cookies de `localhost` no Chrome do Pedro passam do limite do Vite (erro 431).

### 13.2 Visual aprovado

A gramática de editor de nós do n8n com a identidade da MÊTIS. Só tokens do tema; vale nos três temas.

| Elemento | Como é |
|---|---|
| Canvas | Fundo `--term` com grade de pontinhos que anda e escala junto com o canvas; arrastar move, ⌘ + rolar dá zoom, botão de enquadrar |
| Passo comum | Bloco quadrado de 84 px, cantos arredondados, ícone grande no centro e uma faixa na cor do tipo na base. Nome e ferramenta embaixo, fora do bloco |
| Gatilho | Lado esquerdo arredondado, com selo de raio na cor `--wait` e sem entrada |
| Condição | Bloco com o lado direito arredondado e duas saídas, `sim` (linha cheia e verde) e `não` (tracejada) |
| Agente | Bloco largo de 240 px com a sprite greco-romana do agente da galeria (ou ✻ do Claude, ◇ do Codex), o nome e o custo médio. Embaixo, três peças penduradas por losangos: **Modelo** (anel tracejado quando há troca por cota), **Ferramentas** liberadas e **Saída** combinada |
| Conectores | "Elementos" de duas letras na cor do conector, como numa tabela periódica (Sl, Cu, Pd, Sb, Gh, Br, n8); a MÊTIS usa a própria marca. Sem logo de marca de terceiros |
| Ligações | Curvas com seta. Saída livre ganha um "+" na ponta. Ao passar o mouse na ligação, "+" (pôr um passo no meio) e lixeira. Depois de rodar, ficam verdes com a contagem de itens ("6 itens") |
| Estados | Selo no canto: girando (rodando), ✓ verde (ok), ! vermelho (erro), ‖ roxo pulsando (esperando você). O contorno muda de cor junto. Pulado fica apagado; desligado ganha um risco diagonal |
| Ao passar o mouse no passo | Testar só ele, desligar (os dados passam direto) e tirar. Delete tira o passo escolhido; Esc fecha o que estiver por cima |
| Notas no canvas | Callout do Obsidian, arrastáveis |
| Cores por tipo | Gatilho `--wait`, ferramenta `--run`, agente Claude `#d97757`, condição `--acct`, aprovação `--warn`, Brain `--g-brain`, código `--mut`. Verde de sucesso = `--g-brain` |
| Tela | Lista de automações à esquerda (ícones dos conectores usados, estado, última execução); barra com nome, estado e versão, abas **Editor** e **Execuções** no centro, Detalhes, Publicar e o interruptor Ativa (só depois de publicar); "Testar automação" e "Pedir ao Claude" embaixo do canvas; "+" e nota no canto de cima |
| Painel do passo | Dois cliques abrem **Entrada \| Parâmetros (e Ajustes) \| Saída**, com Tabela ou JSON, fixar dados e "Testar passo"; expressões `{{…}}` aparecem como peças verdes |
| Gaveta de passos | "O que acontece depois?" (ou "Quando ela começa?") com busca: gatilhos, agentes da galeria com a sprite, conectores com as ferramentas de cada um (cadeado em quem fala com outras pessoas), lógica e dados |
| Execuções | Lista à esquerda; o canvas mostra aquela execução, com "Copiar para o editor" |

### 13.3 Como funciona

| Peça | Regra |
|---|---|
| Arquivo | Cada automação é um YAML em `~/.harness/automacoes/<id>.yaml`, com histórico num git local. Guarda gatilho, passos (tipo, título, parâmetros, posição no canvas), ligações (com ramo `sim` ou `não`), notas e estado |
| Versões | O motor só roda a **publicada**. Editar, pela tela ou por um agente, só mexe no rascunho. Publicar grava a versão; voltar é publicar uma versão antiga, sempre por ação do Pedro. Detalhes mostra a diferença entre rascunho e publicada |
| Motor | No núcleo Python, junto do agendador das rotinas da `v0.7`: fila, camadas pelo caminho mais longo a partir do gatilho (o que está na mesma camada roda junto), ramos, execuções no SQLite com entrada, saída, tempo e cota de cada passo |
| Gatilhos | Agendado (com a regra de recuperação das rotinas para o Mac dormindo), evento da MÊTIS (nota nova no Brain, tarefa mudou de coluna, agente terminou ou errou, worktree criada), novidade num conector por sondagem, captura rápida e `metis rodar <automação>`. Sem webhook (princípio 3) |
| Ferramenta | Chamada direta à central de MCP da `v0.6.0`, sem agente e sem cota, com as permissões e o log da Atividade. Cada conta ligada em Conectores vira passo sem configurar |
| Agente | Terminal interativo do `claude` ou do `codex`, como as rotinas, numa aba do grupo Automações (em segundo plano ou visível), com MCP só com as ferramentas liberadas no passo. O pedido sai montado com as expressões. A resposta volta pela ferramenta `metis saida` da central de MCP e é conferida contra o formato combinado; se faltar campo, a MÊTIS pede de novo no mesmo terminal, até 2 vezes, e depois marca erro |
| Cota | Cada passo de agente grava tokens e quanto da janela de 5 h gastou. Acima de 80%, roda no outro provedor no mesmo nível, e a troca aparece na execução |
| Código | Python ou JavaScript local, escrito pelo Claude a partir da descrição e guardado no YAML |
| Condição | Regra de uma linha, ou pergunta de sim ou não a um agente barato |
| Aprovação | A mesma da central de MCP (notificação do macOS e DM no Slack). Entra sozinha antes de toda ferramenta marcada como "fala com outras pessoas"; tirar exige ação explícita do Pedro |
| Expressões | `{{Nome do passo.campo}}` |
| Testar | Roda o rascunho inteiro, inclusive as sub-automações (nada de "só roda publicado"). Passo que fala com outras pessoas vira **ensaio**: o envio vai para a DM do Pedro. Dados fixados num passo substituem a chamada ao conector |
| Erros | Nunca calados: execução vermelha, aviso no Mac e no Slack, **Pedir conserto** (abre um Claude com o YAML e o log; a correção vai para o rascunho) e **Reexecutar daqui** (com as entradas guardadas, sem rodar de novo o que veio antes) |
| Criar por frase | Um Claude rascunha o YAML a partir do catálogo de passos (como o agente por descrição da `v0.7.1`); a tela mostra a proposta tracejada e só aplica ao rascunho com o Pedro |
| Rotinas | As rotinas da `v0.7` passam a ser automações de um gatilho e um agente, sem perder a recuperação nem o aviso |

### 13.4 Fora da `v0.9.0`

- Importar do n8n (ler o workflow pelo MCP do n8n e traduzir nó a nó; webhook e HTTP solto ficam marcados para revisar): proposta para a `v0.9.2`, depois do motor provado.
- Orquestração de agentes no canvas (explorar e construir, melhor de N, portão de revisão): `v0.9.2`, no mesmo canvas e motor.
- **Rodar com o Mac desligado (nuvem da Anthropic ou VPS): fora.** Decidido pelo Pedro em 2026-11-08: as Automações são só pessoais e só rodam com o Mac acordado, com acesso a tudo do Brain e dos outros projetos; o n8n da empresa continua onde está. O que a nuvem da Anthropic e uma VPS exigiriam ficou registrado no Brain (`[[Tarefas agendadas na nuvem do Claude Code gastam o plano mas não enxergam o Mac]]`), para o caso de isso mudar.
- Webhook e fluxos de produção 24 h: ficam no n8n.
