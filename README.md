# MÊTIS

**Inteligência em ação.** O ambiente pessoal onde agentes, projetos e memória trabalham juntos. Antes se chamava Personal Harness; a marca (símbolo, logotipo, cor e voz) está em [`docs/marca/`](docs/marca/) e na seção Marca de [`docs/DESIGN.md`](docs/DESIGN.md).

OS pessoal e ADE no Mac: os agentes (Claude Code, Codex) rodam em terminais de verdade, com o Brain como memória. O plano completo está em [`docs/MAPA.md`](docs/MAPA.md), o visual em [`docs/DESIGN.md`](docs/DESIGN.md) e a régua do Orca em [`docs/PARIDADE-ORCA.md`](docs/PARIDADE-ORCA.md).

## O que já faz (v0.9.9)

**Na 0.9.9, as telas dos mockups e o apanhado do Pedro:**

- **Sala dos agentes** (ícone de pessoas): a casa de trabalho dos agentes, o escritório animado de dia e de noite, com cada agente na sua mesa, o movimento parado da sprite (respira e pisca) e o balão quando ele trabalha ou espera você. Arraste para qualquer lugar; solto perto de uma mesa, ele senta. Apagar um agente pela lista ou pelo painel.
- **Sprites no modelo da MÊTIS:** quem desenha é sempre o GPT (a ferramenta de imagem do Codex, pelo seu plano), no modelo de referência e com as características que você pedir, em 4 quadros de movimento parado.
- **Kanban com a coluna Auto:** Pendente, Auto, Em andamento, Em teste e Concluído, com as tarefas de todos os projetos. Solte uma tarefa em Auto e ela roda sozinha num agente (numa worktree nova ou na pasta do projeto) e para em Em teste para você revisar.
- **Telas no desenho dos mockups:** Hoje, Brain (árvore do vault, abas e o grafo de sempre), Estudo (as perguntas do Sócrates como formulário), Terminais (barra de entrada em cada agente) e Conectores (cada ferramenta livre, pedindo aprovação ou desligada).
- **Avisos do macOS com o ícone da MÊTIS**, pela Central de Notificações; clicar no aviso abre a sessão, a aprovação ou a automação.
- **Uso dos modelos:** tokens e custo equivalente em API por modelo, por dia e por projeto (Ajustes → Contas e uso). Clicar no uso da barra de baixo abre as barras do plano de cada conta.
- **Projetos e workspaces no jeito do Orca:** Adicionar projeto (abrir pasta, os repositórios do Mac, clonar ou criar) e Novo workspace (⌘N).
- **Ícones oficiais:** Claude e Codex com o ícone deles em todo lugar, e cada conector com o logo da ferramenta.

**Na 0.9.8, tudo o que o MAPA prometeu, em cinco partes. Parte 5 (código e estudo):**

- **Checks falhos ao agente** e **revisão de PR por IA** (Claude em modo plano ou Codex só leitura, sem editar nem comentar no GitHub), no cartão do PR do painel de Git.
- **Grafo do código pela central de MCP:** numa worktree com o grafo do graphify, os agentes consultam o grafo; na aba Arquivos, atualizar sem IA ou gerar com o agente.
- **Estudo completo:** Foco (revisar os vencidos, medir, praticar), O que eu sei (um conceito por nota em `01-PROJETOS/<projeto>/conceitos`, com domínio, revisão espaçada e calibração da confiança) e Plano (o cronograma da nota do projeto).
- **Perfis** (Ajustes → Perfis e backup): cada perfil é uma MÊTIS separada, com pasta, núcleo, senhas e Brain próprios; **backup** da configuração num .zip sem segredos, com conferir antes de importar.
- **Skills:** instalar de git, pasta ou .zip no Claude, no Codex ou no projeto; atualizar, exportar, copiar para a outra CLI e mandar para a Lixeira.

**Parte 4 de 5 (automações):**

- **Passo Código** (Python ou JavaScript, escrito pelo Claude), **gatilhos por evento** da MÊTIS e **por novidade** num conector.
- **Criar e ajustar por frase**, **importar do n8n** e **estratégias de agentes** (melhor de N, portão de revisão…).
- **Troca por cota:** o agente roda no outro provedor acima de 80% da janela de 5 h; os terminais sugerem a troca.
- **Rotinas viraram automações** (a tela Hoje continua igual).

**Parte 3 de 5 (conectores e kanban):**

- **Conectores:** Notion, GitHub (com o login do `gh`), Google (Gmail, Agenda e Drive) e **MCP próprio** (por endereço, por comando ou do catálogo oficial de MCP); testar conexão; copiar um MCP entre o Claude e o Codex.
- **Kanban:** rótulos com filtro, subtarefas no cartão, a lista do ClickUp do projeto e o **painel de agentes** (⌘K → Painel de agentes).
- **Atividade** com o que cada agente fez, tempo e custo; **cota dos planos** no Hoje.

**Parte 2 de 5 (navegador e tela):**

- **O agente usa o navegador da MÊTIS** pelas ferramentas `navegador_*` da central de MCP: lê a página, clica, digita, tira foto e vê o console e a rede, com o cursor "agente" à vista.
- **Perfis do navegador** com cookies separados, **cookies importados do Chrome**, **emulação de iPhone, Android e iPad**, e o ⌘K com endereços e histórico.
- **Barra lateral** com filtro, fixados, apelidos, terminais renomeados e cor por projeto; **worktree a partir de um branch ou commit**.
- **Temas por prompt ou importados do VS Code e do Obsidian**, fontes, densidade e zoom (⌘+ ⌘-).

**Parte 1 de 5 (agentes e terminal):**

- **Agentes com argumentos e variáveis de ambiente próprios**, e agentes de **outra CLI** (opencode, aider, um script): na tela de Agentes, escolha "Outra CLI" e escreva o comando.
- **Hibernar agente parado** (Ajustes → Agentes e avisos): o agente que espera você há 15, 30 ou 60 min fica pausado e acorda quando você volta a ele.
- **Menu ⋯ do terminal:** copiar o ID da conversa, o caminho do transcript, as últimas mensagens ou a pasta. Programas no terminal (vim, tmux) copiam para o Mac.
- **Barra de baixo:** `@` sugere notas do Brain; `/` lista os comandos e as skills do Claude ou do Codex daquele terminal.
- **Skill da MÊTIS** (Ajustes → Skills): ensina os agentes a usar o `metis` e a central de MCP.

**Na 0.9.7, editores dentro da MÊTIS:**

- **Arquivos da worktree abrem num editor de código** (o Monaco, o mesmo do VS Code), numa aba ao lado dos terminais. ⌘S salva, ou ligue "Salvar sozinho". Se o agente mexer no arquivo, a aba recarrega; se você tinha uma edição pendente, aparece o aviso com as duas versões lado a lado, para escolher. Markdown, CSV e HTML continuam com a prévia em "Visualizar".
- **Notas do Brain editáveis**, com cara de Obsidian (o mesmo motor, CodeMirror): "Editar" no leitor, ou "Abrir ao lado" para editar numa aba junto dos terminais. A marcação some fora da linha do cursor; `[[` sugere títulos do vault, `/` insere título, tarefa, callout, tabela ou código; o frontmatter vira uma caixa de propriedades; tarefas têm caixinha. Salva sozinho, e nunca grava por cima do que o Obsidian salvou depois.
- Com o foco num editor, ⌘D, ⌘F e ⌘L são do editor (como no VS Code). Fechar uma aba com mudança não salva avisa antes.

**Na 0.9.6, Git e GitHub (paridade com o Orca):**

- **Marcar por trecho e por linha** no diff: em "Não marcado", cada trecho tem marcar e descartar; clique no número da linha para escolher linhas soltas (⇧ + clique pega um intervalo). Em "Marcado", desmarcar do mesmo jeito.
- **Comparar com outro branch, tag ou commit:** no painel de mudanças ("Comparar com outro branch") ou no modo Comparar do diff. Imagens aparecem antes e agora, lado a lado.
- **O botão do branch muda com o estado:** Publicar branch, Subir ↑, Puxar ↓ ou Sincronizar; o ícone ao lado busca o remoto. Subida recusada oferece forçar com `--force-with-lease`.
- **Commit:** "Corrigir o último commit" (amend); se o pre-commit recusar, a saída aparece e "Consertar com o agente" manda para ele.
- **Merge e rebase:** a faixa da operação em andamento tem Continuar, Abortar e Resolver com o agente; cada conflito abre bloco a bloco (o nosso, o deles, os dois) ou vai inteiro para um lado.
- **GitHub** (pelo `gh` já logado): o PR do branch com checks e revisão, Criar PR (formulário ou agente), Pronto para revisão e Juntar. No kanban, as tarefas de um projeto ganham a coluna GitHub com as issues e os PRs abertos; "Executar com agente" numa issue cria a worktree `issue-<n>-…` e deixa o pedido na barra.
- **Ajustes → Git:** as receitas que o agente da worktree recebe no commit e no PR, qual agente abre, assinar os commits e o editor externo.

**Na 0.9.5:** a MÊTIS instalada abre pelo Finder, pelo Launchpad e pelo Dock com o PATH do seu shell (antes, aberta assim, não achava o `uv`, o `claude` nem o `codex`).

**Na 0.9.4, uso diário:**

- **A MÊTIS de uso fica instalada** em `/Applications/MÊTIS.app`, montada de uma versão marcada (`scripts/instalar.sh`, ver [Instalar e atualizar](#instalar-e-atualizar)). Ela não recompila quando o código muda, então dá para usá-la o dia todo enquanto a MÊTIS é desenvolvida.
- **Atualizar:** a instalada procura versão nova a cada 6 horas e avisa no sino; Ajustes → Sobre atualiza num terminal à vista (ou `metis atualizar`). Os terminais abertos continuam; o núcleo passa para a versão nova quando você o reinicia.
- **A de desenvolvimento** (`scripts/dev.sh`) usa outros dados (`~/.harness-dev`) e outra porta, então as duas abrem juntas sem dividir terminais nem rodar as rotinas duas vezes.
- **Kanban:** arrastar cartão funciona na janela do app.
- **Codex avisa** quando termina (pelo `notify` dele, sem desligar o que você já tinha no `config.toml`), e o estado dele passa a "trabalhando" quando você manda uma mensagem.
- **Agente que saiu** mostra o código de saída.
- A lista de mudanças de cada versão está no [`CHANGELOG.md`](CHANGELOG.md).

**Na 0.9.3, terminal e navegação (paridade com o Orca):**

- **Divisão da tela por worktree.** Cada worktree guarda a própria divisão (e "fora dos projetos" também), e ela volta como estava ao reabrir a MÊTIS. Escolher uma worktree na barra lateral, ou uma aba dela, mostra a divisão de lá; as abas das outras worktrees ficam em cinza na barra de abas.
  - ⌘D divide à direita e ⌘⇧D para baixo, quantas vezes quiser; o painel novo ganha a aba mais nova da worktree que não está à vista, ou fica vazio com os botões de abrir.
  - Arraste uma aba para a borda de um painel para dividir ali, ou para o meio para trocar. Arraste a divisória para mudar o tamanho (dois cliques voltam ao meio).
  - ⌘⇧W tira o painel da divisão (a aba continua aberta); ⌘⌥ e as setas andam entre os painéis. Fechar uma aba tira o painel dela e o vizinho cresce.
- **Busca no terminal** (⌘F ou a lupa no cabeçalho): acende todos os achados, também no histórico de rolagem, com contagem, maiúsculas e regex. Enter vai para o próximo, ⇧Enter para o anterior, Esc fecha.
- **Comandos salvos** (⌘⇧K, ou pelo ⌘K; Ajustes → Comandos salvos): comandos do shell e prompts, para todos os projetos ou só um. O comando roda no shell em foco (ou no mais recente da worktree, ou abre um); o prompt vai para a barra de entrada, para revisar. Ficam em `~/.harness/comandos.json`.
- **Pular para** (⌘J): as abas pelas mais recentes (Enter volta para a anterior), as worktrees e as telas.
- **Atalhos remapeáveis** (Ajustes → Atalhos): Mudar grava a próxima tecla; um atalho de outra ação passa para esta e a outra fica sem (com aviso); os do macOS são recusados. O que você muda fica em `~/.harness/atalhos.json`, que também dá para editar à mão.
- **Busca nos Ajustes:** ⌘, já abre com o foco na busca, que entende português, inglês e espanhol ("shortcuts", "tema", "awake"…), abre a seção e acende a linha.
- **Tema do terminal** (Ajustes → Aparência): os temas do Ghostty (do Ghostty.app, da sua pasta de temas e do seu config), do Kitty (`~/.config/kitty`) e do Warp (`~/.warp/themes`), ou um tema colado em qualquer um dos três formatos. Os temas da interface também podem ser feitos por prompt ou importados do VS Code e do Obsidian. O **Ghostty Default Style Dark**, o tema do seu Orca, vem junto.

**Na 0.9.2, sessões, agentes e avisos (paridade com o Orca):**

- **Agentes sobrevivem a fechar o app.** O núcleo roda por conta própria: fechar, recarregar ou atualizar a janela não fecha os terminais, e as rotinas e automações seguem com a janela fechada (Mac acordado). Desligar de vez: Ajustes → Desligar a MÊTIS, ou `metis desligar`. Se o núcleo em execução for de outra versão, a tela oferece reiniciá-lo.
- **Retomar uma conversa** (⌘K): o histórico do Claude e do Codex de todas as contas, com busca; retomar abre `claude --resume` ou `codex resume` na pasta certa.
- **Agente que saiu:** Reiniciar, ou Continuar a conversa. **Passar o trabalho** do Claude para o Codex (e o contrário), com o registro da conversa e as últimas mensagens.
- **Ajustes → Agentes e avisos:** modo de permissão das sessões novas por CLI (padrão, manual, auto, yolo), pastas dos projetos e worktrees como confiáveis, Mac acordado (nunca, com agente trabalhando, sempre), avisos do macOS e som quando o agente termina ou espera você, aprovações e erros. Os avisos do agente seguem os hooks do Claude Code: o `Stop` é "terminou" e o `Notification` (pedido de licença ou pergunta) é "espera você". O Codex não tem esses hooks e por enquanto não avisa.
- **Sino** na barra de título com os avisos não lidos (e no ícone do Dock); **Recursos** (memória e CPU por sessão); **Skills** (do usuário e do projeto); **scripts da worktree** por projeto (ao criar e antes de apagar).

**Na 0.9.1, os Quadros** (ícone de quadro na faixa): um quadro livre por projeto, como o Canvas do Obsidian, e é de fato um `.canvas` do Obsidian em `01-PROJETOS/<Projeto>/quadros/` no Brain, que abre lá também.

- Cartões: notas do Brain (título, tipo, status e resumo), sessões vivas do Claude, do Codex ou do shell (estado, últimas mensagens, campo para mandar mensagem e abrir o terminal), tarefas do kanban, links (abrem no navegador da MÊTIS, com modo de design para localhost), notas suas e grupos, ligados por setas com rótulo.
- Arraste uma nota do Brain para cima de uma sessão (ou ligue as duas): a sessão recebe o pedido de ler a nota e ela entra no mini-mapa daquela sessão.
- Editou no Obsidian? A MÊTIS percebe e recarrega; ela nunca grava por cima do que o Obsidian salvou depois.

**Na 0.9.0, as Automações (o "n8n da MÊTIS"):**

- **Canvas de passos** (ícone de fluxo na faixa): gatilho, Ferramenta, Agente, Condição, Aprovação, Brain e Esperar, ligados por setas, com notas no canvas. Cada automação é um YAML legível em `~/.harness/automacoes/`, com histórico num git local.
- **Rascunho e publicada sempre explícitos:** editar (pela tela, à mão ou por um agente) só mexe no rascunho; o motor só roda a publicada; voltar é publicar uma versão antiga. Detalhes mostra a diferença.
- **Ferramenta** chama a central de MCP direto, sem agente e sem gastar cota (Brain, kanban, lembrete, Slack, ClickUp…). Quem fala com outras pessoas pede a sua aprovação antes.
- **Agente** abre um terminal de verdade do Claude ou do Codex, pelo plano, só com as ferramentas liberadas no passo; o resultado volta pela ferramenta `saida` e é conferido contra o formato combinado (até 2 pedidos de correção).
- **Testar** roda o rascunho em **ensaio**: o que falaria com outras pessoas vai para a sua DM; dados fixados substituem a chamada; esperar vira 3 segundos.
- **Execuções** com entrada, saída, itens e tempo de cada passo; erro nunca calado (vermelho na tela e DM no Slack em produção), **Pedir conserto** (um Claude corrige o rascunho) e **Reexecutar daqui**.
- **Gatilhos:** manual, `metis rodar <automação>` e agendado (com a recuperação das rotinas para o Mac dormindo).
- Ficou para a 0.9.x: passo de Código, criar por frase, gatilhos por evento e por sondagem, troca de provedor por cota e as rotinas virando automações.

**Na 0.8.0, o Brain vivo:**

- **Busca por significado, local.** O modelo [potion-multilingual-128M](https://huggingface.co/minishlab/potion-multilingual-128M) (model2vec, ~260 MB em disco, roda só com numpy no Mac Intel e entende português) dá um vetor a cada registro do Brain. Precedentes passam a ser achados por significado e por palavra, juntos. O modelo só carrega no núcleo, quando precisa, e sai da memória depois de 20 minutos parado (carregado, ocupa ~1,5 GB).
- **Antes de decidir:** `brain_conflitos` (MCP) e `metis brain conflitos "<decisão>"` mostram decisões parecidas do mesmo projeto (repetição ou contradição) e registros parecidos dos outros (precedente).
- **Sugestões entre projetos:** cada registro novo procura outros projetos com registros bem parecidos. Se houver, o Claude (Haiku, pelo plano, no máximo 25 por dia) julga se vale lá e já escreve a decisão. A sugestão aparece no painel Brain do projeto, em Hoje e no leitor de notas; **Aceitar** vira decisão aceita no projeto alvo pelo `brain.py registrar`, ligada à nota de origem (dá para editar título e resumo antes).
- **Fora da MÊTIS também:** `metis brain mcp` é um servidor MCP do Brain para o Claude Code e o Codex abertos em qualquer terminal (instalado como `metis-brain`), e `metis brain contexto` é o hook de início de sessão do `~/.claude/settings.json` com os precedentes e as sugestões do projeto da pasta. Nenhum dos dois carrega o modelo: usam os vetores já guardados e pedem ao núcleo o vetor de um texto livre quando a MÊTIS está aberta.
- **Mini-mapa** no canto de cada terminal de agente: o projeto em âmbar e as notas do Brain que a sessão viu (precedentes do início, leituras, buscas, conflitos) ou registrou. Clique abre a nota.
- **Janela de contexto** (aba Contexto do painel, ou clique em "contexto" na barra de status): o que ocupa o contexto do Claude em foco, por categoria (fixo da sessão, comandos, arquivos lidos, MCP, hooks…) e os itens que mais pesam, lidos do transcript.

**Na 0.7.2:** a barra de baixo (Ditar, Anexar) é a única entrada dos terminais do Claude e do Codex. O terminal fica só para ler: o que você digita ou cola nele vai para a barra, e a caixa de entrada vazia do Claude some atrás de um véu (a linha de modo, como "auto mode on", vai para o cabeçalho do terminal). Com a barra vazia, ↑↓, Enter, Esc, ⇧Tab e ⌃C vão para o agente, para escolher opções de menus e perguntas, confirmar e interromper. O shell segue um terminal normal.

**Na 0.7.1, o resto do OS pessoal:**

- **Captura rápida** (⌥Espaço de qualquer app, ou ⌘K → "Captura rápida"): uma caixinha por cima de tudo. "me lembra de pagar o boleto sexta 9h" vira lembrete no Slack; "tarefa revisar o PR no Personal Harness" vira linha nas Próximas ações do projeto; "tarefa…" ou "anota…" sem projeto vai para as Capturas do dia no Brain; o resto vai para o **Hermes**, o concierge, num terminal da MÊTIS, que age pela central de MCP.
- **Hermes**: agente novo, concierge da captura rápida.
- **Agente por descrição**: em "Novo agente", descreva numa frase e o Claude rascunha nome, papel, dor, cor e pasta; "Testar sem salvar" abre um terminal com o rascunho. Todo agente ganhou o campo "Qual dor resolve?".
- **Sprites animadas** por estado na barra lateral e nas abas: respira parado, balança trabalhando, "!" esperando você, pulinho ao concluir, treme no erro.
- **Estudo** (ícone de livro): Pomodoro (25/5, 50/10 ou 15/3) que continua ao trocar de tela, com o relógio na barra de título; cada foco vira uma linha em "📚 Estudo" na nota do dia do Brain. Placar com o piso de 20 minutos, a semana, a sequência e o aviso de dois dias seguidos sem estudar; botões para a Aurora e o Sócrates.

**Na 0.7.0, rotinas e Hoje:**

- **Rotinas**: um agente que abre sozinho num terminal na hora marcada, com um pedido como primeira mensagem (`claude "<pedido>"`, interativo e pelo plano). Dias da semana, hora, aviso no Slack (toca no iPhone) e janela de recuperação: se o Mac dormia na hora e acordou dentro dela, roda; depois, pula e fica registrado. Cada rotina é um `.md` em `~/.harness/rotinas/`.
- **Hoje** (ícone de casa): as rotinas do dia com o que rodou, pulou ou espera, o que está em andamento nos projetos do Brain, o que aguarda a sua aprovação e um lembrete rápido. À direita, todas as rotinas com a próxima execução e o editor (nome, agente, dias, hora, recuperação, pedido, aviso).
- Já vêm duas: **Check-in de estudo** com a Aurora (seg a sáb, 20h50, aviso no Slack, recupera até 21h50) e **Consolidação semanal do Brain** com a Alexandria (sexta, 22h10, recupera até o dia seguinte).

**Desde a 0.6:**

**Novo na 0.6, conectores e avisos:**

- **Central de MCP**: todo Claude e todo Codex aberto na MÊTIS já vem com o MCP "metis" (por `--mcp-config` no Claude e `mcp_servers` no Codex, com um token por terminal). Ele traz as ferramentas do Brain e do kanban (`brain_buscar`, `brain_ler`, `brain_precedentes`, `tarefas`, `tarefa_mover`, `tarefa_nova`), o `lembrete` e as ferramentas de cada conta conectada, com o id da conta na frente.
- **Conectores** (ícone de tomada): **Slack** por um bot da MÊTIS em cada workspace (o passo a passo e o manifesto estão na tela; você cola o token do bot) e **ClickUp** pelo MCP oficial, com login no navegador. Várias contas por ferramenta; tokens no Keychain do Mac.
- **Lembretes**: `metis lembrete "pagar o boleto" sexta 9h` (ou "amanhã 14:30", "em 20 min", "13/11 9h") agenda a mensagem do bot na sua DM do Slack; o iPhone toca na hora, mesmo com o Mac dormindo. Os agentes fazem o mesmo pela ferramenta `lembrete`.
- **Aprovação**: mensagem para outras pessoas e escrita no ClickUp esperam o seu "Aprovar" num cartão que aparece em qualquer tela (dá para desligar por conta). Em 10 minutos sem resposta, a ação não acontece.
- **Atividade**: tudo o que os agentes fizeram pela central, com quem, o quê e o resultado.
- **Conectores por agente**: no editor de agentes, escolha quais contas cada um pode usar (todas, nenhuma ou algumas).

**Desde a 0.5:**

**Novo na 0.5, Brain e kanban:**

- **Grafo do Brain** (v0.5.1): sem nota aberta, o Brain mostra o grafo das notas, com uma nuvem por área do projeto (vinda do `area:` da nota) e as ligações entre projetos na cor de acento. Os nomes ficam escondidos e aparecem passando o mouse; o botão "Nomes" mostra os dos projetos. As forças ficam vivas, como no Obsidian: o grafo se acomoda animando, arrastar um nó puxa os vizinhos, e o painel "Forças" tem força de centro, repulsão, força e distância das ligações (guardados entre aberturas). Pinça aproxima, dois dedos andam, passar o mouse acende as ligações, clicar abre a nota; a busca acende as notas achadas. Filtros por tipo, "Precedentes entre projetos", "Notas sem ligação" e a legenda liga e desliga cada área.
- **Brain** (ícone de grafo na faixa, ou ⌘K → "Buscar no Brain"): busca por palavra em todo o vault, sem acento e por começo de palavra, com filtro por tipo (decisões, incidentes, aprendizados, entregas, projetos, conhecimento) e por projeto. A nota abre ao lado, com `[[links]]` clicáveis (link para nota que não existe fica tracejado), callouts, "Citada por" e "Abrir no Obsidian".
- **Kanban** (ícone de colunas, ou ⌘K → "Kanban de projetos"): os projetos de `01-PROJETOS` como cartões nas colunas Ideia, Planejando, Construindo, Em produção e Pausado. Arrastar grava `estagio:` na nota. O cartão abre as tarefas, que são as "Próximas ações" da nota, em Pendente, Em andamento, Em teste e Concluído. Arrastar troca a etiqueta na linha (`#em-andamento`, `#em-teste`) ou marca `[x]` com a data; "+ Adicionar" escreve uma linha nova.
- **Executar com agente**: numa tarefa, cria uma worktree com o nome dela, abre o Claude, põe a tarefa em "Em andamento" e deixa o pedido na barra de entrada para você revisar.
- **Precedentes v1**: toda sessão do Claude aberta na pasta de um projeto do Brain começa com decisões, incidentes, aprendizados e entregas de **outros** projetos que batem com as tarefas abertas. No painel da worktree, a aba **Brain** mostra o projeto, as tarefas abertas e os mesmos precedentes.
- **Para os agentes**: `metis brain buscar|ler|precedentes`, `metis tarefas` e `metis tarefa nova|mover`, em qualquer terminal da MÊTIS.

**Desde a 0.4:**

- **Navegador embutido**: abas de navegador ao lado dos terminais (botão de globo na barra lateral, ⌘K → "Abrir navegador", "Abrir" no painel Portas, `metis web <endereço>` em qualquer terminal, ou ⌘ + clique num link do terminal; com ⇧, abre no navegador do Mac). É o WebKit do macOS, com barra de endereço, voltar e avançar, recarregar, inspetor (devtools), aba anônima, downloads em `~/Downloads` e links `target=_blank` virando aba nova.
- **Modo de design**: botão Design na barra da aba (ou ⌘K → "Modo de design", que abre uma aba já no modo se nenhuma estiver em foco), realça o elemento sob o mouse; o clique manda para a barra de entrada do agente da worktree o seletor, o texto, o HTML, o estilo e, quando a página é React, Svelte ou Vue em desenvolvimento, o componente e o arquivo de origem. Esc sai.
- **Sprites por prompt**: na tela de Agentes, um chat da sprite. Você descreve, o Codex desenha e a MÊTIS pixeliza em 48 × 48. Todo agente é **greco-romano** por padrão; sem sprite escolhida, ganha um busto greco-romano gerado do nome.
- O app escolhe uma porta livre para o núcleo e o núcleo se encerra se o app morrer, então recompilar ou travar não deixa a MÊTIS "sem núcleo".

**Desde a 0.3, para programar:**

- **Projetos e worktrees**: a barra lateral é organizada por projeto (repositório git), depois as worktrees, depois os terminais de cada uma. Cria worktree com branch novo (em `~/orca/workspaces/<repo>/<nome>`, a mesma pasta do Orca, copiando o `.env`) e já abre o Claude nela. Apagar avisa se há terminal aberto ou mudança sem commit, e nunca apaga um branch com commits que não foram juntados.
- **Painel da worktree** (⌘⇧B): **Mudanças** (marcar, desmarcar, commit, pull e push), **Arquivos** (árvore com as cores do git) e **Portas** (os servidores que os terminais subiram, com um clique para abrir).
- **Revisão com notas**: o diff de cada arquivo abre numa aba; uma nota por linha, e "Mandar ao agente" junta todas na barra de entrada do agente da worktree.
- **Commit pelo agente**: "Pedir ao agente" manda o agente da worktree escrever a mensagem e commitar, no terminal dele (se não houver agente aberto, abre um Claude).
- **Visualizadores**: Markdown, imagem, PDF, CSV, áudio, vídeo, HTML (sem scripts) e código. ⌘P abre qualquer arquivo da worktree.
- **Agentes em arquivo**: cada agente é um `.md` em `~/.harness/agentes/` (nome, descrição, CLI, modelo, conta, pasta, cor, argumentos extras, variáveis de ambiente e o papel; na outra CLI, o comando). A tela de Agentes edita tudo, inclusive a sprite (PNG em pixel art) e os importados do Maestri. O papel vai como `--append-system-prompt` no Claude e `developer_instructions` no Codex.

**Desde a 0.2:**

- **Claude Code e Codex de verdade em terminais**, com a sua conta, do mesmo jeito que no seu terminal. Também abre shell comum. A MÊTIS não lê nem guarda login.
- **Abas, tela dividida (em árvore, por worktree, desde a 0.9.3) e terminal flutuante** (⌃\`). Os terminais ficam vivos ao trocar de aba, dividir ou abrir os Ajustes.
- **Salto rápido** (⌘K): pula para um terminal, abre um novo, divide a tela, troca de conta ou de tema.
- **Barra de entrada** embaixo dos terminais: escreva com calma, revise e mande para o terminal em foco (⏎ envia, ⌥⏎ só cola).
- **Ditado com o microfone**: o botão Ditar vira uma onda sonora ao vivo enquanto grava; ao parar, o Whisper transcreve no próprio Mac (sem internet, sem custo) e o texto cai na barra para revisar.
- **Anexos**: o botão Anexar ou arrastar arquivos do Finder. Solto num terminal, o caminho vai direto para ele; solto na barra, entra junto com o texto.
- **Contas e uso**: várias contas do Claude Code e do Codex, cada uma na própria pasta (`CLAUDE_CONFIG_DIR`, `CODEX_HOME`). Troca pelos Ajustes, pelo ⌘K ou com `metis switch`. A barra de status mostra as janelas de 5 horas e 7 dias da conta em uso de cada plano, em destaque a partir de 80%.
- **Status do agente** (trabalhando, esperando você) vindo dos hooks do Claude Code, e o contexto da sessão em foco.
- **Ajustes**: contas e uso, aparência (Drácula azul, Grafite, Claro), voz e atalhos.

As outras telas do protótipo aparecem na faixa de ícones e mostram em que versão chegam.

O projeto do Brain de uma pasta vem do `diretorio:` no frontmatter da nota do projeto (o mesmo vínculo do `brain.py`); uma worktree conta como o repositório principal dela.

## Comando `metis`

Dentro dos terminais do app (e em `core/` com `uv run metis`):

```sh
metis contas                       # contas de cada CLI e qual está em uso
metis switch codex pessoal         # as próximas sessões do Codex usam a conta "pessoal"
metis login claude trabalho        # cria a conta e abre o login oficial do Claude Code nela
metis web 5173                     # abre uma aba do navegador da MÊTIS
metis brain buscar webhook guru    # busca no Brain (--tipo decisao, --projeto "Nome")
metis brain ler "Título da nota"   # mostra a nota e quem cita ela
metis brain precedentes            # registros de outros projetos parecidos com o desta pasta
metis brain conflitos "Webhook passa por fila"  # antes de decidir: repetição, contradição, precedente
metis brain sugestoes              # sugestões de precedente esperando você neste projeto
metis brain mcp                    # servidor MCP do Brain por stdio (sessões fora da MÊTIS)
metis brain contexto               # hook SessionStart fora da MÊTIS (lê o JSON do Claude no stdin)
metis sessoes                      # terminais abertos, com o id (--json para agentes)
metis sessao ler 6d57ea05          # o fim do terminal ou as últimas mensagens do agente
metis sessao escrever 6d57ea05 "oi" # manda para o terminal, como a barra de baixo
metis desligar                     # desliga a MÊTIS de vez (fechar a janela não desliga)
metis automacoes                   # as automações, com estado e a última execução
metis rodar "Briefing da manhã"    # roda a versão publicada agora
metis tarefas                      # Próximas ações do projeto desta pasta, com o id
metis tarefa mover 4ea9e8ea em-teste
metis worktree nova personal-harness corrige-login  # worktree nova (--base, --sem-env)
metis worktree nova personal-harness --branch origin/ajuste  # a partir de um branch que já existe (ou --commit <sha>)
metis agente codex "rode os testes" # abre outro agente num terminal (claude, codex ou um agente salvo)
metis versao                       # a versão em uso e se há uma nova
metis atualizar                    # instala a versão nova neste terminal (ou: metis atualizar v0.9.4)
```

O nome antigo, `harness`, continua funcionando como apelido. Os dados seguem em `~/.harness`.

## Instalar e atualizar

Precisa de `uv`, Node 22+, Rust e o Xcode Command Line Tools.

```sh
./scripts/instalar.sh           # a versão marcada mais nova (a maior tag v*)
./scripts/instalar.sh v0.9.4    # uma versão específica (também serve para voltar)
```

- Cada versão vira uma cópia em `~/.harness/versoes/<versão>`, com o núcleo dela; o app vai para `/Applications/MÊTIS.app`. Ficam as duas cópias mais novas (e qualquer uma cujo núcleo ainda esteja rodando).
- A primeira instalação compila o app inteiro e demora vários minutos num Mac Intel; as seguintes reaproveitam o cache em `~/.harness/build`.
- Os dados (agentes, rotinas, automações, contas, conectores) seguem em `~/.harness`, de qualquer versão.
- Depois de instalar ou atualizar: feche a MÊTIS (⌘Q) e abra de novo. Os terminais continuam; quando quiser, a janela oferece reiniciar o núcleo para a versão nova (isso fecha os terminais).

## Desenvolver

```sh
./scripts/dev.sh        # a janela do Tauri deste repositório (recompila ao editar)
./scripts/dev-web.sh    # só no navegador, em http://localhost:1420
```

A MÊTIS de desenvolvimento usa `~/.harness-dev` (os modelos são os da de uso, por link, e os agentes vêm copiados na primeira vez; as rotinas não) e a porta 47840, e deixa o ⌥Espaço para a de uso. Para abrir os dados de uso de propósito: `HARNESS_HOME=~/.harness ./scripts/dev.sh`.

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

- O núcleo é dono dos terminais e roda por conta própria (desde a 0.9.2): a janela se liga a ele pelo `~/.harness/runtime.json` e não o derruba ao fechar. A saída dele fica em `~/.harness/nucleo.log`.
- O núcleo é dono dos terminais. Cada sessão do Claude recebe um `--settings` com a statusline e os hooks apontando para o núcleo. Esse `--settings` tem precedência sobre `~/.claude/settings.json`, então o Orca e o seu Claude Code de sempre não são afetados.
- O núcleo só escuta em `127.0.0.1` e exige um token novo a cada execução.
- Variáveis do Orca, marcadores da sessão que abriu o núcleo e o Python do próprio núcleo não passam para os agentes.
- Cada conta é uma pasta de configuração. A conta "padrão" usa o `~/.claude` e o `~/.codex` de sempre.
- O modelo de voz (Whisper "small", cerca de 460 MB) e o de significado (potion-multilingual-128M em float16, cerca de 260 MB) ficam em `~/.harness/modelos`; os anexos, em `~/.harness/anexos`.
- As sugestões de precedente ficam em `~/.harness/sugestoes.db`; os vetores, no `brain.db` (cache, refeito do vault). Na primeira vez, o núcleo marca todos os registros que já existem como vistos: só os novos são julgados.

## Estrutura

```
core/   núcleo em Python (uv): sessões, PTY, relay, API
app/    janela Tauri e tela React
docs/   mapa, design e paridade com o Orca
scripts/ instalar.sh (MÊTIS de uso), dev.sh e dev-web.sh (desenvolvimento)
```
