// Gravação para ditado: microfone → PCM → WAV 16 kHz mono, o formato que o Whisper do núcleo lê.

export const TARGET_RATE = 16000;

/** PCM float em [-1, 1] → WAV PCM 16 bits mono. */
export function encodeWav(samples: Float32Array, rate: number): Blob {
  const buffer = new ArrayBuffer(44 + samples.length * 2);
  const view = new DataView(buffer);
  const text = (offset: number, value: string) => {
    for (let i = 0; i < value.length; i++) view.setUint8(offset + i, value.charCodeAt(i));
  };
  text(0, "RIFF");
  view.setUint32(4, 36 + samples.length * 2, true);
  text(8, "WAVE");
  text(12, "fmt ");
  view.setUint32(16, 16, true); // tamanho do bloco fmt
  view.setUint16(20, 1, true); // PCM
  view.setUint16(22, 1, true); // mono
  view.setUint32(24, rate, true);
  view.setUint32(28, rate * 2, true); // bytes por segundo
  view.setUint16(32, 2, true); // bytes por amostra
  view.setUint16(34, 16, true); // bits
  text(36, "data");
  view.setUint32(40, samples.length * 2, true);
  for (let i = 0; i < samples.length; i++) {
    const s = Math.max(-1, Math.min(1, samples[i]));
    view.setInt16(44 + i * 2, s < 0 ? s * 0x8000 : s * 0x7fff, true);
  }
  return new Blob([buffer], { type: "audio/wav" });
}

/** Junta os pedaços gravados e reamostra para 16 kHz com o filtro do próprio navegador. */
export async function toWav16k(chunks: Float32Array[], rate: number): Promise<Blob> {
  const length = chunks.reduce((sum, chunk) => sum + chunk.length, 0);
  const merged = new Float32Array(length);
  let offset = 0;
  for (const chunk of chunks) {
    merged.set(chunk, offset);
    offset += chunk.length;
  }
  if (rate === TARGET_RATE || length === 0) return encodeWav(merged, TARGET_RATE);
  const outLength = Math.max(1, Math.ceil((length * TARGET_RATE) / rate));
  const offline = new OfflineAudioContext(1, outLength, TARGET_RATE);
  const source = offline.createBufferSource();
  const buffer = offline.createBuffer(1, length, rate);
  buffer.copyToChannel(merged, 0);
  source.buffer = buffer;
  source.connect(offline.destination);
  source.start();
  const rendered = await offline.startRendering();
  return encodeWav(rendered.getChannelData(0), TARGET_RATE);
}

/**
 * Uma gravação. `level()` devolve o volume do instante (0 a 1) para desenhar a onda;
 * `stop()` devolve o WAV pronto; `cancel()` descarta.
 */
export class Recording {
  private chunks: Float32Array[] = [];
  private readonly data: Uint8Array<ArrayBuffer>;
  readonly startedAt = Date.now();

  private constructor(
    private readonly stream: MediaStream,
    private readonly context: AudioContext,
    private readonly analyser: AnalyserNode,
    private readonly processor: ScriptProcessorNode,
  ) {
    this.data = new Uint8Array(analyser.fftSize);
    processor.onaudioprocess = (event) => {
      this.chunks.push(new Float32Array(event.inputBuffer.getChannelData(0)));
    };
  }

  static async start(): Promise<Recording> {
    if (!navigator.mediaDevices?.getUserMedia) {
      throw new Error("este ambiente não dá acesso ao microfone");
    }
    const stream = await navigator.mediaDevices.getUserMedia({
      audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true, autoGainControl: true },
    });
    const context = new AudioContext();
    await context.resume();
    const source = context.createMediaStreamSource(stream);
    const analyser = context.createAnalyser();
    analyser.fftSize = 1024;
    // ScriptProcessor é antigo, mas roda igual no WebKit do app e no Chrome, sem worklet nem CSP extra.
    const processor = context.createScriptProcessor(4096, 1, 1);
    source.connect(analyser);
    source.connect(processor);
    processor.connect(context.destination); // a saída fica em silêncio; só precisa estar ligada para rodar
    return new Recording(stream, context, analyser, processor);
  }

  level(): number {
    this.analyser.getByteTimeDomainData(this.data);
    let sum = 0;
    for (const value of this.data) {
      const centered = (value - 128) / 128;
      sum += centered * centered;
    }
    return Math.min(1, Math.sqrt(Math.sqrt(sum / this.data.length)) * 1.6);
  }

  get seconds(): number {
    return (Date.now() - this.startedAt) / 1000;
  }

  private async release(): Promise<void> {
    this.processor.onaudioprocess = null;
    this.processor.disconnect();
    this.analyser.disconnect();
    this.stream.getTracks().forEach((track) => track.stop());
    await this.context.close().catch(() => undefined);
  }

  async stop(): Promise<Blob> {
    const rate = this.context.sampleRate;
    await this.release();
    return toWav16k(this.chunks, rate);
  }

  async cancel(): Promise<void> {
    this.chunks = [];
    await this.release();
  }
}

/** Mensagem legível para os erros comuns do microfone. */
export function micError(cause: unknown): string {
  const name = cause instanceof DOMException ? cause.name : "";
  if (name === "NotAllowedError" || name === "SecurityError") {
    return "Sem permissão para o microfone. Libere em Ajustes do Sistema › Privacidade e Segurança › Microfone.";
  }
  if (name === "NotFoundError") return "Nenhum microfone encontrado.";
  return cause instanceof Error ? cause.message : String(cause);
}
