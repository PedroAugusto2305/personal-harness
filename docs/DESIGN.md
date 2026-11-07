# MÊTIS: direção visual

> O app se chamava Personal Harness até 2026-11-07. Folha de marca completa: https://claude.ai/artifact/5DNZE4R1Fo8TXs3UT5HxU5

## Marca

- **Nome:** MÊTIS, em caixa alta e com acento; `metis` no terminal e no código. Assinatura: **Inteligência em ação.** Descrição curta: **O ambiente pessoal onde agentes, projetos e memória trabalham juntos.**
- **Símbolo (variante C, Partes):** um M em meandro numa grade de 7 × 7 em que o traço e o vão têm a mesma largura (1 unidade). Dois arcos na cor do texto e o vale do meio suspenso em `acento`, separados por um corte de 0,35 unidade. Cantos retos, sem curva, diagonal ou gradiente. Arquivos: `docs/marca/metis-simbolo.svg` e `docs/marca/metis-icone.svg` (fonte dos ícones de `app/src-tauri/icons`, gerados com `npx tauri icon`). No app: `MetisMark` em `app/src/icons.tsx`.
- **Ícone do app:** escuro (`#1e1f29`) nos três temas, símbolo a 58% do quadrado. Na barra de menu, uma cor só.
- **Logotipo:** as letras desenhadas na mesma grade do símbolo; o acento do Ê é um pedaço de meandro em `acento`. Na interface, o nome vai em texto (Inter 600, espaço de 0,06 em entre as letras).
- **Fica de fora:** colunas, templos, bustos, elmos, louros, corujas, cérebro com circuitos, robô, infinito, estrela de quatro pontas, órbitas e gradiente neon.

> **Estado:** proposta, a validar com o Pedro. **Atualizado em:** 2026-11-07.
> Construída a partir das referências em [`../refs.md`](../refs.md) e do visual que o Pedro já usa no Orca.
> **Mockups:** cinco direções (A Cabine, B Foco, C Hoje, D Quadro livre, E Sala dos agentes) em https://claude.ai/artifact/LAFQ8F9HdM9XGpMpfA5KaG. O acento de cada uma muda no painel Tweaks (âmbar, índigo, verde).

## 0. Direção atual (2026-11-07, segunda rodada)

O Pedro pediu uma mistura de **Alethe + Orca + Obsidian**, em **tons de cinza e azul, quase um Drácula**, sem botões verdes ou amarelos, e com **troca de tema nos ajustes, inclusive criando tema por prompt**. Esta seção substitui os tokens, a tipografia com serifa e o acento âmbar das seções 2 e 3.

| Vem de | O que entra |
|---|---|
| Orca | Cinza neutro, árvore de projetos com worktrees e agentes em linhas (modelo e tempo em mono), caixa de mensagem arredondada com "Acesso total", modelo e microfone, barra de status com o uso de cada plano |
| Obsidian | Faixa de ícones à esquerda, explorador de arquivos, abas, propriedades, callouts, `[[links]]` e tags em pílula, painel de backlinks, grafo, Canvas com cartões de borda colorida |
| Alethe | Densidade de IDE, contorno no painel ativo, chips na barra de título (tema, memória) |

**Tema padrão "Drácula azul":**

| Token | Valor | Uso |
|---|---|---|
| `barra` | `#191a21` | Barra de título, faixa de ícones, barra de status |
| `painel` | `#21222c` | Barras laterais, caixa de mensagem |
| `fundo` | `#282a36` | Conteúdo |
| `superfície` | `#343746` | Cartões, chips |
| `borda` / `borda-forte` | `#3b3e4f` / `#44475a` | Linhas e contornos |
| `terminal` | `#1e1f29` | Fundo dos terminais |
| `texto` / `texto fraco` / `rótulo` | `#f8f8f2` / `#a9aec9` / `#8f95b2` | Texto |
| `acento` / `acento-texto` | `#82a0ff` / `#a9bcff` | Botão principal, seleção, links, painel ativo |
| `trabalhando` | `#8be9fd` | Status de agente rodando |
| `esperando você` | `#bd93f9` | Status que pede atenção |
| `alerta` / `erro` | `#ff79c6` / `#ff5555` | Cota alta, falha, gravando |

- **Tipografia:** Inter na interface, Fira Code nos terminais, caminhos, modelos e números. Sem serifa.
- **Sprites:** camisas e acessórios na paleta Drácula (roxo, ciano, rosa, azul).
- **Temas prontos:** Drácula azul (padrão), Grafite (neutro, como o Orca) e Claro.

**Tema por prompt.** Em Ajustes → Aparência:
1. Você descreve o tema em texto.
2. Um agente (Claude ou Codex) devolve os tokens no formato acima, em `themes/<nome>.json`, e opcionalmente o tema do terminal.
3. O Harness confere o contraste: 4,5:1 para texto e 3:1 para borda e ícone. Se algum token falhar, ele devolve ao agente para ajustar antes de mostrar.
4. Você vê a prévia, aplica, ajusta com outro prompt ou salva.

Também dá para importar temas do Obsidian, do VS Code e do Ghostty. Como toda a interface usa tokens, trocar o tema troca o app inteiro. Nos mockups, o painel Tweaks troca entre os três temas prontos, e a prancha de Ajustes é clicável.

## 1. O que as referências têm em comum

| Referência | O que levar |
|---|---|
| **LearnHarness: sessão de aula** | Fundo quase preto e neutro; **título em serifa** grande; texto de leitura em sans; **rótulos e metadados em monoespaçada, caixa alta pequena**; lista de sessões com linha de status em mono ("esperando você · agora"); bloco "agentes em segundo plano" com tempo e custo; barra inferior com contexto e custo (`83.7k / 1M · $0.17`), gravação com onda sonora e botão vermelho "Parar", modelo e esforço em pílulas; mini-mapa do plano no canto com o nó atual em âmbar |
| **LearnHarness: grafo de conhecimento** | Grafo como **céu estrelado**: pontos pequenos, linhas finas, **nuvens de cor suave por assunto**, rótulos em mono tingidos; barra flutuante de pílulas (buscar, cadeias, importar, ajustes); campo grande arredondado embaixo com "Ditar", modelo e esforço |
| **Alethe: janela no macOS** | Densidade de IDE nos terminais; barra lateral com projetos em árvore, bolinha de cor por grupo e contadores; cabeçalho do painel com ícone do agente, **caminho em chip mono** e bolinha de status; **contorno de destaque no painel ativo**; perfil e memória usada na barra de título; interface em português |
| **Alethe: canvas de orquestração** | Cartões de etapa com `modelo · esforço` em mono; losangos de decisão; seta verde para "sim" e tracejada para "não"; **alternativa fantasma** ("se Claude baixo → Codex"); painel de detalhes à direita com seções em caixa alta; chips de cota por provedor (38%, 26%) |
| **CodeAgentSwarm** | Kanban ao lado dos terminais, com os agentes movendo os próprios cartões |
| **Seu Orca hoje** | Tema escuro, **Fira Code**, barra lateral `#18181b`, divisórias `#3f3f46` (paleta zinco), painel inativo a 90% de opacidade, transição de 140 ms |

**Síntese:** escuro e calmo; a cor só aparece onde significa alguma coisa; três vozes de tipografia (serifa para conteúdo, sans para leitura, mono para máquina); denso onde se trabalha (terminais, código) e respirado onde se lê (Brain, Hoje, Estudo).

## 2. Tokens

### Cores (tema escuro primeiro; o claro vem depois, com os mesmos nomes)

| Token | Valor | Uso |
|---|---|---|
| `fundo` | `#0f0f10` | Fundo do app |
| `painel` | `#141416` | Barra lateral, painéis |
| `superficie` | `#18181b` | Cartões, campos (o zinco do seu Orca) |
| `borda` | `#27272a` | Bordas finas |
| `borda-forte` | `#3f3f46` | Divisórias e hover (a divisória do seu Orca) |
| `texto` | `#e4e4e7` | Texto principal |
| `texto-fraco` | `#a1a1aa` | Texto secundário |
| `texto-mudo` | `#8e8e98` | Metadados, rótulos. O `#71717a` do zinco não passa 4,5:1 em letra pequena sobre o fundo |
| `acento` | `#f2c94c` | Foco, seleção, nó atual, ligação entre projetos no grafo |
| `sucesso` | `#4ade80` | Check passou, "sim" no fluxo |
| `atencao` | `#fb923c` | Cota acima de 80%, aprovação pendente |
| `erro` | `#f87171` | Falha, gravando |
| `info` | `#60a5fa` | Links, dicas |
| `claude` | `#d97757` | Só no ícone e na bolinha do agente Claude |
| `codex` | `#e4e4e7` | Só no ícone do Codex |

**Nuvens do grafo por área** (dessaturadas, com brilho suave): Carreira e estudo em oliva, trabalho em azul-petróleo, clientes em roxo, pessoal em rosa e Brain e sistema em verde. As ligações **entre** projetos (os precedentes) aparecem em `acento`: é a inteligência entre projetos ficando visível.

### Tipografia

| Voz | Fonte proposta | Onde |
|---|---|---|
| Máquina | **Fira Code** (você já usa) | Terminais, rótulos em caixa alta (11 px, espaçamento 0,08 em), caminhos, números, status |
| Leitura | **Inter** | Texto de interface e de notas |
| Conteúdo | **Source Serif 4** | Títulos de nota, de projeto, do painel Hoje, do Estudo |

### Forma e movimento

- Raio: 12 px em cartões e painéis, pílula (999 px) em botões e chips.
- Borda de 1 px e quase nenhuma sombra. Foco: borda `acento` mais um brilho leve, como o painel ativo do Alethe.
- Painel inativo a 90% de opacidade. Transições de 140 ms, como no seu Orca.

## 3. Padrões de tela

1. **Barra lateral.** Seções em mono caixa alta (PROJETOS, AGENTES, BRAIN). Projetos em árvore com a bolinha da área. Sessões com linha de status em mono. Rodapé "agentes em segundo plano" com tempo e custo, e a conta ativa.
2. **Painel de terminal.** Cabeçalho com ícone do agente, nome do papel, caminho em chip mono, bolinha de status (rodando, esperando você, parado) e ações (abrir no editor, expandir). Contorno `acento` no painel ativo.
3. **Barra de entrada.** Campo grande arredondado com enviar à direita. Embaixo, pílulas: 🎙️ Ditar (vira onda sonora e "Parar" em vermelho enquanto grava), 📎 anexo, modelo, esforço e `@nota`.
4. **Barra de status.** Contexto e custo da sessão (`83,7k / 1M · US$ 0,17`), chips de cota de 5 h e 7 dias por provedor (ficam laranja acima de 80%) e memória usada pelo app (importa no seu Mac Intel).
5. **Grafo do Brain.** Céu estrelado com nuvens por área, rótulo do projeto em mono e ligações entre projetos em âmbar. Barra flutuante: buscar notas, caminhos, filtros (decisão, incidente, aprendizado), ajustes.
6. **Mini-mapa.** No canto do terminal, o pedaço do grafo ligado à sessão: os precedentes em uso, com o projeto atual em âmbar.
7. **Canvas de fluxo.** Para rotinas e orquestração: cartões de etapa com `modelo · esforço`, losangos de decisão, alternativa fantasma por cota e painel de detalhes à direita.
8. **Kanban.** Colunas de estágio para projetos; Pendente, Em andamento, Em teste e Concluído para tarefas. Cartões com rótulos, contadores e a bolinha do agente que está trabalhando neles.
9. **Cartão interativo.** Pergunta com opções e barra de confiança (do LearnHarness), usado no Estudo e nas aprovações de conector.

## 4. Sprites dos agentes (pixel art)

Cada agente tem um personagem em pixel art. É o único lugar do app onde a cor e a brincadeira entram de propósito, e isso contrasta bem com a interface sóbria.

| Regra | Valor |
|---|---|
| Grade | 32 × 32 pixels, corpo inteiro, vista de frente ou 3/4 |
| Paleta | Até 16 cores, com a cor do agente como cor principal; contorno escuro de 1 px |
| Fundo | Transparente |
| Exibição | Só em múltiplos inteiros (2×, 3×, 4×), com `image-rendering: pixelated`, para o pixel não borrar |
| Onde aparece | Barra lateral, cabeçalho do terminal (com um selinho pequeno da CLI: Claude ou Codex), cartões do kanban (quem está trabalhando), Hoje |

**Como nasce:**
1. No "Novo agente", o Harness pede ao Codex (`codex exec` com geração de imagem) 4 variações a partir da descrição do agente e deste guia.
2. O Harness **pixeliza** o resultado: encaixa numa grade de 32 × 32, reduz a paleta e limpa o fundo. Modelo de imagem costuma fazer "pixel art falsa", com pixels de tamanhos diferentes; esse passo garante que todos pareçam do mesmo jogo.
3. Você escolhe uma variação ou pede outra rodada. O arquivo fica em `agents/<nome>/sprite.png`, junto com o prompt usado.
4. Sem Codex disponível, o Harness desenha um personagem simples a partir do nome, para nenhum agente ficar sem rosto.

**Estados animados** (feitos por código em cima do sprite parado, então o personagem nunca muda de cara):

| Estado do agente | Animação |
|---|---|
| Parado | Respira: sobe e desce 1 pixel |
| Trabalhando | Balança mais rápido, com faíscas de digitação |
| Esperando você | Balão com "!" piscando em `atencao` |
| Dormindo (hibernado) | "zzz" subindo |
| Concluiu | Pulinho e confete de 3 cores |
| Erro | Treme, com fumacinha |

Fica para depois da 1.0: uma folha de sprites com quadros desenhados de verdade, mais difícil de manter coerente entre quadros, e uma "sala dos agentes", com cada personagem na sua mesa mostrando o que está fazendo.

## 5. O que evitar

- Gradientes coloridos, vidro fosco exagerado e muitas cores de marca.
- Ícones grandes e decorativos.
- Tela vazia sem orientação: todo estado vazio diz o que fazer (a tela do Alethe mostra um painel inteiro vazio).

## 6. Perguntas para o Pedro

1. Serifa nos títulos de conteúdo (como no LearnHarness), ou só mono e sans?
2. Acento âmbar, ou o índigo do Alethe?
3. Fira Code também nos rótulos da interface, ou outra mono (JetBrains Mono, como no LearnHarness)?
4. Quer um mockup da tela principal aplicando isto antes de qualquer código?
