// Explicit capture controls. No microphone audio is recorded or stored.
export async function startMic({ onLevel = () => {}, onPcm = () => {}, onSegment,
  onCommit = () => {}, onDiscard = () => {}, onTurnStart = () => {},
  onTurnEnd = () => {}, canBeginTurn = () => true, pushToTalk = false, pttKey = 'Space' } = {}) {
  const stream = await navigator.mediaDevices.getUserMedia({
    audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true,
      autoGainControl: true },
  });
  let ctx, source, worklet, silent;
  let enabled = true, pressed = false, stopped = false, epoch = 0, accepting = false;
  let keyOwned = false, keyboardTurn = false;
  const editable = (event) => ['INPUT', 'TEXTAREA', 'SELECT'].includes(event.target?.tagName)
    || event.target?.isContentEditable;
  function capture(value, { flush = false, commit = false } = {}) {
    if (value) { epoch++; accepting = true; }
    else if (!(flush && commit)) { epoch++; accepting = false; }
    worklet.port.postMessage({ type: 'enabled', value, flush, commit, epoch });
    if (!value) onLevel(0);
  }
  function beginTurn() {
    if (!pushToTalk || !enabled || stopped || pressed || accepting || !canBeginTurn()) return false;
    pressed = true; onTurnStart(); capture(true); return true;
  }
  function endTurn() {
    if (!pressed || stopped) return false;
    pressed = false; keyboardTurn = false; capture(false, { flush: true, commit: true }); return true;
  }
  function cancelTurn() {
    if (!pushToTalk || stopped || (!pressed && !accepting)) return false;
    pressed = false; keyboardTurn = false; capture(false); onDiscard(); return true;
  }
  function keyDown(event) {
    if (event.code !== pttKey || editable(event) || stopped) return;
    // PTT owns non-editable Space even while paused/busy; Enter still activates buttons.
    event.preventDefault();
    if (event.repeat) { keyOwned = true; return; }
    if (keyOwned) return;
    keyOwned = true; keyboardTurn = beginTurn();
  }
  function keyUp(event) {
    if (event.code !== pttKey) return;
    const owned = keyOwned, started = keyboardTurn;
    keyOwned = false; keyboardTurn = false;
    if (owned) event.preventDefault();
    if (started) endTurn();
  }
  function blurCapture() {
    keyOwned = false; keyboardTurn = false; cancelTurn();
  }

  async function stop() {
    if (stopped) return;
    stopped = true; enabled = false; pressed = false; accepting = false; epoch++;
    keyOwned = false; keyboardTurn = false;
    window.removeEventListener('keydown', keyDown);
    window.removeEventListener('keyup', keyUp);
    window.removeEventListener('blur', blurCapture);
    if (worklet) { worklet.port.onmessage = null; worklet.port.close(); worklet.disconnect(); }
    source?.disconnect(); silent?.disconnect();
    stream.getTracks().forEach((track) => track.stop());
    onLevel(0);
    if (ctx && ctx.state !== 'closed') await ctx.close();
  }

  try {
    ctx = new AudioContext();
    if (!ctx.audioWorklet) throw new Error('This browser needs AudioWorklet microphone support.');
    await ctx.audioWorklet.addModule('/js/mic_worklet.js');
    worklet = new AudioWorkletNode(ctx, 'pres-mic', {
      numberOfInputs: 1, numberOfOutputs: 1, channelCount: 1,
    });
    worklet.port.onmessage = ({ data }) => {
      if (stopped || !enabled || !accepting || data.epoch !== epoch) return;
      if (data.type === 'commit') { accepting = false; onCommit(); onTurnEnd(); return; }
      if (data.type === 'pcm') {
        onLevel(Math.min(1, data.level)); onPcm(new Uint8Array(data.pcm));
      }
    };
    source = ctx.createMediaStreamSource(stream);
    silent = ctx.createGain(); silent.gain.value = 0;
    source.connect(worklet); worklet.connect(silent); silent.connect(ctx.destination);
    capture(!pushToTalk);
    if (pushToTalk) {
      window.addEventListener('keydown', keyDown);
      window.addEventListener('keyup', keyUp);
      window.addEventListener('blur', blurCapture);
    }
    await ctx.resume();
  } catch (error) { await stop(); throw error; }

  function setEnabled(value) {
    const next = Boolean(value);
    if (stopped || enabled === next) return;
    enabled = next; pressed = false; keyboardTurn = false;
    capture(enabled && !pushToTalk);
  }
  return {
    hasSTT: false, stream, setEnabled, beginTurn, endTurn, cancelTurn,
    pause: () => setEnabled(false),
    async resume() { if (!stopped) { await ctx.resume(); setEnabled(true); } },
    stop,
  };
}
