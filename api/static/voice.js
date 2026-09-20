// Aria voice: listen-along reading with live highlighting, and voice questions.
//
// Everything runs in the browser (Web Speech API). Nothing here calls the Aria server or an AI
// service, so it adds no load to Render and no API cost, and reading aloud works offline with a
// local voice. Highlighting uses the CSS Custom Highlight API, so the page DOM is never mutated
// (streamed answers can be re-rendered freely); browsers without it highlight the whole block.
(function () {
  'use strict';

  const PREF_KEY = 'aria-voice-prefs';
  const MAX_CHUNK = 220;
  const RATES = [0.8, 1, 1.2, 1.5];
  const SKIP = 'button, select, input, textarea, script, style, .listen-bar, [data-no-speak]';
  const BLOCK_TAGS = new Set(['DIV', 'P', 'LI', 'UL', 'OL', 'H1', 'H2', 'H3', 'H4', 'TR', 'TABLE', 'SECTION', 'ARTICLE', 'BR', 'LABEL']);

  const state = {
    engine: null,
    session: null,
    speakNext: false,
    prefs: loadPrefs(),
    voices: [],
    recognition: null,
  };

  function loadPrefs() {
    const defaults = { rate: 1, voiceURI: '', auto: false };
    try { return { ...defaults, ...JSON.parse(localStorage.getItem(PREF_KEY) || '{}') }; } catch (_) { return defaults; }
  }
  function savePrefs() {
    try { localStorage.setItem(PREF_KEY, JSON.stringify(state.prefs)); } catch (_) { /* private mode */ }
  }

  const engine = () => state.engine || window.speechSynthesis || null;
  const supportsTts = () => !!(engine() && (window.SpeechSynthesisUtterance || state.engine));
  const RecognitionCtor = () => window.SpeechRecognition || window.webkitSpeechRecognition || null;
  const supportsStt = () => !!RecognitionCtor();
  const canHighlight = () => typeof Highlight === 'function' && !!(window.CSS && CSS.highlights);

  // ── Turn a rendered element into speakable sentences ──────────────────────
  function collect(root) {
    const parts = [];
    let text = '';
    const breakLine = () => { if (text && !text.endsWith('\n')) text += '\n'; };
    const addText = node => {
      const value = node.nodeValue.replace(/\s+/g, ' ');
      if (!value.trim() && !text) return;
      parts.push({ kind: 'text', node, start: text.length, len: value.length, value });
      text += value;
    };
    (function walk(node) {
      for (const child of node.childNodes) {
        if (child.nodeType === 3) { addText(child); continue; }
        if (child.nodeType !== 1 || child.matches(SKIP) || child.hidden) continue;
        if (child.tagName === 'PRE') {
          breakLine();
          const line = 'Code example shown on screen.';
          parts.push({ kind: 'el', node: child, start: text.length, len: line.length, value: line });
          text += line;
          breakLine();
          continue;
        }
        const block = BLOCK_TAGS.has(child.tagName);
        if (block) breakLine();
        walk(child);
        if (block) breakLine();
      }
    })(root);
    return { text, parts };
  }

  function splitSentences(text) {
    const out = [];
    const push = (start, end) => {
      let s = start; let e = end;
      while (s < e && /\s/.test(text[s])) s += 1;
      while (e > s && /\s/.test(text[e - 1])) e -= 1;
      if (e - s < 2 || !/[\p{L}\p{N}]/u.test(text.slice(s, e))) return;
      // very long sentences are split at commas or spaces so speech and highlighting stay in step
      while (e - s > MAX_CHUNK) {
        let cut = text.lastIndexOf(', ', s + MAX_CHUNK);
        if (cut <= s + 40) cut = text.lastIndexOf(' ', s + MAX_CHUNK);
        if (cut <= s) cut = s + MAX_CHUNK;
        out.push({ start: s, end: cut + 1 });
        s = cut + 1;
        while (s < e && /\s/.test(text[s])) s += 1;
      }
      out.push({ start: s, end: e });
    };
    let start = 0;
    const re = /[.!?]+["')\]]*(?=\s|$)|\n/g;
    let match;
    while ((match = re.exec(text))) {
      // "1." list numbers and abbreviations such as "e.g." are not the end of a sentence
      if (match[0][0] !== '\n') {
        const before = text.slice(start, match.index).trim();
        if (/^\d{1,2}$/.test(before) || /(^|\s)(e\.g|i\.e|etc|vs|approx)$/i.test(before)) continue;
      }
      push(start, match.index + (match[0] === '\n' ? 0 : match[0].length));
      start = match.index + match[0].length;
    }
    push(start, text.length);
    return out.map(s => ({ ...s, text: text.slice(s.start, s.end) }));
  }

  function locate(parts, index, atEnd) {
    for (const p of parts) {
      const within = atEnd ? index > p.start && index <= p.start + p.len : index >= p.start && index < p.start + p.len;
      if (within) return { part: p, offset: index - p.start };
    }
    return null;
  }

  function rangeFor(parts, from, to) {
    const a = locate(parts, from, false);
    const b = locate(parts, to, true);
    if (!a || !b) return null;
    const range = document.createRange();
    if (a.part.kind === 'el') { range.selectNodeContents(a.part.node); return range; }
    try {
      range.setStart(a.part.node, Math.min(a.offset, a.part.node.nodeValue.length));
      range.setEnd(b.part.kind === 'el' ? a.part.node : b.part.node, b.part.kind === 'el' ? a.part.node.nodeValue.length : Math.min(b.offset, b.part.node.nodeValue.length));
    } catch (_) { return null; }
    return range;
  }

  // ── Highlighting ──────────────────────────────────────────────────────────
  let fallbackEl = null;
  function clearHighlight() {
    if (canHighlight()) { CSS.highlights.delete('spk-sentence'); CSS.highlights.delete('spk-word'); }
    if (fallbackEl) { fallbackEl.classList.remove('spk-block'); fallbackEl = null; }
  }
  function highlightSentence(range) {
    if (!range) return;
    if (canHighlight()) {
      CSS.highlights.set('spk-sentence', new Highlight(range));
    } else {
      const el = (range.startContainer.nodeType === 1 ? range.startContainer : range.startContainer.parentElement)?.closest('div, p, li, h1, h2, h3, h4, pre');
      if (fallbackEl && fallbackEl !== el) fallbackEl.classList.remove('spk-block');
      if (el) { el.classList.add('spk-block'); fallbackEl = el; }
    }
    const scrollTo = range.startContainer.nodeType === 1 ? range.startContainer : range.startContainer.parentElement;
    scrollTo?.scrollIntoView?.({ block: 'nearest', behavior: 'smooth' });
  }
  function highlightWord(range) {
    if (canHighlight()) { if (range) CSS.highlights.set('spk-word', new Highlight(range)); else CSS.highlights.delete('spk-word'); }
  }

  // ── Voices ────────────────────────────────────────────────────────────────
  function refreshVoices() {
    const list = engine()?.getVoices?.() || [];
    if (list.length) state.voices = list;
    return state.voices;
  }
  function pickVoice() {
    const voices = refreshVoices();
    if (!voices.length) return null;
    const chosen = voices.find(v => v.voiceURI === state.prefs.voiceURI);
    if (chosen) return chosen;
    const offline = navigator.onLine === false;
    const pool = offline ? voices.filter(v => v.localService).concat(voices.filter(v => !v.localService)) : voices;
    for (const lang of ['en-ZA', 'en-GB', 'en-US', 'en']) {
      const hit = pool.find(v => v.lang && v.lang.replace('_', '-').toLowerCase().startsWith(lang.toLowerCase()));
      if (hit) return hit;
    }
    return pool[0];
  }

  // ── Speaking ──────────────────────────────────────────────────────────────
  function stop(silent) {
    const s = state.session;
    state.session = null;
    if (s) s.cancelled = true;
    try { engine()?.cancel?.(); } catch (_) { /* ignore */ }
    clearHighlight();
    updateBars(null);
    if (s && panelOpen() && panel.state === 'speaking') setPanelState('idle', { text: 'Stopped. Tap the microphone to ask another question.' });
    if (!silent && s?.onStop) s.onStop();
  }

  function speak(target, options = {}) {
    if (!supportsTts() || !target) return false;
    stop(true);
    const { text, parts } = collect(target);
    const sentences = splitSentences(text);
    if (!sentences.length) return false;
    const session = { id: Date.now() + Math.random(), target, text, parts, sentences, index: 0, paused: false, cancelled: false, onStop: options.onStop };
    state.session = session;
    updateBars(target);
    if (panelOpen()) setPanelState('speaking');
    setTimeout(() => { if (state.session === session) next(session); }, 60); // Chrome drops speak() right after cancel()
    return true;
  }

  function next(session) {
    if (session.cancelled || state.session !== session) return;
    if (session.index >= session.sentences.length) { finish(session); return; }
    const sentence = session.sentences[session.index];
    const utter = new (window.SpeechSynthesisUtterance || state.utteranceCtor)(sentence.text);
    const voice = pickVoice();
    if (voice) { utter.voice = voice; utter.lang = voice.lang; } else { utter.lang = 'en-ZA'; }
    utter.rate = Number(state.prefs.rate) || 1;
    utter.onstart = () => {
      if (session.cancelled) return;
      highlightSentence(rangeFor(session.parts, sentence.start, sentence.end));
      highlightWord(null);
      panelSentence(sentence.text);
    };
    utter.onboundary = event => {
      if (session.cancelled || (event.name && event.name !== 'word')) return;
      const at = sentence.start + (event.charIndex || 0);
      let end = at;
      while (end < sentence.end && /\S/.test(session.text[end])) end += 1;
      highlightWord(rangeFor(session.parts, at, end));
    };
    utter.onend = () => { if (session.cancelled) return; session.index += 1; next(session); };
    utter.onerror = event => {
      if (session.cancelled || (event && (event.error === 'interrupted' || event.error === 'canceled'))) return;
      session.index += 1;
      next(session);
    };
    engine().speak(utter);
  }

  function finish(session) {
    if (state.session !== session) return;
    state.session = null;
    clearHighlight();
    updateBars(null);
    panelSpeechEnded();
  }

  function pause() { const s = state.session; if (!s || s.paused) return; s.paused = true; engine().pause?.(); updateBars(s.target); }
  function resume() { const s = state.session; if (!s || !s.paused) return; s.paused = false; engine().resume?.(); updateBars(s.target); }

  // ── Listen bar ────────────────────────────────────────────────────────────
  const ICON = '<svg viewBox="0 0 24 24" aria-hidden="true" width="16" height="16" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M11 5 6 9H3v6h3l5 4z"/><path d="M15.5 8.5a5 5 0 0 1 0 7M18.5 5.5a9 9 0 0 1 0 13"/></svg>';
  const bars = new Set();

  function hasSpeakable(target) {
    return collect(target).text.trim().length > 1 && !target.querySelector(':scope > .empty:only-child');
  }

  function addListen(container) {
    if (!container) return null;
    if (container._listenBar) return container._listenBar;
    const bar = document.createElement('div');
    bar.className = 'listen-bar';
    bar.setAttribute('role', 'group');
    bar.setAttribute('aria-label', 'Listen to this answer');
    bar.hidden = true;
    if (!supportsTts()) {
      bar.innerHTML = '<span class="listen-status">Listening is not supported in this browser. Try Chrome, Edge or Safari.</span>';
      container.parentNode.insertBefore(bar, container);
      container._listenBar = bar;
      return bar;
    }
    bar.innerHTML = `
      <button type="button" class="btn btn-good btn-sm listen-play" aria-pressed="false">${ICON}<span>Listen</span></button>
      <button type="button" class="btn btn-ghost btn-sm listen-stop" disabled>Stop</button>
      <label class="listen-field">Speed <select class="field listen-rate" aria-label="Reading speed">${RATES.map(r => `<option value="${r}">${r}×</option>`).join('')}</select></label>
      <label class="listen-field listen-voice-wrap">Voice <select class="field listen-voice" aria-label="Voice"></select></label>
      <label class="listen-check"><input type="checkbox" class="listen-auto"> Read answers aloud</label>`;
    const $ = sel => bar.querySelector(sel);
    $('.listen-rate').value = String(RATES.includes(Number(state.prefs.rate)) ? Number(state.prefs.rate) : 1);
    $('.listen-auto').checked = !!state.prefs.auto;
    fillVoiceSelect($('.listen-voice'));
    $('.listen-play').addEventListener('click', () => {
      const s = state.session;
      if (s && (s.target === container || container.contains(s.target))) { s.paused ? resume() : pause(); return; }
      speak(container);
    });
    $('.listen-stop').addEventListener('click', () => stop());
    $('.listen-rate').addEventListener('change', e => { state.prefs.rate = Number(e.target.value); savePrefs(); restartCurrent(container); });
    $('.listen-voice').addEventListener('change', e => { state.prefs.voiceURI = e.target.value; savePrefs(); restartCurrent(container); });
    $('.listen-auto').addEventListener('change', e => { state.prefs.auto = e.target.checked; savePrefs(); bars.forEach(b => { const c = b.querySelector('.listen-auto'); if (c) c.checked = state.prefs.auto; }); });
    container.parentNode.insertBefore(bar, container);
    container._listenBar = bar;
    bars.add(bar);
    bar._container = container;
    return bar;
  }

  function fillVoiceSelect(select) {
    const voices = refreshVoices();
    select.innerHTML = '<option value="">Automatic</option>' + voices
      .filter(v => /^en/i.test(v.lang))
      .map(v => `<option value="${escapeAttr(v.voiceURI)}">${escapeAttr(v.name)}${v.localService ? '' : ' (online)'}</option>`).join('');
    select.value = state.prefs.voiceURI || '';
    if (select.value !== (state.prefs.voiceURI || '')) select.value = '';
  }
  const escapeAttr = s => String(s).replace(/&/g, '&amp;').replace(/"/g, '&quot;').replace(/</g, '&lt;');

  function restartCurrent(container) {
    const s = state.session;
    if (s && (s.target === container || container.contains(s.target))) { const target = s.target; stop(true); speak(target); }
  }

  function updateBars(activeTarget) {
    const s = state.session;
    for (const bar of bars) {
      const container = bar._container;
      const active = !!activeTarget && !!s && (s.target === container || container.contains(s.target));
      const play = bar.querySelector('.listen-play');
      const stopBtn = bar.querySelector('.listen-stop');
      if (!play) continue;
      play.setAttribute('aria-pressed', String(!!active && !s.paused));
      play.querySelector('span').textContent = active ? (s.paused ? 'Resume' : 'Pause') : 'Listen';
      stopBtn.disabled = !active;
    }
  }

  function refresh(container) {
    const bar = container?._listenBar;
    if (!bar) return;
    bar.hidden = !hasSpeakable(container);
    if (bar.hidden && state.session && (state.session.target === container || container.contains(state.session.target))) stop(true);
  }

  // ── Auto-read / voice-to-voice ────────────────────────────────────────────
  function armSpeakNext() { state.speakNext = true; }
  function disarm() { state.speakNext = false; if (panelOpen() && panel.state === 'thinking') setPanelState('idle', { text: 'Tap the microphone and ask your question.' }); }

  function onContentReady(container, target) {
    refresh(container);
    const want = state.speakNext || state.prefs.auto;
    state.speakNext = false;
    if (want && supportsTts() && speak(target || container)) return;
    if (panelOpen() && panel.state === 'thinking') setPanelState('idle', { text: 'Your answer is on screen.' });
  }

  // ── Voice panel: a floating, draggable, minimisable voice assistant ─────────
  // Opens when "Ask by voice" is used. It shows what Aria hears, what she is thinking about and,
  // while she reads her answer aloud, the sentence being spoken. It works like the call panel:
  // drag it by its header (mouse, touch or arrow keys), minimise it to a small pill, close it.
  const PANEL_KEY = 'aria-voice-panel';
  const MARGIN = 8;
  const panel = { el: null, state: 'idle', moved: false, lastAsk: null, convo: false, minimized: false };

  const MIC_SVG = '<svg viewBox="0 0 24 24" width="20" height="20" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 1a3 3 0 0 0-3 3v8a3 3 0 0 0 6 0V4a3 3 0 0 0-3-3z"/><path d="M19 10v2a7 7 0 0 1-14 0v-2M12 19v4M8 23h8"/></svg>';
  const STATE_TEXT = {
    idle: 'Tap the microphone and ask your question.',
    listening: 'Listening… ask your question.',
    thinking: 'Aria is thinking…',
    speaking: 'Aria is speaking',
    error: '',
  };
  const PILL_TEXT = { idle: 'Ask Aria', listening: 'Listening…', thinking: 'Thinking…', speaking: 'Speaking…', error: 'Needs attention' };

  function loadPanelPrefs() {
    try { return JSON.parse(localStorage.getItem(PANEL_KEY) || '{}'); } catch (_) { return {}; }
  }
  function savePanelPrefs() {
    const el = panel.el;
    if (!el) return;
    const data = { minimized: panel.minimized, convo: panel.convo };
    if (panel.moved) { const r = el.getBoundingClientRect(); data.left = Math.round(r.left); data.top = Math.round(r.top); }
    try { localStorage.setItem(PANEL_KEY, JSON.stringify(data)); } catch (_) { /* private mode */ }
  }

  function clampToViewport() {
    const el = panel.el;
    if (!el || !panel.moved) return;
    // Use the stored coordinates and real (or default) size: a hidden panel measures as 0x0, which used to snap it to the corner.
    const width = el.offsetWidth || 320;
    const height = el.offsetHeight || 230;
    const left = parseFloat(el.style.left);
    const top = parseFloat(el.style.top);
    if (Number.isNaN(left) || Number.isNaN(top)) return;
    el.style.left = `${Math.min(Math.max(MARGIN, left), Math.max(MARGIN, window.innerWidth - width - MARGIN))}px`;
    el.style.top = `${Math.min(Math.max(MARGIN, top), Math.max(MARGIN, window.innerHeight - height - MARGIN))}px`;
  }

  function placeAt(left, top) {
    const el = panel.el;
    panel.moved = true;
    el.style.right = 'auto';
    el.style.bottom = 'auto';
    el.style.left = `${left}px`;
    el.style.top = `${top}px`;
    clampToViewport();
  }

  function buildPanel() {
    if (panel.el) return panel.el;
    const prefs = loadPanelPrefs();
    const el = document.createElement('div');
    el.id = 'voice-panel';
    el.className = 'voice-panel';
    el.hidden = true;
    el.setAttribute('role', 'dialog');
    el.setAttribute('aria-label', 'Aria voice assistant');
    el.dataset.state = 'idle';
    el.innerHTML = `
      <div class="vp-top" tabindex="0" role="group" aria-label="Voice assistant. Drag to move, or focus here and use the arrow keys.">
        <span class="vp-dot" aria-hidden="true"></span>
        <span class="vp-title">Ask Aria</span>
        <span class="vp-pill-text" aria-hidden="true"></span>
        <div class="vp-controls">
          <button type="button" class="cp-icon-btn vp-min" aria-label="Minimise voice panel" title="Minimise"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M6 12h12"/></svg></button>
          <button type="button" class="cp-icon-btn vp-close" aria-label="Close voice panel" title="Close"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M6 6l12 12M18 6 6 18"/></svg></button>
        </div>
      </div>
      <div class="vp-body">
        <div class="vp-wave" aria-hidden="true"><i></i><i></i><i></i><i></i><i></i><i></i><i></i></div>
        <p class="vp-state" role="status" aria-live="polite"></p>
        <p class="vp-quote" hidden></p>
        <p class="vp-now" hidden></p>
        <div class="vp-actions">
          <button type="button" class="icon-btn mic vp-mic" aria-label="Start listening" aria-pressed="false">${MIC_SVG}</button>
          <button type="button" class="btn btn-ghost btn-sm vp-pause" disabled>Pause</button>
          <button type="button" class="btn btn-ghost btn-sm vp-stop" disabled>Stop reading</button>
        </div>
        <label class="listen-check vp-convo-label"><input type="checkbox" class="vp-convo"> Keep the conversation going</label>
      </div>`;
    document.body.appendChild(el);
    panel.el = el;
    panel.convo = !!prefs.convo;
    panel.minimized = !!prefs.minimized;
    el.querySelector('.vp-convo').checked = panel.convo;
    el.classList.toggle('is-minimized', panel.minimized);
    if (Number.isFinite(prefs.left) && Number.isFinite(prefs.top)) placeAt(prefs.left, prefs.top);

    const $ = sel => el.querySelector(sel);
    $('.vp-min').addEventListener('click', () => setMinimized(!panel.minimized));
    $('.vp-close').addEventListener('click', () => closePanel());
    $('.vp-mic').addEventListener('click', micPressed);
    $('.vp-pause').addEventListener('click', () => { const s = state.session; if (!s) return; s.paused ? resume() : pause(); refreshPanelButtons(); });
    $('.vp-stop').addEventListener('click', () => stop());
    $('.vp-convo').addEventListener('change', e => { panel.convo = e.target.checked; savePanelPrefs(); });
    // a minimised pill expands when tapped (but not at the end of a drag)
    el.addEventListener('click', e => { if (panel.minimized && !e.target.closest('.vp-controls') && !panel.justDragged) setMinimized(false); });
    el.addEventListener('keydown', e => {
      if (e.key === 'Escape') { setMinimized(true); return; }
      if (!e.target.closest('.vp-top') || !e.key.startsWith('Arrow')) return;
      e.preventDefault();
      const r = el.getBoundingClientRect();
      const step = e.shiftKey ? 48 : 16;
      placeAt(r.left + (e.key === 'ArrowRight' ? step : e.key === 'ArrowLeft' ? -step : 0), r.top + (e.key === 'ArrowDown' ? step : e.key === 'ArrowUp' ? -step : 0));
      savePanelPrefs();
    });
    enableDrag($('.vp-top'));
    window.addEventListener('resize', () => { clampToViewport(); });
    return el;
  }

  function enableDrag(handle) {
    let start = null;
    handle.addEventListener('pointerdown', e => {
      if (e.target.closest('button') || (e.pointerType === 'mouse' && e.button !== 0)) return;
      const r = panel.el.getBoundingClientRect();
      start = { dx: e.clientX - r.left, dy: e.clientY - r.top, x: e.clientX, y: e.clientY, moved: false };
      handle.setPointerCapture(e.pointerId);
    });
    handle.addEventListener('pointermove', e => {
      if (!start) return;
      if (!start.moved && Math.hypot(e.clientX - start.x, e.clientY - start.y) < 4) return;   // a tap is not a drag
      start.moved = true;
      panel.el.classList.add('is-dragging');
      placeAt(e.clientX - start.dx, e.clientY - start.dy);
    });
    const end = e => {
      if (!start) return;
      const wasDrag = start.moved;
      start = null;
      panel.el.classList.remove('is-dragging');
      try { handle.releasePointerCapture(e.pointerId); } catch (_) { /* already released */ }
      if (wasDrag) { savePanelPrefs(); panel.justDragged = true; setTimeout(() => { panel.justDragged = false; }, 0); }
    };
    handle.addEventListener('pointerup', end);
    handle.addEventListener('pointercancel', end);
  }

  function setMinimized(value) {
    panel.minimized = !!value;
    panel.el.classList.toggle('is-minimized', panel.minimized);
    const min = panel.el.querySelector('.vp-min');
    min.setAttribute('aria-label', panel.minimized ? 'Expand voice panel' : 'Minimise voice panel');
    min.title = panel.minimized ? 'Expand' : 'Minimise';
    clampToViewport();
    savePanelPrefs();
  }

  function openPanel() {
    buildPanel();
    if (panel.el.hidden) {
      panel.el.classList.add('vp-enter');
      panel.el.addEventListener('animationend', () => panel.el.classList.remove('vp-enter'), { once: true });
    }
    panel.el.hidden = false;
    clampToViewport();
    return panel.el;
  }

  function closePanel() {
    if (!panel.el || panel.el.hidden) return;
    panel.el.hidden = true;
    if (state.recognition) { try { state.recognition.abort(); } catch (_) { /* ignore */ } }
    if (state.session) stop(true);
    setPanelState('idle');
  }

  const panelOpen = () => !!panel.el && !panel.el.hidden;

  function setPanelState(name, info = {}) {
    if (!panel.el) return;
    const el = panel.el;
    panel.state = name;
    el.dataset.state = name;
    el.querySelector('.vp-state').textContent = info.text || STATE_TEXT[name] || '';
    el.querySelector('.vp-pill-text').textContent = PILL_TEXT[name] || '';
    const quote = el.querySelector('.vp-quote');
    if (info.quote !== undefined) { quote.textContent = info.quote ? `“${info.quote}”` : ''; quote.hidden = !info.quote; }
    const now = el.querySelector('.vp-now');
    if (name !== 'speaking') { now.textContent = ''; now.hidden = true; }
    const mic = el.querySelector('.vp-mic');
    mic.setAttribute('aria-pressed', String(name === 'listening'));
    mic.setAttribute('aria-label', name === 'listening' ? 'Stop listening' : 'Start listening');
    mic.classList.toggle('listening', name === 'listening');
    refreshPanelButtons();
  }

  function refreshPanelButtons() {
    if (!panel.el) return;
    const s = state.session;
    const pause = panel.el.querySelector('.vp-pause');
    const stopBtn = panel.el.querySelector('.vp-stop');
    pause.disabled = !s;
    stopBtn.disabled = !s;
    pause.textContent = s && s.paused ? 'Resume' : 'Pause';
  }

  function panelSentence(text) {
    if (!panelOpen()) return;
    const now = panel.el.querySelector('.vp-now');
    now.textContent = text;
    now.hidden = false;
  }

  function micPressed() {
    const last = panel.lastAsk;
    if (!last) return;
    ask(last.button, last.statusEl, last.onText);
  }

  // called when Aria finishes reading on her own: keep the conversation going if asked to
  function panelSpeechEnded() {
    if (!panelOpen()) return;
    setPanelState('idle', { text: panel.convo ? 'Listening again…' : 'Done. Tap the microphone to ask another question.' });
    if (panel.convo && !state.recognition) setTimeout(() => { if (panelOpen() && !state.recognition && !state.session && panel.state !== 'thinking') micPressed(); }, 700);
  }

  // ── Voice questions ───────────────────────────────────────────────────────
  function ask(button, statusEl, onText) {
    const setStatus = (msg, kind) => { if (statusEl) { statusEl.textContent = msg; statusEl.dataset.kind = kind || ''; } };
    panel.lastAsk = { button, statusEl, onText };
    openPanel();
    if (!supportsStt()) {
      const message = 'Voice questions need Chrome, Edge or Safari. You can still type your question.';
      setStatus(message, 'warn');
      setPanelState('error', { text: message });
      return;
    }
    if (state.recognition) { state.recognition.stop(); return; }
    stop(true); // never let Aria's own voice into the microphone
    setPanelState('listening', { quote: '' });
    const rec = new (RecognitionCtor())();
    rec.lang = state.prefs.lang || 'en-ZA';
    rec.interimResults = true;
    rec.continuous = false;
    rec.maxAlternatives = 1;
    let finalText = '';
    let heard = false;
    let failed = false;
    button.setAttribute('aria-pressed', 'true');
    button.classList.add('is-listening');
    setStatus('Listening… ask your question.', 'info');
    rec.onresult = event => {
      let interim = '';
      for (let i = event.resultIndex; i < event.results.length; i += 1) {
        const piece = event.results[i][0].transcript;
        if (event.results[i].isFinal) finalText += piece; else interim += piece;
      }
      heard = true;
      setStatus(`“${(finalText + interim).trim()}”`, 'info');
      setPanelState('listening', { quote: (finalText + interim).trim() });
    };
    rec.onerror = event => {
      const messages = {
        'not-allowed': 'The microphone is blocked. Allow microphone access for this site and try again.',
        'service-not-allowed': 'The microphone is blocked. Allow microphone access for this site and try again.',
        'no-speech': "I didn't hear anything. Tap the button and try again.",
        'audio-capture': 'No microphone was found.',
        network: 'Speech recognition in this browser needs an internet connection. You can type your question instead.',
      };
      const failure = messages[event.error] || 'Voice input stopped. You can type your question instead.';
      setStatus(failure, 'warn');
      setPanelState('error', { text: failure, quote: '' });
      failed = true;
      heard = false;
      finalText = '';
    };
    rec.onend = () => {
      state.recognition = null;
      button.setAttribute('aria-pressed', 'false');
      button.classList.remove('is-listening');
      const question = finalText.trim();
      if (question) { setStatus('', ''); setPanelState('thinking', { text: 'Aria is thinking about your question…', quote: question }); armSpeakNext(); onText(question.slice(0, 480)); }
      else if (!failed) { setPanelState('idle', { text: "I didn't catch that. Tap the microphone and try again.", quote: '' }); if (!heard && statusEl && !statusEl.dataset.kind) setStatus('', ''); }
    };
    state.recognition = rec;
    try { rec.start(); } catch (_) { state.recognition = null; setStatus('Could not start the microphone. Try again.', 'warn'); button.setAttribute('aria-pressed', 'false'); button.classList.remove('is-listening'); }
  }

  if (window.speechSynthesis) {
    window.speechSynthesis.onvoiceschanged = () => {
      refreshVoices();
      document.querySelectorAll('.listen-voice').forEach(fillVoiceSelect);
    };
  }
  window.addEventListener('beforeunload', () => stop(true));
  document.addEventListener('visibilitychange', () => { if (document.hidden && state.session && !state.session.paused) pause(); });

  window.Voice = {
    supported: { get tts() { return supportsTts(); }, get stt() { return supportsStt(); } },
    addListen, refresh, speak, stop, pause, resume, onContentReady, armSpeakNext, disarm, ask, openPanel, closePanel,
    get prefs() { return state.prefs; },
    // exposed for tests
    _collect: collect, _splitSentences: splitSentences,
    _setEngine(mock, utteranceCtor) { state.engine = mock; state.utteranceCtor = utteranceCtor; },
    _state: state, _panel: panel,
  };
})();
