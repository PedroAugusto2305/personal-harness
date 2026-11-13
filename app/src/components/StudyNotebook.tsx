import { useEffect, useRef, useState } from "react";
import { BrowserView, type WebInfo } from "./BrowserView";
import { ICON, Icon } from "../icons";
import { browser, openExternal } from "../lib/browser";
import type { CoreClient } from "../lib/core";
import type { BrowserProfile, Notebook, NotebookDetail, NotebookStatus } from "../types";

/**
 * O NotebookLM dentro do Estudo (v1.3.0).
 *
 * - O site de verdade (notebook.google.com) num navegador embutido da MÊTIS, na aba NotebookLM:
 *   cadernos, fontes, chat, resumos em áudio e vídeo, mapas mentais, tudo sem sair da MÊTIS.
 * - A barra de cima lê os cadernos pelo notebooklm-py (o CLI que o Pedro já usa) e escolhe o
 *   caderno do estudo: o Sócrates responde com base nele (ferramentas caderno_* da central).
 * - Ao lado, o resumo do NotebookLM, as perguntas que ele sugere (vão para o Sócrates) e as fontes.
 *
 * O login do site (o WebKit da MÊTIS) e o do CLI (o Chromium do Playwright) são separados: o do
 * site vale para usar o NotebookLM aqui; o do CLI liga o caderno ao Sócrates.
 */

export const STUDY_WEB_LABEL = "estudo-notebooklm";
const SIDE_KEY = "harness.study.notebook.side";
const PROFILE_KEY = "harness.study.notebook.profile";

interface Props {
  client: CoreClient;
  tick: number;
  /** A aba NotebookLM está na tela e nada da interface está por cima (a página nativa fica por cima de tudo). */
  shown: boolean;
  info: WebInfo | undefined;
  profiles: BrowserProfile[];
  defaultProfile: string;
  onDesign: (on: boolean) => void;
  onDevice: (id: string) => void;
  /** Uma pergunta sugerida pelo NotebookLM vai para o Sócrates. */
  onAskTutor: (text: string) => void;
  onError: (message: string) => void;
}

const message = (cause: unknown) => (cause instanceof Error ? cause.message : String(cause));

function stored<T>(key: string, fallback: T): T {
  try {
    const raw = localStorage.getItem(key);
    return raw ? (JSON.parse(raw) as T) : fallback;
  } catch {
    return fallback;
  }
}

function remember(key: string, value: unknown) {
  try {
    localStorage.setItem(key, JSON.stringify(value));
  } catch {
    // sem armazenamento
  }
}

const KIND_LABEL: Record<string, string> = {
  pdf: "PDF",
  youtube: "YouTube",
  web_page: "site",
  website: "site",
  url: "site",
  text: "texto",
  pasted_text: "texto",
  google_docs: "Docs",
  google_slides: "Slides",
  audio: "áudio",
  video: "vídeo",
  image: "imagem",
};

export function StudyNotebook({ client, tick, shown, info, profiles, defaultProfile, onDesign, onDevice, onAskTutor, onError }: Props) {
  const [status, setStatus] = useState<NotebookStatus | null>(null);
  const [books, setBooks] = useState<Notebook[] | null>(null);
  const [detail, setDetail] = useState<NotebookDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<"lista" | "detalhe" | "entrar" | null>(null);
  const [side, setSide] = useState<boolean>(() => stored(SIDE_KEY, true));
  const [profile, setProfile] = useState<string>(() => stored(PROFILE_KEY, defaultProfile));
  const [reload, setReload] = useState(0);
  const fresh = useRef(false);

  useEffect(() => remember(SIDE_KEY, side), [side]);
  useEffect(() => remember(PROFILE_KEY, profile), [profile]);

  // O status (instalado, versão, login e o caderno do estudo), de novo quando o login termina.
  useEffect(() => {
    let alive = true;
    const force = fresh.current;
    fresh.current = false;
    client
      .notebookStatus(force)
      .then((value) => alive && (setStatus(value), setError(null)))
      .catch((cause) => alive && setError(message(cause)));
    return () => {
      alive = false;
    };
  }, [client, tick, reload]);

  const logged = !!status?.logado;
  const chosen = status?.caderno ?? { id: "", titulo: "", url: "https://notebook.google.com" };

  useEffect(() => {
    if (!logged) {
      setBooks(null);
      return;
    }
    let alive = true;
    setBusy("lista");
    client
      .notebooks(reload > 0)
      .then((value) => alive && setBooks(value))
      .catch((cause) => alive && setError(message(cause)))
      .finally(() => alive && setBusy(null));
    return () => {
      alive = false;
    };
  }, [client, logged, reload]);

  useEffect(() => {
    if (!logged || !chosen.id || !side) {
      setDetail(null);
      return;
    }
    let alive = true;
    setBusy("detalhe");
    client
      .notebook(chosen.id)
      .then((value) => alive && setDetail(value))
      .catch((cause) => alive && setError(message(cause)))
      .finally(() => alive && setBusy(null));
    return () => {
      alive = false;
    };
  }, [client, logged, chosen.id, side]);

  const choose = async (id: string) => {
    const book = books?.find((b) => b.id === id);
    try {
      const next = await client.chooseNotebook(id, book?.titulo ?? "");
      setStatus((current) => (current ? { ...current, caderno: next } : current));
      // O site vai junto para o caderno escolhido.
      if (browser.available() && info) await browser.navigate(STUDY_WEB_LABEL, next.url).catch(() => undefined);
    } catch (cause) {
      onError(message(cause));
    }
  };

  const login = async () => {
    setBusy("entrar");
    try {
      const entrando = await client.notebookLogin();
      setStatus((current) => (current ? { ...current, entrando } : current));
    } catch (cause) {
      onError(message(cause));
    } finally {
      setBusy(null);
    }
  };

  const refresh = () => {
    fresh.current = true;
    setReload((n) => n + 1);
  };

  const entering = !!status?.entrando?.rodando;
  const loginFailed = status?.entrando && status.entrando.ok === false ? status.entrando.erro : null;

  return (
    <div className="snb">
      <div className="snb-bar">
        <span className="snb-brand">
          <Icon d={ICON.study} size={14} />
          NotebookLM
        </span>
        {status === null ? (
          <span className="small snb-note">conferindo o NotebookLM…</span>
        ) : logged ? (
          <select
            className="web-select snb-pick"
            value={chosen.id}
            disabled={!books}
            onChange={(event) => void choose(event.target.value)}
            title="O caderno que o Sócrates usa como base das respostas"
            aria-label="Caderno do estudo"
          >
            <option value="">{books ? "Sem caderno: o Sócrates explica por conta própria" : "lendo os cadernos…"}</option>
            {chosen.id && !books?.some((b) => b.id === chosen.id) && <option value={chosen.id}>{chosen.titulo || chosen.id}</option>}
            {books?.map((b) => (
              <option key={b.id} value={b.id}>
                {b.titulo}
              </option>
            ))}
          </select>
        ) : entering ? (
          <span className="small snb-note">Termine o login do Google na janela do Chromium que abriu; a MÊTIS confere sozinha.</span>
        ) : (
          <>
            <span className="small snb-warn" title={status.erro ?? undefined}>
              {loginFailed ? `O login não terminou: ${loginFailed}` : (status.erro ?? "O NotebookLM não está ligado ao Sócrates.")}
            </span>
            {status.instalado && status.versao_ok && (
              <button type="button" className="btn primary" disabled={busy === "entrar"} onClick={() => void login()} title="Abre o login do Google do notebooklm-py, que liga os cadernos ao Sócrates">
                {busy === "entrar" ? "Abrindo…" : "Entrar e ligar ao Sócrates"}
              </button>
            )}
          </>
        )}
        <span className="grow" />
        {chosen.id && (
          <span className="chip snb-linked" title={`O Sócrates responde com base em «${chosen.titulo || chosen.id}»`}>
            ligado ao Sócrates
          </span>
        )}
        <button type="button" className="icon-btn" aria-pressed={side} title={side ? "Esconder fontes e resumo" : "Fontes e resumo do caderno"} aria-label="Fontes e resumo" onClick={() => setSide((v) => !v)}>
          <Icon d={ICON.panel} size={14} />
        </button>
        <button type="button" className="icon-btn" title="Conferir o login e os cadernos de novo" aria-label="Conferir de novo" onClick={refresh}>
          <Icon d={ICON.refresh} size={14} />
        </button>
      </div>
      {error && (
        <p className="small error-box snb-error">
          {error}{" "}
          <button type="button" className="link-btn" onClick={() => setError(null)}>
            fechar
          </button>
        </p>
      )}
      <div className="snb-body">
        <div className="snb-web">
          <BrowserView
            label={STUDY_WEB_LABEL}
            initialUrl={chosen.url}
            incognito={false}
            info={info}
            profileId={profile}
            profiles={profiles}
            keepAlive={false}
            onProfile={setProfile}
            onDevice={onDevice}
            shown={shown}
            slot="tile"
            focused={false}
            focusUrlSignal={0}
            onFocus={() => undefined}
            onDesign={onDesign}
            onError={onError}
          />
        </div>
        {side && (
          <aside className="snb-side" aria-label="Fontes e resumo do caderno">
            {!logged ? (
              <p className="small snb-hint">
                Use o NotebookLM aqui ao lado como no navegador (o login do Google desta página fica guardado no perfil do navegador da MÊTIS). Para o Sócrates responder com base num caderno, use <b>Entrar e ligar ao Sócrates</b> acima.
              </p>
            ) : !chosen.id ? (
              <p className="small snb-hint">Escolha um caderno acima: o Sócrates passa a explicar com base nas fontes dele, citando de onde veio cada ponto.</p>
            ) : busy === "detalhe" && !detail ? (
              <p className="small snb-hint">lendo o caderno…</p>
            ) : detail ? (
              <>
                {detail.resumo && (
                  <section>
                    <div className="section-title">Resumo do NotebookLM</div>
                    <p className="snb-summary">{detail.resumo}</p>
                  </section>
                )}
                {detail.topicos.length > 0 && (
                  <section>
                    <div className="section-title">Pergunte ao Sócrates</div>
                    {detail.topicos.map((topic) => (
                      <button key={topic} type="button" className="snb-topic" onClick={() => onAskTutor(topic)} title="Manda a pergunta para o Sócrates">
                        {topic}
                      </button>
                    ))}
                  </section>
                )}
                <section>
                  <div className="section-title">Fontes · {detail.fontes.length}</div>
                  {detail.fontes.map((source) => (
                    <div key={source.id} className="snb-source">
                      <span className="snb-kind small mono">{(source.tipo && KIND_LABEL[source.tipo]) || source.tipo || "fonte"}</span>
                      {source.url ? (
                        <button type="button" className="link-btn snb-source-name" title={source.url} onClick={() => void openExternal(source.url!)}>
                          {source.titulo}
                        </button>
                      ) : (
                        <span className="snb-source-name">{source.titulo}</span>
                      )}
                    </div>
                  ))}
                </section>
              </>
            ) : null}
          </aside>
        )}
      </div>
    </div>
  );
}
