# Mudanças da MÊTIS

Cada versão, da mais nova para a mais velha. O detalhe de cada uma está no [`README.md`](README.md), o plano em [`docs/MAPA.md`](docs/MAPA.md) e o porquê das decisões no Brain, em `01-PROJETOS/Personal Harness/`. Versões no formato `MAIOR.MENOR.CORREÇÃO`, uma tag `v*` por versão.

## v0.9.8 · o que o MAPA prometeu (em andamento, em cinco partes)

### Parte 1 · agentes e terminal

- **Agente com argumentos e variáveis próprios** (tela de Agentes): argumentos extras no fim da linha de comando e variáveis de ambiente só daquele agente, no Claude e no Codex.
- **Outra CLI:** um agente pode ser qualquer programa de terminal (opencode, aider, um script), com o comando, os argumentos e as variáveis dele. Roda num terminal comum, sem a central de MCP.
- **Hibernar agente parado** (Ajustes → Agentes e avisos: nunca, 15, 30 ou 60 min): o Claude ou o Codex que espera você há esse tempo fica pausado e para de gastar memória e CPU; acorda quando você foca o terminal ou escreve para ele. Automações e rotinas não hibernam.
- **Menu ⋯ do terminal:** copiar o ID da conversa, o caminho do transcript, as últimas mensagens ou a pasta.
- **Programas no terminal copiam para o Mac** (OSC 52: o `y` do vim e do tmux por SSH vão para a área de transferência).
- **Temas do terminal do Kitty e do Warp**, além dos do Ghostty; "Colar um tema" descobre o formato sozinho.
- **Barra de baixo:** `@` sugere notas do Brain e insere o título e o caminho; `/` num Claude ou num Codex lista os comandos do projeto, os seus, as skills e os da CLI, com a descrição.
- **`metis worktree nova <projeto> <nome>`** e **`metis agente <claude|codex|agente> [pedido]`**: um agente abre outra worktree ou outro agente pelo terminal.
- **Skill da MÊTIS** (Ajustes → Skills): ensina o Claude e o Codex a usar o comando `metis` e a central de MCP; "Instalar no Claude e no Codex" grava nas pastas de cada conta.

## v0.9.7 · editores dentro da MÊTIS (paridade com o Orca, bloco D)

- **Editor de código (Monaco, o do VS Code)** nos arquivos da worktree: abrir um arquivo (⌘P, Arquivos, "Abrir arquivo") já é editar. ⌘S salva, ou "Salvar sozinho". Só grava se o arquivo não mudou no disco desde que abriu: sem edição pendente, a aba recarrega sozinha quando o agente mexe no arquivo; com edição pendente, aparece o aviso com as duas versões lado a lado (ficar com a do disco ou gravar a sua por cima). Markdown, CSV e HTML mantêm a prévia em "Visualizar".
- **Editor de notas do Brain (CodeMirror, o motor do Obsidian)**: "Editar" no leitor de notas, ou "Abrir ao lado" numa aba junto dos terminais. Visualização ao vivo (a marcação some fora da linha do cursor), `[[links]]` clicáveis (os de nota que não existe ficam tracejados), callouts coloridos, frontmatter como caixa de propriedades, tarefas com caixinha clicável, `[[` sugere títulos do vault e `/` insere blocos. Salva sozinho e nunca grava por cima do que o Obsidian salvou depois.
- Com o foco num editor, ⌘D, ⌘F, ⌘L e ⌘⌥ e as setas são do editor. Fechar uma aba com mudança não salva avisa antes.

## v0.9.6 · Git e GitHub (paridade com o Orca, bloco C)

- **Marcar por trecho e por linha.** No diff, em "Não marcado": marcar ou descartar um trecho, ou escolher linhas (clique no número; ⇧ + clique escolhe um intervalo). Em "Marcado": desmarcar trecho ou linhas. Descartar pede confirmação.
- **Comparar com qualquer ref:** no diff (modo Comparar) e no painel ("Comparar com outro branch"), o que mudou desde que o branch saiu de um branch, tag ou commit, contando o que não foi commitado. Imagem mostra antes e agora lado a lado.
- **Botão de subir que muda com o estado:** publicar branch, subir, puxar ou sincronizar (pull com rebase e push); buscar o remoto; forçar com `--force-with-lease` quando a subida é recusada.
- **Commit:** corrigir o último commit (amend, com aviso se já subiu); a saída do pre-commit fica à vista, com "Consertar com o agente".
- **Merge, rebase, cherry-pick e revert em andamento:** faixa com continuar, abortar e "Resolver com o agente"; conflito bloco a bloco (o nosso, o deles, os dois ou a base), ou o arquivo inteiro de um lado.
- **GitHub pelo `gh`:** cartão do PR do branch (checks, revisão, conflito), abrir PR por formulário ou pelo agente, sair do rascunho e juntar (rebase, squash ou merge); issues e PRs abertos na coluna GitHub das tarefas do kanban, com "Executar com agente" numa worktree nova.
- **Ajustes → Git:** receitas do commit e do PR, qual agente abre, assinar os commits e o editor externo ("Abrir no editor" no painel).
- Descartar arquivo não rastreado manda para a Lixeira.

## v0.9.5 · correção

- **A MÊTIS instalada abre pelo Finder, pelo Launchpad e pelo Dock.** Aberto fora de um terminal, o app recebia só o PATH mínimo do macOS (`/usr/bin:/bin:/usr/sbin:/sbin`) e não achava o `uv` para subir o núcleo, nem o núcleo achava o `claude` e o `codex`. Agora o app pergunta o PATH ao shell de login ao abrir sem terminal (até 5 s; se não responder, segue com o que veio).

## v0.9.4 · uso diário

- **MÊTIS de uso instalada.** `scripts/instalar.sh [versão]` monta uma cópia da versão marcada em `~/.harness/versoes/<versão>`, com o núcleo dela, e põe o `MÊTIS.app` em `/Applications`. Os dados seguem em `~/.harness`.
- **Atualizar.** A MÊTIS instalada procura versão nova no repositório a cada 6 horas e avisa no sino. Ajustes → Sobre mostra a versão e atualiza num terminal à vista; `metis versao` e `metis atualizar` fazem o mesmo pelo terminal. O núcleo em uso só passa para a versão nova quando é reiniciado.
- **MÊTIS de desenvolvimento separada.** `scripts/dev.sh` usa `~/.harness-dev` e a porta 47840, com outro identificador: não divide o núcleo, os terminais nem as rotinas com a de uso, e deixa o ⌥Espaço para ela.
- **Kanban:** arrastar cartão funciona na janela do app (arrasto com o ponteiro).
- **Codex avisa** quando termina o turno, pelo `notify` dele, sem desligar o `notify` que já estava no `config.toml`. Enter num Codex parado marca "trabalhando". O passo de agente das Automações no Codex também é cobrado quando termina sem devolver a saída.
- **Agente que saiu** mostra o código de saída na faixa de reiniciar.
- Este `CHANGELOG.md`.

## v0.9.3 · terminal e navegação (paridade com o Orca, bloco B)

- Divisão da tela em árvore, salva por worktree: dividir à direita (⌘D) e para baixo (⌘⇧D), arrastar a aba para a borda de um painel, divisórias arrastáveis, ⌘⇧W tira o painel, ⌘⌥ e as setas andam entre painéis.
- Busca no terminal (⌘F), com maiúsculas, regex e contagem.
- Comandos salvos (⌘⇧K), globais ou de um projeto.
- ⌘J: abas pelas mais recentes, worktrees e telas.
- Atalhos remapeáveis (Ajustes → Atalhos e `~/.harness/atalhos.json`).
- Busca nos Ajustes, também em inglês e espanhol.
- Tema do terminal importado do Ghostty, com o Ghostty Default Style Dark embutido.

## v0.9.2 · sessões, agentes e avisos (paridade com o Orca, blocos A e E)

- O núcleo roda por conta própria: fechar, recarregar ou recompilar a janela não fecha os terminais.
- Histórico das conversas do Claude e do Codex com retomar; reiniciar e continuar o agente que saiu; passar o trabalho entre Claude e Codex.
- Modo de permissão por CLI, pastas dos projetos como confiáveis, Mac acordado.
- Avisos do macOS e sino com não lidos; Recursos; Skills; scripts de setup e arquivamento por projeto; `metis sessoes`, `metis sessao` e `--json`.
- Correção: Reiniciar o núcleo não deixa mais a MÊTIS sem núcleo (porta em TIME_WAIT).

## v0.9.1 · Quadros

- Quadro livre por projeto, um `.canvas` do Obsidian na pasta do projeto no Brain, com notas, sessões vivas, tarefas, links, notas suas, grupos e ligações. Nota solta numa sessão vira contexto.

## v0.9.0 · Automações

- O "n8n da MÊTIS": canvas de passos (Ferramenta, Agente, Condição, Aprovação, Brain, Esperar), YAML com rascunho e publicada num git local, testar em ensaio, execuções, Pedir conserto e Reexecutar daqui; gatilhos manual, `metis rodar` e agendado.

## v0.8.0 · Brain vivo

- Busca por significado local (potion-multilingual-128M), `brain_conflitos` antes de decidir, sugestões de precedente entre projetos julgadas pelo Haiku, MCP `metis-brain` e hook de início de sessão também fora da MÊTIS, mini-mapa e janela de contexto.

## v0.7.2

- A barra de baixo é a única entrada dos terminais do Claude e do Codex; o terminal fica só para ler.

## v0.7.1 · OS pessoal

- Captura rápida no ⌥Espaço, Hermes (concierge), agente por descrição, sprites animadas por estado, Estudo com Pomodoro na nota do dia.

## v0.7.0 · rotinas e Hoje

- Rotinas que abrem um agente na hora marcada, com janela de recuperação para o Mac dormindo; tela Hoje.

## v0.6.0 · conectores e avisos

- Central de MCP em todo Claude e Codex, Slack (bot por workspace) e ClickUp (OAuth), `metis lembrete`, aprovação de escrita num cartão, Atividade.

## v0.5.1

- Grafo do Brain com uma nuvem por área, forças vivas e nomes no hover.

## v0.5.0 · Brain e kanban

- Busca no Brain, leitor de notas, kanban de projetos (estágio na nota) e de tarefas (Próximas ações), Executar com agente, precedentes v1, `metis brain` e `metis tarefa`.

## v0.4.2

- Correção: a página do navegador embutido não fica mais presa fora do lugar.

## v0.4.1

- Botão do navegador na barra lateral e `metis web`.

## v0.4.0 · navegador embutido

- Navegador por worktree (WebKit do macOS) com modo de design; sprites dos agentes por prompt ao Codex.

## v0.3.0 · código

- Projetos e worktrees, painel da worktree (mudanças, arquivos, portas), revisão do diff com notas, commit pelo agente, visualizadores, agentes em arquivo. O app passa a se chamar MÊTIS.

## v0.2.0 · núcleo do dia a dia

- Codex, várias contas por pasta, abas, tela dividida, terminal flutuante, ⌘K, barra de entrada com ditado (Whisper local) e anexos, Ajustes.

## v0.1.0 · fatia vertical

- Moldura do app (Tauri + React + núcleo Python), o Claude Code real num terminal, contexto e cota na barra de status.
