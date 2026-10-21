export class RealtimeAudioCapture {
  private context: AudioContext | null = null;
  private stream: MediaStream | null = null;
  private worklet: AudioWorkletNode | null = null;
  private muted = false;
  private stopped = false;
  private readonly outputSampleRate: number;
  private readonly deviceId?: string;

  constructor(outputSampleRate: number, deviceId?: string) {
    this.outputSampleRate = outputSampleRate;
    this.deviceId = deviceId;
  }

  async start(
    onAudio: (pcm16: ArrayBuffer) => void,
    onDeviceEnded: () => void,
  ): Promise<void> {
    if (this.stream) return;
    if (this.stopped) throw new DOMException("Capture stopped", "AbortError");

    // Construct the context before the first await so a direct button click
    // counts as browser user activation in Web and Tauri WebView.
    const context = new AudioContext();
    this.context = context;
    const resumePromise = context.resume();
    const streamPromise = navigator.mediaDevices.getUserMedia({
      audio: {
        channelCount: 1,
        ...(this.deviceId ? { deviceId: { exact: this.deviceId } } : {}),
        echoCancellation: true,
        noiseSuppression: true,
        autoGainControl: true,
      },
      video: false,
    });
    let stream: MediaStream;
    try {
      [, , stream] = await Promise.all([
        resumePromise,
        context.audioWorklet.addModule("/worklets/realtimeVoiceProcessor.js"),
        streamPromise,
      ]);
    } catch (reason) {
      void streamPromise.then(
        (openedStream) => {
          for (const track of openedStream.getTracks()) track.stop();
        },
        () => undefined,
      );
      this.context = null;
      if (context.state !== "closed") await context.close();
      throw reason;
    }
    if (this.stopped) {
      for (const track of stream.getTracks()) track.stop();
      this.context = null;
      if (context.state !== "closed") await context.close();
      throw new DOMException("Capture stopped", "AbortError");
    }
    this.stream = stream;
    for (const track of stream.getAudioTracks()) {
      track.enabled = !this.muted;
      track.addEventListener("ended", onDeviceEnded, { once: true });
    }

    const source = context.createMediaStreamSource(stream);
    const worklet = new AudioWorkletNode(context, "qwenpaw-pcm16-capture", {
      processorOptions: { outputSampleRate: this.outputSampleRate },
    });
    const silent = context.createGain();
    silent.gain.value = 0;
    worklet.port.onmessage = (event: MessageEvent<ArrayBuffer>) => {
      if (!this.muted && event.data instanceof ArrayBuffer) onAudio(event.data);
    };
    source.connect(worklet).connect(silent).connect(context.destination);
    this.worklet = worklet;
  }

  setMuted(muted: boolean): void {
    this.muted = muted;
    for (const track of this.stream?.getAudioTracks() ?? []) {
      track.enabled = !muted;
    }
  }

  async stop(): Promise<void> {
    this.stopped = true;
    this.worklet?.disconnect();
    this.worklet = null;
    for (const track of this.stream?.getTracks() ?? []) track.stop();
    this.stream = null;
    const context = this.context;
    this.context = null;
    if (context && context.state !== "closed") await context.close();
  }
}
