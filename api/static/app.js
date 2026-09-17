const conversation = document.querySelector('#conversation');
const textarea = document.querySelector('#message');
const send = document.querySelector('#send');
const mic = document.querySelector('#mic');
const status = document.querySelector('#status');
const voiceNote = document.querySelector('#voice-note');
const ticketBanner = document.querySelector('#ticket-banner');
const conversationIdKey = 'aria-conversation-id';
let conversationId = localStorage.getItem(conversationIdKey) || crypto.randomUUID();
localStorage.setItem(conversationIdKey, conversationId);

function setBusy(busy, text = busy ? 'Thinking…' : 'Ready to help') {
  status.classList.toggle('busy', busy); status.lastChild.textContent = text; send.disabled = busy;
}
function addMessage(kind, text, sources = []) {
  document.querySelector('.welcome')?.remove();
  const item = document.createElement('article'); item.className = `message ${kind}`;
  const label = kind === 'user' ? 'YOU' : 'ARIA';
  item.innerHTML = `<span class="label">${label}</span><div></div>`;
  item.querySelector('div').textContent = text;
  if (sources.length) { const source = document.createElement('p'); source.className = 'sources'; source.textContent = `Grounded in: ${sources.map(s => s.title).join(', ')}`; item.append(source); }
  conversation.append(item); conversation.scrollTop = conversation.scrollHeight;
}
async function submit(message = textarea.value.trim()) {
  if (!message || send.disabled) return;
  textarea.value = ''; textarea.style.height = 'auto'; addMessage('user', message); setBusy(true);
  try {
    const response = await fetch('/support', { method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({message, conversation_id: conversationId}) });
    const data = await response.json(); if (!response.ok) throw new Error(data.detail || 'Unable to reach Aria');
    const spokenReply = data.response.replace(/_Source:.*?_/s, '').trim();
    addMessage('aria', spokenReply, data.faq_sources);
    if (data.escalated && data.ticket) { ticketBanner.hidden = false; ticketBanner.innerHTML = `<strong>HUMAN SUPPORT REQUESTED</strong><br>Ticket ${data.ticket.id} is open.`; }
    const sound = await fetch('/voice', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({text: spokenReply})});
    if (sound.ok) {
      const audio = new Audio(URL.createObjectURL(await sound.blob())); audio.play();
    } else {
      // Kokoro model unavailable (e.g. Render free tier) — fall back to browser TTS
      const utt = new SpeechSynthesisUtterance(spokenReply);
      utt.rate = 1.0; utt.pitch = 1.05; utt.lang = 'en-US';
      window.speechSynthesis.cancel();
      window.speechSynthesis.speak(utt);
    }
    setBusy(false, data.escalated ? 'Support ticket created' : 'Ready to help');
  } catch (error) { addMessage('aria', `I’m having trouble connecting right now. ${error.message}`); setBusy(false, 'Connection issue'); }
}
textarea.addEventListener('input', () => { textarea.style.height = 'auto'; textarea.style.height = `${Math.min(textarea.scrollHeight,130)}px`; });
textarea.addEventListener('keydown', event => { if (event.key === 'Enter' && !event.shiftKey) { event.preventDefault(); submit(); } });
send.addEventListener('click', () => submit());
document.querySelectorAll('[data-prompt]').forEach(button => button.addEventListener('click', () => submit(button.dataset.prompt)));
document.querySelector('#human-help').addEventListener('click', () => submit('I need a human agent to help me.'));
document.querySelector('#new-chat').addEventListener('click', () => { conversationId = crypto.randomUUID(); localStorage.setItem(conversationIdKey, conversationId); conversation.innerHTML = ''; ticketBanner.hidden = true; textarea.focus(); setBusy(false, 'New conversation'); });
let recorder, stream, chunks = [], audioContext, analyser, silenceTimer, listeningStarted;
function monitorSilence() {
  const samples = new Uint8Array(analyser.fftSize);
  const tick = () => {
    if (recorder?.state !== 'recording') return;
    analyser.getByteTimeDomainData(samples);
    let energy = 0; for (const sample of samples) energy += Math.abs(sample - 128);
    const speaking = energy / samples.length > 2.5;
    if (speaking) { silenceTimer = performance.now(); }
    // Give the user an opening window, then finish after 1.8 s of silence.
    if (performance.now() - listeningStarted > 1500 && performance.now() - silenceTimer > 1800) { recorder.stop(); return; }
    requestAnimationFrame(tick);
  };
  requestAnimationFrame(tick);
}
mic.addEventListener('click', async () => {
  if (recorder?.state === 'recording') { voiceNote.textContent = 'LISTENING — PAUSE TO SEND'; return; }
  try {
    stream = await navigator.mediaDevices.getUserMedia({audio:true});
    const options = MediaRecorder.isTypeSupported('audio/webm') ? {mimeType:'audio/webm'} : undefined;
    recorder = new MediaRecorder(stream, options);
    chunks = []; recorder.ondataavailable = e => chunks.push(e.data);
    recorder.onstart = () => {
      audioContext = new AudioContext(); analyser = audioContext.createAnalyser(); analyser.fftSize = 1024;
      audioContext.createMediaStreamSource(stream).connect(analyser);
      listeningStarted = silenceTimer = performance.now(); mic.classList.add('listening'); voiceNote.textContent = 'LISTENING — PAUSE WHEN YOU FINISH'; monitorSilence();
    };
    recorder.onerror = () => { mic.classList.remove('listening'); voiceNote.textContent = 'RECORDING FAILED — TRY AGAIN'; stream?.getTracks().forEach(track => track.stop()); };
    recorder.onstop = async () => {
      mic.classList.remove('listening'); audioContext?.close(); voiceNote.textContent = 'TRANSCRIBING LOCALLY…'; stream.getTracks().forEach(track => track.stop());
      try { const form = new FormData(); form.append('audio', new Blob(chunks, {type:recorder.mimeType}), 'aria-recording.webm'); const r = await fetch('/transcribe',{method:'POST',body:form}); const d = await r.json(); if (!r.ok || !d.text) throw new Error(); voiceNote.textContent = 'VOICE MODE · LOCAL KOKORO'; submit(d.text); }
      catch (err) { voiceNote.textContent = err?.message?.startsWith('No speech') ? 'NO SPEECH DETECTED — TRY AGAIN' : 'MIC ERROR — SPEAK CLEARLY & RETRY'; }
    }; recorder.start();
  } catch (error) { voiceNote.textContent = error.name === 'NotAllowedError' ? 'ALLOW MICROPHONE ACCESS, THEN TRY AGAIN' : 'MICROPHONE IS UNAVAILABLE — TRY AGAIN'; }
});
