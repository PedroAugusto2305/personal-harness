import { useEffect, useRef, useState } from "react";
import type { Recording } from "../lib/audio";
import { clock } from "../lib/format";

const BAR = 3;
const GAP = 2;
const STEP_MS = 45;

/** Onda da gravação ao vivo: barras que entram pela direita, na altura da voz. */
export function Waveform({ recording }: { recording: Recording }) {
  const canvas = useRef<HTMLCanvasElement>(null);
  const [seconds, setSeconds] = useState(0);

  useEffect(() => {
    const el = canvas.current;
    if (!el) return;
    const ctx = el.getContext("2d");
    if (!ctx) return;
    const levels: number[] = [];
    let frame = 0;
    let last = 0;
    let width = 0;
    let height = 0;

    const resize = () => {
      const ratio = window.devicePixelRatio || 1;
      width = el.clientWidth;
      height = el.clientHeight;
      el.width = Math.round(width * ratio);
      el.height = Math.round(height * ratio);
      ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
    };
    const observer = new ResizeObserver(resize);
    observer.observe(el);
    resize();

    const color = getComputedStyle(document.documentElement).getPropertyValue("--acc").trim() || "#82a0ff";
    const faint = getComputedStyle(document.documentElement).getPropertyValue("--line2").trim() || "#44475a";

    const draw = (now: number) => {
      if (now - last >= STEP_MS) {
        last = now;
        levels.push(recording.level());
        const max = Math.ceil(width / (BAR + GAP)) + 1;
        if (levels.length > max) levels.splice(0, levels.length - max);
        setSeconds(recording.seconds);
      }
      ctx.clearRect(0, 0, width, height);
      const mid = height / 2;
      // Linha de base pontilhada onde ainda não há voz.
      ctx.fillStyle = faint;
      for (let x = width - levels.length * (BAR + GAP); x > 0; x -= BAR + GAP) ctx.fillRect(x, mid - 0.5, BAR, 1);
      ctx.fillStyle = color;
      levels.forEach((level, index) => {
        const x = width - (levels.length - index) * (BAR + GAP);
        const h = Math.max(2, level * (height - 4));
        ctx.beginPath();
        if (ctx.roundRect) ctx.roundRect(x, mid - h / 2, BAR, h, 1.5);
        else ctx.rect(x, mid - h / 2, BAR, h);
        ctx.fill();
      });
      frame = requestAnimationFrame(draw);
    };
    frame = requestAnimationFrame(draw);
    return () => {
      cancelAnimationFrame(frame);
      observer.disconnect();
    };
  }, [recording]);

  return (
    <div className="wave">
      <span className="rec-dot" aria-hidden="true" />
      <canvas ref={canvas} className="wave-canvas" aria-label="Onda da gravação" role="img" />
      <span className="mono wave-time">{clock(seconds)}</span>
    </div>
  );
}
