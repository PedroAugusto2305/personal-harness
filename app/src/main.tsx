import React from "react";
import ReactDOM from "react-dom/client";
import "@fontsource/inter/400.css";
import "@fontsource/inter/500.css";
import "@fontsource/inter/600.css";
import "@fontsource/inter/700.css";
import "@fontsource/fira-code/400.css";
import "@fontsource/fira-code/500.css";
import "@xterm/xterm/css/xterm.css";
import "./styles.css";
import App from "./App";
import { CaptureApp } from "./components/CaptureApp";

// A mesma tela serve à janela principal e à caixinha da captura rápida (⌥Espaço, ?captura=1).
const capture = new URLSearchParams(window.location.search).has("captura");
if (capture) document.body.classList.add("capture-body");

ReactDOM.createRoot(document.getElementById("root") as HTMLElement).render(
  <React.StrictMode>{capture ? <CaptureApp /> : <App />}</React.StrictMode>,
);
