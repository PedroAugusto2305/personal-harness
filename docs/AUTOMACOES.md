# Automações: o "n8n" da MÊTIS

> **Estado:** ideia em avaliação, com protótipo de tela. Nada decidido. **Criado em:** 2026-11-08.
> Protótipo no branch `ideia/automacoes` (worktree `~/orca/workspaces/personal-harness/ideia-automacoes`), ícone de fluxo na faixa da esquerda.

---

## 1. Por que não só usar o n8n

As dores abaixo já estão registradas no Brain, nos projetos que rodam no n8n:

| Dor | Onde apareceu |
|---|---|
| Rascunho e publicado confundem: sub-fluxo chamado pelo AI Agent só roda publicado, e o erro volta calado para o modelo | [[A ferramenta da base nunca rodou no AI Agent porque o Call n8n Workflow Tool só roda sub-fluxo publicado]] |
| Editar workflow ativo pelo MCP publica na hora, e o rollback também | [[Editar workflow ativo pelo MCP do n8n publica na hora e o rollback também]] |
| A API não diz em que pasta está o workflow; a guarda vira uma lista de ids no repositório | [[API do n8n não diz a pasta do workflow e a chave do MCP não alcança pastas]] |
| IA é peça avulsa: nome do nó vira nome da ferramenta, `$fromAI` para cada campo, e paga API | [[No Call n8n Workflow Tool 2.2 o nome do nó é o nome da ferramenta]] |
| Testar manda de verdade: não há ensaio para o passo que fala com outras pessoas | uso diário |

## 2. A ideia em uma frase

Um canvas de passos em que **ferramenta é determinística e não gasta cota**, **agente é um terminal de verdade do Claude ou do Codex pelo seu plano**, e tudo mora num **arquivo versionado**, com rascunho e publicada sempre explícitos.

## 3. Os tipos de passo

| Passo | O que faz | Gasta cota? |
|---|---|---|
| **Quando** | Agendado (com regra para o Mac dormindo), evento da MÊTIS (nota nova no Brain, tarefa mudou de coluna, agente terminou ou errou, check do PR falhou), conector por sondagem, captura rápida, `metis rodar <automação>` | não |
| **Ferramenta** | Qualquer ferramenta da central de MCP da `v0.6.0`. Cada conector ligado vira passo, sem programar nada | não |
| **Agente** | Abre o `claude` ou o `codex` interativo num terminal, com pedido, ferramentas liberadas e formato de saída | sim |
| **Código** | Python ou JavaScript local para mexer nos dados. Você descreve, o Claude escreve | não |
| **Condição** | Regra de uma linha, ou pergunta de sim ou não a um agente barato | só na pergunta |
| **Aprovação** | Pausa até você aprovar. Entra sozinha antes de todo passo que fala com outras pessoas (princípio 4) | não |
| **Brain** | Ler, buscar, registrar, ligar notas | não |
| **Esperar** | Um tempo, ou até um evento | não |

## 4. Como funciona por dentro

```
 ~/.harness/automacoes/*.yaml  ──►  motor no núcleo Python  ──►  execuções no SQLite
   (rascunho + versões no git)       agendador + fila              (entrada e saída
                                        │                            de cada passo)
              ┌─────────────────────────┼───────────────────────────┐
              ▼                         ▼                           ▼
   Ferramenta: central de MCP   Agente: terminal (PTY) com    Aprovação: a mesma da
   chama direto, com log        claude/codex interativo,      central (macOS + DM
                                MCP só com o que foi liberado  no Slack)
                                saída volta por `metis saida`
```

1. **Arquivo e versões.** Cada automação é um YAML legível em `~/.harness/automacoes/`, com o histórico num git local. Publicar é gravar uma versão; o motor só roda a **publicada**. Editar, pela tela ou por um agente, só mexe no rascunho. Voltar é publicar uma versão antiga, sempre por ação sua.
2. **Testar roda o rascunho inteiro**, inclusive as sub-automações que ele chama. Não existe "só roda publicado" escondido. No teste, o passo que fala com outras pessoas vira **ensaio**: a mensagem vai para a sua DM.
3. **Agente sem `claude -p`.** A decisão [[Personal Harness roda o Claude Code e o Codex em terminais dentro do app]] continua valendo: o passo abre um terminal igual aos outros, numa aba do grupo Automações, com `--mcp-config` só com as ferramentas liberadas, e manda o pedido montado. A resposta volta quando o agente chama `metis saida` com o JSON. A MÊTIS confere contra o formato combinado; se faltar campo, pede de novo no mesmo terminal (até 2 vezes) e depois marca erro. Dá para abrir a aba e conversar no meio, como na rotina da Aurora.
4. **Cota.** Cada passo de agente grava tokens e quanto da janela de 5 h gastou. A alternativa por cota do `DESIGN.md` vale aqui: acima de 80%, o passo roda no outro provedor, no mesmo nível, e a troca aparece na execução.
5. **Mac dormindo.** Ao acordar, o motor vê o que perdeu e aplica a regra da automação: rodar até um horário limite ou pular. É a regra já decidida em [[Personal Harness é um app de Mac em Python que só roda com o Mac acordado]].
6. **Erro nunca calado.** Execução com erro fica vermelha, avisa no Mac e no Slack e oferece **Pedir conserto** (abre um Claude com o YAML e o log; a correção vai para o rascunho) e **Reexecutar daqui** (com as entradas guardadas, sem rodar de novo o que veio antes).
7. **Criar por frase.** Um Claude num terminal recebe o catálogo de passos (as ferramentas da central e os agentes da galeria) e escreve o YAML. A tela mostra como proposta tracejada; aplicar leva ao rascunho, nunca publica.
8. **Importar do n8n.** Lê o workflow pelo MCP do n8n e traduz nó a nó: nó com conector vira Ferramenta, Code vira Código, AI Agent vira Agente, IF vira Condição. Webhook e HTTP solto ficam marcados para revisar.

Um passo de agente no arquivo seria mais ou menos assim:

```yaml
- id: escrever
  agente: claude          # ou codex, ou um agente da galeria (aurora, alexandria…)
  nivel: padrao           # barato | padrao | forte
  se_cota_acima: { "80%": codex }
  onde: segundo-plano     # ou: visivel
  ferramentas: [pipedrive.ler, brain.buscar]
  pedido: |
    Com os negócios parados ({{negocios}}) e os leads de ontem ({{leads}}),
    escreva um briefing de 5 linhas e um follow-up por negócio.
  saida:
    resumo: texto
    followups[]: { negocio: texto, prioridade: alta|media|baixa, mensagem: texto }
```

## 5. O que ela não substitui

| Caso | Por quê | Saída |
|---|---|---|
| Fluxo de produção 24 h com webhook (Manu 2.0, funil de leads, Guru e Hotmart) | A MÊTIS não abre porta na internet e para quando o Mac dorme | Fica no n8n. Ponte nos dois sentidos: o n8n avisa pelo Slack e a MÊTIS sonda; a MÊTIS chama um workflow do n8n pela ferramenta do MCP dele |
| Volume alto, de minuto em minuto | Cada passo de agente é um terminal e gasta cota do plano | Passo determinístico (Ferramenta, Código) sempre que der; limite de 2 agentes de automação ao mesmo tempo no Mac Intel |
| Atender cliente ou lead | Produto atendendo terceiros num servidor não é uso pessoal do plano | API, como o [[Agente de IA SDR]] já faz |

## 6. Onde entra no roadmap

**Decidido em 2026-11-08:** entra na `v0.9.0`. A paridade restante, que era a `v0.9.0`, passa para a `v0.9.1`. A especificação para quem constrói está na seção 13 do `docs/MAPA.md` da versão atual; este documento fica como a proposta original.

| Versão | Entrega |
|---|---|
| `v0.9.0` | Automações: arquivo e versões, canvas, gatilhos, passos Ferramenta, Agente, Código, Condição, Aprovação, Brain e Esperar, testar com ensaio, execuções, pedir conserto, criar por frase; as rotinas da `v0.7` viram automações |
| `v0.9.1` | Orquestração no mesmo canvas e motor, importar do n8n (proposta) e o resto da paridade com o Orca |

## 7. O que ficou decidido

| # | Pergunta | Resposta |
|---|---|---|
| 1 | Escopo | Automações pessoais e de IA no Mac; o n8n segue com a produção 24 h com webhook |
| 2 | Rotinas e orquestração | Um motor só: as rotinas viram automações na `v0.9.0`; a orquestração usa o mesmo canvas na `v0.9.1` |
| 3 | Rodar na nuvem | Fora por enquanto; verificar antes os gatilhos e se o uso sai do plano |
| 4 | Importar do n8n | Proposta para a `v0.9.1`, depois do motor provado |
| 5 | Visual | A segunda versão do protótipo. Moldura de coluna grega e canvas de mármore foram testados e recusados |

## 8. O protótipo

Tela só de frente, com dados de exemplo na memória: nenhum conector é chamado e nenhum terminal abre.

**Desenho (2026-11-08, segunda versão):** a gramática de editor de nós que faz o n8n ser bom de usar, com a cara da MÊTIS. Do n8n vem a forma de trabalhar: blocos com ícone e o nome embaixo, "+" na ponta de cada saída, "+" e lixeira no meio da ligação, contagem de itens na ligação depois de rodar, painel do passo com Entrada, Parâmetros e Saída (tabela ou JSON, fixar dados), notas no canvas, Editor e Execuções lado a lado. Da MÊTIS vem a identidade: tokens do tema (Drácula, Grafite, Claro), rótulos em Fira Code, conectores como "elementos" de duas letras (Sl, Cu, Pd, Sb, Gh), as sprites greco-romanas nos passos de agente, a faixa de cor na base de cada bloco, notas como callout do Obsidian e expressões `{{…}}` como peças.

Mostra:

- cinco automações de exemplo: briefing comercial (com aprovação antes do Slack do time), placar da Aurora (a rotina como automação), decisão nova → precedentes (evento do Brain), check do PR → conserto (agente forte em terminal visível) e um funil importado do n8n com dois passos sem equivalente;
- o agente como bloco largo com três peças penduradas: **Modelo** (com a alternativa por cota), **Ferramentas** liberadas e **Saída** combinada;
- gaveta "O que acontece depois?" com busca, gatilhos, agentes da galeria, conectores com as ferramentas de cada um (cadeado em quem fala com outras pessoas) e lógica;
- dois cliques num passo abrem o painel com o que entrou, a configuração e o que saiu na última execução;
- passar o mouse num bloco mostra testar só ele, desligar (os dados passam direto) e tirar; Delete tira o escolhido, Esc fecha;
- **Testar automação**: roda passo a passo, pinta as ligações com a quantidade de itens, para na aprovação esperando você e grava a execução; o que fala com outras pessoas vira ensaio;
- **Execuções**: lista à esquerda e o canvas mostrando aquela execução, inclusive um erro de token expirado com "Pedir conserto";
- **Pedir ao Claude** e **Nova automação** por frase, com a proposta tracejada antes de aplicar;
- versões (rascunho e publicada, com a diferença) em Detalhes, e o botão de ativar só depois de publicar.

Para abrir no navegador, sem mexer no app em uso: `cd ~/orca/workspaces/personal-harness/ideia-automacoes/app && npx vite --port 1430 --host 127.0.0.1` e abra `http://127.0.0.1:1430`. O ícone de fluxo fica na faixa da esquerda, logo abaixo de Agentes.
