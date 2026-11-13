# Mudanças da MÊTIS

Cada versão, da mais nova para a mais velha. O detalhe de cada uma está no [`README.md`](README.md), o plano em [`docs/MAPA.md`](docs/MAPA.md) e o porquê das decisões no Brain, em `01-PROJETOS/Personal Harness/`. Versões no formato `MAIOR.MENOR.CORREÇÃO`, uma tag `v*` por versão.

## v1.3.1 · o login do NotebookLM fica aberto até você entrar

- **Entrar e ligar ao chat voltou a funcionar.** A janela do Chrome abria, piscava e fechava sozinha, e a aba continuava dizendo que o login tinha vencido. O perfil próprio do `notebooklm-py` guardava o cookie de uma sessão do Google que já tinha caído; o CLI tomava esse cookie por login feito, salvava uma sessão que não vale e fechava a janela antes de você conseguir entrar. Agora o Entrar sempre começa num perfil limpo (`--fresh`): a janela abre na tela de login do Google e espera até você terminar, inclusive a verificação em duas etapas (até 14 minutos, eram 5).
- **Quando o login não vale, a aba diz por quê.** Se a janela fechar e o Google não tiver dado uma sessão válida, a aba avisa e pede para entrar de novo, em vez de voltar calada para "o login venceu". Tempo esgotado e janela fechada no meio também aparecem em português.

## v1.3.0 · o NotebookLM dentro do Estudo e o chat explicando com diagramas e imagens

- **NotebookLM na aba de Estudo.** Uma aba nova, NotebookLM, ao lado de Foco, O que eu sei e Plano, abre o site de verdade (notebook.google.com) no navegador da MÊTIS: cadernos, fontes, chat, resumos em áudio e vídeo, tudo sem sair da MÊTIS. O login do Google dessa página fica no perfil do navegador escolhido (dá para importar os cookies do Chrome, como em qualquer aba).
- **O caderno do estudo.** A barra da aba lista os seus cadernos (pelo `notebooklm-py`, o mesmo CLI da skill do NotebookLM) e escolhe um: o site vai para ele e o agente de estudo passa a explicar com base nas fontes dele, citando de onde veio cada ponto. Ao lado, o resumo que o NotebookLM faz do caderno, as perguntas que ele sugere (um clique manda para o chat) e as fontes. **Entrar e ligar ao chat** abre o login do Google do `notebooklm-py` (no Chrome do Mac, num perfil próprio) e a MÊTIS confere sozinha quando termina.
- **O agente de estudo é seu e se conecta.** A aba de Estudo começa sem agente (nada de Sócrates fixo nem do check-in da Aurora, que vinham da época do Maestri). Crie o seu agente de estudos na aba Agentes e conecte no painel da direita do Estudo; o × do cabeçalho desconecta (as conversas abertas continuam em Terminais). Entram na lista os agentes do Claude ou do Codex criados na MÊTIS; os herdados do Maestri ficam de fora.
- **O chat do Estudo é a conversa rica.** O painel do agente trocou a espiada em texto puro pela conversa da 1.2.0: fluxogramas, mapas mentais e outros diagramas Mermaid desenhados, tabelas, imagens e código com cor, com "Ampliar". O botão de alargar divide a tela com o centro, para diagrama e imagem ficarem grandes; o + abre outra conversa.
- **Modo de estudo.** Toda sessão do agente de estudo explica em passos curtos, com exemplo concreto em cada passo, fecha com uma pergunta de fixação (e a sua confiança de 1 a 5, registrada no mapa) e usa recurso visual sempre que a explicação pede: Mermaid para fluxo, sequência, mapa mental, linha do tempo e estrutura; tabela para comparar; imagem quando a forma importa. Essas regras vão junto com o papel do agente que você conectar.
- **Imagens desenhadas pelo GPT.** A ferramenta `estudo_imagem` da central pede a ilustração ao gerador de imagens do GPT pelo Codex (o mesmo caminho das sprites, pelo seu plano), com rótulos em português; a imagem fica em `~/.harness/estudo/imagens` e aparece na conversa. Leva cerca de 1 minuto: o agente escreve a explicação enquanto isso e mostra a imagem quando fica pronta.
- **Conversar com o agente** abre uma conversa de estudo livre (com o panorama do caderno e três perguntas, se houver um escolhido).
- **Central:** `cadernos`, `caderno_fontes`, `caderno_perguntar` (a resposta do NotebookLM com as citações) e `caderno_fonte` (o texto da fonte, em pedaços) e `estudo_imagem`, só nas sessões de estudo, sem pedir aprovação.
- **Precisa do `notebooklm-py` 0.8 ou mais novo:** o NotebookLM mudou para notebook.google.com e as versões anteriores davam o login como vencido. A aba avisa com o comando para atualizar.

## v1.2.0 · o Claude e o Codex abrem numa conversa com imagens, fluxogramas e código desenhados

- **O painel do agente agora é uma conversa,** no jeito do app do Codex: o que você mandou em balões à direita, a resposta do agente em texto corrido, e as ferramentas (comandos, leituras, edições, buscas, MCP, subagentes) em linhas compactas que abrem com o resultado. Três ou mais ferramentas seguidas viram um resumo ("7 ações · 2 comandos · 2 edições…") que abre num clique; com o agente trabalhando, as últimas ficam à mostra.
- **Imagens na conversa.** O print que você cola ou anexa aparece no seu balão. A imagem que uma ferramenta devolve (o print do navegador, uma imagem lida) aparece na linha dela, mesmo com o grupo fechado. A imagem que o agente gera em arquivo aparece assim que fica pronta: o `.png` ou `.svg` que ele escreveu e o caminho de imagem que ele cita na resposta. No Codex, a imagem vista (`view_image`) e a gerada também. Clicar amplia dentro do painel, com "Abrir numa aba" e "Mostrar no Finder". Se o macOS entregar o anexo em JPEG XL (`.jxl`) ou AVIF disfarçado de `.png`, a MÊTIS o transforma em PNG antes de passá-lo ao agente.
- **Fluxogramas e diagramas desenhados.** Bloco ` ```mermaid ` (fluxograma, sequência, estados, Gantt, mapa mental…) vira o desenho, nas cores do tema, com "Ampliar" e "Código". Diagrama com erro de sintaxe mostra o código e o motivo.
- **O resto do conteúdo rico:** tabelas com cabeçalho e rolagem de lado, código com a cor do editor (o mesmo Monaco) e botão de copiar, diff da edição em verde e vermelho com a contagem +N −N, links que abrem no navegador da MÊTIS (com ⇧, no do Mac), caminhos de arquivo que abrem numa aba, o plano do agente como checklist, o pensamento recolhido e marcos do turno ("Trabalhou por 2m 11s", conversa compactada, `/model sonnet`, interrompido).
- **Ao vivo:** a conversa é conferida a cada 0,9 s com o agente trabalhando (2,5 s parado) e só o que mudou vem do núcleo. Embaixo, "Trabalhando" com o tempo; quando o agente espera uma resposta sua, um aviso com "Ver o terminal". A tela fica no fim enquanto você está no fim; rolando para cima, ela para e aparece o botão de descer. Conversa longa carrega as mensagens antigas ao chegar no topo.
- **O terminal continua lá, no mesmo painel.** O Claude e o Codex seguem rodando interativos no terminal, pelo plano, como sempre: a conversa é desenhada a partir do registro que a própria CLI grava. A alternância no cabeçalho (ou ⌘⇧T) mostra o terminal, e ele aparece sozinho quando o agente abre um menu (permissão, pergunta, plano, `/model`): ↑↓ e ⏎ na barra vazia escolhem, e ao sair do menu a conversa volta. "Voltar à conversa" dispensa o menu da vez.
- **Tudo o que o terminal fazia continua:** a barra de baixo (escrever, ditar, anexar, colar print, `@nota`, `/comando`, modelo), ⌘F (agora busca na conversa, ou no terminal quando ele está na frente), reiniciar e continuar, passar para o outro agente, o ⋯ com o ID e o transcript, o mini-mapa do Brain, a hibernação e o terminal flutuante. O terminal comum (shell) não muda.
- **Sessões já abertas** ganham a conversa ao atualizar: ela é lida do registro, com o histórico inteiro, sem reiniciar o agente.
- **Ajustes → Agentes → "O Claude e o Codex abrem em":** Conversa (padrão) ou Terminal. A troca feita no cabeçalho vale para aquele painel.
- **Conversas do Codex 0.154 voltam a ser achadas.** Nessa versão a primeira mensagem vem depois de uns 90 KB de instruções (lista de skills, AGENTS.md), e o núcleo só olhava os primeiros 64 KB: a conversa ficava vazia com o Codex trabalhando, e a conversa também sumia do histórico, do "continuar" e do "passar para o Claude". Agora o começo é lido linha a linha até a primeira mensagem.
- **O comando do Codex aparece rodando desde o começo.** O Codex só grava o comando no registro quando ele termina, e um teste de 4 minutos deixava a conversa parada em "Trabalhando". Agora a linha do comando entra assim que o Codex o chama, girando, e fecha com o resultado no fim, inclusive quando ele roda vários comandos de uma vez.
- **Codex retomado pelo histórico** já abre com a conversa antiga, sem esperar o primeiro turno novo.

## v1.1.4 · dá para excluir tarefa do kanban

- **Excluir uma tarefa.** Antes, uma tarefa só saía do kanban apagando a linha à mão na nota do Brain. Agora há a lixeira no rodapé de cada cartão e no alto do cartão aberto, e ⌫ (ou Delete) com o cartão em foco faz o mesmo. Antes de excluir, uma confirmação mostra a tarefa e diz o que vai junto; Enter confirma, Esc desiste (com o cartão aberto, o Esc fecha só a confirmação).
- **O que sai junto:** a linha some das Próximas ações da nota do projeto, com a descrição e o checklist, sem deixar linha vazia sobrando. A atividade, os comentários e os anexos da tarefa saem do núcleo, e o arquivo do anexo também, quando foi a MÊTIS que guardou (o que está em `~/.harness/anexos`). Não dá para desfazer.
- **Fila do Auto:** a tarefa que estava na fila sai dela. A que está rodando não pode ser excluída: feche o terminal dela antes (a lixeira fica apagada, com o aviso).
- **Só você exclui.** As tarefas são suas (decisão de 2026-11-10): não há ferramenta de excluir para os agentes, e o núcleo recusa o pedido que vem de um terminal.
- **Tarefas repetidas:** com duas tarefas de mesmo título, excluir a de cima passa o id dela para a de baixo, e a atividade e a fila do Auto da de baixo vão junto.

## v1.1.3 · o calendário das datas fecha ao clicar fora, a prioridade troca e o agente cria a tarefa inteira

- **O calendário do cartão não fechava quando você clicava fora,** nem depois de escolher a data. Era o calendário nativo do WebKit, aberto por um campo escondido que nunca recebia o foco; tudo indica que esse calendário só fecha quando o campo perde o foco, e sem foco não havia o que perder. Agora o calendário é do próprio cartão: fecha ao escolher o dia, ao clicar fora ou no Esc (o Esc fecha só o calendário, o cartão fica aberto), e abrir o do Início fecha o da Entrega.
- **De quebra, sai em português e nas cores do tema** ("novembro de 2026", D S T Q Q S S), com hoje destacado, a data escolhida marcada, setas para trocar o mês e o botão Hoje.
- **A prioridade não trocava, e ficava em Normal.** Na pílula "⚑ Normal ↓", só a palavra era o seletor; a bandeira, a seta e a borda eram a moldura dele, e no WebKit da janela clicar na moldura não abre o menu. Agora a pílula inteira abre o menu. A pílula do Status tinha o mesmo defeito e saiu junto.
- **O agente cria a tarefa já inteira no kanban.** A ferramenta `tarefa_nova` da central (e o `metis tarefa nova`) só levava título, rótulos e subtarefas; a descrição, a prioridade e o prazo ficavam de fora. Agora ela aceita também `descricao` (Markdown, o corpo do cartão), `prioridade` (urgente, alta, media, normal, baixa ou minima), `inicio` e `entrega` (AAAA-MM-DD), e a tarefa nasce como o cartão aberto a deixaria. Campo errado é recusado antes de gravar, sem deixar meia tarefa na nota. No `metis tarefa nova`: `--descricao`, `--prioridade`, `--inicio`, `--entrega`, `--rotulo` e `--subtarefa`.

## v1.1.2 · o editor de código abre com tema personalizado

- **O editor de código ficava em "carregando o editor…" e nunca abria** quando o tema da MÊTIS era um tema criado por prompt ou importado (como o Noite em Atenas). O Monaco só aceita letras, números e hífen no nome do tema, e o nome levava o `tema:` do id. Agora o nome vai limpo e o editor abre na hora, com as cores do tema.
- **Trocar para um tema personalizado com um arquivo aberto** não derruba mais a tela (dava o mesmo erro).
- **Se o editor não abrir por outro motivo, o motivo aparece no lugar do "carregando",** e o próximo arquivo tenta carregar o editor de novo (antes, uma falha ficava guardada até reabrir a MÊTIS).

## v1.1.1 · a janela não trava mais com um agente encerrado em foco

- **A janela abria vazia e parada** (sem projetos, sem terminais, sem uso, só "núcleo conectado") quando a aba em foco era um agente que já tinha terminado. O terminal de agente manda o foco para a barra de baixo, e o agente encerrado não tem barra: a barra devolvia o foco ao terminal, que mandava de volta, sem fim. No WebKit da janela isso não estourava a pilha, girava para sempre e a tela congelava antes de mostrar os dados. Agora, sem barra, o foco vai direto ao terminal. O defeito vinha da 0.9.9 e só aparecia nesse caso.

## v1.1.0 · o cartão do kanban abre inteiro, no jeito do ClickUp

- **Clicar num cartão de tarefa abre o cartão inteiro,** no desenho do ClickUp: título, status (com o botão de passar para a próxima coluna e o de concluir), prioridade, datas de início e de entrega, projeto, etiquetas, descrição, checklist e anexos à esquerda; a atividade e os comentários à direita. O duplo clique que abria as subtarefas no próprio cartão saiu.
- **O agente e o modelo ficam no cartão,** com o mesmo painel do raio: Claude Code, Codex ou um agente seu, modelo, raciocínio, permissão e worktree ou pasta do projeto. Dali dá para **Executar agora** (que agora respeita o agente e o modelo escolhidos) ou **Rodar sozinha** (a coluna Auto). O pedido leva a descrição, o checklist, as datas e os caminhos dos anexos, então o agente vê o print que você anexou.
- **Tudo o que é da tarefa continua na nota do Brain.** Prioridade e datas são os campos do plugin Tasks no fim da linha (🔺 ⏫ 🔼 🔽, 🛫 início, 📅 entrega), a descrição são as linhas recuadas logo abaixo, antes das subtarefas. O Obsidian mostra igual, e os agentes leem tudo pela nota e pela ferramenta `tarefas`.
- **Atividade, comentários e anexos** ficam no núcleo (`~/.harness/tarefas.db`, que entra no backup; os arquivos em `~/.harness/anexos`). A atividade diz quem mexeu: você, o Auto ou o agente do terminal que rodou `metis tarefa` ou a central de MCP. Trocar o título pelo app leva o histórico e a fila do Auto junto para o id novo.
- **Anexar:** botão Anexar arquivo, arrastar do Finder para o cartão ou colar um print com ⌘V. Imagem aparece em miniatura; clicar abre no app padrão do Mac.
- **Checklist editável:** clicar no texto de um item edita, o × tira o item.
- **O cartão no quadro** mostra a prioridade, a data de entrega (em vermelho quando passou), e se tem descrição, anexos e comentários.

## v1.0.2 · print colado com ⌘V vira anexo

- **Colar um print na barra de mensagem agora funciona.** Antes, ⌘V com uma imagem na área de transferência não fazia nada: a barra só aceitava texto, e o jeito era o botão de anexar ou arrastar o arquivo. Agora o print copiado (⌘⌃⇧4) ou uma imagem copiada do navegador vira anexo na hora, como no botão de anexar: o arquivo vai para `~/.harness/anexos`, com nome `print-<data>-<hora>.png`, e o caminho entra na mensagem para o agente abrir.
- **Vale também com o foco no terminal.** No terminal de um agente, o print vai para a barra do próprio painel. No terminal comum, o caminho é colado direto, como no arrastar.
- Quando a colagem traz texto, o texto continua valendo. Um trecho copiado de planilha ou do Word leva junto uma imagem dele, e não vira anexo.

## v1.0.1 · o aviso de núcleo antigo some ao reiniciar

- **O aviso "o núcleo em execução é a v0.9.9" não sumia na 1.0.0,** nem depois de reiniciar o núcleo. O núcleo já era o da 1.0.0, mas continuava dizendo que era o 0.9.9, porque o número dele estava escrito num segundo lugar que ficou para trás no lançamento. Agora o núcleo lê a própria versão do mesmo lugar que o lançamento atualiza, e um teste falha se o núcleo e o app ficarem com números diferentes.

## v1.0.0 · a MÊTIS no lugar do Orca e do Maestri

A primeira versão estável. Antes dela, tudo o que entrou da v0.9.6 à v0.9.8 (git e GitHub, editores, agentes e terminal, navegador, conectores e kanban, automações, perfis, backup, Skills e estudo) passou por uma revisão de código, PR por PR, e o que ela achou foi corrigido. Ficaram 72 testes novos, 463 no total.

- **Janela com os botões do macOS:** vermelho, amarelo e verde de verdade, com tela cheia pelo botão verde, por ⌃⌘F e pelo menu Visualizar. Em tela cheia a barra começa na borda.
- **Escritório final da Sala dos agentes**, de dia e de noite, com a pixel art nítida.
- **Rotinas voltaram a ser só abrir o agente:** a rotina abre o terminal com o pedido e já conta como rodou. Antes ela esperava o agente "devolver a saída" por 2 horas e virava erro (foi o que aconteceu com o check-in da Aurora), além de segurar a vaga das automações. O pedido vai exatamente como foi escrito, e uma automação comum com "Rotina" no nome não vai mais parar na tela Rotinas.
- **Seus dados mais protegidos:**
  - Importar um backup não apaga mais as contas dos conectores nem as variáveis de ambiente e os segredos que já estão no Mac.
  - O backup não troca mais por `<SEGREDO REMOVIDO>` palavras como "task-…" ou "risk-…".
  - Uma Skill com nome `..` não consegue mais mandar o `~/.claude` para a Lixeira.
- **Git sem perder trabalho:**
  - No conflito do Sincronizar, "nosso" volta a ser a mudança deste branch (estava invertido durante o rebase).
  - Resolver bloco a bloco não reescreve mais o arquivo inteiro, nem o fim das linhas nem os acentos.
  - O push forçado não apaga mais o commit de um colega que chegou só pela busca automática do painel.
- **Editores sem perder texto:**
  - O que você digitou é gravado ao sair da nota.
  - Uma gravação que falha não fica tentando sem parar.
  - A sua gravação não passa por cima do que o agente acabou de salvar.
  - Arquivos fora do UTF-8 abrem só para leitura, em vez de serem corrompidos.
  - ⌘⇧K volta a apagar a linha dentro do editor.
- **Aprovação mais segura:**
  - Ferramenta de MCP externo sem a marca de "só leitura" volta a pedir aprovação (antes passava pelo nome, como `query`).
  - No navegador, rodar JavaScript na página ou digitar e enviar um formulário pede aprovação.
  - No teste de uma automação, um passo Código marcado como "escreve" não roda de verdade.
- **Terminal:**
  - Um texto no terminal não consegue mais ler a sua área de transferência.
  - Acordar um agente hibernado não faz ele dormir de novo 30 s depois, e agente com servidor de dev aberto não hiberna.
  - "Copiar o ID da conversa" funciona, e com dois Codex na mesma pasta cada um acha a sua conversa.
  - O `/` da barra prefere o comando que você digitou inteiro.
- **Navegador:** `navegador_js` funciona em sites que bloqueavam o código, como o GitHub e o Google, e uma aba aberta logo ao iniciar usa o perfil certo.
- **Conectores e kanban:**
  - Conectar o GitHub pelo login do `gh` volta a funcionar.
  - Mudar os rótulos de uma tarefa não muda mais o número dela nem marca como feita uma tarefa cancelada.
  - A agenda de um dia mostra os eventos daquele dia.
  - O MCP que demora a iniciar não fica preso pela metade.
- **Mais leve:** o fim de turno dos agentes não trava mais o núcleo enquanto lê a conversa, o painel de agentes só relê o que mudou, e o painel de git roda metade dos processos.

## v0.9.9 · as telas dos mockups e o kanban do jeito certo

- **Agentes:** abre na **Sala dos agentes**, agora a casa de trabalho dos agentes: o escritório animado (de dia das 6h às 18h, de noite no resto) cobrindo a sala inteira, com cada agente de corpo inteiro na sua mesa (as 9 mesas, a mesa redonda e o mosaico); cada agente fica na sua mesa, com as pernas atrás do móvel, e com o movimento parado da própria sprite (respira e pisca), o nome embaixo, o balão quando trabalha ou espera você e a sprite no estado (trabalhando, esperando você, dormindo, concluiu, erro). Agente novo aparece na primeira mesa livre; arrastar leva o agente para qualquer lugar da sala, e soltar perto de uma mesa faz ele sentar nela (com a mesa ocupada, os dois trocam); dois cliques abrem o terminal. As sprites ficaram bem maiores e as mesinhas saíram. Lembra o último agente aberto (não volta mais sempre para o primeiro). À direita, as propriedades, a missão, a última mensagem, Abrir terminal e Editar. Apagar um agente direto da sala: a lixeira ao passar o mouse na lista ou o botão ao lado de Editar, com confirmação; o arquivo e a sprite vão para a lixeira dos agentes.
- **Conectores:** cartões das contas e abas Conectados, Catálogo, Permissões por agente e Atividade. No painel do conector, cada ferramenta com o seu modo: **livre, pede aprovação ou desligada** (a desligada some dos agentes). A tabela de permissões libera ou tira uma conta de um agente com um clique.
- **Kanban novo**, no jeito do CodeAgentSwarm: Pendente, **Auto**, Em andamento, Em teste e Concluído (recolhido), com as tarefas de todos os projetos, busca e filtro de projeto. Arraste uma tarefa para **Auto** (ou use o ⚡): escolha Claude, Codex ou um agente, o modelo, o raciocínio, a permissão e se roda numa worktree nova ou na pasta do projeto. Ela começa sozinha (até 1 a 4 por vez), vai para Em andamento e, quando o agente termina, para Em teste, esperando a sua revisão.
- **Arrastar cartão** reescrito para a janela do app (WebKit), no kanban e no Hoje.
- **Hoje:** resumo do dia, caixa do Hermes, mini-kanban dos projetos (arraste para mudar o estágio), grafo por projeto, precedente sugerido e os cartões Agentes, Rotinas, Uso dos planos e Conectores.
- **Brain:** árvore do vault e busca à esquerda, abas com o grafo de sempre (zoom, arrasto, filtros, áreas e forças; a busca acende as notas achadas) e as notas, a nota à direita com propriedades, backlinks e onde mais ela serve, e a gaveta de conversas com os agentes embaixo, que fica do tamanho da caixa de pergunta quando não há conversa aberta.
- **Estudo:** a nota da aula no centro e o Sócrates ao lado. As perguntas que o Sócrates escreve na nota viram formulário (alternativas, confiança e o seu raciocínio); responder manda para ele e marca a alternativa na nota. Foco (Pomodoro), O que eu sei e Plano viraram abas; o placar fica à esquerda.
- **Terminais:** cada terminal de agente tem a própria barra de entrada (anexar, trocar o modelo, ditar, enviar); a barra lateral ganhou Tarefas e Rotinas no topo e sessões numa linha só; o painel da direita tem abas de ícone e a aba do Brain com precedentes, aprovação e grafo local.
- **Editor de código** abre na hora: o Monaco carrega em segundo plano depois que a MÊTIS abre.
- **Avisos do macOS com o ícone da MÊTIS**, como os do Orca: saem pela Central de Notificações em nome do app (não mais pelo Editor de Scripts), e clicar no aviso abre a sessão, a aprovação ou a automação. Com a janela fechada, o núcleo avisa pelo próprio app. Na primeira vez, o macOS pergunta se a MÊTIS pode mandar avisos; Ajustes → Agentes e avisos mostra o estado e tem "Testar aviso". O app passa a sair assinado (assinatura local, sem conta da Apple), porque o macOS não deixa app sem assinatura mandar aviso.
- **Uso dos modelos** (Ajustes → Contas e uso, ou clicando no uso na barra de baixo): quanto cada modelo gastou hoje, em 7 ou em 30 dias, em tokens (entrada, saída, cache gravado e lido) e em custo equivalente em API, com o gráfico por dia, a tabela por modelo e o gasto por projeto. Conta também as sessões abertas fora da MÊTIS: lê os registros que o Claude Code e o Codex gravam no Mac, sem rede e sem credencial. A barra de baixo mostra o gasto de hoje, e clicar nela abre uma janela suspensa com as barras de uso do plano de cada conta (5 horas e semana, quanto falta para zerar), o gasto de hoje por modelo e o atalho para o painel completo; o limite do Claude (5h e 7d) agora sobrevive a reiniciar o núcleo e mostra quando foi visto.
- **Sprites no modelo da MÊTIS, com movimento parado:** o GPT desenha uma folha com 4 quadros do mesmo personagem (normal, respirando, normal, piscando) e a MÊTIS reduz os quatro com a mesma grade, as mesmas cores e o mesmo chão, e anima em loop na sala, no painel e no chat da sprite. O pedido já diz que o personagem fica na mesa do escritório (luz, ângulo, pés no chão). Toda sprite nova sai no mesmo modelo, a referência que você escolheu (corpo inteiro, chibi greco-romano, pixel art com contorno preto e fundo transparente), com as características que você pedir (cabelo, roupa, cores, o que segura). Quem desenha é sempre o GPT, pela ferramenta de imagem do Codex com o seu plano; imagem feita de outro jeito é recusada. A MÊTIS acha a grade de pixels do desenho e deixa em pixel art de verdade nela (uns 40 × 80 pixels), em vez de espremer em 48 × 48. O modelo aparece no chat da sprite.
- **Projetos e workspaces no jeito do Orca:** o cabeçalho de Projetos tem filtro, Adicionar projeto e Novo workspace juntos à direita, com ícones maiores (e a fileira "novo em" sem as caixinhas). **Adicionar projeto** abre um diálogo com "Abrir pasta" (o seletor de pasta do macOS), os repositórios que já estão no seu Mac com um clique (os mais mexidos primeiro), clonar de uma URL, criar um projeto novo (pasta com git, README e o primeiro commit) e digitar o caminho. **Novo workspace** (⌘N, ou o + de cada projeto) abre um diálogo com o projeto, de onde sai (branch novo, branch existente ou commit), o nome, o que abre nele (Claude Code, Codex, um agente seu, um terminal ou nada), o pedido inicial para o agente, o avançado (copiar o .env) e "Criar mais". Saíram a caixinha de caminho e o formulário apertado dentro da árvore.
- **Ícones oficiais do Claude e do Codex** no lugar de ✻ e ◇: na barra de baixo, na janela do uso, no painel de uso, nas contas, na barra lateral (criar terminal e sessões), nas abas, no histórico, no kanban, nos quadros, nas automações e nos diálogos. O terminal comum segue como `>_`.
- **Logos nos Conectores:** cada ferramenta aparece com o logo dela (Slack, ClickUp, Notion, GitHub, Google, n8n e dezenas de outras, reconhecidas pelo nome ou pelo endereço do MCP), nos cartões, no catálogo, no painel, nas permissões, na atividade, nos MCPs do Claude e do Codex e no cartão do Hoje.

## v0.9.8 · o que o MAPA prometeu (em cinco partes)

### Parte 5 · código e estudo

- **Checks falhos ao agente:** no cartão do PR, o botão leva ao agente da worktree os checks que falharam (do PR, ou do último commit sem PR) com o fim do log de cada um, para consertar.
- **Revisão de PR por IA, só leitura:** "Revisar com IA" abre um Claude (em modo plano) ou um Codex (sandbox só leitura) que lê o diff e o repositório e lista os problemas por gravidade, com arquivo e linha. Não edita, não faz commit e não comenta no GitHub: a revisão fica no terminal.
- **Grafo do código pelo MCP:** numa worktree com o grafo do graphify, os agentes ganham na central as ferramentas de consultar o grafo (buscar, caminho entre dois pontos, explicar um nó). Na aba Arquivos, o tamanho e a idade do grafo, "atualizar" (reextrai o código mudado, sem IA) e "gerar com o agente" (o `/graphify` pelo seu plano).
- **Estudo completo,** em três abas. **Foco:** a semana do cronograma, com revisar os conceitos vencidos, medir o que você sabe e praticar, cada um abrindo uma sessão com o Sócrates. **O que eu sei:** cada conceito é uma nota em `01-PROJETOS/<projeto>/conceitos`, com domínio (de "não vi" a "consigo ensinar"), acertos e erros, próxima revisão (revisão espaçada) e se a sua confiança bate com o acerto; abrir a nota, aprender um conceito ou criar outro. **Plano:** a tabela do cronograma da nota do projeto, com a semana de agora em destaque. O Sócrates registra cada resposta pela central; nota permanente continua só com a sua destilação.
- **Perfis** (Ajustes → Perfis e backup): cada perfil é uma MÊTIS separada (ex.: Pessoal e Seller Pro), com pasta, núcleo, senhas no Keychain e, se quiser, Brain próprios. Trocar fecha os terminais do perfil atual e reabre a MÊTIS no outro; o perfil em uso aparece na barra de título.
- **Backup:** exportar a configuração (ajustes, atalhos, comandos, projetos, agentes com as sprites, automações, rotinas, temas e o registro do estudo) num .zip em Downloads, sem senha nem token; conferir o que um backup traz antes de importar, e importar guardando antes um backup automático de agora.
- **Skills:** instalar de um repositório git, de uma pasta ou de um .zip no Claude, no Codex ou no projeto; atualizar pela origem, exportar em .zip para compartilhar, copiar para a outra CLI, mostrar no Finder e mandar para a Lixeira.

### Parte 4 · automações

- **Passo Código:** Python ou JavaScript rodando no Mac, sem gastar cota; o Claude escreve a partir da descrição.
- **Gatilhos novos:** evento da MÊTIS (nota nova no Brain, tarefa mudou de coluna, agente terminou ou errou, worktree criada, captura rápida) e novidade num conector (sondagem de uma ferramenta de tempos em tempos).
- **Troca por cota:** o passo de agente roda no outro provedor quando a janela de 5 h passa de 80%, e a troca aparece na execução. Nos terminais, a mesma conta acima de 80% sugere passar o trabalho para a outra CLI.
- **Criar e ajustar por frase:** o Claude monta (ou muda) a automação; a proposta aparece tracejada no canvas e só vai para o rascunho quando você aplica.
- **Importar do n8n:** um workflow colado (ou lido de um n8n ligado em Conectores) vira automação, com o que não tem igual marcado para revisar.
- **Estratégias de agentes:** explorar e construir, planejar e executar, melhor de N e portão de revisão, prontas para preencher.
- **Rotinas viraram automações** de um gatilho e um agente, com a recuperação e o aviso no Slack de antes; a tela Hoje continua igual.

### Parte 3 · conectores e kanban

- **Conectores novos:** Notion (MCP oficial, login no navegador), GitHub (MCP oficial, com o login do `gh` ou um token), Google (Gmail, Agenda e Drive pelas APIs do Google, com o cliente OAuth do Pedro) e **MCP próprio**: qualquer servidor por endereço (com login, token ou nada) ou por comando, ou um achado no **catálogo oficial de MCP**. Os logins se renovam sozinhos.
- **Testar conexão** de cada conta: responde ou não, quantas ferramentas e em quanto tempo.
- **MCPs do Claude e do Codex** lado a lado, com **copiar de um para o outro** pela própria CLI.
- **Kanban:** **rótulos** (`#etiqueta`) com filtro, **subtarefas** marcadas e criadas no cartão, a **lista do ClickUp** do projeto numa coluna (mudar o status muda no ClickUp, trazer para as Próximas ações, executar com agente) e o **painel de agentes** (precisa de você, trabalhando, feito, parado).
- **Atividade dos agentes:** quem está aberto, há quanto tempo e quanto custou, e a linha do tempo do que cada um fez (terminou, perguntou, saiu), com a prévia.
- **Cota dos planos no Hoje**, por conta do Claude e do Codex.

### Parte 2 · navegador e tela

- **O agente usa o navegador da MÊTIS** pela central de MCP: abrir, ler a página (com refs para clicar), clicar, digitar, teclas, listas, rolar, esperar, foto da tela, console, rede e JavaScript. Cada ação mostra o cursor "agente" andando até o alvo, e a aba ganha o chip "agente". A aba que o agente abre entra na lista sem tirar você do que está vendo.
- **Perfis do navegador** (Ajustes → Navegador): cada um com os próprios cookies e logins; o perfil das abas novas e o de cada aba (na barra de endereço). **Importar cookies do Chrome** (e do Brave, Edge e Arc) para um perfil, com o macOS pedindo licença para ler a chave.
- **Emulação de aparelho** na barra da aba: iPhone, Android, iPad ou notebook, com o tamanho da tela e o user agent; encolhe com zoom quando não cabe no painel.
- **⌘K com endereços e histórico:** digitar um endereço oferece abrir; as páginas visitadas aparecem ao digitar. Os links do terminal (⌘ + clique) abrem na MÊTIS ou no navegador do Mac, como preferir.
- **Barra lateral:** filtro por nome e por estado (esperando você, trabalhando, com mudanças), worktrees fixadas no topo, apelido para a worktree e nome novo para o terminal (duplo clique), cor por projeto.
- **Worktree a partir de um branch que já existe** (local ou do remoto) **ou de um commit**, no formulário e no `metis worktree nova --branch/--commit`.
- **Temas por prompt e importados do VS Code e do Obsidian** (Ajustes → Aparência), com o contraste conferido e corrigido. **Fontes** da interface e do terminal, **tamanho da letra** do terminal, **densidade** e **zoom da janela** (⌘+, ⌘-, ⌘0).

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
