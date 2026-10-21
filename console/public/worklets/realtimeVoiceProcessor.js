class QwenPawPcm16Capture extends AudioWorkletProcessor {
  constructor(options) {
    super();
    this.source = [];
    this.output = [];
    this.readPosition = 0;
    this.inputRate = sampleRate;
    this.outputRate = options.processorOptions?.outputSampleRate || 16000;
    this.ratio = this.inputRate / this.outputRate;
    this.frameSamples = Math.max(1, Math.round(this.outputRate / 50));
  }

  process(inputs) {
    const channel = inputs[0]?.[0];
    if (!channel?.length) return true;
    for (const sample of channel) this.source.push(sample);

    while (this.readPosition + Math.max(1, this.ratio) < this.source.length) {
      let sample;
      if (this.ratio >= 1) {
        const end = this.readPosition + this.ratio;
        let sum = 0;
        for (
          let index = Math.floor(this.readPosition);
          index < Math.ceil(end);
          index += 1
        ) {
          const weight =
            Math.min(end, index + 1) - Math.max(this.readPosition, index);
          if (weight > 0) sum += this.source[index] * weight;
        }
        sample = sum / this.ratio;
      } else {
        const lower = Math.floor(this.readPosition);
        const fraction = this.readPosition - lower;
        sample =
          this.source[lower] * (1 - fraction) +
          this.source[lower + 1] * fraction;
      }
      const clamped = Math.max(-1, Math.min(1, sample));
      this.output.push(clamped < 0 ? clamped * 0x8000 : clamped * 0x7fff);
      this.readPosition += this.ratio;
    }

    const consumed = Math.floor(this.readPosition);
    if (consumed > 0) {
      this.source = this.source.slice(consumed);
      this.readPosition -= consumed;
    }
    while (this.output.length >= this.frameSamples) {
      const pcm = Int16Array.from(this.output.splice(0, this.frameSamples));
      this.port.postMessage(pcm.buffer, [pcm.buffer]);
    }
    return true;
  }
}

registerProcessor("qwenpaw-pcm16-capture", QwenPawPcm16Capture);
