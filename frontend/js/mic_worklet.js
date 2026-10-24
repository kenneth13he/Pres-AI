// Capture-only processor: mono, streaming resampling to PCM16 at 24 kHz.
// Linear interpolation preserves fractional phase across render blocks (e.g. 44.1 kHz).
class PresMicProcessor extends AudioWorkletProcessor {
  constructor() {
    super();
    this.enabled = false;
    this.epoch = 0;
    this.reset();
    this.port.onmessage = ({ data }) => {
      if (data.type !== 'enabled') return;
      if (!data.value && data.flush) this.flush();
      this.enabled = data.value;
      this.epoch = data.epoch ?? this.epoch;
      this.reset();
      if (data.commit) this.port.postMessage({ type: 'commit', epoch: this.epoch });
    };
  }

  reset() {
    this.index = 0; this.nextAt = 0; this.previous = 0;
    this.frame = new Int16Array(480); this.used = 0; this.power = 0;
  }

  flush() {
    if (!this.used) return;
    const pcm = new ArrayBuffer(this.used * 2), view = new DataView(pcm);
    for (let i = 0; i < this.used; i++) view.setInt16(i * 2, this.frame[i], true);
    this.port.postMessage({ type: 'pcm', pcm, epoch: this.epoch,
      level: Math.sqrt(this.power / this.used) }, [pcm]);
    this.used = 0; this.power = 0;
  }

  process(inputs) {
    const samples = inputs[0]?.[0];
    if (!this.enabled || !samples) return true;
    for (const current of samples) {
      if (this.index === 0) this.previous = current;
      while (this.nextAt <= this.index) {
        const fraction = this.index === 0 ? 1 : this.nextAt - (this.index - 1);
        const value = Math.max(-1, Math.min(1,
          this.previous + (current - this.previous) * fraction));
        this.frame[this.used++] = Math.round(value * (value < 0 ? 32768 : 32767));
        this.power += value * value;
        if (this.used === this.frame.length) this.flush();
        this.nextAt += sampleRate / 24000;
      }
      this.previous = current; this.index++;
    }
    return true;
  }
}
registerProcessor('pres-mic', PresMicProcessor);
