/* 8-bit sound effects synthesised with Web Audio: no audio files. */
const sfx = (() => {
  let ctx = null;
  let muted = false;
  try { muted = localStorage.getItem("sq-muted") === "1"; } catch {}

  // Each sound is a list of notes: [frequency Hz, start s, length s, wave, volume, slide-to Hz?]
  const SOUNDS = {
    click:   [[880, 0, 0.04, "square", 0.05]],
    nav:     [[660, 0, 0.05, "square", 0.05], [990, 0.04, 0.05, "square", 0.04]],
    open:    [[520, 0, 0.07, "triangle", 0.12, 780]],
    close:   [[780, 0, 0.07, "triangle", 0.12, 440]],
    select:  [[1047, 0, 0.05, "square", 0.04]],
    done:    [[988, 0, 0.07, "square", 0.06], [1319, 0.07, 0.16, "square", 0.06]],       // coin
    undo:    [[660, 0, 0.07, "square", 0.05], [440, 0.07, 0.12, "square", 0.05]],
    topic:   [[523, 0, 0.08, "square", 0.06], [659, 0.08, 0.08, "square", 0.06], [784, 0.16, 0.08, "square", 0.06], [1047, 0.24, 0.22, "square", 0.06]],
    fanfare: [[392, 0, 0.1, "square", 0.06], [523, 0.1, 0.1, "square", 0.06], [659, 0.2, 0.1, "square", 0.06], [784, 0.3, 0.12, "square", 0.06], [659, 0.42, 0.08, "square", 0.05], [784, 0.5, 0.3, "square", 0.06]],
    sweep:   [[300, 0, 0.25, "square", 0.04, 1200]],
    on:      [[440, 0, 0.12, "triangle", 0.12, 880], [1175, 0.12, 0.1, "square", 0.04]],
    off:     [[880, 0, 0.15, "triangle", 0.12, 330]],
    send:    [[740, 0, 0.05, "square", 0.04], [988, 0.05, 0.05, "square", 0.04]],
    message: [[1319, 0, 0.06, "triangle", 0.12], [1568, 0.08, 0.12, "triangle", 0.12]],
    warn:    [[220, 0, 0.12, "sawtooth", 0.05], [220, 0.16, 0.12, "sawtooth", 0.05]],
    error:   [[330, 0, 0.12, "square", 0.05], [196, 0.13, 0.25, "square", 0.05]],
  };

  let master = null;
  let warmed = false;

  // Browsers only let audio start during a click/keypress, and many of our sounds play after a
  // server reply (outside the click). So the audio engine is unlocked on every interaction.
  // Safari is stricter: it needs "click"/"touchend"-type events and a sound actually started
  // inside the gesture, so a silent one-sample buffer is played the first time.
  function unlock() {
    try {
      if (!ctx) {
        ctx = new (window.AudioContext || window.webkitAudioContext)();
        master = ctx.createGain();
        master.gain.value = 1.6;
        master.connect(ctx.destination);
      }
      if (ctx.state !== "running") ctx.resume();
      if (!warmed) {
        const src = ctx.createBufferSource();
        src.buffer = ctx.createBuffer(1, 1, 22050);
        src.connect(ctx.destination);
        src.start(0);
        warmed = true;
      }
    } catch {}
  }
  for (const ev of ["pointerdown", "mousedown", "touchend", "click", "keydown"]) {
    document.addEventListener(ev, unlock, true);
  }

  function schedule(notes) {
    const now = ctx.currentTime + 0.02;
    for (const [freq, at, len, wave, vol, slide] of notes) {
      const osc = ctx.createOscillator();
      const gain = ctx.createGain();
      osc.type = wave;
      osc.frequency.setValueAtTime(freq, now + at);
      if (slide) osc.frequency.exponentialRampToValueAtTime(slide, now + at + len);
      gain.gain.setValueAtTime(vol, now + at);
      gain.gain.exponentialRampToValueAtTime(0.0001, now + at + len);
      osc.connect(gain).connect(master);
      osc.start(now + at);
      osc.stop(now + at + len + 0.02);
    }
  }

  function play(name) {
    if (muted || !SOUNDS[name]) return;
    unlock();
    if (!ctx) return;
    try {
      // If the engine is still waking up (Safari: "suspended"/"interrupted"), play once it runs.
      if (ctx.state === "running") schedule(SOUNDS[name]);
      else ctx.resume().then(() => schedule(SOUNDS[name])).catch(() => {});
    } catch {}
  }

  function setMuted(m) {
    muted = m;
    try { localStorage.setItem("sq-muted", m ? "1" : "0"); } catch {}
  }

  return { play, setMuted, get muted() { return muted; } };
})();
