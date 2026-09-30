// Aria Overviews: a two-host podcast (Aria and Leo) about any topic.
//
// - The script streams in line by line; playback starts on the first line while the rest is written.
// - Each line is voiced by the server (/podcast/voice) and the next few are fetched ahead, so there are no gaps.
// - "Ask a question" pauses the episode, takes a typed or spoken question, plays the hosts' answer and then
//   replays the line that was interrupted.
// - The finished episode downloads as one MP3 (optionally with the Q&A), and the transcript as text.
// All model text enters the page through textContent, never innerHTML.
(function () {
  const API_HEADERS = { 'Content-Type': 'application/json', 'X-API-Key': 'aria-demo-key-2024' };
  const PREFETCH_AHEAD = 3;
  const NAMES = { aria: 'Aria', leo: 'Leo' };
  const $ = id => document.getElementById(id);

  const ep = {
    topic: '', notes: '', accent: 'us', length: 'standard',
    lines: [],            // {speaker, text, kind: 'main'|'qa', question?, audio?: Promise<string|null>}
    index: 0,
    playing: false,
    writing: false,       // the script is still streaming in
    waiting: false,       // playback reached the end of what has been written so far
    asking: false,
    audio: new Audio(),
    rate: 1,
    runId: 0,
    abort: null,
    recognition: null,
    useBrowserVoice: false,
  };
  ep.audio.preload = 'auto';
  const SILENCE = 'data:audio/wav;base64,UklGRiQAAABXQVZFZm10IBAAAAABAAEAQB8AAEAfAAABAAgAZGF0YQAAAAA=';

  // iOS only lets an audio element play after it has been started inside a tap, and the first line
  // arrives a few seconds after the tap. Playing silence during the tap unlocks the element for the episode.
  function unlockAudio() {
    if (ep.audio.src && !ep.audio.src.startsWith('data:')) return;
    ep.audio.src = SILENCE;
    ep.audio.play().catch(() => { /* nothing to unlock */ });
  }

  // ── setup form ──────────────────────────────────────────────────────────────
  function segValue(groupId) { return document.querySelector(`#${groupId} button.is-active`)?.dataset.value; }
  document.querySelectorAll('#pod-length button, #pod-accent button').forEach(btn => {
    btn.addEventListener('click', () => {
      btn.parentElement.querySelectorAll('button').forEach(b => {
        const on = b === btn;
        b.classList.toggle('is-active', on);
        b.setAttribute('aria-pressed', String(on));
      });
    });
  });

  $('pod-file')?.addEventListener('change', async e => {
    const file = e.target.files[0];
    e.target.value = '';
    if (!file) return;
    const status = $('pod-file-status');
    status.dataset.kind = 'info';
    status.textContent = `Reading ${file.name}…`;
    try {
      const form = new FormData();
      form.append('file', file);
      const resp = await fetch('/podcast/extract', { method: 'POST', headers: { 'X-API-Key': API_HEADERS['X-API-Key'] }, body: form });
      const data = await resp.json().catch(() => ({}));
      if (!resp.ok) throw new Error(data.detail || 'Could not read that file.');
      const notes = $('pod-notes');
      notes.value = (notes.value.trim() ? notes.value.trim() + '\n\n' : '') + data.text;
      notes.value = notes.value.slice(0, 12000);
      if (!$('pod-topic').value.trim()) $('pod-topic').value = file.name.replace(/\.[^.]+$/, '').replace(/[-_]+/g, ' ');
      status.textContent = data.truncated ? `Added ${file.name} (only the first part fits).` : `Added ${file.name}.`;
    } catch (err) {
      status.dataset.kind = 'warn';
      status.textContent = err instanceof TypeError ? "Can't reach the Aria server." : err.message;
    }
  });

  $('pod-generate')?.addEventListener('click', generate);
  $('pod-topic')?.addEventListener('keydown', e => { if (e.key === 'Enter') { e.preventDefault(); generate(); } });

  // ── generating the script ───────────────────────────────────────────────────
  async function generate() {
    const topic = $('pod-topic').value.trim();
    if (topic.length < 2) { window.showToast?.('Type a topic for the episode first.'); $('pod-topic').focus(); return; }
    resetEpisode();
    unlockAudio();
    const run = ep.runId;
    ep.topic = topic;
    ep.notes = $('pod-notes').value.trim();
    ep.length = segValue('pod-length') || 'standard';
    ep.accent = segValue('pod-accent') || 'us';
    ep.writing = true;
    ep.playing = true;  // start as soon as the first line arrives
    $('pod-player').hidden = false;
    $('pod-episode-title').textContent = topic;
    $('pod-sources').textContent = '';
    $('pod-notice').hidden = true;
    setStatus('Aria and Leo are getting ready…');
    refreshControls();
    $('pod-player').scrollIntoView({ behavior: 'smooth', block: 'start' });

    const controller = new AbortController();
    ep.abort = controller;
    try {
      const resp = await fetch('/podcast/script', {
        method: 'POST', headers: API_HEADERS, signal: controller.signal,
        body: JSON.stringify({ topic, notes: ep.notes, length: ep.length }),
      });
      if (!resp.ok) {
        const e = await resp.json().catch(() => ({}));
        throw new Error(typeof e.detail === 'string' ? e.detail : 'Could not start the episode.');
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
          if (!raw.startsWith('data: ') || run !== ep.runId) continue;
          const evt = JSON.parse(raw.slice(6));
          if (evt.type === 'line') addLine({ speaker: evt.speaker, text: evt.text, kind: 'main' });
          else if (evt.type === 'sources') $('pod-sources').textContent = evt.items.length ? `Grounded in: ${evt.items.join(', ')}` : 'No knowledge-base match: the hosts use general knowledge.';
          else if (evt.type === 'notice') showNotice(evt.text);
          else if (evt.type === 'error') throw new Error(evt.detail);
        }
      }
    } catch (err) {
      if (err.name === 'AbortError' || run !== ep.runId) return;
      showNotice(err instanceof TypeError ? "Can't reach the Aria server. Check your connection." : err.message);
    } finally {
      if (run === ep.runId) {
        ep.writing = false;
        ep.abort = null;
        if (!ep.lines.length) { ep.playing = false; setStatus('No episode this time. Try again.'); }
        else if (ep.waiting) finish();
        updateProgress();
        refreshControls();
      }
    }
  }

  function resetEpisode() {
    ep.runId += 1;
    ep.abort?.abort();
    stopAudio();
    stopListening();
    ep.lines = [];
    ep.index = 0;
    ep.playing = false;
    ep.waiting = false;
    ep.asking = false;
    ep.useBrowserVoice = false;
    $('pod-transcript').innerHTML = '';
    $('pod-ask-box').hidden = true;
  }

  function addLine(line) {
    ep.lines.push(line);
    const li = renderLine(line);
    $('pod-transcript').appendChild(li);
    prefetch();
    updateProgress();
    refreshControls();
    if (ep.waiting && ep.playing) { ep.waiting = false; playCurrent(); }
    else if (ep.lines.length === 1 && ep.playing) playCurrent();
  }

  function renderLine(line) {
    const li = document.createElement('li');
    li.className = `pod-line pod-${line.speaker}` + (line.kind === 'qa' ? ' pod-qa' : '');
    const who = document.createElement('span');
    who.className = 'pod-who';
    who.textContent = NAMES[line.speaker] || 'Aria';
    const text = document.createElement('span');
    text.className = 'pod-text';
    text.textContent = line.text;
    li.append(who, text);
    li.tabIndex = 0;
    li.title = 'Play from here';
    const jump = () => { const i = ep.lines.indexOf(line); if (i >= 0) jumpTo(i); };
    li.addEventListener('click', jump);
    li.addEventListener('keydown', e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); jump(); } });
    line.el = li;
    return li;
  }

  // ── audio ───────────────────────────────────────────────────────────────────
  function lineAudio(line) {
    if (!line.audio) {
      line.audio = fetch('/podcast/voice', {
        method: 'POST', headers: API_HEADERS,
        body: JSON.stringify({ text: line.text, speaker: line.speaker, accent: ep.accent }),
      })
        .then(r => (r.ok ? r.blob() : null))
        .then(blob => (blob ? URL.createObjectURL(blob) : null))
        .catch(() => null);
    }
    return line.audio;
  }

  function prefetch() {
    if (ep.useBrowserVoice) return;
    for (let i = ep.index; i < Math.min(ep.lines.length, ep.index + PREFETCH_AHEAD + 1); i += 1) lineAudio(ep.lines[i]);
  }

  async function playCurrent() {
    const run = ep.runId;
    const line = ep.lines[ep.index];
    if (!line) {
      if (ep.writing) { ep.waiting = true; setStatus('Aria is still writing the next part…'); } else finish();
      return;
    }
    highlight();
    prefetch();
    setStatus(line.kind === 'qa' ? 'Answering your question' : 'Playing');
    updateMediaSession();
    const url = ep.useBrowserVoice ? null : await lineAudio(line);
    if (run !== ep.runId || !ep.playing || ep.lines[ep.index] !== line) return;
    if (url) {
      ep.audio.src = url;
      ep.audio.playbackRate = ep.rate;
      try { await ep.audio.play(); } catch (_) { ep.playing = false; refreshControls(); setStatus('Tap play to listen.'); }
    } else {
      // The server voice is unavailable: read the rest in the browser's own voices.
      if (!ep.useBrowserVoice) { ep.useBrowserVoice = true; showNotice("The podcast voices aren't reachable, so your browser's voices are reading this episode."); }
      browserSpeak(line, run);
    }
  }

  function browserSpeak(line, run) {
    const synth = window.speechSynthesis;
    if (!synth) { ep.playing = false; refreshControls(); setStatus('This browser cannot read the episode aloud.'); return; }
    const voices = synth.getVoices().filter(v => /^en/i.test(v.lang));
    const utter = new SpeechSynthesisUtterance(line.text);
    const pick = voices.length ? voices[line.speaker === 'leo' ? Math.min(1, voices.length - 1) : 0] : null;
    if (pick) utter.voice = pick;
    utter.pitch = line.speaker === 'leo' ? 0.85 : 1.1;
    utter.rate = ep.rate;
    utter.onend = () => { if (run === ep.runId && ep.playing) advance(); };
    utter.onerror = utter.onend;
    synth.cancel();
    synth.speak(utter);
  }

  const speaking = () => ep.playing && ep.audio.src && !ep.audio.src.startsWith('data:');
  ep.audio.addEventListener('ended', () => { if (speaking()) advance(); });
  ep.audio.addEventListener('error', () => { if (speaking()) advance(); });

  function advance() {
    const finished = ep.lines[ep.index];
    ep.index += 1;
    if (finished?.kind === 'qa' && ep.lines[ep.index]?.kind !== 'qa') setStatus('Back to the episode');
    updateProgress();
    refreshControls();
    playCurrent();
  }

  function stopAudio() {
    ep.audio.pause();
    ep.audio.removeAttribute('src');
    window.speechSynthesis?.cancel();
  }

  function play() {
    if (!ep.lines.length || ep.asking) return;
    if (ep.index >= ep.lines.length && !ep.writing) ep.index = 0;  // replay a finished episode
    window.Voice?.stop(true);
    ep.playing = true;
    refreshControls();
    if (ep.audio.src && !ep.audio.src.startsWith('data:') && ep.audio.paused && !ep.useBrowserVoice && ep.audio.currentTime > 0 && !ep.audio.ended) {
      ep.audio.play().catch(() => {});
      setStatus('Playing');
    } else playCurrent();
  }

  function pause() {
    if (!ep.playing) return;
    ep.playing = false;
    ep.waiting = false;
    ep.audio.pause();
    if (ep.useBrowserVoice) window.speechSynthesis?.cancel();
    setStatus('Paused');
    refreshControls();
  }

  function jumpTo(i) {
    if (ep.asking || i < 0 || i >= ep.lines.length) return;
    stopAudio();
    ep.index = i;
    ep.playing = true;
    refreshControls();
    updateProgress();
    playCurrent();
  }

  function finish() {
    ep.playing = false;
    ep.waiting = false;
    ep.index = ep.lines.length;
    highlight();
    updateProgress();
    setStatus('Episode finished. Download it, or ask a question about it.');
    refreshControls();
  }

  // ── raise your hand ─────────────────────────────────────────────────────────
  function openAsk() {
    if (!ep.lines.length || ep.asking) return;
    const wasPlaying = ep.playing;
    pause();
    ep.resumeAfterAsk = wasPlaying || ep.index < ep.lines.length;
    $('pod-ask-box').hidden = false;
    $('pod-ask-status').textContent = '';
    $('pod-question').value = '';
    $('pod-question').focus();
    setStatus('Paused for your question');
  }

  function closeAsk() {
    stopListening();
    $('pod-ask-box').hidden = true;
    $('pod-ask-btn').focus();
  }

  async function submitQuestion() {
    const question = $('pod-question').value.trim();
    if (question.length < 2) { $('pod-question').focus(); return; }
    stopListening();
    const run = ep.runId;
    ep.asking = true;
    refreshControls();
    const askStatus = $('pod-ask-status');
    askStatus.dataset.kind = 'info';
    askStatus.textContent = 'Aria and Leo are thinking about your question…';
    const here = Math.min(ep.index, ep.lines.length);
    const recent = ep.lines.slice(Math.max(0, here - 6), here + 1).map(l => ({ speaker: l.speaker, text: l.text }));
    try {
      const resp = await fetch('/podcast/ask', {
        method: 'POST', headers: API_HEADERS,
        body: JSON.stringify({ topic: ep.topic, question, recent, notes: ep.notes }),
      });
      const data = await resp.json().catch(() => ({}));
      if (!resp.ok) throw new Error(typeof data.detail === 'string' ? data.detail : 'Could not ask that right now.');
      if (run !== ep.runId) return;
      if (data.notice) showNotice(data.notice);
      insertAnswer(question, data.lines || [], here);
      ep.asking = false;
      $('pod-ask-box').hidden = true;
      ep.index = here;
      ep.playing = true;
      refreshControls();
      updateProgress();
      playCurrent();
    } catch (err) {
      ep.asking = false;
      refreshControls();
      askStatus.dataset.kind = 'warn';
      askStatus.textContent = err instanceof TypeError ? "Can't reach the Aria server." : err.message;
    }
  }

  function insertAnswer(question, lines, at) {
    // The answer is inserted before the interrupted line, so that line is replayed in full afterwards.
    const list = $('pod-transcript');
    const before = ep.lines[at]?.el || null;
    const asked = document.createElement('li');
    asked.className = 'pod-asked';
    asked.textContent = `You asked: “${question}”`;
    list.insertBefore(asked, before);
    const added = lines.map(l => ({ speaker: l.speaker, text: l.text, kind: 'qa', question }));
    ep.lines.splice(at, 0, ...added);
    added.forEach(line => list.insertBefore(renderLine(line), before));
  }

  // Speak the question. The episode is already paused, so the hosts' voices never reach the microphone.
  function listen() {
    const Ctor = window.SpeechRecognition || window.webkitSpeechRecognition;
    const askStatus = $('pod-ask-status');
    if (!Ctor) { askStatus.dataset.kind = 'warn'; askStatus.textContent = 'Voice questions need Chrome, Edge or Safari. You can type instead.'; return; }
    if (ep.recognition) { ep.recognition.stop(); return; }
    stopAudio();
    const rec = new Ctor();
    rec.lang = 'en-ZA';
    rec.interimResults = true;
    rec.continuous = false;
    let finalText = '';
    const btn = $('pod-ask-mic');
    btn.classList.add('listening');
    btn.setAttribute('aria-pressed', 'true');
    askStatus.dataset.kind = 'info';
    askStatus.textContent = 'Listening… ask your question.';
    rec.onresult = e => {
      let interim = '';
      for (let i = e.resultIndex; i < e.results.length; i += 1) {
        if (e.results[i].isFinal) finalText += e.results[i][0].transcript; else interim += e.results[i][0].transcript;
      }
      $('pod-question').value = (finalText + interim).trim();
    };
    rec.onerror = e => {
      askStatus.dataset.kind = 'warn';
      askStatus.textContent = e.error === 'not-allowed' || e.error === 'service-not-allowed'
        ? 'The microphone is blocked. Allow microphone access and try again, or type your question.'
        : e.error === 'no-speech' ? "I didn't hear anything. Try again, or type your question." : 'Voice input stopped. You can type your question instead.';
    };
    rec.onend = () => {
      ep.recognition = null;
      btn.classList.remove('listening');
      btn.setAttribute('aria-pressed', 'false');
      if (finalText.trim()) { $('pod-question').value = finalText.trim().slice(0, 500); submitQuestion(); }
    };
    ep.recognition = rec;
    try { rec.start(); } catch (_) { ep.recognition = null; btn.classList.remove('listening'); }
  }

  function stopListening() {
    if (!ep.recognition) return;
    try { ep.recognition.abort(); } catch (_) { /* already stopped */ }
    ep.recognition = null;
  }

  // ── downloads ───────────────────────────────────────────────────────────────
  function episodeLines() {
    const withQa = $('pod-include-qa').checked;
    return ep.lines.filter(l => withQa || l.kind === 'main').map(l => ({ speaker: l.speaker, text: l.text }));
  }

  function saveBlob(blob, name) {
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = name;
    document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 2000);
  }

  function fileSlug() { return ep.topic.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '').slice(0, 60) || 'aria-overview'; }

  async function downloadAudio() {
    const btn = $('pod-download');
    const label = btn.textContent;
    btn.disabled = true;
    btn.textContent = 'Preparing…';
    const status = $('pod-download-status');
    status.dataset.kind = 'info';
    status.textContent = 'Building your episode. This can take up to a minute for a long one.';
    try {
      const resp = await fetch('/podcast/download', {
        method: 'POST', headers: API_HEADERS,
        body: JSON.stringify({ title: ep.topic, lines: episodeLines().slice(0, 90), accent: ep.accent }),
      });
      if (!resp.ok) {
        const e = await resp.json().catch(() => ({}));
        throw new Error(typeof e.detail === 'string' ? e.detail : 'Download failed.');
      }
      const blob = await resp.blob();
      saveBlob(blob, `${fileSlug()}.${blob.type === 'audio/wav' ? 'wav' : 'mp3'}`);
      status.textContent = `Downloaded (${(blob.size / 1048576).toFixed(1)} MB).`;
    } catch (err) {
      status.dataset.kind = 'warn';
      status.textContent = err instanceof TypeError ? "Can't reach the Aria server." : err.message;
    } finally {
      btn.textContent = label;
      refreshControls();
    }
  }

  function downloadTranscript() {
    const withQa = $('pod-include-qa').checked;
    const out = [`Aria Overview: ${ep.topic}`, ''];
    let lastQuestion = null;
    for (const l of ep.lines) {
      if (l.kind === 'qa' && !withQa) continue;
      if (l.kind === 'qa' && l.question !== lastQuestion) { out.push('', `[You asked: ${l.question}]`); lastQuestion = l.question; }
      if (l.kind === 'main' && lastQuestion) { out.push(''); lastQuestion = null; }
      out.push(`${NAMES[l.speaker]}: ${l.text}`);
    }
    saveBlob(new Blob([out.join('\n') + '\n'], { type: 'text/plain' }), `${fileSlug()}-transcript.txt`);
  }

  // ── display ─────────────────────────────────────────────────────────────────
  function setStatus(text) { const el = $('pod-status'); if (el) el.textContent = text; }

  function showNotice(text) {
    const el = $('pod-notice');
    el.textContent = text;
    el.hidden = false;
  }

  function highlight() {
    ep.lines.forEach((l, i) => {
      const on = i === ep.index;
      l.el?.classList.toggle('is-current', on);
      l.el?.classList.toggle('is-done', i < ep.index);
      if (on) l.el?.setAttribute('aria-current', 'true'); else l.el?.removeAttribute('aria-current');
    });
    const current = ep.lines[ep.index]?.el;
    const box = $('pod-transcript');
    if (current && box) box.scrollTo({ top: current.offsetTop - box.offsetTop - box.clientHeight / 3, behavior: 'smooth' });
  }

  function updateProgress() {
    const main = ep.lines.filter(l => l.kind === 'main');
    const done = ep.lines.slice(0, ep.index).filter(l => l.kind === 'main').length;
    const total = main.length;
    $('pod-progress-text').textContent = total ? `${Math.min(done + 1, total)} of ${total}${ep.writing ? '+' : ''}` : '';
    const bar = $('pod-progress-bar');
    bar.style.width = total ? `${Math.round((done / total) * 100)}%` : '0%';
    bar.parentElement.setAttribute('aria-valuenow', String(total ? Math.round((done / total) * 100) : 0));
  }

  const PLAY_ICON = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M8 5.5v13l10.5-6.5z"/></svg>';
  const PAUSE_ICON = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M8 5v14M16 5v14"/></svg>';

  function refreshControls() {
    const has = ep.lines.length > 0;
    const toggle = $('pod-play');
    toggle.innerHTML = ep.playing ? PAUSE_ICON : PLAY_ICON;
    toggle.setAttribute('aria-label', ep.playing ? 'Pause episode' : 'Play episode');
    toggle.disabled = !has || ep.asking;
    $('pod-prev').disabled = !has || ep.asking || ep.index === 0;
    $('pod-next').disabled = !has || ep.asking || ep.index >= ep.lines.length - 1;
    $('pod-ask-btn').disabled = !has || ep.asking;
    $('pod-ask-send').disabled = ep.asking;
    $('pod-download').disabled = !has || ep.writing;
    $('pod-transcript-btn').disabled = !has || ep.writing;
    $('pod-generate').disabled = ep.writing;
    $('pod-generate').textContent = ep.writing ? 'Writing the episode…' : 'Generate episode';
    if ('mediaSession' in navigator) navigator.mediaSession.playbackState = ep.playing ? 'playing' : 'paused';
  }

  function updateMediaSession() {
    if (!('mediaSession' in navigator) || !window.MediaMetadata) return;
    navigator.mediaSession.metadata = new MediaMetadata({ title: ep.topic, artist: 'Aria & Leo', album: 'Aria Overviews', artwork: [{ src: '/static/aria-mark.svg', type: 'image/svg+xml', sizes: 'any' }] });
  }
  if ('mediaSession' in navigator) {
    const handlers = { play, pause, previoustrack: () => jumpTo(ep.index - 1), nexttrack: () => jumpTo(ep.index + 1) };
    for (const [action, fn] of Object.entries(handlers)) { try { navigator.mediaSession.setActionHandler(action, fn); } catch (_) { /* unsupported action */ } }
  }

  // ── wiring ──────────────────────────────────────────────────────────────────
  $('pod-play')?.addEventListener('click', () => (ep.playing ? pause() : play()));
  $('pod-prev')?.addEventListener('click', () => jumpTo(ep.index - 1));
  $('pod-next')?.addEventListener('click', () => jumpTo(ep.index + 1));
  $('pod-rate')?.addEventListener('change', e => { ep.rate = Number(e.target.value) || 1; ep.audio.playbackRate = ep.rate; });
  $('pod-ask-btn')?.addEventListener('click', openAsk);
  $('pod-ask-cancel')?.addEventListener('click', () => { closeAsk(); if (ep.resumeAfterAsk) play(); });
  $('pod-ask-send')?.addEventListener('click', submitQuestion);
  $('pod-ask-mic')?.addEventListener('click', listen);
  $('pod-question')?.addEventListener('keydown', e => {
    if (e.key === 'Enter') { e.preventDefault(); submitQuestion(); }
    if (e.key === 'Escape') { e.preventDefault(); closeAsk(); }
  });
  $('pod-download')?.addEventListener('click', downloadAudio);
  $('pod-transcript-btn')?.addEventListener('click', downloadTranscript);

  // A "Make it a podcast" button under a chat answer: the question becomes the topic, the answer a note.
  function offer(messageEl, question) {
    if (!messageEl || !question || messageEl.querySelector('.pod-offer')) return;
    const btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'pod-offer';
    btn.textContent = 'Make it a podcast';
    btn.addEventListener('click', () => {
      const answer = (messageEl.querySelector('div')?.textContent || '').replace(/_Source:.*?_/s, '').trim();
      $('pod-topic').value = question.slice(0, 300);
      $('pod-notes').value = answer ? `Aria's answer in chat:\n${answer}`.slice(0, 12000) : '';
      window.switchMode?.('podcast');
      $('pod-generate').focus();
    });
    messageEl.appendChild(btn);
  }

  window.Podcast = { offer, pause, isPlaying: () => ep.playing };
})();
