export type PlaybackStatus = "drained" | "interrupted" | "failed";

interface Output {
  id: string;
  sealed: boolean;
  pending: number;
  sources: Set<AudioBufferSourceNode>;
  settled: boolean;
  feedback: (outputId: string, status: PlaybackStatus) => void;
}

export class RealtimeAudioPlayback {
  private context: AudioContext | null = null;
  private nextPlayTime = 0;
  private output: Output | null = null;

  isActive(id: string): boolean {
    return this.output?.id === id && !this.output.settled;
  }

  begin(id: string, feedback: Output["feedback"]): void {
    if (this.output?.id === id) return;
    if (this.output && !this.output.settled) this.finish(this.output, "failed");
    this.output = {
      id,
      sealed: false,
      pending: 0,
      sources: new Set(),
      settled: false,
      feedback,
    };
  }

  seal(id: string): void {
    const output = this.output;
    if (!output || output.id !== id || output.settled) return;
    output.sealed = true;
    this.checkDrained(output);
  }

  private checkDrained(output: Output): void {
    if (output.sealed && !output.pending && !output.sources.size) {
      this.finish(output, "drained");
    }
  }

  private finish(output: Output, status: PlaybackStatus): void {
    if (output.settled) return;
    // Fence first: stop/onended and a pending resume may run synchronously.
    output.settled = true;
    for (const source of output.sources) {
      try {
        source.stop();
      } catch {
        /* Already stopped. */
      }
    }
    output.sources.clear();
    this.nextPlayTime = this.context?.currentTime ?? 0;
    output.feedback(output.id, status);
  }

  unlock(): Promise<void> {
    if (!this.context) this.context = new AudioContext();
    return this.context.resume();
  }

  async enqueue(pcmBuffer: ArrayBuffer, sampleRate: number): Promise<void> {
    const context = this.context;
    const output = this.output;
    if (!output || output.settled) return;
    if (output.sealed) throw new Error("Audio arrived after output seal");
    output.pending += 1;
    try {
      if (!context) throw new Error("Audio playback is not unlocked");
      if (context.state !== "running") await context.resume();
      if (this.context !== context || this.output !== output || output.settled)
        return;
      const pcm = new Int16Array(pcmBuffer);
      const audio = context.createBuffer(1, pcm.length, sampleRate);
      const channel = audio.getChannelData(0);
      for (let index = 0; index < pcm.length; index += 1) {
        channel[index] = pcm[index] / 32768;
      }
      const source = context.createBufferSource();
      source.buffer = audio;
      source.connect(context.destination);
      const startAt = Math.max(context.currentTime + 0.015, this.nextPlayTime);
      this.nextPlayTime = startAt + audio.duration;
      output.sources.add(source);
      source.onended = () => {
        output.sources.delete(source);
        this.checkDrained(output);
      };
      source.start(startAt);
    } catch (error) {
      this.finish(output, "failed");
      throw error;
    } finally {
      output.pending -= 1;
      this.checkDrained(output);
    }
  }

  interrupt(): void {
    if (this.output) this.finish(this.output, "interrupted");
  }

  async close(): Promise<void> {
    this.interrupt();
    const context = this.context;
    this.context = null;
    if (context && context.state !== "closed") await context.close();
  }
}
