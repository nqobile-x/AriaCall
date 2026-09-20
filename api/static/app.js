// Every request carries an anonymous per-browser id. The server rate-limits per browser (and more loosely per
// network), so a whole class behind one school IP is not throttled as if it were one person. It is random
// and holds no personal data.
(function () {
  let id = '';
  try { id = localStorage.getItem('aria-client-id') || ''; } catch (_) { /* private mode */ }
  if (!id) {
    id = (crypto.randomUUID ? crypto.randomUUID() : String(Math.random()).slice(2) + Date.now());
    try { localStorage.setItem('aria-client-id', id); } catch (_) { /* keep in memory for this page */ }
  }
  const realFetch = window.fetch.bind(window);
  window.fetch = (input, init = {}) => {
    try {
      const url = typeof input === 'string' ? input : input.url;
      if (url.startsWith('/') || url.startsWith(location.origin)) {
        const headers = new Headers(init.headers || (typeof input !== 'string' ? input.headers : undefined));
        headers.set('X-Client-Id', id);
        init = { ...init, headers };
      }
    } catch (_) { /* never block a request over this */ }
    return realFetch(input, init);
  };
})();

const conversation = document.querySelector('#conversation');
const textarea = document.querySelector('#message');
const send = document.querySelector('#send');
const mic = document.querySelector('#mic');
const callBtn = document.querySelector('#call');
const status = document.querySelector('#status');
const ticketBanner = document.querySelector('#ticket-banner');
const callPanel = document.querySelector('#call-panel');
const cpStatus = document.querySelector('#cp-status');
const cpMinimize = document.querySelector('#cp-minimize');
const cpExpand = document.querySelector('#cp-expand');
const cpEndMini = document.querySelector('#cp-end-mini');
const cpEndButton = document.querySelector('#cp-end-btn');
const cpMuteBtn = document.querySelector('#cp-mute');
const promptPanes = document.querySelector('#prompt-panes');
const conversationIdKey = 'aria-conversation-id';

// ── ONBOARDING WIZARD ────────────────────────────────────────────────────────
// Exposed to window so inline onclick attrs work even if addEventListener is slow
(function () {
  const TOTAL = 3;
  let step = 1;

  function obOverlay() { return document.getElementById('onboard-overlay'); }

  window.__obDismiss = function () {
    try { localStorage.setItem('aria-onboarded', '1'); } catch (_) {}
    const el = obOverlay();
    const wasOpen = el && el.style.display !== 'none' && !el.classList.contains('hidden');
    if (el) { el.classList.add('hidden'); el.style.display = 'none'; }
    // Give the message box focus so typing works straight away (skipped on touch, where it would pop the keyboard).
    if (wasOpen && window.matchMedia && window.matchMedia('(pointer: fine)').matches) {
      const box = document.getElementById('message');
      if (box) box.focus();
    }
  };

  window.__obGoTo = function (n) {
    step = n;
    document.querySelectorAll('.ob-step').forEach(s => s.classList.remove('active'));
    const stepEl = document.getElementById('ob-step-' + n);
    if (stepEl) stepEl.classList.add('active');
    for (let i = 1; i <= TOTAL; i++) {
      const pb = document.getElementById('pb' + i);
      if (pb) pb.className = 'ob-prog-bar' + (i < n ? ' done' : i === n ? ' active' : '');
    }
    const nextBtn = document.getElementById('ob-next');
    if (nextBtn) nextBtn.textContent = n === TOTAL ? 'Start chatting' : 'Next';
    const overlay = obOverlay();
    if (overlay) overlay.setAttribute('aria-label', 'Welcome to Aria, step ' + n + ' of ' + TOTAL);
  };

  window.__obNext = function () {
    if (step < TOTAL) window.__obGoTo(step + 1); else window.__obDismiss();
  };

  // /chat?guide=1 replays the guide (the landing page links to it).
  try {
    if (new URLSearchParams(location.search).has('guide')) {
      localStorage.removeItem('aria-onboarded');
      history.replaceState(null, '', location.pathname);
    }
  } catch (_) {}

  // Hide immediately if already seen
  try {
    if (localStorage.getItem('aria-onboarded')) {
      const el = obOverlay();
      if (el) { el.classList.add('hidden'); el.style.display = 'none'; }
      return;
    }
  } catch (_) {}

  window.__obGoTo(1);

  // Keyboard: focus starts on Next, Tab stays inside the dialog, Esc closes it.
  const focusables = () => [document.getElementById('ob-skip'), document.getElementById('ob-next')].filter(Boolean);
  document.addEventListener('keydown', function (e) {
    const el = obOverlay();
    if (!el || el.classList.contains('hidden') || el.style.display === 'none') return;
    if (e.key === 'Escape') { e.preventDefault(); window.__obDismiss(); return; }
    if (e.key !== 'Tab') return;
    const items = focusables();
    if (!items.length) return;
    const first = items[0], last = items[items.length - 1];
    if (!el.contains(document.activeElement)) { e.preventDefault(); (e.shiftKey ? last : first).focus(); }
    else if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
    else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
  });
  const startBtn = document.getElementById('ob-next');
  if (startBtn) startBtn.focus();
})();

// ── ARIA WAVE AVATAR ─────────────────────────────────────────────────────────
// The wave SVG is always animated by its own CSS keyframes — no JS state needed.

let selectedVoiceEngine = localStorage.getItem('aria-voice-engine') || 'orpheus';
document.querySelectorAll('.vbtn').forEach(btn => {
  btn.classList.toggle('active', btn.dataset.engine === selectedVoiceEngine);
  btn.addEventListener('click', () => {
    selectedVoiceEngine = btn.dataset.engine;
    localStorage.setItem('aria-voice-engine', selectedVoiceEngine);
    document.querySelectorAll('.vbtn').forEach(b => b.classList.toggle('active', b === btn));
  });
});

let conversationId = localStorage.getItem(conversationIdKey) || crypto.randomUUID();
localStorage.setItem(conversationIdKey, conversationId);
const LIMITED_TEXT = 'AI limited — built-in mode';

async function refreshHealth() {
  const setLabel = (text, limited, title = '') => {
    if (limited) status.dataset.limited = text; else delete status.dataset.limited;
    if (!status.classList.contains('busy')) status.lastChild.textContent = text;
    status.title = title;
  };
  if (navigator.onLine === false) return setLabel('Offline — device has no connection', true, 'Reconnect to use the online features. Lessons and Python practice you have already opened may still work.');
  try {
    const health = await (await fetch('/health')).json();
    if (health.mode === 'offline') return setLabel('Offline mode', true, 'This server is running without internet. Built-in guidance, local AI (if installed), data cleaning and checks still work.');
    const limited = health.llm_circuit?.status === 'down' || health.llm === 'local fallback';
    const title = limited ? 'The online AI is unavailable. Built-in guidance' + (health.local_ai ? `, the local AI (${health.local_ai})` : '') + ', data cleaning and checks still work.' : '';
    setLabel(limited ? (health.local_ai ? 'AI limited — local model' : LIMITED_TEXT) : 'System available', limited, title);
  } catch (_) {
    setLabel('Server unreachable', true, 'Cannot reach the Aria server. Check your connection.');
  }
}
refreshHealth();
setInterval(refreshHealth, 60 * 1000);
window.addEventListener('online', refreshHealth);
window.addEventListener('offline', refreshHealth);
if ('serviceWorker' in navigator) navigator.serviceWorker.register('/sw.js').catch(() => { /* optional: the app works without it */ });

function setBusy(busy, text = busy ? 'Thinking…' : (status.dataset.limited || 'Ready to help')) {
  status.classList.toggle('busy', busy);
  status.lastChild.textContent = text;
  send.disabled = busy;
}

function showPromptPanes() {
  if (promptPanes && !promptPanes.classList.contains('visible')) {
    promptPanes.classList.add('visible');
  }
}

function setCpStatus(text) {
  if (cpStatus) cpStatus.textContent = text;
}

function openCallPanel() {
  if (!callPanel) return;
  callPanel.setAttribute('aria-hidden', 'false');
  requestAnimationFrame(() => callPanel.classList.add('open'));
}

function closeCallPanel() {
  if (!callPanel) return;
  callPanel.classList.remove('open');
  callPanel.setAttribute('aria-hidden', 'true');
}

function setCallPanelMinimized(minimized) {
  if (!callPanel) return;
  callPanel.classList.toggle('minimized', minimized);
  if (minimized) callPanel.classList.remove('expanded');
  if (cpMinimize) {
    cpMinimize.setAttribute('aria-label', minimized ? 'Restore call panel' : 'Minimise call panel');
    cpMinimize.title = minimized ? 'Restore' : 'Minimise';
  }
}

function toggleCallPanelExpanded() {
  if (!callPanel) return;
  setCallPanelMinimized(false);
  const expanded = callPanel.classList.toggle('expanded');
  if (cpExpand) {
    cpExpand.setAttribute('aria-label', expanded ? 'Restore call panel size' : 'Expand call panel');
    cpExpand.title = expanded ? 'Restore size' : 'Expand';
  }
}

cpMinimize?.addEventListener('click', () => setCallPanelMinimized(!callPanel?.classList.contains('minimized')));
cpExpand?.addEventListener('click', toggleCallPanelExpanded);

// ── CONVERSATION HISTORY (for PDF export) ────────────────────────────────────
const chatHistory = [];

function addMessage(kind, text, sources = []) {
  chatHistory.push({ role: kind === 'user' ? 'user' : 'aria', text });
  document.querySelector('.welcome')?.remove();
  showPromptPanes();
  const item = document.createElement('article');
  item.className = `message ${kind}`;
  item.innerHTML = `<span class="label">${kind === 'user' ? 'YOU' : 'ARIA'}</span><div></div>`;
  item.querySelector('div').textContent = text;
  if (sources.length) {
    const src = document.createElement('p');
    src.className = 'sources';
    src.textContent = `Grounded in: ${sources.map(s => s.title).join(', ')}`;
    item.append(src);
  }
  conversation.append(item);
  conversation.scrollTop = conversation.scrollHeight;
}

function addStreamingMessage() {
  document.querySelector('.welcome')?.remove();
  showPromptPanes();
  const item = document.createElement('article');
  item.className = 'message aria';
  item.innerHTML = '<span class="label">ARIA</span><div><span class="typing-cursor"></span></div>';
  conversation.append(item);
  conversation.scrollTop = conversation.scrollHeight;
  return item;
}

function appendToStreamingMessage(item, token) {
  const div = item.querySelector('div');
  const cursor = div.querySelector('.typing-cursor');
  const text = document.createTextNode(token);
  div.insertBefore(text, cursor);
  conversation.scrollTop = conversation.scrollHeight;
}

function finalizeStreamingMessage(item, sources = []) {
  item.querySelector('.typing-cursor')?.remove();
  const ariaText = (item.querySelector('div')?.textContent || '').trim();
  if (ariaText) chatHistory.push({ role: 'aria', text: ariaText });
  if (sources.length) {
    const src = document.createElement('p');
    src.className = 'sources';
    src.textContent = `Grounded in: ${sources.map(s => s.title).join(', ')}`;
    item.append(src);
  }
}

async function callSupportStream(message, onToken, onDone) {
  const response = await fetch('/support/stream', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', 'X-API-Key': 'aria-demo-key-2024' },
    body: JSON.stringify({ message, conversation_id: conversationId }),
  });
  if (!response.ok) {
    const data = await response.json().catch(() => ({}));
    throw new Error(data.detail || 'Unable to reach Aria');
  }
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const parts = buffer.split('\n\n');
    buffer = parts.pop();
    for (const part of parts) {
      if (!part.startsWith('data: ')) continue;
      const ev = JSON.parse(part.slice(6));
      if (ev.type === 'token') onToken(ev.text);
      else if (ev.type === 'done') onDone(ev);
      else if (ev.type === 'error') throw new Error(ev.detail);
    }
  }
}

async function callSupport(message, retries = 3) {
  for (let attempt = 0; attempt < retries; attempt++) {
    if (attempt > 0) {
      setBusy(true, `Aria waking up… retrying (${attempt}/${retries - 1})`);
      await new Promise(r => setTimeout(r, 12000));
    }
    const response = await fetch('/support', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-API-Key': 'aria-demo-key-2024' },
      body: JSON.stringify({ message, conversation_id: conversationId }),
    });
    let data;
    try { data = await response.json(); } catch (_) {
      if (attempt < retries - 1) continue;
      throw new Error('Aria is still waking up — please try again in a moment.');
    }
    if (!response.ok) throw new Error(data.detail || 'Unable to reach Aria');
    return data;
  }
}

async function speak(text) {
  const withTimeout = (promise, ms) =>
    Promise.race([promise, new Promise(r => setTimeout(r, ms))]);

  const sound = await fetch('/voice', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ text, engine: selectedVoiceEngine }),
  }).catch(() => null);

  if (sound?.ok) {
    return withTimeout(new Promise(resolve => {
      sound.blob().then(blob => {
        const a = new Audio(URL.createObjectURL(blob));
        a.onended = resolve;
        a.onerror = resolve;
        a.play().catch(resolve);
      }).catch(resolve);
    }), 12000);
  }

  return withTimeout(new Promise(resolve => {
    const utt = new SpeechSynthesisUtterance(text);
    utt.rate = 1.0; utt.pitch = 1.05; utt.lang = 'en-US';
    utt.onend = resolve;
    utt.onerror = resolve;
    window.speechSynthesis.cancel();
    window.speechSynthesis.speak(utt);
  }), 12000);
}

async function submit(message = textarea.value.trim()) {
  if (!message || send.disabled) return;
  textarea.value = ''; textarea.style.height = 'auto';
  addMessage('user', message);
  setBusy(true);
  const ariaItem = addStreamingMessage();
  let finalData = null;
  try {
    await callSupportStream(
      message,
      (token) => appendToStreamingMessage(ariaItem, token),
      (result) => {
        finalData = result;
        finalizeStreamingMessage(ariaItem, result.faq_sources);
        if (result.escalated && result.ticket) {
          ticketBanner.hidden = false;
          ticketBanner.innerHTML = `<strong>HUMAN SUPPORT REQUESTED</strong><br>Ticket ${result.ticket.id} is open.`;
        }
        // Log quality score to admin panel if available
        if (result.quality && typeof window.logQuality === 'function') {
          window.logQuality(message, result.quality);
        }
      },
    );
    const spokenReply = (ariaItem.querySelector('div').textContent || '').replace(/_Source:.*?_/s, '').trim();
    await speak(spokenReply);
    setBusy(false, finalData?.escalated ? 'Support ticket created' : 'Ready to help');
  } catch (error) {
    finalizeStreamingMessage(ariaItem);
    ariaItem.querySelector('div').textContent = `I'm having trouble connecting right now. ${error.message}`;
    setBusy(false, 'Connection issue');
  }
}

textarea.addEventListener('input', () => {
  textarea.style.height = 'auto';
  textarea.style.height = `${Math.min(textarea.scrollHeight, 130)}px`;
});
textarea.addEventListener('keydown', e => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); submit(); } });
send.addEventListener('click', () => submit());
document.querySelectorAll('[data-prompt]').forEach(btn => btn.addEventListener('click', () => submit(btn.dataset.prompt)));
document.querySelector('#human-help')?.addEventListener('click', () => submit('I need a human agent to help me.'));
document.querySelector('#new-chat').addEventListener('click', () => {
  conversationId = crypto.randomUUID();
  localStorage.setItem(conversationIdKey, conversationId);
  conversation.innerHTML = '';
  chatHistory.length = 0;
  ticketBanner.hidden = true;
  promptPanes?.classList.remove('visible');
  textarea.focus();
  setBusy(false, 'New conversation');
  if (inCall) endCall();
});

// ── VOICE-TO-VOICE CALL MODE ─────────────────────────────────────────────────
let inCall = false;
let recognition = null;
let callAudioPlaying = false;
let callMuted = false;

function setMuted(muted) {
  callMuted = muted;
  if (cpMuteBtn) {
    cpMuteBtn.title = muted ? 'Unmute' : 'Mute';
    cpMuteBtn.setAttribute('aria-label', muted ? 'Unmute microphone' : 'Mute microphone');
    cpMuteBtn.classList.toggle('is-muted', muted);
  }
  if (muted) {
    recognition?.stop();
    setCpStatus('Muted');
  } else if (inCall && !callAudioPlaying) {
    setBusy(false, 'CALL ACTIVE — listening…');
    setCpStatus('Listening…');
    recognition?.start();
  }
}

cpMuteBtn?.addEventListener('click', () => setMuted(!callMuted));

function startCall() {
  const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
  if (!SR) { showToast('Your browser does not support speech recognition. Try Chrome or Edge.'); return; }
  inCall = true;
  callMuted = false;
  callBtn.classList.add('in-call');
  callBtn.setAttribute('aria-label', 'End voice call');
  callBtn.title = 'End call';
  setBusy(false, 'CALL ACTIVE — Aria greeting…');
  openCallPanel();
  setCpStatus('Connecting…');

  const GREETINGS = [
    "Hi, thanks for calling PulseFlow support. I'm Aria. How can I help you today?",
    "Hello! You've reached PulseFlow support. I'm Aria, your virtual assistant. What can I do for you?",
    "Hi there! This is Aria from PulseFlow support. How can I assist you today?",
  ];
  const FILLERS = [
    "Got it, one moment.",
    "Sure, let me check that for you.",
    "Absolutely, give me just a second.",
    "On it, one moment please.",
    "Of course, let me look into that.",
  ];

  recognition = new SR();
  recognition.lang = 'en-US';
  recognition.continuous = false;
  recognition.interimResults = false;

  // Speak greeting before starting to listen
  callAudioPlaying = true;
  setCpStatus('Aria is greeting you…');
  const greeting = GREETINGS[Math.floor(Math.random() * GREETINGS.length)];
  addMessage('aria', greeting);
  speak(greeting).then(() => {
    callAudioPlaying = false;
    if (inCall) {
      setBusy(false, 'CALL ACTIVE — listening…');
      setCpStatus('Listening…');
      recognition.start();
    }
  });

  recognition.onresult = async (e) => {
    if (callMuted) return;
    const text = e.results[0][0].transcript.trim();
    if (!text) { if (inCall && !callAudioPlaying && !callMuted) recognition.start(); return; }
    recognition.stop();
    callAudioPlaying = true;
    addMessage('user', text);
    setBusy(false, 'CALL ACTIVE — Aria speaking…');
    setCpStatus('Aria is speaking…');

    // Speak filler immediately while fetching the real answer
    const filler = FILLERS[Math.floor(Math.random() * FILLERS.length)];
    const fillerDone = speak(filler);
    const supportDone = callSupport(text);

    try {
      await fillerDone;
      const data = await supportDone;
      const reply = data.response.replace(/_Source:.*?_/s, '').trim();
      addMessage('aria', reply, data.faq_sources);
      if (data.escalated && data.ticket) {
        ticketBanner.hidden = false;
        ticketBanner.innerHTML = `<strong>HUMAN SUPPORT REQUESTED</strong><br>Ticket ${data.ticket.id} is open.`;
      }
      await speak(reply);
    } catch (err) {
      addMessage('aria', `Connection issue: ${err.message}`);
    }
    callAudioPlaying = false;
    if (inCall) {
      setBusy(false, 'CALL ACTIVE — listening…');
      setCpStatus('Listening…');
      recognition.start();
    }
  };

  recognition.onerror = (e) => {
    if (e.error === 'no-speech' && inCall && !callAudioPlaying && !callMuted) { recognition.start(); return; }
    if (e.error !== 'aborted') setBusy(false, `CALL — mic error: ${e.error}`);
  };

  recognition.onend = () => {
    if (inCall && !callAudioPlaying && !callMuted) recognition.start();
  };

  recognition.start();
}

function endCall() {
  inCall = false;
  callAudioPlaying = false;
  setMuted(false);
  callBtn.classList.remove('in-call');
  callBtn.setAttribute('aria-label', 'Start voice call');
  callBtn.title = 'Start voice call';
  recognition?.stop();
  recognition = null;
  window.speechSynthesis?.cancel();
  closeCallPanel();
  setBusy(false, 'Ready to help');
}

window.__endCall = endCall;
cpEndButton?.addEventListener('click', endCall);
cpEndMini?.addEventListener('click', endCall);

callBtn.addEventListener('click', () => { inCall ? endCall() : startCall(); });

// ── ONE-SHOT MIC (whisper-to-text) ───────────────────────────────────────────
let recorder, stream, chunks = [], audioContext, analyser, silenceTimer, listeningStarted;

function monitorSilence() {
  const samples = new Uint8Array(analyser.fftSize);
  const tick = () => {
    if (recorder?.state !== 'recording') return;
    analyser.getByteTimeDomainData(samples);
    let energy = 0;
    for (const s of samples) energy += Math.abs(s - 128);
    if (energy / samples.length > 2.5) silenceTimer = performance.now();
    if (performance.now() - listeningStarted > 1500 && performance.now() - silenceTimer > 1800) { recorder.stop(); return; }
    requestAnimationFrame(tick);
  };
  requestAnimationFrame(tick);
}

mic.addEventListener('click', async () => {
  if (inCall) { endCall(); return; }
  if (recorder?.state === 'recording') return;
  try {
    stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    const options = MediaRecorder.isTypeSupported('audio/webm') ? { mimeType: 'audio/webm' } : undefined;
    recorder = new MediaRecorder(stream, options);
    chunks = [];
    recorder.ondataavailable = e => chunks.push(e.data);
    recorder.onstart = () => {
      audioContext = new AudioContext();
      analyser = audioContext.createAnalyser();
      analyser.fftSize = 1024;
      audioContext.createMediaStreamSource(stream).connect(analyser);
      listeningStarted = silenceTimer = performance.now();
      mic.classList.add('listening');
      setBusy(false, 'Listening…');
      monitorSilence();
    };
    recorder.onerror = () => { mic.classList.remove('listening'); stream?.getTracks().forEach(t => t.stop()); };
    recorder.onstop = async () => {
      mic.classList.remove('listening');
      audioContext?.close();
      stream.getTracks().forEach(t => t.stop());
      try {
        const form = new FormData();
        form.append('audio', new Blob(chunks, { type: recorder.mimeType }), 'aria-recording.webm');
        const r = await fetch('/transcribe', { method: 'POST', body: form });
        const d = await r.json();
        if (!r.ok || !d.text) throw new Error('No speech detected');
        submit(d.text);
      } catch (err) {
        setBusy(false, err.message.startsWith('No speech') ? 'No speech detected — try again' : 'Mic error — try again');
      }
    };
    recorder.start();
  } catch (error) {
    setBusy(false, error.name === 'NotAllowedError' ? 'Allow microphone access' : 'Microphone unavailable');
  }
});

// ── PDF EXPORT ────────────────────────────────────────────────────────────────
function openExportModal() {
  if (chatHistory.length === 0) {
    showToast('Nothing to export yet — start a conversation first.');
    return;
  }
  const existing = document.getElementById('export-modal');
  if (existing) { existing.hidden = false; existing.querySelector('#export-name').focus(); return; }

  const modal = document.createElement('div');
  modal.id = 'export-modal';
  modal.className = 'modal-backdrop';
  modal.innerHTML = `
    <div class="modal" role="dialog" aria-modal="true" aria-labelledby="export-title">
      <h3 id="export-title">Export conversation</h3>
      <p class="note">Aria will email you a PDF transcript of this conversation.</p>
      <label class="form-label" for="export-name">Your name</label>
      <input id="export-name" class="field" type="text" placeholder="e.g. Nqobile" autocomplete="name" />
      <label class="form-label" for="export-email">Your email</label>
      <input id="export-email" class="field" type="email" placeholder="you@example.com" autocomplete="email" inputmode="email" />
      <div class="modal-actions">
        <button id="export-cancel" class="btn btn-ghost" type="button">Cancel</button>
        <button id="export-send" class="btn btn-primary" type="button">Send PDF →</button>
      </div>
      <p id="export-status" class="note" role="status" style="margin-top:12px;text-align:center;min-height:20px"></p>
    </div>`;
  document.body.appendChild(modal);
  const close = () => { modal.hidden = true; document.getElementById('export-pdf-btn')?.focus(); };
  document.getElementById('export-cancel').addEventListener('click', close);
  modal.addEventListener('click', e => { if (e.target === modal) close(); });
  modal.addEventListener('keydown', e => { if (e.key === 'Escape') close(); });
  document.getElementById('export-name').focus();

  document.getElementById('export-send').addEventListener('click', async () => {
    const email = document.getElementById('export-email').value.trim();
    const name = document.getElementById('export-name').value.trim() || 'Learner';
    const status = document.getElementById('export-status');
    if (!email || !email.includes('@')) { status.dataset.kind = 'warn'; status.textContent = 'Enter a valid email address.'; return; }

    const btn = document.getElementById('export-send');
    btn.disabled = true; btn.textContent = 'Sending…';
    status.dataset.kind = ''; status.textContent = '';

    try {
      const resp = await fetch('/support/export-pdf', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'X-API-Key': 'aria-demo-key-2024' },
        body: JSON.stringify({ to_email: email, recipient_name: name, messages: chatHistory }),
      });
      if (!resp.ok) {
        const err = await resp.json().catch(() => ({}));
        throw new Error(err.detail || 'Failed to send');
      }
      status.dataset.kind = 'info'; status.textContent = `Sent! Check ${email}`;
      btn.textContent = 'Sent ✓';
    } catch (err) {
      status.dataset.kind = 'warn'; status.textContent = err instanceof TypeError ? "Can't reach the Aria server." : err.message;
      btn.disabled = false; btn.textContent = 'Send PDF →';
    }
  });
}

document.getElementById('export-pdf-btn')?.addEventListener('click', openExportModal);

// ── MODE TABS (Chat / Code / Data / Practice) ────────────────────────────────
let _codeLang = 'python';
let _lessonsRequested = false;  // lessons load the first time the Code section opens (not for chat-only visitors)

function escapeHtml(s) {
  return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}

function showToast(message, ms = 3800) {
  document.querySelector('.toast')?.remove();
  const el = document.createElement('div');
  el.className = 'toast';
  el.setAttribute('role', 'status');
  el.textContent = message;
  document.body.appendChild(el);
  setTimeout(() => el.remove(), ms);
}
window.showToast = showToast;

function switchMode(mode) {
  window.Voice?.stop(true);
  window.Voice?.closePanel();
  document.querySelectorAll('.mode-tab').forEach(t => {
    const active = t.dataset.mode === mode;
    t.classList.toggle('is-active', active);
    t.setAttribute('aria-selected', String(active));
    t.tabIndex = active ? 0 : -1;
  });
  const isChat = mode === 'chat';
  const chat = [
    document.getElementById('conversation'),
    document.getElementById('ticket-banner'),
    document.getElementById('prompt-panes'),
    document.querySelector('.composer'),
  ];
  chat.forEach(el => { if (el && el.id !== 'ticket-banner') el.style.display = isChat ? '' : 'none'; });
  const banner = document.getElementById('ticket-banner');
  if (banner) banner.style.display = isChat ? '' : 'none';
  for (const [id, name] of [['panel-code', 'code'], ['panel-data', 'data'], ['panel-practice', 'practice']]) {
    const panel = document.getElementById(id);
    if (panel) panel.style.display = mode === name ? 'flex' : 'none';
  }
  if (mode === 'practice') window.Practice?.open();
  if (mode === 'code' && !_lessonsRequested) { _lessonsRequested = true; _loadLessons(_codeLang); }
}
window.switchMode = switchMode;

document.querySelectorAll('.mode-tab').forEach(tab => {
  tab.addEventListener('click', () => switchMode(tab.dataset.mode));
  tab.addEventListener('keydown', e => {
    if (e.key !== 'ArrowRight' && e.key !== 'ArrowLeft') return;
    const tabs = [...document.querySelectorAll('.mode-tab')];
    const next = tabs[(tabs.indexOf(tab) + (e.key === 'ArrowRight' ? 1 : tabs.length - 1)) % tabs.length];
    next.focus();
    switchMode(next.dataset.mode);
  });
});
document.querySelectorAll('.mode-tab').forEach(t => { t.tabIndex = t.classList.contains('is-active') ? 0 : -1; });

// ── CODE MODE: mentor (Python / Java / Spring Boot / Data Science) ───────────
let _codeLevel = 'beginner';
window.getCodeLevel = () => _codeLevel;
let _lessons = [];
let _activeLesson = null;
let _lastStarter = '';
let _tutorAbort = null;

function _renderMarkdown(text) {
  return text.split('```').map((part, i) => {
    if (i % 2 === 1) {
      const nl = part.indexOf('\n');
      const body = (nl >= 0 ? part.slice(nl + 1) : part).replace(/\n$/, '');
      return `<pre class="pre">${escapeHtml(body)}</pre>`;
    }
    return part.split('\n').map(rawLine => {
      let line = rawLine.replace(/\\([<>_*`])/g, '$1');
      if (/^\s*\|?[\s:|-]+\|[\s:|-]*$/.test(line) && line.includes('-')) return '';
      if (/^\s*\|.*\|\s*$/.test(line)) {
        line = '- ' + line.trim().slice(1, -1).split('|').map(c => c.trim()).filter(Boolean).join(' — ');
      }
      if (!line.trim()) return '<div class="md-gap"></div>';
      if (/^\s*(-{3,}|\*{3,})\s*$/.test(line)) return '<hr class="md-hr">';
      const h = escapeHtml(line)
        .replace(/`([^`\n]+)`/g, '<code class="code-inline">$1</code>')
        .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
        .replace(/(^|[\s(])\*([^*\s][^*]*?)\*(?=[\s).,;:!?]|$)/g, '$1<em>$2</em>');
      const heading = h.match(/^#{1,4}\s+(.*)$/);
      if (heading) return `<div class="result-h">${heading[1]}</div>`;
      const bullet = h.match(/^\s*[-*]\s+(.*)$/);
      if (bullet) return `<div class="md-li">• ${bullet[1]}</div>`;
      return `<div>${h}</div>`;
    }).join('');
  }).join('');
}

function _renderNotice(text) {
  return `<div class="notice notice-warn">${escapeHtml(text)}</div>`;
}

function _renderLint(items) {
  if (!items?.length) return '';
  const rows = items.map(i => `<div class="lint-row"><span class="sev sev-${escapeHtml(i.severity)}">${escapeHtml(i.severity)}</span><span>${escapeHtml(i.message)}</span></div>`).join('');
  return `<div class="lint card"><span class="label">Automated checks</span>${rows}</div>`;
}

async function _streamTutor(body, output, opts = {}) {
  const listenRoot = opts.listenContainer || output;
  _tutorAbort?.abort();
  const controller = new AbortController();
  _tutorAbort = controller;
  if (!opts.listenContainer) window.Voice?.addListen(output);
  window.Voice?.stop(true);
  if (!opts.listenContainer && output._listenBar) output._listenBar.hidden = true;
  output.setAttribute('aria-busy', 'true');
  output.innerHTML = '<p class="empty">Aria is thinking… <span class="typing-cursor"></span></p>';
  let lintHtml = '';
  let noticeHtml = '';
  let text = '';
  const paint = done => {
    output.innerHTML = noticeHtml + lintHtml + _renderMarkdown(text) + (done ? '' : '<span class="typing-cursor"></span>');
    output.scrollTop = output.scrollHeight;
  };
  try {
    const resp = await fetch('/tutor/stream', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-API-Key': 'aria-demo-key-2024' },
      body: JSON.stringify(body),
      signal: controller.signal,
    });
    if (!resp.ok) {
      const e = await resp.json().catch(() => ({}));
      throw new Error(typeof e.detail === 'string' ? e.detail : 'Request failed');
    }
    const reader = resp.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const events = buffer.split('\n\n');
      buffer = events.pop();
      for (const raw of events) {
        if (!raw.startsWith('data: ')) continue;
        const evt = JSON.parse(raw.slice(6));
        if (evt.type === 'lint') { lintHtml = _renderLint(evt.items); paint(false); }
        else if (evt.type === 'notice') { noticeHtml = _renderNotice(evt.text); paint(false); }
        else if (evt.type === 'token') { text += evt.text; paint(false); }
        else if (evt.type === 'error') throw new Error(evt.detail);
      }
    }
    paint(true);
    window.Voice?.onContentReady(listenRoot, output);
  } catch (e) {
    if (e.name === 'AbortError') return;
    if (e instanceof TypeError) e = new Error("Can't reach the Aria server. Check your connection. Data cleaning, lessons and Python practice may still work offline if you have opened them before.");
    output.innerHTML = noticeHtml + lintHtml + _renderMarkdown(text) + `<div class="notice notice-bad">${escapeHtml(e.message)}</div>`;
    window.Voice?.disarm();
  } finally {
    output.removeAttribute('aria-busy');
    if (_tutorAbort === controller) _tutorAbort = null;
  }
}
window._streamTutor = _streamTutor;

function _setActive(buttons, active) {
  buttons.forEach(b => {
    const on = b === active;
    b.classList.toggle('is-active', on);
    b.setAttribute('aria-pressed', String(on));
  });
}

async function _loadLessons(language) {
  const select = document.getElementById('lesson-select');
  if (!select) return;
  _lessons = [];
  _activeLesson = null;
  select.innerHTML = '<option value="">Free practice</option>';
  _updateLessonUi();
  try {
    const resp = await fetch(`/tutor/lessons?language=${encodeURIComponent(language)}`, { headers: { 'X-API-Key': 'aria-demo-key-2024' } });
    if (!resp.ok || language !== _codeLang) return;
    _lessons = await resp.json();
    _lessons.forEach((lesson, i) => {
      const opt = document.createElement('option');
      opt.value = lesson.id;
      opt.textContent = `${i + 1}. ${lesson.title}`;
      select.appendChild(opt);
    });
  } catch (_) { /* lessons are optional; free practice still works */ }
}

function _updateLessonUi() {
  const teach = document.getElementById('lesson-teach-btn');
  const goal = document.getElementById('lesson-goal');
  if (teach) teach.disabled = !_activeLesson;
  if (goal) {
    goal.hidden = !_activeLesson;
    goal.textContent = _activeLesson ? `Goal: ${_activeLesson.goal}` : '';
  }
}

document.querySelectorAll('.clang-btn').forEach(btn => {
  btn.addEventListener('click', () => {
    _setActive([...document.querySelectorAll('.clang-btn')], btn);
    _codeLang = btn.dataset.lang;
    _lessonsRequested = true;
    const runBtn = document.getElementById('code-run-btn');
    if (runBtn) runBtn.hidden = !(_codeLang === 'python' || _codeLang === 'datascience');
    _loadLessons(_codeLang);
  });
});

document.querySelectorAll('.clevel-btn').forEach(btn => {
  btn.addEventListener('click', () => {
    _setActive([...document.querySelectorAll('.clevel-btn')], btn);
    _codeLevel = btn.dataset.level;
  });
});

document.getElementById('lesson-select')?.addEventListener('change', e => {
  _activeLesson = _lessons.find(l => l.id === e.target.value) || null;
  const input = document.getElementById('code-input');
  if (_activeLesson && input) {
    const untouched = !input.value.trim() || input.value === _lastStarter;
    if (untouched || confirm("Replace the code in the box with this lesson's starter code?")) {
      input.value = _activeLesson.starter;
      _lastStarter = _activeLesson.starter;
    }
  }
  _updateLessonUi();
});

function _runMentor(mode, question = '') {
  const input = document.getElementById('code-input');
  const output = document.getElementById('code-output');
  if (!output) return;
  const code = input?.value.trim() || '';
  if (mode !== 'teach' && !code) {
    showToast('Paste some code first.');
    input?.focus();
    return;
  }
  _streamTutor({
    language: _codeLang,
    level: _codeLevel,
    mode,
    code: mode === 'teach' ? '' : code,
    lesson_id: _activeLesson?.id || null,
    question: question.slice(0, 480),
  }, output);
}

document.getElementById('code-explain-btn')?.addEventListener('click', () => _runMentor('explain'));
document.getElementById('code-review-btn')?.addEventListener('click', () => _runMentor('review'));
document.getElementById('lesson-teach-btn')?.addEventListener('click', () => _runMentor('teach'));

// Ask by voice: speak a question about the code (or the chosen lesson); Aria answers and reads it aloud.
document.getElementById('code-voice-btn')?.addEventListener('click', () => {
  const button = document.getElementById('code-voice-btn');
  const status = document.getElementById('code-voice-status');
  window.Voice?.ask(button, status, question => {
    const code = document.getElementById('code-input')?.value.trim();
    if (code) _runMentor('explain', question);
    else if (_activeLesson) _runMentor('teach', question);
    else {
      window.Voice.disarm();
      status.textContent = 'Paste some code or pick a lesson first, then ask your question.';
      status.dataset.kind = 'warn';
      return;
    }
    status.textContent = `You asked: “${question}”`;
    status.dataset.kind = 'info';
  });
});

// Keyboard: Ctrl/Cmd+Enter explains; Tab indents (press Esc first to move focus away with Tab).
(() => {
  const editor = document.getElementById('code-input');
  if (!editor) return;
  let releaseTab = false;
  editor.addEventListener('keydown', e => {
    if (e.key === 'Escape') { releaseTab = true; return; }
    if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) { e.preventDefault(); _runMentor('explain'); return; }
    if (e.key === 'Tab' && !e.shiftKey && !releaseTab) {
      e.preventDefault();
      editor.setRangeText('    ', editor.selectionStart, editor.selectionEnd, 'end');
    } else if (e.key !== 'Tab') {
      releaseTab = false;
    }
  });
})();

// The mentor's answer gets a listen bar (read aloud with the current sentence highlighted).
window.Voice?.addListen(document.getElementById('code-output'));

// ── CODE MODE: run (Python only) ──────────────────────────────────────────────
document.getElementById('code-run-btn')?.addEventListener('click', async () => {
  const code = document.getElementById('code-input')?.value.trim();
  const output = document.getElementById('code-output');
  if (!output) return;
  if (!code) { showToast('Paste some code first.'); return; }
  window.Voice?.stop(true);
  if (output._listenBar) output._listenBar.hidden = true;
  output.innerHTML = '<p class="empty">Running… <span class="typing-cursor"></span></p>';
  try {
    const resp = await fetch('/code/run', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-API-Key': 'aria-demo-key-2024' },
      body: JSON.stringify({ code, language: _codeLang === 'datascience' ? 'datascience' : 'python' }),
    });
    if (!resp.ok) throw new Error((await resp.json().catch(() => ({}))).detail || 'The code runner is unavailable.');
    const result = await resp.json();
    const stdout = (result.stdout || '').trim();
    const stderr = (result.stderr || '').trim();
    const error = (result.error || '').trim();
    let html = '';
    if (stdout) html += `<span class="label">Output</span><pre class="pre">${escapeHtml(stdout)}</pre>`;
    if (stderr || error) html += `<span class="label" style="margin-top:12px">Error</span><pre class="pre pre-bad">${escapeHtml(stderr || error)}</pre>`;
    output.innerHTML = html || '<p class="empty">No output.</p>';
  } catch (e) {
    output.innerHTML = `<div class="notice notice-bad">${escapeHtml(e instanceof TypeError ? "Can't reach the Aria server." : e.message)}</div>`;
  }
});

// ── DATA MODE: file handling ──────────────────────────────────────────────────
const _dataDropzone = document.getElementById('data-dropzone');
const _dataFileInput = document.getElementById('data-file-input');
const _dataAnalyzeBtn = document.getElementById('data-analyze-btn');
const _dataFileName = document.getElementById('data-file-name');
const _DATA_EXT = /\.(csv|xlsx|xls|json)$/i;
let _dataFile = null;
let _lastProfile = null;

function _setDataFile(file) {
  if (file && !_DATA_EXT.test(file.name)) {
    showToast('Please choose a CSV, Excel (.xlsx/.xls) or JSON file.');
    return;
  }
  _dataFile = file;
  if (_dataFileName) _dataFileName.textContent = file ? file.name : '';
  if (_dataAnalyzeBtn) _dataAnalyzeBtn.disabled = !file;
}

_dataFileInput?.addEventListener('change', () => _setDataFile(_dataFileInput.files[0] || null));
_dataDropzone?.addEventListener('click', e => { if (e.target !== _dataFileInput) _dataFileInput?.click(); });
_dataDropzone?.addEventListener('keydown', e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); _dataFileInput?.click(); } });
_dataDropzone?.addEventListener('dragover', e => { e.preventDefault(); _dataDropzone.classList.add('is-over'); });
_dataDropzone?.addEventListener('dragleave', () => _dataDropzone.classList.remove('is-over'));
_dataDropzone?.addEventListener('drop', e => {
  e.preventDefault();
  _dataDropzone.classList.remove('is-over');
  const file = e.dataTransfer?.files[0];
  if (file) _setDataFile(file);
});

function _statCard(label, value) {
  return `<div class="stat"><span class="label">${label}</span><b>${value ?? '—'}</b></div>`;
}

_dataAnalyzeBtn?.addEventListener('click', async () => {
  if (!_dataFile) return;
  const output = document.getElementById('data-output');
  if (!output) return;
  _dataAnalyzeBtn.disabled = true;
  _dataAnalyzeBtn.textContent = 'Analyzing…';
  output.innerHTML = '<p class="note">Reading your file… <span class="typing-cursor"></span></p>';

  try {
    const form = new FormData();
    form.append('file', _dataFile);
    const resp = await fetch('/data/profile', { method: 'POST', body: form });
    if (!resp.ok) {
      const e = await resp.json().catch(() => ({}));
      throw new Error(e.detail || 'Analysis failed');
    }
    const { profile, file: fname } = await resp.json();
    _lastProfile = profile;
    const nullCount = Object.values(profile.null_cols || {}).reduce((a, b) => a + b, 0);

    const colRows = (profile.column_profiles || []).map(col => `
      <tr>
        <td class="mono">${escapeHtml(col.name)}</td>
        <td>${escapeHtml(col.dtype)}</td>
        <td>${col.null_count > 0 ? `<span class="tag">${col.null_count}</span>` : '<span class="muted">0</span>'}</td>
        <td>${col.unique_count ?? '—'}</td>
      </tr>`).join('');

    const issueHtml = profile.issues?.length
      ? `<div class="stack"><span class="label">Issues found</span>${profile.issues.map(i => `<div class="notice notice-bad">${escapeHtml(i)}</div>`).join('')}</div>`
      : '<div class="notice notice-good">No issues found — clean dataset.</div>';

    output.innerHTML = `
      <div class="stack" style="gap:16px">
        <span class="label" style="margin:0">Profile — ${escapeHtml(fname)}</span>
        <div class="stats">
          ${_statCard('Rows', profile.rows)}
          ${_statCard('Columns', profile.columns)}
          ${_statCard('Missing', nullCount)}
          ${_statCard('Duplicates', profile.duplicate_rows)}
        </div>
        ${issueHtml}
        <div class="table-wrap"><table class="table">
          <thead><tr><th>Column</th><th>Type</th><th>Missing</th><th>Unique</th></tr></thead>
          <tbody>${colRows}</tbody>
        </table></div>
        <div id="data-actions" class="actions">
          <button type="button" class="btn btn-primary" data-act="clean">Clean &amp; download</button>
          <button type="button" class="btn btn-secondary" data-act="report">Show what changed</button>
          <button type="button" class="btn btn-secondary" data-act="script">Download Python script</button>
          <button type="button" class="btn btn-outline" data-act="analyse">Ask the data scientist</button>
          <button type="button" class="btn btn-outline" data-act="voice" aria-pressed="false">Ask by voice</button>
        </div>
        <p id="data-action-status" class="note" role="status" aria-live="polite"></p>
        <div id="data-report"></div>
        <div id="data-mentor" class="output" data-listen hidden></div>
      </div>`;
    _wireDataActions(output);
    window.Voice?.addListen(output.querySelector('#data-mentor'));
  } catch (e) {
    output.innerHTML = `<div class="notice notice-bad">${escapeHtml(e instanceof TypeError ? "Can't reach the Aria server. Check your connection." : e.message)}</div>`;
  } finally {
    _dataAnalyzeBtn.disabled = false;
    _dataAnalyzeBtn.textContent = 'Analyze with Aria →';
  }
});

// ── DATA MODE: clean / report / script / ask actions ─────────────────────────
function _downloadBlob(blob, filename) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

async function _postDataFile(mode) {
  const form = new FormData();
  form.append('file', _dataFile);
  const resp = await fetch(`/data/clean?mode=${mode}`, { method: 'POST', body: form });
  if (!resp.ok) {
    const e = await resp.json().catch(() => ({}));
    throw new Error(e.detail || 'Request failed');
  }
  return resp;
}

function _renderDataReport(report) {
  const summary = (report.summary || []).map(s =>
    `<div class="result-row"><b class="mono" style="color:var(--accent)">${s.count}</b> &nbsp;${escapeHtml(s.reason)}<span class="muted"> — ${escapeHtml(s.columns.join(', '))}</span></div>`).join('');
  const removed = report.duplicates_removed
    ? `<div class="result-row">${report.duplicates_removed} duplicate record(s) removed (file rows ${report.removed_rows.map(r => r.row).join(', ')}).</div>` : '';
  const flags = (report.flags || []).map(f => `<div class="notice notice-warn">${escapeHtml(f)}</div>`).join('');
  const rows = (report.changes || []).slice(0, 150).map(c =>
    `<tr><td>${c.row}</td><td class="mono">${escapeHtml(c.column)}</td><td style="color:var(--bad)">${escapeHtml(String(c.before ?? ''))}</td><td style="color:var(--good)">${escapeHtml(String(c.after ?? '(blank)'))}</td></tr>`).join('');
  const more = report.changes_truncated || (report.changes || []).length > 150
    ? '<p class="note">Showing the first 150 changes. Download the cleaned file for the full result.</p>' : '';
  return `<div class="stack">
      <span class="label" style="margin:0">Changes — ${report.rows_before} → ${report.rows_after} rows</span>
      ${summary}${removed}${flags}
      <div class="table-wrap" style="max-height:300px"><table class="table">
        <thead><tr><th>Row</th><th>Column</th><th>Before</th><th>After</th></tr></thead><tbody>${rows}</tbody></table></div>${more}</div>`;
}

function _wireDataActions(root) {
  const status = root.querySelector('#data-action-status');
  const reportBox = root.querySelector('#data-report');
  const mentorBox = root.querySelector('#data-mentor');
  const setStatus = (msg, kind = '') => { status.textContent = msg; status.dataset.kind = kind; };

  const analyse = (question = '') => {
    mentorBox.hidden = false;
    setStatus('Sending column names and counts only, never row values.', 'info');
    return _streamTutor({ language: 'datascience', level: _codeLevel, mode: 'analyse', context: _profileContext(_lastProfile), question }, mentorBox);
  };

  root.querySelectorAll('#data-actions button').forEach(btn => {
    btn.addEventListener('click', async () => {
      if (!_dataFile) return;
      const act = btn.dataset.act;
      if (act === 'voice') {
        window.Voice?.ask(btn, status, question => { setStatus(`You asked: “${question}”. Sending column names and counts only, never row values.`, 'info'); analyse(question); });
        return;
      }
      const label = btn.textContent;
      btn.disabled = true;
      btn.textContent = 'Working…';
      setStatus('');
      try {
        if (act === 'analyse') { await analyse(); return; }
        const resp = await _postDataFile(act);
        if (act === 'report') {
          reportBox.innerHTML = _renderDataReport(await resp.json());
        } else if (act === 'script') {
          _downloadBlob(await resp.blob(), `clean_${_dataFile.name}.py`);
          setStatus('Script downloaded. Run it with: python clean_script.py your_file', 'info');
        } else {
          _downloadBlob(await resp.blob(), `cleaned_${_dataFile.name}`);
          const before = resp.headers.get('X-Rows-Before');
          const after = resp.headers.get('X-Rows-After');
          const changes = resp.headers.get('X-Changes-Made');
          setStatus(`Cleaned file downloaded — ${before} → ${after} rows, ${changes} values fixed. Use “Show what changed” to review every edit.`, 'info');
        }
      } catch (e) {
        setStatus(e instanceof TypeError ? "Can't reach the Aria server. Check your connection." : e.message, 'warn');
      } finally {
        btn.disabled = false;
        btn.textContent = label;
      }
    });
  });
}

function _profileContext(profile) {
  if (!profile) return '';
  const cols = (profile.column_profiles || [])
    .map(c => `- ${c.name}: ${c.dtype}, ${c.null_count} missing, ${c.unique_count} distinct`)
    .join('\n');
  const issues = (profile.issues || []).map(i => `- ${i}`).join('\n');
  return `Rows: ${profile.rows}\nColumns: ${profile.columns}\n\nColumns:\n${cols}\n\nDetected quality issues:\n${issues || '- none'}`.slice(0, 4000);
}
