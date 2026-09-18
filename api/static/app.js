const conversation = document.querySelector('#conversation');
const textarea = document.querySelector('#message');
const send = document.querySelector('#send');
const mic = document.querySelector('#mic');
const callBtn = document.querySelector('#call');
const status = document.querySelector('#status');
const ticketBanner = document.querySelector('#ticket-banner');
const conversationIdKey = 'aria-conversation-id';

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

function addMessage(kind, text, sources = []) {
  document.querySelector('.welcome')?.remove();
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

async function callSupport(message, retries = 3) {
  for (let attempt = 0; attempt < retries; attempt++) {
    if (attempt > 0) {
      setBusy(true, `Aria waking up… retrying (${attempt}/${retries - 1})`);
      await new Promise(r => setTimeout(r, 12000));
    }
    const response = await fetch('/support', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
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
  const sound = await fetch('/voice', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ text, engine: selectedVoiceEngine }),
  });
  if (sound.ok) {
    return new Promise(resolve => {
      sound.blob().then(blob => {
        const a = new Audio(URL.createObjectURL(blob));
        a.onended = resolve;
        a.play();
      });
    });
  } else {
    return new Promise(resolve => {
      const utt = new SpeechSynthesisUtterance(text);
      utt.rate = 1.0; utt.pitch = 1.05; utt.lang = 'en-US';
      utt.onend = resolve;
      window.speechSynthesis.cancel();
      window.speechSynthesis.speak(utt);
    });
  }
}

async function submit(message = textarea.value.trim()) {
  if (!message || send.disabled) return;
  textarea.value = ''; textarea.style.height = 'auto';
  addMessage('user', message);
  setBusy(true);
  try {
    const data = await callSupport(message);
    const spokenReply = data.response.replace(/_Source:.*?_/s, '').trim();
    addMessage('aria', spokenReply, data.faq_sources);
    if (data.escalated && data.ticket) {
      ticketBanner.hidden = false;
      ticketBanner.innerHTML = `<strong>HUMAN SUPPORT REQUESTED</strong><br>Ticket ${data.ticket.id} is open.`;
    }
    await speak(spokenReply);
    setBusy(false, data.escalated ? 'Support ticket created' : 'Ready to help');
  } catch (error) {
    addMessage('aria', `I'm having trouble connecting right now. ${error.message}`);
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
document.querySelector('#human-help').addEventListener('click', () => submit('I need a human agent to help me.'));
document.querySelector('#new-chat').addEventListener('click', () => {
  conversationId = crypto.randomUUID();
  localStorage.setItem(conversationIdKey, conversationId);
  conversation.innerHTML = '';
  ticketBanner.hidden = true;
  textarea.focus();
  setBusy(false, 'New conversation');
  if (inCall) endCall();
});

// ── VOICE-TO-VOICE CALL MODE ─────────────────────────────────────────────────
let inCall = false;
let recognition = null;
let callAudioPlaying = false;

function startCall() {
  const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
  if (!SR) { alert('Your browser does not support speech recognition. Try Chrome.'); return; }
  inCall = true;
  callBtn.classList.add('in-call');
  callBtn.textContent = '🔴';
  callBtn.title = 'End call';
  setBusy(false, 'CALL ACTIVE — listening…');

  recognition = new SR();
  recognition.lang = 'en-US';
  recognition.continuous = false;
  recognition.interimResults = false;

  recognition.onresult = async (e) => {
    const text = e.results[0][0].transcript.trim();
    if (!text) { if (inCall && !callAudioPlaying) recognition.start(); return; }
    recognition.stop();
    callAudioPlaying = true;
    addMessage('user', text);
    setBusy(true, 'Aria is thinking…');
    try {
      const data = await callSupport(text);
      const reply = data.response.replace(/_Source:.*?_/s, '').trim();
      addMessage('aria', reply, data.faq_sources);
      if (data.escalated && data.ticket) {
        ticketBanner.hidden = false;
        ticketBanner.innerHTML = `<strong>HUMAN SUPPORT REQUESTED</strong><br>Ticket ${data.ticket.id} is open.`;
      }
      setBusy(false, 'CALL ACTIVE — Aria speaking…');
      await speak(reply);
    } catch (err) {
      addMessage('aria', `Connection issue: ${err.message}`);
    }
    callAudioPlaying = false;
    if (inCall) { setBusy(false, 'CALL ACTIVE — listening…'); recognition.start(); }
  };

  recognition.onerror = (e) => {
    if (e.error === 'no-speech' && inCall && !callAudioPlaying) { recognition.start(); return; }
    if (e.error !== 'aborted') setBusy(false, `CALL — mic error: ${e.error}`);
  };

  recognition.onend = () => {
    if (inCall && !callAudioPlaying) recognition.start();
  };

  recognition.start();
}

function endCall() {
  inCall = false;
  callAudioPlaying = false;
  callBtn.classList.remove('in-call');
  callBtn.textContent = '📞';
  callBtn.title = 'Start voice call';
  recognition?.stop();
  recognition = null;
  window.speechSynthesis?.cancel();
  setBusy(false, 'Ready to help');
}

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
