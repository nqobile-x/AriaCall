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
    if (el) { el.classList.add('hidden'); el.style.display = 'none'; }
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
  };

  window.__obNext = function () {
    if (step < TOTAL) window.__obGoTo(step + 1); else window.__obDismiss();
  };

  // Hide immediately if already seen
  try {
    if (localStorage.getItem('aria-onboarded')) {
      const el = obOverlay();
      if (el) { el.classList.add('hidden'); el.style.display = 'none'; }
      return;
    }
  } catch (_) {}

  window.__obGoTo(1);
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
setInterval(() => fetch('/health').catch(() => {}), 10 * 60 * 1000);

function setBusy(busy, text = busy ? 'Thinking…' : 'Ready to help') {
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
    cpMuteBtn.style.background = muted ? '#ff6d4a' : 'transparent';
    cpMuteBtn.style.color = muted ? '#fff' : '#ff6d4a';
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
  if (!SR) { alert('Your browser does not support speech recognition. Try Chrome.'); return; }
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
    alert('Nothing to export yet — start a conversation first.');
    return;
  }
  const existing = document.getElementById('export-modal');
  if (existing) { existing.style.display = 'flex'; return; }

  const modal = document.createElement('div');
  modal.id = 'export-modal';
  modal.style.cssText = 'position:fixed;inset:0;z-index:999;background:rgba(7,8,12,.82);backdrop-filter:blur(6px);display:flex;align-items:center;justify-content:center;padding:24px;';
  modal.innerHTML = `
    <div style="background:#13141a;border:1px solid #252738;border-radius:16px;padding:32px;width:100%;max-width:400px;">
      <h3 style="margin:0 0 8px;font-size:17px;color:#eeeaf4;font-family:'DM Sans',sans-serif;">Export conversation</h3>
      <p style="margin:0 0 20px;font-size:13px;color:#9898a8;line-height:1.6;">Aria will email you a PDF transcript of this conversation.</p>
      <label style="display:block;font-size:11px;letter-spacing:.08em;color:#686872;margin-bottom:6px;">YOUR NAME</label>
      <input id="export-name" type="text" placeholder="e.g. Nqobile" style="width:100%;box-sizing:border-box;background:#0f1018;border:1px solid #252738;border-radius:8px;padding:10px 12px;font-size:14px;color:#eeeaf4;margin-bottom:12px;outline:none;"/>
      <label style="display:block;font-size:11px;letter-spacing:.08em;color:#686872;margin-bottom:6px;">YOUR EMAIL</label>
      <input id="export-email" type="email" placeholder="you@example.com" style="width:100%;box-sizing:border-box;background:#0f1018;border:1px solid #252738;border-radius:8px;padding:10px 12px;font-size:14px;color:#eeeaf4;margin-bottom:20px;outline:none;"/>
      <div style="display:flex;gap:10px;">
        <button id="export-cancel" style="flex:1;padding:11px;background:transparent;border:1px solid #35363d;border-radius:8px;color:#9898a8;font-size:13px;cursor:pointer;">Cancel</button>
        <button id="export-send" style="flex:2;padding:11px;background:#ff6d4a;border:none;border-radius:8px;color:#fff;font-size:13px;font-weight:600;cursor:pointer;">Send PDF →</button>
      </div>
      <p id="export-status" style="margin:12px 0 0;font-size:12px;text-align:center;color:#9898a8;min-height:18px;"></p>
    </div>`;

  document.body.appendChild(modal);

  document.getElementById('export-cancel').addEventListener('click', () => modal.style.display = 'none');
  modal.addEventListener('click', e => { if (e.target === modal) modal.style.display = 'none'; });

  document.getElementById('export-send').addEventListener('click', async () => {
    const email = document.getElementById('export-email').value.trim();
    const name = document.getElementById('export-name').value.trim() || 'Learner';
    const status = document.getElementById('export-status');
    if (!email || !email.includes('@')) { status.style.color = '#f87171'; status.textContent = 'Enter a valid email address.'; return; }

    const btn = document.getElementById('export-send');
    btn.disabled = true; btn.textContent = 'Sending…';
    status.style.color = '#9898a8'; status.textContent = '';

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
      status.style.color = '#6ee7b7'; status.textContent = `Sent! Check ${email}`;
      btn.textContent = 'Sent ✓';
    } catch (err) {
      status.style.color = '#f87171'; status.textContent = err.message;
      btn.disabled = false; btn.textContent = 'Send PDF →';
    }
  });
}

document.getElementById('export-pdf-btn')?.addEventListener('click', openExportModal);
