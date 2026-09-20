// Practice / mock-interview mode. Python and data-science answers run in the learner's browser
// (Pyodide in a Web Worker); Java and Spring answers are checked statically by the server.
// Nothing here needs an AI key. Every challenge screen can be read aloud with the current
// sentence highlighted, and questions can be asked by voice (all in the browser).
(function () {
  'use strict';

  const API_KEY = 'aria-demo-key-2024';
  const PYODIDE_CDN = 'https://cdn.jsdelivr.net/pyodide/v0.26.4/full/';
  const PYODIDE_LOCAL = '/static/vendor/pyodide/'; // filled by scripts/fetch_offline_assets.py for fully offline installs
  const INTERVIEW_MINUTES = 30;
  const RUN_LIMIT_MS = 12000;
  const HINT_PENALTY = 0.25;
  const TRACKS = [
    { id: 'python', label: 'Python' },
    { id: 'datascience', label: 'Data Science' },
    { id: 'java', label: 'Java' },
    { id: 'spring', label: 'Spring Boot' },
  ];

  const state = {
    track: 'python', list: [], index: 0, session: null,
    solved: loadSolved(), busy: false,
  };

  const esc = s => String(s ?? '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
  const root = () => document.getElementById('panel-practice');
  const trackLabel = () => TRACKS.find(t => t.id === state.track).label;

  function loadSolved() {
    try { return JSON.parse(localStorage.getItem('aria-practice-solved') || '{}'); } catch (_) { return {}; }
  }
  function saveSolved() {
    try { localStorage.setItem('aria-practice-solved', JSON.stringify(state.solved)); } catch (_) { /* private mode */ }
  }

  // ── Python runner (Web Worker, hard timeout) ───────────────────────────────
  let pyodideBase = null;
  async function resolvePyodideBase() {
    if (pyodideBase) return pyodideBase;
    try {
      const probe = await fetch(PYODIDE_LOCAL + 'pyodide.js', { method: 'HEAD' });
      pyodideBase = probe.ok ? location.origin + PYODIDE_LOCAL : PYODIDE_CDN;
    } catch (_) {
      pyodideBase = PYODIDE_CDN;
    }
    return pyodideBase;
  }

  const workerSource = base => `
    importScripts('${base}pyodide.js');
    let py = null;
    self.onmessage = async ({ data }) => {
      const { id, harness, code, tests, packages } = data;
      try {
        if (!py) {
          self.postMessage({ id, type: 'progress', text: 'Loading Python (first time only, about 10 MB)…' });
          py = await loadPyodide({ indexURL: '${base}' });
          py.runPython(harness);
        }
        if (packages && packages.length) {
          self.postMessage({ id, type: 'progress', text: 'Loading ' + packages.join(', ') + '…' });
          await py.loadPackage(packages);
        }
        py.globals.set('_user_code', code);
        py.globals.set('_tests_src', tests);
        self.postMessage({ id, type: 'running' });
        const proxy = py.runPython('run_challenge(_user_code, _tests_src)');
        const result = proxy.toJs({ dict_converter: Object.fromEntries });
        if (proxy.destroy) proxy.destroy();
        self.postMessage({ id, type: 'result', result });
      } catch (e) {
        self.postMessage({ id, type: 'error', message: String((e && e.message) || e).split('\\n').filter(Boolean).slice(-1)[0] });
      }
    };`;

  const runner = {
    worker: null, harness: null, seq: 0,
    async run(code, tests, packages, onProgress) {
      if (!this.harness) this.harness = await (await fetch('/static/challenge_harness.py')).text();
      if (!this.worker) {
        const base = await resolvePyodideBase();
        this.worker = new Worker(URL.createObjectURL(new Blob([workerSource(base)], { type: 'text/javascript' })));
      }
      const id = ++this.seq;
      const worker = this.worker;
      return new Promise((resolve, reject) => {
        let timer = null;
        const arm = (ms, message) => {
          clearTimeout(timer);
          timer = setTimeout(() => {
            worker.terminate();
            if (this.worker === worker) this.worker = null;
            reject(new Error(message));
          }, ms);
        };
        // Generous while the interpreter and packages download; strict once the learner's code is running.
        arm(150000, 'The Python engine took too long to load. Check your connection and try again.');
        worker.onmessage = ({ data }) => {
          if (data.id !== id) return;
          if (data.type === 'progress') { onProgress?.(data.text); return; }
          if (data.type === 'running') { onProgress?.('Running your code…'); arm(RUN_LIMIT_MS, 'Your code ran for too long (possibly an infinite loop) and was stopped.'); return; }
          clearTimeout(timer);
          if (data.type === 'result') resolve(data.result);
          else reject(new Error(data.message || 'The Python engine failed to start. Check your connection and try again.'));
        };
        worker.onerror = e => { clearTimeout(timer); reject(new Error(e.message || 'The Python engine failed to load. Check your connection.')); };
        worker.postMessage({ id, harness: this.harness, code, tests, packages: packages || [] });
      });
    },
  };

  // ── API ────────────────────────────────────────────────────────────────────
  const OFFLINE_MESSAGE = "Can't reach the Aria server. Python and Data Science challenges you have opened before can still run offline; quizzes and Java checks need the server.";

  async function api(path, options) {
    let resp;
    try {
      resp = await fetch(path, { ...options, headers: { 'Content-Type': 'application/json', 'X-API-Key': API_KEY, ...(options?.headers || {}) } });
    } catch (_) {
      throw new Error(OFFLINE_MESSAGE);
    }
    if (!resp.ok) {
      const e = await resp.json().catch(() => ({}));
      throw new Error(typeof e.detail === 'string' ? e.detail : 'Request failed');
    }
    return resp.json();
  }

  // ── Home: track, mode and challenge list ───────────────────────────────────
  function home() {
    stopTimer();
    window.Voice?.stop(true);
    state.session = null;
    const isBrowserGraded = state.track === 'python' || state.track === 'datascience';
    root().innerHTML = `
      <div class="stack" style="gap:16px">
        <span class="label" style="margin:0">Practice &amp; interview</span>
        <div class="seg" role="group" aria-label="Track">
          ${TRACKS.map(t => `<button type="button" data-track="${t.id}" class="${t.id === state.track ? 'is-active' : ''}" aria-pressed="${t.id === state.track}">${t.label}</button>`).join('')}
        </div>
        <div class="row">
          <button id="pr-start-interview" class="btn btn-primary" type="button">Start mock interview (${INTERVIEW_MINUTES} min)</button>
        </div>
        <p class="note">${isBrowserGraded
          ? 'Your code runs <strong>in your browser</strong> against real tests. Nothing is executed on our server and no AI is needed.'
          : 'Answers are <strong>checked statically</strong> (structure and common mistakes). Java is not executed, so passing proves the shape is right, not that it runs. No AI is needed.'}</p>
        <span class="label" style="margin:0">Challenges</span>
        <div id="pr-list" class="stack"><p class="note">Loading…</p></div>
      </div>`;
    root().querySelectorAll('[data-track]').forEach(b => b.addEventListener('click', () => { state.track = b.dataset.track; home(); }));
    root().querySelector('#pr-start-interview').addEventListener('click', startInterview);
    loadList();
  }

  async function loadList() {
    const box = root().querySelector('#pr-list');
    try {
      state.list = await api(`/challenges?track=${encodeURIComponent(state.track)}`);
    } catch (e) {
      if (box) box.innerHTML = `<div class="notice notice-bad">${esc(e.message)}</div>`;
      return;
    }
    if (!box) return;
    box.innerHTML = state.list.map((c, i) => {
      const done = state.solved[c.id];
      return `<button type="button" class="list-row" data-i="${i}">
        <span class="tick ${done ? 'ok' : 'idle'}" aria-label="${done ? 'Solved' : 'Not solved yet'}">${done ? '✓' : '○'}</span>
        <span class="title">${esc(c.title)}</span>
        <span class="meta type">${c.type === 'mcq' ? 'quiz' : 'code'}</span>
        <span class="meta diff-${esc(c.difficulty)}">${esc(c.difficulty)}</span>
        <span class="meta">${c.points}pt</span></button>`;
    }).join('');
    box.querySelectorAll('[data-i]').forEach(row => row.addEventListener('click', () => openChallenge(Number(row.dataset.i), null)));
  }

  // ── Mock interview ─────────────────────────────────────────────────────────
  function startInterview() {
    if (!state.list.length) return;
    const pick = (difficulty, n) => state.list.filter(c => c.difficulty === difficulty).sort(() => Math.random() - 0.5).slice(0, n);
    const questions = [...pick('easy', 2), ...pick('medium', 2), ...pick('hard', 1)];
    state.session = { questions, results: {}, endsAt: Date.now() + INTERVIEW_MINUTES * 60000, startedAt: Date.now() };
    startTimer();
    openChallenge(0, state.session);
  }

  let timerHandle = null;
  function startTimer() {
    stopTimer();
    timerHandle = setInterval(() => {
      const el = document.getElementById('pr-timer');
      if (!state.session) return stopTimer();
      const left = Math.max(0, state.session.endsAt - Date.now());
      if (el) el.textContent = `${String(Math.floor(left / 60000)).padStart(2, '0')}:${String(Math.floor(left / 1000) % 60).padStart(2, '0')}`;
      if (left === 0) finishInterview('Time is up.');
    }, 500);
  }
  function stopTimer() { if (timerHandle) clearInterval(timerHandle); timerHandle = null; }

  const fmt = text => esc(text).replace(/`([^`]+)`/g, '<code class="code-inline">$1</code>');
  const tick = ok => `<span class="tick ${ok ? 'ok' : 'no'}" aria-label="${ok ? 'Passed' : 'Failed'}">${ok ? '✓' : '✗'}</span>`;
  const banner = (ok, text) => `<div class="notice ${ok ? 'notice-good' : 'notice-bad'}"><b>${text}</b></div>`;

  // ── One challenge ──────────────────────────────────────────────────────────
  function openChallenge(i, session) {
    const list = session ? session.questions : state.list;
    const c = list[i];
    if (!c) return;
    window.Voice?.stop(true);
    state.index = i;
    const attempt = { hints: 0, revealed: false, best: null, submitted: false };
    const el = root();
    const isCode = c.type !== 'mcq';
    const total = list.length;
    const runLabel = c.graded === 'browser' ? '▶ Run tests' : c.type === 'mcq' ? 'Check answer' : 'Review my code';
    el.innerHTML = `
      <div class="stack" style="gap:14px">
        <div class="row row-between">
          <button id="pr-back" type="button" class="btn btn-ghost btn-sm">← ${session ? 'End interview' : 'Back'}</button>
          <div class="row" style="gap:12px">
            ${session ? `<span class="timer" id="pr-timer" role="timer">--:--</span><span class="meta muted small">Q${i + 1}/${total}</span>` : ''}
            <span class="small diff-${esc(c.difficulty)}">${esc(c.difficulty)} · ${c.points}pt</span>
          </div>
        </div>
        <h2 style="margin:0;font-size:22px;line-height:1.25">${esc(c.title)}</h2>
        <div id="pr-listen" class="stack" style="gap:14px">
          <p class="prompt">${fmt(c.prompt)}</p>
          ${isCode
            ? `<label class="sr-only" for="pr-code">Your code</label><textarea id="pr-code" class="code-editor" spellcheck="false" autocapitalize="off" autocomplete="off" style="min-height:220px">${esc(c.starter)}</textarea>`
            : `<div id="pr-options" class="stack" role="radiogroup" aria-label="Answer options">${c.options.map((o, k) => `<label class="option"><input type="radio" name="pr-choice" value="${k}"><span>${esc(o)}</span></label>`).join('')}</div>`}
          <div class="actions">
            <button id="pr-run" type="button" class="btn btn-primary">${runLabel}</button>
            ${session ? `<button id="pr-submit" type="button" class="btn btn-secondary">${i + 1 < total ? 'Submit &amp; next →' : 'Submit &amp; finish'}</button>` : ''}
            <button id="pr-hint" type="button" class="btn btn-secondary" ${c.hint_count ? '' : 'disabled'}>Hint (0/${c.hint_count})</button>
            ${session ? '' : '<button id="pr-solution" type="button" class="btn btn-secondary">Show solution</button>'}
            ${isCode ? '<button id="pr-aria" type="button" class="btn btn-outline">Ask Aria why</button><button id="pr-voice" type="button" class="btn btn-outline" aria-pressed="false">Ask by voice</button>' : ''}
            ${!session && i + 1 < total ? '<button id="pr-next" type="button" class="btn btn-ghost">Next →</button>' : ''}
          </div>
          <div id="pr-hints" class="stack"></div>
          <p id="pr-status" class="note" role="status" aria-live="polite"></p>
          <div id="pr-result" aria-live="polite"></div>
          <div id="pr-solution-box"></div>
          <div id="pr-aria-box" class="output" data-listen hidden></div>
        </div>
      </div>`;

    const $ = id => el.querySelector(id);
    const listen = $('#pr-listen');
    window.Voice?.addListen(listen);
    window.Voice?.refresh(listen);
    const editor = $('#pr-code');
    let releaseTab = false;
    editor?.addEventListener('keydown', e => {
      if (e.key === 'Escape') { releaseTab = true; return; }
      if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) { e.preventDefault(); grade(c, attempt, $, session); return; }
      if (e.key === 'Tab' && !e.shiftKey && !releaseTab) { e.preventDefault(); editor.setRangeText('    ', editor.selectionStart, editor.selectionEnd, 'end'); }
      else if (e.key !== 'Tab') releaseTab = false;
    });
    $('#pr-back').addEventListener('click', () => (session ? finishInterview('Interview ended.') : home()));
    $('#pr-hint').addEventListener('click', () => showHint(c, attempt, $, listen));
    $('#pr-run').addEventListener('click', () => grade(c, attempt, $, session));
    $('#pr-next')?.addEventListener('click', () => openChallenge(i + 1, null));
    $('#pr-solution')?.addEventListener('click', () => reveal(c, attempt, $, listen));
    $('#pr-aria')?.addEventListener('click', () => askAria(c, $, listen));
    $('#pr-voice')?.addEventListener('click', () => {
      window.Voice?.ask($('#pr-voice'), $('#pr-status'), question => askAria(c, $, listen, question));
    });
    $('#pr-submit')?.addEventListener('click', async () => {
      if (!attempt.best) await grade(c, attempt, $, session);
      attempt.submitted = true;
      session.results[c.id] = { ...(attempt.best || { fraction: 0, passed: false }), hints: attempt.hints, points: scoreFor(c, attempt) };
      if (i + 1 < total) openChallenge(i + 1, session); else finishInterview('All questions submitted.');
    });
  }

  function showHint(c, attempt, $, listen) {
    if (attempt.hints >= c.hint_count) return;
    attempt.hints += 1;
    $('#pr-hints').insertAdjacentHTML('beforeend', `<div class="notice notice-warn">Hint ${attempt.hints}: ${fmt(c.hints[attempt.hints - 1])}</div>`);
    $('#pr-hint').textContent = `Hint (${attempt.hints}/${c.hint_count})`;
    if (attempt.hints >= c.hint_count) $('#pr-hint').disabled = true;
    window.Voice?.onContentReady(listen, $('#pr-hints').lastElementChild);
  }

  function scoreFor(c, attempt) {
    if (attempt.revealed || !attempt.best) return 0;
    return Math.max(0, Math.round(c.points * attempt.best.fraction * Math.max(0, 1 - HINT_PENALTY * attempt.hints)));
  }

  async function grade(c, attempt, $, session) {
    if (state.busy) return;
    const run = $('#pr-run');
    const status = $('#pr-status');
    const out = $('#pr-result');
    const listen = $('#pr-listen');
    state.busy = true; run.disabled = true;
    status.textContent = ''; status.dataset.kind = '';
    window.Voice?.stop(true);
    try {
      if (c.type === 'mcq') {
        const chosen = $('#pr-options input:checked');
        if (!chosen) { status.textContent = 'Choose an answer first.'; status.dataset.kind = 'warn'; return; }
        const r = await api('/challenges/check', { method: 'POST', body: JSON.stringify({ id: c.id, choice: Number(chosen.value) }) });
        attempt.best = { passed: r.passed, fraction: r.passed ? 1 : 0 };
        out.innerHTML = renderMcq(c, r, !session);
        if (r.passed) markSolved(c);
      } else if (c.graded === 'browser') {
        status.textContent = 'Running your code…';
        const r = await runner.run($('#pr-code').value, c.tests, c.packages, t => { status.textContent = t; });
        status.textContent = '';
        const passedCount = r.results.filter(x => x.passed).length;
        attempt.best = { passed: r.passed, fraction: r.results.length ? passedCount / r.results.length : 0 };
        out.innerHTML = renderTests(r);
        if (r.passed) markSolved(c);
      } else {
        const r = await api('/challenges/check', { method: 'POST', body: JSON.stringify({ id: c.id, code: $('#pr-code').value }) });
        attempt.best = { passed: r.passed, fraction: r.score };
        out.innerHTML = renderChecks(r);
        if (r.passed) markSolved(c);
      }
      // Doing nothing must never earn points: tests such as "does not mutate the input" pass trivially.
      const editor = $('#pr-code');
      if (c.type !== 'mcq' && editor && editor.value.trim() === c.starter.trim() && attempt.best) {
        attempt.best = { passed: false, fraction: 0 };
        status.textContent = 'You have not changed the starter code yet, so this scores 0.';
        status.dataset.kind = 'warn';
      }
      window.Voice?.onContentReady(listen, out);
    } catch (e) {
      status.textContent = e.message;
      status.dataset.kind = 'warn';
      window.Voice?.disarm();
    } finally {
      state.busy = false; run.disabled = false;
    }
  }

  function markSolved(c) { state.solved[c.id] = true; saveSolved(); }

  function renderTests(r) {
    if (!r.ok) return banner(false, 'Your code could not run') + `<pre class="pre pre-bad">${esc(r.error)}</pre>`;
    const passed = r.results.filter(x => x.passed).length;
    const rows = r.results.map(x => `<div class="result-row">${tick(x.passed)}${esc(x.name)}${x.passed ? '' : `<div class="why">${esc(x.message)}</div>`}</div>`).join('');
    const printed = r.stdout ? `<span class="label" style="margin-top:12px">Your print output</span><pre class="pre" style="color:var(--text-2)">${esc(r.stdout)}</pre>` : '';
    return banner(r.passed, r.passed ? `All ${passed} tests passed` : `${passed} of ${r.results.length} tests passed`) + rows + printed;
  }

  function renderChecks(r) {
    const rows = r.checks.map(x => `<div class="result-row">${tick(x.ok)}${esc(x.description)}${x.ok ? '' : `<div class="fix">Fix: ${esc(x.message)}</div>`}</div>`).join('');
    const notes = (r.notes || []).map(n => `<div class="result-row" style="color:var(--warn)">${esc(n.severity.toUpperCase())}: ${esc(n.message)}</div>`).join('');
    const passedCount = r.checks.filter(x => x.ok).length;
    return banner(r.passed, r.passed ? 'All checks passed' : `${passedCount} of ${r.checks.length} checks passed`)
      + '<p class="note" style="margin-bottom:8px">Static review: this checks structure and common mistakes. It does not run your Java.</p>'
      + rows + notes
      + (r.explanation ? `<p class="prompt" style="margin-top:12px"><b>Why:</b> ${esc(r.explanation)}</p>` : '');
  }

  function renderMcq(c, r, showExplanation) {
    return banner(r.passed, r.passed ? 'Correct' : 'Not quite')
      + (r.passed || showExplanation
        ? `<p class="prompt">${!r.passed ? `Correct answer: <b>${esc(c.options[r.correct_index])}</b>. ` : ''}${esc(r.explanation)}</p>`
        : '<p class="note">Explanations are shown when the interview ends.</p>');
  }

  async function reveal(c, attempt, $, listen) {
    if (!confirm('Show the solution? You will earn no points for this challenge.')) return;
    try {
      const r = await api('/challenges/solution', { method: 'POST', body: JSON.stringify({ id: c.id }) });
      attempt.revealed = true;
      $('#pr-solution-box').innerHTML = `<div class="stack"><span class="label" style="margin:0">Explanation</span><p class="prompt">${esc(r.explanation)}</p>`
        + (r.solution ? `<span class="label" style="margin:0">Reference solution</span><pre class="pre">${esc(r.solution)}</pre>` : '') + '</div>';
      window.Voice?.onContentReady(listen, $('#pr-solution-box'));
    } catch (e) {
      $('#pr-status').textContent = e.message;
      $('#pr-status').dataset.kind = 'warn';
    }
  }

  function askAria(c, $, listen, spoken = '') {
    const code = $('#pr-code')?.value || '';
    if (typeof window._streamTutor !== 'function') return;
    const box = $('#pr-aria-box');
    box.hidden = false;
    const question = spoken || `Why does my answer to "${c.title}" pass or fail? ${c.prompt}`;
    window._streamTutor({
      language: c.track, level: (window.getCodeLevel && window.getCodeLevel()) || 'beginner', mode: 'review', code,
      question: question.slice(0, 480),
    }, box, { listenContainer: listen });
  }

  // ── Interview summary ──────────────────────────────────────────────────────
  function finishInterview(reason) {
    const s = state.session;
    if (!s) return home();
    stopTimer();
    window.Voice?.stop(true);
    state.session = null;
    const seconds = Math.round((Math.min(Date.now(), s.endsAt) - s.startedAt) / 1000);
    const maxPoints = s.questions.reduce((a, c) => a + c.points, 0);
    const earned = s.questions.reduce((a, c) => a + (s.results[c.id]?.points || 0), 0);
    const pct = maxPoints ? Math.round((earned / maxPoints) * 100) : 0;
    const colour = pct >= 70 ? 'var(--good)' : pct >= 40 ? 'var(--warn)' : 'var(--bad)';
    const rows = s.questions.map(c => {
      const r = s.results[c.id];
      return `<div class="list-row" style="cursor:default">${tick(r?.passed)}<span class="title">${esc(c.title)}</span><span class="meta diff-${esc(c.difficulty)}">${esc(c.difficulty)}</span><span class="meta">${r ? r.points : 0}/${c.points}</span></div>`;
    }).join('');
    const missed = s.questions.filter(c => !s.results[c.id]?.passed);
    const review = missed.length
      ? `<div class="row"><span>Focus next on ${[...new Set(missed.map(c => c.difficulty))].join(', ')} questions.</span><button id="pr-open-lesson" type="button" class="btn btn-secondary btn-sm">Open the ${esc(trackLabel())} lessons</button></div>` : '';
    root().innerHTML = `
      <div class="stack" style="gap:16px">
        <span class="label" style="margin:0">Interview result</span>
        <div id="pr-summary" class="stack" style="gap:14px">
          <div class="row" style="align-items:baseline;gap:16px">
            <span class="big-score" style="color:${colour}">${pct}%</span>
            <span class="muted">You scored ${earned} out of ${maxPoints} points in ${Math.floor(seconds / 60)} minutes ${seconds % 60} seconds. ${esc(reason)}</span>
          </div>
          <p class="note">Hints cost ${HINT_PENALTY * 100}% each. Java and Spring answers are reviewed statically.</p>
          <div class="stack" style="gap:8px">${rows}</div>
          ${review}
        </div>
        <div class="row"><button id="pr-again" type="button" class="btn btn-primary">Try another interview</button><button id="pr-home" type="button" class="btn btn-secondary">Back to challenges</button></div>
      </div>`;
    const summary = root().querySelector('#pr-summary');
    window.Voice?.addListen(summary);
    window.Voice?.refresh(summary);
    root().querySelector('#pr-again').addEventListener('click', startInterview);
    root().querySelector('#pr-home').addEventListener('click', () => home());
    root().querySelector('#pr-open-lesson')?.addEventListener('click', () => {
      window.switchMode?.('code');
      document.querySelector(`.clang-btn[data-lang="${state.track}"]`)?.click();
    });
    if (!state.list.length) loadList();
  }

  window.Practice = {
    open() { if (!root().innerHTML.trim()) home(); },
    _state: state,
    _runner: runner,
  };
})();
