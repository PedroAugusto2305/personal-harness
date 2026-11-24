import type { Agent, AgentType } from "../types";

/** v1.5.0: o tipo do agente decide onde o terminal aberto pela tela de Agentes aparece
 * (o de estudo, numa conversa no painel do Estudo; o de trabalho, em Terminais). */
export const TIPO_LABEL: Record<AgentType, string> = { trabalho: "Trabalho", estudo: "Estudo" };

/** Sem o campo (núcleo antigo), o agente é de trabalho. */
export const tipoOf = (agent: Pick<Agent, "tipo">): AgentType => agent.tipo ?? "trabalho";
