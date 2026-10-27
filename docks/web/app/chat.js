// Bowers web app: The conversation: rendering events, the composer and the slash palette.
// Plain scripts that share one global scope, loaded in order by app.html.
// ---------------------------------------------------------------- chat rendering
const log = $('log'), thread = $('thread');
let state = {}, blocks = {}, group = null, lastStep = null, typing = null, stick = true, pending = 0;
let steps = {}, quietCalls = new Set(), userCount = 0, helperSteps = {};
log.addEventListener('scroll', () => { stick = log.scrollHeight - log.scrollTop - log.clientHeight < 120; });
const scrollDown = () => { if (stick) log.scrollTop = log.scrollHeight; };

function add(el) {
  if (thread.querySelector('.welcome')) { thread.querySelector('.welcome').remove(); setHome(false); }
  if (typing) thread.insertBefore(el, typing); else thread.appendChild(el);
  scrollDown(); return el;
}
function endGroup() { finishRunning(); group = null; }
function finishRunning() { thread.querySelectorAll('.step.running').forEach(s => { if (!s.dataset.out && s.dataset.name !== 'delegate' && !s.querySelector('.tag.helper')) markStep(s, 'done'); }); }
function markStep(s, st) {
  s.classList.remove('running', 'waiting', 'done', 'error'); s.classList.add(st);
  if (st === 'done' || st === 'error') s.querySelector('.label').textContent = tl(s.dataset.name, JSON.parse(s.dataset.args), st === 'error' ? 'run' : 'done') + (st === 'error' ? ' (failed)' : '');
}

const RUN = ' When it works, start it with start_process so I can see it live in the preview.';
const TEMPLATES = [
  ['layout', 'Landing page', 'HTML · Tailwind', 'Build a modern, responsive landing page for a coffee shop called Bean There: hero section with a call to action, menu with prices, testimonials, opening hours and a contact form. Use Tailwind via CDN in a single index.html with tasteful animations.'],
  ['zap', 'React web app', 'Vite · React · Tailwind', 'Create a React + Vite + Tailwind app: a habit tracker where I can add habits, check them off each day, see streaks, and keep data in localStorage. Polished, responsive UI.' + RUN],
  ['server', 'Full-stack app', 'FastAPI · SQLite · React', 'Build a full-stack notes app: a FastAPI backend with SQLite (create, list, search, edit, delete notes) and a React + Vite frontend that talks to it. Include a README with how to run both.' + RUN],
  ['chart', 'Dashboard', 'React · Charts', 'Build a sales analytics dashboard with KPI tiles, a revenue line chart, a top-products bar chart and a sortable orders table, using realistic sample data. Clean, responsive design with light and dark mode.' + RUN],
  ['game', 'Browser game', 'Canvas · JavaScript', 'Make a polished snake game in the browser with a canvas, smooth movement, arrow-key and swipe controls, increasing speed, sound effects, and a saved high score. Put it in index.html.'],
  ['smartphone', 'Mobile app', 'Expo · React Native', 'Create an Expo (React Native) app: a simple expense tracker with categories, a monthly total and a chart. Explain how to open it on my phone with Expo Go.'],
  ['puzzle', 'Chrome extension', 'Manifest V3', 'Build a Chrome extension (Manifest V3) that shows a word count and reading time for the current page in a popup, with a clean design. Explain how to load it unpacked.'],
  ['code', 'REST API', 'FastAPI · OpenAPI', 'Build a REST API with FastAPI for a todo service: CRUD endpoints, validation, SQLite storage, and tests with pytest. Run the tests.' + RUN],
  ['sparkle', 'Portfolio site', 'HTML · CSS', 'Build a striking personal portfolio site for a developer: hero with an animated background, projects grid, about section, and contact links. Single index.html, no build step.'],
];
const QUICK = [
  ['book', 'Explain this project', 'Explain what this project does, how it is structured, and how to run it.'],
  ['bug', 'Find and fix bugs', 'Look through this project for bugs, fix the real ones, and run the tests.'],
  ['review', 'Add tests', 'Add tests for the most important code in this project and make them pass.'],
  ['rocket', 'Deploy it', null],
];
function welcome() {
  thread.innerHTML = '';
  const w = h('div', 'welcome greet', `<img class="bowie-live" src="${BOWIE(mood)}" alt="Bowie"><h1></h1><p>What would you like to work on today?</p>`);
  w.querySelector('h1').textContent = `${greetWord()}${profileName ? ', ' + profileName : ''}`;
  thread.appendChild(w);
  setHome(true);
  $('chat').classList.remove('busy-convo');
}

let planShown = false;
function renderPlan(items) {
  const box = $('plan');
  if (!planShown && items && items.length) { planShown = true; box.open = !matchMedia('(max-width: 920px)').matches; }
  box.classList.toggle('hidden', !items || !items.length);
  if (!items || !items.length) return;
  const done = items.filter(i => i.status === 'done').length;
  box.querySelector('.bar i').style.width = `${Math.round(100 * done / items.length)}%`;
  box.querySelector('.count').textContent = `${done} of ${items.length}`;
  if (done === items.length) box.open = false;
  const ul = box.querySelector('ul'); ul.innerHTML = '';
  for (const it of items) {
    const li = h('li', it.status, `<span class="m">${it.status === 'done' ? icon('check', 10) : ''}</span><span></span>`);
    li.children[1].textContent = it.text; ul.appendChild(li);
  }
}
let rewinding = false;
async function rewindTo(turn) {
  if (state.busy) { toast('Stop the current task first'); return; }
  if (!confirm('Undo from here?\n\nFiles go back to how they were before this message, and this message and everything after it are removed. You can edit and resend it.')) return;
  rewinding = true;
  const r = await api('/api/rewind', { turn });
  const body = await r.json().catch(() => ({}));
  if (!r.ok) { rewinding = false; toast(body.error || 'Could not undo'); return; }
  try { sessionStorage.setItem('docks-draft', body.text || ''); sessionStorage.setItem('docks-toast', `Restored ${body.restored.length} file${body.restored.length === 1 ? '' : 's'}`); } catch (e) {}
  location.reload();
}

function setBusy(busy) {
  state.busy = busy;
  const send = $('send');
  send.classList.toggle('stop', busy);
  send.innerHTML = icon(busy ? 'stop' : 'arrow-up');
  send.setAttribute('aria-label', busy ? 'Stop' : 'Send');
  if (busy && !typing) { typing = h('div', 'typing', `<img class="bowie-av bowie-live" src="${BOWIE('thinking')}" alt=""><span class="dots"><i></i><i></i><i></i></span><span class="t-label">Thinking…</span>`); thread.appendChild(typing); scrollDown(); setMood('thinking'); }
  if (!busy && typing) { typing.remove(); typing = null; }
  updateStatus();
}
function updateStatus() {
  const s = $('status'); s.classList.remove('working', 'waiting');
  if (pending > 0) { s.classList.add('waiting'); $('status-text').textContent = 'Needs your OK'; }
  else if (state.busy) { s.classList.add('working'); $('status-text').textContent = 'Working'; }
  else $('status-text').textContent = 'Ready';
}
function applyState(s) {
  state = { ...state, ...s };
  if (s.processes) { processes = {}; s.processes.forEach(onProcess); }
  if (s.mcp) renderMcp(s.mcp);
  const name = (s.root || '').split('/').filter(Boolean).pop() || s.root;
  $('project-name').textContent = name; $('project-name').title = s.root; $('root-path').textContent = s.root;
  if (s.models) {
    const known = s.models.some(m => m.id === s.model);
    $('model').innerHTML = s.models.map(m => `<option value="${esc(m.id)}" title="${esc(m.note)}">${esc(m.label)}</option>`).join('')
      + (known ? '' : `<option value="${esc(s.model)}">${esc(s.model)}</option>`);
  }
  $('model').value = s.model; $('effort').value = s.effort;
  if (s.mode) showMode(s.mode);
  if (s.extensions) renderExt(s.extensions);
  if (s.models || s.model_label) showModelState();
  if (s.output_styles) {
    $('style-select').innerHTML = s.output_styles.map(o => `<option value="${esc(o.name)}">${esc(o.name[0].toUpperCase() + o.name.slice(1))}: ${esc(o.description)}</option>`).join('');
    $('style-select').value = s.output_style;
  }
  if (typeof s.observer === 'boolean') $('observer').checked = s.observer;
  if (s.sandbox) {
    $('sandbox').checked = s.sandbox.on; $('sandbox').disabled = !s.sandbox.available;
    $('sandbox-row').title = s.sandbox.available ? '' : s.sandbox.reason;
  }
  if (s.permissions) renderPermissions(s.permissions);
  showUsage(s.usage); setBusy(s.busy);
}
function renderPermissions(p) {
  const box = $('perm-info'); box.innerHTML = '';
  const rows = ['deny', 'ask', 'allow'].flatMap(k => p[k].map(r => [k, r]));
  if (!rows.length) box.appendChild(h('div', null, 'None yet. "Always allow" on a command saves one for this session.'));
  for (const [k, r] of rows) box.appendChild(h('div', 'mcp-row', `<span class="tag ${k === 'deny' ? 'no' : ''}">${k}</span><code>${esc(r)}</code>`));
  const add = h('div', 'rename-row', `<input class="input" placeholder="Bash(npm test:*)"><select class="input" style="width:auto"><option>allow</option><option>ask</option><option>deny</option></select><button class="btn">Add</button>`);
  add.querySelector('button').onclick = async () => {
    const rule = add.querySelector('input').value.trim(); if (!rule) return;
    const r = await api('/api/permissions', { kind: add.querySelector('select').value, rule });
    if (r.ok) { applyState(await r.json()); toast('Rule saved'); } else toast((await r.json()).error);
  };
  box.appendChild(add);
}
const MODES = {
  ask:  { label: 'Ask first', short: 'Ask', icon: 'shield', desc: 'Confirm each change before it happens' },
  auto: { label: 'Auto', short: 'Auto', icon: 'zap', desc: 'Safe changes run on their own; risky ones ask' },
  plan: { label: 'Plan first', short: 'Plan', icon: 'book', desc: 'Research and propose a plan; change nothing until you approve' },
  yolo: { label: 'Full auto', short: 'Full', icon: 'rocket', desc: 'Never ask. Use when you trust the task' },
};
function showMode(mode) {
  state.mode = mode;
  const m = MODES[mode] || MODES.ask, small = matchMedia('(max-width: 560px)').matches;
  $('mode-chip').className = 'chip mode-' + mode;
  $('mode-icon').innerHTML = icon(m.icon); $('mode-text').textContent = small ? m.short : m.label;
  $('mode-select').value = mode;
}
async function setMode(mode) {
  const r = await api('/api/settings', { mode });
  if (r.ok) { showMode((await r.json()).mode); toast(MODES[mode].label + ': ' + MODES[mode].desc); }
}
function renderModeMenu() {
  const menu = $('mode-menu'); menu.innerHTML = '';
  for (const [key, m] of Object.entries(MODES)) {
    const b = h('button', 'mode-opt' + (state.mode === key ? ' on' : ''), `<span class="ic">${icon(m.icon)}</span><span><b>${esc(m.label)}</b><small>${esc(m.desc)}</small></span>`);
    b.onclick = e => { e.stopPropagation(); menu.classList.add('hidden'); setMode(key); };
    menu.appendChild(b);
  }
}
function renderExt(x) {
  const box = $('ext-info'); box.innerHTML = '';
  box.appendChild(h('div', null, `${x.commands.length} commands · ${x.agents.length} helper types · ${x.skills.length} skills · ${x.hooks} hooks` +
    (x.plugins.length ? `<br>Plugins: ${esc(x.plugins.join(', '))}` : '<br>Add plugins with <code>bowers plugin install owner/repo</code>')));
  for (const file of x.pending_hooks || []) {
    const row = h('div', 'mcp-row', `<span class="d needs-approval"></span><small>Project hooks or settings in ${esc(file.split('/').slice(-2).join('/'))} need approval</small>`);
    const b = h('button', 'btn', 'Approve');
    b.onclick = async e => { e.stopPropagation(); if (!confirm('This project wants to run hooks or let Bowers act without asking (allow rules, a status line). Approve?\n\n' + file)) return; const r = await api('/api/hooks/approve', { file }); if (r.ok) renderExt(await r.json()); };
    row.appendChild(b); box.appendChild(row);
  }
  commands = x.commands;
}
function showUsage(u) { if (u && (u.input || u.output)) $('usage').textContent = `Tokens this session: ${(u.input + u.cache_read).toLocaleString()} in, ${u.output.toLocaleString()} out`; }

function diffView(oldS, newS) {
  const d = h('div', 'diff');
  for (const l of String(oldS).split('\n')) { const r = h('div', 'd'); r.textContent = '− ' + l; d.appendChild(r); }
  for (const l of String(newS).split('\n')) { const r = h('div', 'a'); r.textContent = '+ ' + l; d.appendChild(r); }
  return d;
}
function unifiedDiff(text) {
  const d = h('div', 'diff');
  for (const l of text.split('\n')) {
    const r = h('div', l.startsWith('+') && !l.startsWith('+++') ? 'a' : l.startsWith('-') && !l.startsWith('---') ? 'd' : /^(@@|diff |index )/.test(l) ? 'h' : '');
    r.textContent = l || ' '; d.appendChild(r);
  }
  return d;
}

let refreshTimer = null;
function handle(ev) {
  switch (ev.type) {
    case 'reset': setHome(false); thread.innerHTML = ''; blocks = {}; group = null; lastStep = null; typing = null; pending = 0; steps = {}; quietCalls = new Set(); userCount = 0; applyState(ev.state); renderPlan(ev.state.plan); if (!thread.children.length || (thread.children.length === 1 && typing)) { if (!state.busy) welcome(); } break;
    case 'cleared': loadRecent(); blocks = {}; group = null; lastStep = null; steps = {}; userCount = 0; planShown = false; renderPlan([]); welcome(); refreshAll(); break;
    case 'rewound': if (!rewinding) location.reload(); break;
    case 'plan': renderPlan(ev.items); break;
    case 'user': {
      endGroup();
      if (ev.auto) { userCount++; add(h('div', 'notice auto', icon('users') + 'Continuing with a background helper\'s report')); setBusy(true); break; }
      const u = add(h('div', 'msg-user'));
      const turn = userCount++;
      const ub = h('button', 'undo', icon('undo', 15)); ub.title = 'Undo from here: restore files and edit this message'; ub.setAttribute('aria-label', ub.title);
      ub.onclick = () => rewindTo(turn); u.appendChild(ub);
      if (ev.images?.length) { const box = h('div', 'imgs'); for (const src of ev.images) { const im = h('img'); im.src = src; im.alt = 'attached image'; box.appendChild(im); } u.appendChild(box); }
      u.appendChild(document.createTextNode(ev.text)); setBusy(true); $('chat').classList.add('busy-convo');
      break;
    }
    case 'text': {
      endGroup();
      let b = blocks[ev.id];
      if (!b) {
        const wrap = add(h('div', 'msg-ai', `<img class="bowie-av" src="${BOWIE('happy')}" alt="Bowie"><div style="flex:1;min-width:0"><div class="prose"></div><div class="msg-actions"><button class="btn ghost" data-act="copy">${icon('copy', 13)} Copy</button><button class="btn ghost" data-act="star">${icon('star', 13)} Bookmark</button></div></div>`));
        b = blocks[ev.id] = { el: wrap.querySelector('.prose'), text: '' };
        const bb = b;
        wrap.querySelector('[data-act="copy"]').onclick = () => navigator.clipboard?.writeText(bb.text).then(() => toast('Copied'));
        wrap.querySelector('[data-act="star"]').onclick = async () => { const r = await api('/api/bookmark', { text: bb.text }); if (r.ok) { state.bookmarks = (await r.json()).bookmarks; toast('Bookmarked'); } };
      }
      b.text += ev.text; b.el.innerHTML = md(b.text); scheduleMath(b.el); scrollDown();
      break;
    }
    case 'progress': {
      if (!group) group = add(h('div', 'activity'));
      let b = blocks[ev.id];
      if (!b) { b = blocks[ev.id] = { el: h('div', 'progress-note'), text: '' }; group.appendChild(b.el); }
      b.text += ev.text; b.el.textContent = b.text; scrollDown();
      break;
    }
    case 'tool_call': {
      if (state.busy) setMood('focused');
      if (ev.name === 'update_plan') { quietCalls.add(ev.id); break; }
      if (!ev.helper) finishRunning();
      if (!group) group = add(h('div', 'activity'));
      const t = toolInfo(ev.name);
      const s = h('div', 'step running', `<div class="step-head"><span class="ic">${icon(t.icon)}</span><span class="label"></span><span class="detail"></span><span class="chev">${icon('chev', 14)}</span></div>${ev.name === 'delegate' ? '<div class="subs"></div>' : ''}<div class="step-body"></div>`);
      s.dataset.name = ev.name; s.dataset.args = JSON.stringify(ev.args || {});
      s.querySelector('.label').textContent = tl(ev.name, ev.args, 'run');
      const detail = t.d(ev.args || {}) || '';
      s.querySelector('.detail').textContent = String(detail).split('\n')[0];
      s.querySelector('.step-head').onclick = () => s.classList.toggle('open');
      if (ev.helper) { const tg = h('span', 'tag helper'); tg.textContent = ev.helper; s.querySelector('.chev').before(tg); }
      if (ev.id) steps[ev.id] = s;
      if (ev.name === 'delegate') helperSteps[(ev.args || {}).description] = s;
      const parent = ev.helper && helperSteps[ev.helper];
      (parent ? parent.querySelector('.subs') : group).appendChild(s); lastStep = s; scrollDown();
      break;
    }
    case 'pr_update': {
      const n = h('div', 'notice'); n.innerHTML = `${icon('pr', 13)} <span></span> <a target="_blank" rel="noopener">open</a>`;
      n.querySelector('span').textContent = ev.text; n.querySelector('a').href = ev.url;
      thread.appendChild(n); alertUser(ev.text); toast(ev.text);
      break;
    }
    case 'mcp_login': {
      toast(ev.status === 'connected' ? `Signed in to ${ev.name}` : (ev.error || 'Sign-in failed'));
      refreshAppCatalog(); api('/api/state').then(r => r.json()).then(s => s.mcp && renderMcp(s.mcp)); break;
    }
    case 'github_login': {
      if (ev.status === 'connected') toast('Connected to GitHub as ' + ev.login); else toast(ev.error || 'GitHub sign-in failed');
      loadGit(); break;
    }
    case 'tool_image': {
      const step = (ev.id && steps[ev.id]) || lastStep;
      if (step) { const img = h('img', 'shot'); img.src = `data:${ev.media};base64,${ev.data}`; img.alt = 'Browser screenshot'; img.onclick = () => window.open(img.src); step.querySelector('.step-body').appendChild(img); }
      break;
    }
    case 'tool_output': {
      if (quietCalls.has(ev.id)) break;
      const step = (ev.id && steps[ev.id]) || lastStep;
      if (step) {
        step.dataset.out = '1';
        const p = h('pre', ev.error ? 'err' : ''); p.textContent = ev.text;
        if (step.dataset.name === 'delegate' && !ev.error) { const pr = h('div', 'prose'); pr.innerHTML = md(ev.text); pr.style.cssText = 'padding:10px 12px;border:1px solid var(--line);border-radius:9px;background:var(--surface)'; step.querySelector('.step-body').appendChild(pr); }
        else step.querySelector('.step-body').appendChild(p);
        markStep(step, ev.error ? 'error' : 'done');
        const path = JSON.parse(step.dataset.args).path;
        if (path && path === openPath) openFile(path, true);
      }
      clearTimeout(refreshTimer); refreshTimer = setTimeout(refreshAll, 350);
      break;
    }
    case 'approval': {
      setMood('curious');
      pending++; updateStatus(); alertUser('Bowers needs your OK to continue');
      const a = ev.args || {}; const ask = ASK[ev.name];
      const mm = String(ev.name).match(/^mcp__(.+?)__(.+)$/);
      const what = typeof ask === 'function' ? ask(a) : (ask || (mm ? `use ${mm[2]} from the ${mm[1]} MCP server` : `use ${ev.name}`));
      const box = h('div', 'approval', `<div class="ap-head">${icon('shield')}<span>Bowers wants to ${esc(what)}</span></div><div class="ap-body"></div><div class="ap-actions">
        <button class="btn primary" data-a="yes">Allow</button><button class="btn" data-a="always">Always allow this</button><button class="btn danger" data-a="no">Deny</button></div>`);
      const body = box.querySelector('.ap-body');
      if (ev.name === 'edit_file') body.appendChild(diffView(a.old_string, a.new_string));
      else { const pre = h('pre', 'code-view'); pre.textContent = ev.name === 'bash' || ev.name === 'start_process' ? a.command : ev.name === 'write_file' ? a.content : ev.name === 'create_pull_request' ? `${a.title}\n\n${a.body || ''}` : (a.body || JSON.stringify(a, null, 2)); body.appendChild(pre); }
      box.id = 'ap-' + ev.id;
      box.querySelectorAll('[data-a]').forEach(b => b.onclick = () => { box.querySelectorAll('button').forEach(x => x.disabled = true); api('/api/approve', { id: ev.id, answer: b.dataset.a }); });
      const at = (ev.call && steps[ev.call]) || lastStep;
      if (at) { at.classList.remove('running'); at.classList.add('waiting'); at.after(box); } else add(box);
      scrollDown();
      break;
    }
    case 'approval_done': {
      pending = Math.max(0, pending - 1); updateStatus();
      const box = $('ap-' + ev.id); if (!box) break;
      const step = box.previousElementSibling?.classList.contains('step') ? box.previousElementSibling : null;
      box.remove();
      if (step) {
        const tag = h('span', 'tag' + (ev.answer === 'no' ? ' no' : ''), ev.answer === 'no' ? 'Denied' : ev.answer === 'always' ? 'Always allowed' : 'Approved');
        step.querySelector('.chev').before(tag);
        if (ev.answer === 'no') markStep(step, 'error'); else { step.classList.remove('waiting'); step.classList.add('running'); }
      }
      break;
    }
    case 'question': {
      setMood('curious');
      alertUser('Bowers has a question for you');
      pending++; updateStatus();
      const card = h('div', 'qcard', `<div class="q-head">${icon('question')}<span>Bowers has ${ev.questions.length > 1 ? 'some questions' : 'a question'}</span></div>`);
      card.id = 'q-' + ev.id;
      const picks = ev.questions.map(() => new Set()), others = [];
      ev.questions.forEach((q, i) => {
        const qe = h('div', 'q', `<b></b><div class="qopts"></div>`); qe.querySelector('b').textContent = q.question;
        for (const opt of q.options || []) {
          const o = h('button', 'qopt', `<span></span>${opt.description ? '<small></small>' : ''}`);
          o.firstChild.textContent = opt.label; if (opt.description) o.querySelector('small').textContent = opt.description;
          o.onclick = () => {
            if (!q.multi_select) { picks[i].clear(); qe.querySelectorAll('.qopt').forEach(x => x.classList.remove('sel')); }
            picks[i].has(opt.label) ? picks[i].delete(opt.label) : picks[i].add(opt.label); o.classList.toggle('sel', picks[i].has(opt.label));
          };
          qe.querySelector('.qopts').appendChild(o);
        }
        const other = h('input', 'input other'); other.placeholder = 'Or type your own answer'; others.push(other); qe.appendChild(other);
        card.appendChild(qe);
      });
      const actions = h('div', 'q-actions', `<button class="btn primary">Send answers</button><button class="btn ghost">Skip</button>`);
      actions.children[0].onclick = () => {
        const answers = ev.questions.map((q, i) => others[i].value.trim() || [...picks[i]].join(', '));
        if (answers.some(a => !a)) { toast('Answer each question, or press Skip'); return; }
        api('/api/respond', { id: ev.id, answer: answers });
      };
      actions.children[1].onclick = () => api('/api/respond', { id: ev.id, answer: null });
      card.appendChild(actions);
      const at = (ev.call && steps[ev.call]) || lastStep; if (at) at.after(card); else add(card);
      scrollDown(); break;
    }
    case 'question_done': {
      pending = Math.max(0, pending - 1); updateStatus();
      const card = $('q-' + ev.id); if (!card) break;
      const qs = [...card.querySelectorAll('.q > b')].map(b => b.textContent);
      const done = h('div', 'answered'); done.textContent = ev.answers ? qs.map((q, i) => `${q}\n→ ${ev.answers[i]}`).join('\n') : 'Questions skipped';
      card.replaceWith(done); break;
    }
    case 'plan_review': {
      setMood('curious');
      alertUser('Bowers has a plan for you to review');
      pending++; updateStatus();
      const card = h('div', 'plancard', `<div class="q-head">${icon('book')}<span>Bowers has a plan. Review it before anything changes</span></div><div class="prose"></div><textarea placeholder="What should change? (only needed for Request changes)"></textarea><div class="q-actions"><button class="btn primary" data-d="approve">Approve</button><button class="btn" data-d="approve_auto">Approve and auto mode</button><button class="btn" data-d="reject">Request changes</button></div>`);
      card.id = 'pr-' + ev.id; card.querySelector('.prose').innerHTML = md(ev.plan); scheduleMath(card.querySelector('.prose'));
      card.querySelectorAll('[data-d]').forEach(b => b.onclick = () => {
        const feedback = card.querySelector('textarea').value.trim();
        if (b.dataset.d === 'reject' && !feedback) { toast('Say what should change'); card.querySelector('textarea').focus(); return; }
        api('/api/respond', { id: ev.id, answer: { decision: b.dataset.d, feedback } });
      });
      const at = (ev.call && steps[ev.call]) || lastStep; if (at) at.after(card); else add(card);
      scrollDown(); break;
    }
    case 'plan_review_done': {
      pending = Math.max(0, pending - 1); updateStatus();
      const card = $('pr-' + ev.id); if (!card) break;
      card.querySelector('.q-actions').remove(); card.querySelector('textarea').remove();
      card.style.borderColor = 'var(--line)';
      card.querySelector('.q-head span').textContent = { approve: 'Plan approved', approve_auto: 'Plan approved (auto mode on)', reject: 'Changes requested' }[ev.decision];
      if (ev.decision !== 'reject') refreshState();
      break;
    }
    case 'auto_approved': {
      const step = ev.call && steps[ev.call];
      if (step) { const tg = h('span', 'tag auto', 'Auto-approved'); tg.title = ev.reason; step.querySelector('.chev').before(tg); }
      break;
    }
    case 'warn': endGroup(); add(h('div', 'notice warn', icon('alert') + esc(ev.text))); break;
    case 'error': endGroup(); add(h('div', 'notice error', icon('alert') + esc(ev.text))); break;
    case 'observer': add(observerCard(ev)); break;
    case 'notice': add(h('div', 'notice', icon('sparkle') + esc(ev.text))); refreshAll(); break;
    case 'usage': showUsage(ev.usage); break;
    case 'process': onProcess(ev); if (ev.url && ev.running) liveCard(ev); break;
    case 'project_changed': location.reload(); break;
    case 'idle': if (state.busy) { alertUser('Bowers finished'); setMood('excited', 4000); } loadRecent(); endGroup(); pending = 0; setBusy(false); refreshAll(); break;
  }
}

async function connect() {
  while (true) {
    try {
      const res = await fetch('/api/events', { headers: { 'x-docks-token': token } });
      if (res.status === 401) { $('gate').classList.remove('hidden'); return; }
      const reader = res.body.getReader(); const dec = new TextDecoder(); let buf = '';
      while (true) {
        const { value, done } = await reader.read(); if (done) break;
        buf += dec.decode(value, { stream: true });
        let i;
        while ((i = buf.indexOf('\n\n')) >= 0) {
          const chunk = buf.slice(0, i); buf = buf.slice(i + 2);
          const data = chunk.split('\n').filter(l => l.startsWith('data: ')).map(l => l.slice(6)).join('\n');
          if (data) handle(JSON.parse(data));
        }
      }
    } catch (e) {}
    await new Promise(r => setTimeout(r, 1500)); // the server replays the conversation on reconnect
  }
}

// ---------------------------------------------------------------- composer
async function send(textOverride) {
  if (state.busy) { api('/api/stop', {}); return; }
  const text = (textOverride ?? $('input').value).trim();
  const uiCmd = UI_COMMANDS.find(c => text === '/' + c.name);
  if (uiCmd) { $('input').value = ''; store.set('docks-draft', ''); hidePalette(); autosize(); uiCmd.ui(); return; }
  if (/^#(?!!)/.test(text) && !textOverride) {  // "# use pnpm" -> remembered in the project's instruction file
    const scope = text.startsWith('##') ? 'local' : 'project';
    const r = await api('/api/memory', { text: text.replace(/^#+/, ''), scope });
    if (r.ok) { const j = await r.json(); $('input').value = ''; store.set('docks-draft', ''); autosize(); toast(`Remembered in ${j.name}`); }
    else toast((await r.json()).error);
    return;
  }
  const images = textOverride ? [] : attachments.map(a => ({ media_type: a.type, data: a.data }));
  if (!text && !images.length) return;
  const res = await api('/api/chat', { message: text, images });
  if (res.ok) {
    store.set('docks-last', text);
    if (!textOverride) { $('input').value = ''; attachments = []; renderAttachments(); store.set('docks-draft', ''); }
    hidePalette(); autosize(); mobile('chat');
  }
  else toast((await res.json().catch(() => ({}))).error || 'Could not send');
}
function autosize() { const t = $('input'); t.style.height = 'auto'; t.style.height = Math.min(t.scrollHeight, 220) + 'px'; $('send').disabled = !state.busy && !t.value.trim() && !attachments.length; }

// Image attachments: click, paste or drop. Build UIs from screenshots and mockups.
let attachments = [];
const TYPES = ['image/png', 'image/jpeg', 'image/gif', 'image/webp'];
function addFiles(list) {
  for (const f of list) {
    if (!TYPES.includes(f.type)) { toast('Images only: PNG, JPEG, GIF or WebP'); continue; }
    if (f.size > 5 * 1024 * 1024) { toast(`${f.name} is over 5 MB`); continue; }
    if (attachments.length >= 5) { toast('Up to 5 images'); break; }
    const r = new FileReader();
    r.onload = () => { attachments.push({ type: f.type, url: r.result, data: String(r.result).split(',')[1] }); renderAttachments(); };
    r.readAsDataURL(f);
  }
}
function renderAttachments() {
  const box = $('attachments'); box.innerHTML = '';
  attachments.forEach((a, i) => {
    const t = h('div', 'thumb', `<img alt="attachment ${i + 1}"><button aria-label="Remove image">×</button>`);
    t.querySelector('img').src = a.url;
    t.querySelector('button').onclick = () => { attachments.splice(i, 1); renderAttachments(); };
    box.appendChild(t);
  });
  autosize();
}
$('attach').onclick = () => $('file-input').click();
$('file-input').onchange = e => { addFiles(e.target.files); e.target.value = ''; };
$('input').addEventListener('paste', e => { const files = [...(e.clipboardData?.files || [])]; if (files.length) { e.preventDefault(); addFiles(files); } });
const comp = $('composer');
['dragenter', 'dragover'].forEach(t => comp.addEventListener(t, e => { e.preventDefault(); comp.classList.add('drag'); }));
['dragleave', 'drop'].forEach(t => comp.addEventListener(t, e => { e.preventDefault(); comp.classList.remove('drag'); }));
comp.addEventListener('drop', e => addFiles(e.dataTransfer.files));

async function deploy() {
  const r = await api('/api/github', { action: 'deploy' });
  if (r.ok) { mobile('chat'); toast('Bowers is deploying your project'); } else toast((await r.json()).error);
}
$('deploy').onclick = deploy;
$('send').onclick = () => send();
// On touch keyboards Enter makes a new line and the send button sends; elsewhere Enter sends.
$('input').addEventListener('keydown', e => {
  if (paletteKeys(e)) return;
  if (e.key === 'Tab' && e.shiftKey) { e.preventDefault(); const order = Object.keys(MODES); setMode(order[(order.indexOf(state.mode) + 1) % order.length]); return; }
  if (e.key === 'ArrowUp' && !$('input').value) { const last = store.get('docks-last', ''); if (last) { e.preventDefault(); $('input').value = last; autosize(); } return; }
  if (e.key === 'Enter' && !e.shiftKey && !e.isComposing && !matchMedia('(pointer: coarse)').matches) { e.preventDefault(); if (!state.busy) send(); }
});
$('input').addEventListener('input', () => { autosize(); store.set('docks-draft', $('input').value); updatePalette(); });
if (!$('input').value) { $('input').value = store.get('docks-draft', ''); }

// "/" opens commands, "@" opens files: arrow keys to move, Enter or Tab to pick, Escape to close.
let commands = [], palItems = [], palIndex = 0, palMatch = null;
const UI_COMMANDS = [
  { name: 'clear', description: 'Start a new conversation', ui: () => newChat() },
  { name: 'plan', description: 'Switch to plan mode', ui: () => setMode('plan') },
  { name: 'mode', description: 'Choose how Bowers asks before changes', ui: () => { renderModeMenu(); $('mode-menu').classList.remove('hidden'); fitModeMenu(); } },
  { name: 'resume', description: 'Open saved conversations', ui: () => openDrawer('sessions') },
  { name: 'bookmarks', description: 'Show bookmarked replies', ui: () => openDrawer('bookmarks') },
  { name: 'context', description: "What's filling the context window", ui: () => showContext() },
  { name: 'compact', description: 'Summarize the conversation to free up room', ui: () => compactChat() },
  { name: 'doctor', description: 'Check your setup', ui: () => showDoctor() },
  { name: 'memory', description: 'Instruction files in use (start a message with # to add a line)', ui: () => showMemory() },
  { name: 'style', description: 'Choose an output style', ui: () => { $('open-settings').click(); $('style-select').focus(); } },
];
function sysCard(title, body) {
  const card = h('div', 'syscard', `<div class="syscard-head"><b></b><button class="btn ghost icon-only" aria-label="Close">✕</button></div><div class="syscard-body"></div>`);
  card.querySelector('b').textContent = title;
  card.querySelector('button').onclick = () => card.remove();
  card.querySelector('.syscard-body').appendChild(body);
  thread.appendChild(card); card.scrollIntoView({ behavior: 'smooth', block: 'end' });
}
async function showContext() {
  const r = await api('/api/context'); if (!r.ok) return toast('Could not read the context');
  const c = await r.json(), total = c.measured || c.estimated, body = h('div');
  body.appendChild(h('div', 'muted', `${total.toLocaleString()} tokens` + (c.window ? ` of ${c.window.toLocaleString()} (${Math.round(100 * total / c.window)}%)` : '') + (c.measured ? '' : ' (estimated)')));
  const max = Math.max(...Object.values(c.parts), 1);
  for (const [name, n] of Object.entries(c.parts).sort((a, b) => b[1] - a[1])) {
    if (n <= 0) continue;
    body.appendChild(h('div', 'ctx-row', `<span>${esc(name)}</span><i style="width:${Math.max(2, 100 * n / max)}%"></i><small>~${n.toLocaleString()}</small>`));
  }
  body.appendChild(h('div', 'muted', 'Long sessions are summarized automatically. /compact does it now; /clear starts over.'));
  sysCard('Context', body);
}
async function compactChat() {
  toast('Summarizing the conversation…');
  const r = await api('/api/compact', {});
  if (r.ok) { applyState(await r.json()); toast('Conversation summarized'); } else toast((await r.json()).error);
}
async function showDoctor() {
  const r = await api('/api/doctor'); if (!r.ok) return toast('Could not run the checks');
  const body = h('div'), marks = { ok: '✓', warn: '!', fail: '✗' };
  for (const [status, what, detail] of (await r.json()).results)
    body.appendChild(h('div', 'doc-row ' + status, `<span>${marks[status]}</span><b>${esc(what)}</b><small>${esc(detail)}</small>`));
  sysCard('Setup check', body);
}
async function showMemory() {
  const r = await api('/api/memory'); if (!r.ok) return;
  const { files } = await r.json(), body = h('div');
  if (!files.length) body.appendChild(h('div', 'muted', 'No instruction files yet. Start a message with # to add one, or run /init.'));
  for (const f of files) { const d = h('details', null, `<summary><code></code></summary><pre></pre>`); d.querySelector('code').textContent = f.path; d.querySelector('pre').textContent = f.text; body.appendChild(d); }
  sysCard('Instruction files', body);
}
function updatePalette() {
  const t = $('input'), before = t.value.slice(0, t.selectionStart);
  let m;
  if ((m = before.match(/^\/([\w:.-]*)$/))) {
    const q = m[1].toLowerCase();
    palMatch = { kind: '/', start: 0, end: before.length };
    palItems = [...UI_COMMANDS, ...commands].filter(c => c.name.toLowerCase().includes(q)).slice(0, 40)
      .map(c => ({ label: '/' + c.name, sub: c.hint ? `${c.hint}  ${c.description}` : c.description, cmd: c }));
  } else if ((m = before.match(/(^|\s)@([\w./-]*)$/))) {
    const q = m[2].toLowerCase();
    palMatch = { kind: '@', start: before.length - m[2].length - 1, end: before.length };
    palItems = files.filter(f => f.toLowerCase().includes(q)).slice(0, 30).map(f => ({ label: '@' + f, sub: '', file: f }));
  } else { hidePalette(); return; }
  if (!palItems.length) { hidePalette(); return; }
  palIndex = 0; renderPalette();
}
function renderPalette() {
  const box = $('palette'); box.innerHTML = ''; box.classList.remove('hidden');
  palItems.forEach((it, i) => {
    const row = h('div', 'pal-item' + (i === palIndex ? ' active' : ''), `<code></code><span></span>`);
    row.firstChild.textContent = it.label; row.lastChild.textContent = it.sub || '';
    row.onmousedown = e => { e.preventDefault(); pickPalette(i); };
    box.appendChild(row);
  });
  box.children[palIndex]?.scrollIntoView({ block: 'nearest' });
}
function hidePalette() { $('palette').classList.add('hidden'); palItems = []; palMatch = null; }
function pickPalette(i) {
  const it = palItems[i], t = $('input'); if (!it) return;
  if (it.cmd?.ui) { t.value = ''; hidePalette(); autosize(); it.cmd.ui(); return; }
  const insert = it.cmd ? `/${it.cmd.name} ` : `@${it.file} `;
  t.value = t.value.slice(0, palMatch.start) + insert + t.value.slice(palMatch.end);
  const pos = palMatch.start + insert.length; t.setSelectionRange(pos, pos);
  hidePalette(); autosize(); t.focus(); store.set('docks-draft', t.value);
}
function paletteKeys(e) {
  if (!palItems.length) return false;
  if (e.key === 'ArrowDown' || e.key === 'ArrowUp') { e.preventDefault(); palIndex = (palIndex + (e.key === 'ArrowDown' ? 1 : palItems.length - 1)) % palItems.length; renderPalette(); return true; }
  if (e.key === 'Enter' || e.key === 'Tab') { e.preventDefault(); pickPalette(palIndex); return true; }
  if (e.key === 'Escape') { e.preventDefault(); hidePalette(); return true; }
  return false;
}
$('input').addEventListener('blur', () => setTimeout(hidePalette, 150));

// Math in replies ($$…$$, \[…\], \(…\)) renders with KaTeX, loaded only when needed.
let katexLoading = null; const mathQueue = new Set(); let mathTimer = null;
function loadKatex() {
  if (katexLoading) return katexLoading;
  const base = 'https://cdnjs.cloudflare.com/ajax/libs/KaTeX/0.16.9/';
  const css = h('link'); css.rel = 'stylesheet'; css.href = base + 'katex.min.css'; document.head.appendChild(css);
  const load = src => new Promise((ok, fail) => { const sc = h('script'); sc.src = src; sc.onload = ok; sc.onerror = fail; document.head.appendChild(sc); });
  katexLoading = load(base + 'katex.min.js').then(() => load(base + 'contrib/auto-render.min.js')).catch(() => null);
  return katexLoading;
}
function scheduleMath(el) {
  if (!/\$\$|\\\[|\\\(/.test(el.textContent)) return;
  mathQueue.add(el); clearTimeout(mathTimer);
  mathTimer = setTimeout(async () => {
    await loadKatex(); if (!window.renderMathInElement) return;
    for (const node of mathQueue) renderMathInElement(node, { throwOnError: false, delimiters: [
      { left: '$$', right: '$$', display: true }, { left: '\\[', right: '\\]', display: true }, { left: '\\(', right: '\\)', display: false }] });
    mathQueue.clear();
  }, 350);
}
autosize();

async function saveSettings(extra = {}) {
  const res = await api('/api/settings', { model: $('model').value, effort: $('effort').value, ...extra });
  if (res.ok) { const st = await res.json(); showMode(st.mode); state.model = st.model; }
  else { toast((await res.json()).error || 'Could not change that'); $('model').value = state.model; }
}
async function refreshState() { const r = await api('/api/state'); if (r.ok) { const s = await r.json(); showMode(s.mode); state.bookmarks = s.bookmarks; } }
$('model').onchange = () => saveSettings(); $('effort').onchange = () => saveSettings();
$('mode-select').onchange = () => setMode($('mode-select').value);
$('style-select').onchange = async () => { const r = await api('/api/settings', { output_style: $('style-select').value }); if (r.ok) { applyState(await r.json()); toast('Output style: ' + $('style-select').value); } };
$('observer').onchange = async () => {
  const r = await api('/api/settings', { observer: $('observer').checked });
  if (r.ok) toast($('observer').checked ? 'The observer will check tasks that change things' : 'Observer off');
};
$('sandbox').onchange = async () => {
  const r = await api('/api/settings', { sandbox: $('sandbox').checked });
  if (r.ok) { applyState(await r.json()); toast($('sandbox').checked ? 'Commands now run in a sandbox' : 'Sandbox off'); }
  else { $('sandbox').checked = false; toast((await r.json()).error); }
};
$('notify').checked = store.get('docks-notify', '') === '1' && 'Notification' in window && Notification.permission === 'granted';
$('notify').onchange = async () => {
  if ($('notify').checked && 'Notification' in window && Notification.permission !== 'granted') {
    if (await Notification.requestPermission() !== 'granted') { $('notify').checked = false; toast('Your browser blocked notifications'); }
  }
  store.set('docks-notify', $('notify').checked ? '1' : '');
};
function alertUser(text) {  // only when the tab is in the background
  if (!document.hidden || store.get('docks-notify', '') !== '1' || !('Notification' in window) || Notification.permission !== 'granted') return;
  try { const n = new Notification('Bowers', { body: text, tag: 'docks' }); n.onclick = () => { window.focus(); n.close(); }; } catch (e) {}
}
function fitModeMenu() {  // keep the menu on screen when the chip sits far right (phones)
  const menu = $('mode-menu'); menu.style.left = '0px';
  const over = menu.getBoundingClientRect().right - (innerWidth - 16);
  if (over > 0) menu.style.left = -over + 'px';
}
$('mode-chip').onclick = e => { e.stopPropagation(); renderModeMenu(); $('mode-menu').classList.toggle('hidden'); fitModeMenu(); };
document.addEventListener('click', e => { if (!e.target.closest('.mode-wrap')) $('mode-menu').classList.add('hidden'); });

// Conversations and bookmarks drawer
let drawerTab = 'sessions', drawerLoad = 0;
async function openDrawer(tab) {
  drawerTab = tab || drawerTab; $('drawer').classList.remove('hidden');
  const load = ++drawerLoad;  // a slower earlier load must not draw over a newer tab
  document.querySelectorAll('[data-dtab]').forEach(t => t.classList.toggle('on', t.dataset.dtab === drawerTab));
  const body = $('drawer-body');
  if (drawerTab === 'sessions') {
    const r = await api('/api/sessions'); if (!r.ok || load !== drawerLoad) return;
    const { sessions, current } = await r.json(); if (load !== drawerLoad) return;
    body.innerHTML = '';
    const rename = h('div', 'rename-row', `<input class="input" placeholder="Name this conversation"><button class="btn">Rename</button>`);
    rename.querySelector('input').value = state.session?.name || '';
    rename.querySelector('button').onclick = async () => { const name = rename.querySelector('input').value.trim(); if (!name) return; await api('/api/sessions/rename', { name }); state.session = { ...(state.session || {}), name }; toast('Renamed'); openDrawer('sessions'); };
    body.appendChild(rename);
    if (!sessions.length) body.appendChild(h('div', 'empty-state', 'No saved conversations yet. They appear here after your first message.'));
    for (const sn of sessions) {
      const wrap = h('div', 'srow-wrap');
      const row = h('button', 'srow' + (sn.id === current ? ' current' : ''), `<b></b><small></small>`);
      const rb = h('button', 'btn replay-btn', `${icon('play', 12)} Replay`); rb.onclick = () => openReplay(sn.id, sn.name);
      wrap.append(row, rb);
      row.querySelector('b').textContent = sn.name;
      row.querySelector('small').textContent = `${new Date(sn.updated * 1000).toLocaleString()} · ${sn.turns} message${sn.turns === 1 ? '' : 's'}${sn.id === current ? ' · open now' : ''}`;
      row.onclick = async () => {
        if (sn.id === current) { $('drawer').classList.add('hidden'); return; }
        const rr = await api('/api/sessions/resume', { id: sn.id });
        if (!rr.ok) { toast((await rr.json()).error || 'Could not open it'); return; }
        toast('Resumed: ' + sn.name); $('drawer').classList.add('hidden');
      };
      body.appendChild(wrap);
    }
  } else {
    const r = await api('/api/state'); if (r.ok) state.bookmarks = (await r.json()).bookmarks;
    if (load !== drawerLoad) return;
    body.innerHTML = '';
    if (!state.bookmarks?.length) body.appendChild(h('div', 'empty-state', 'No bookmarks yet. Hover a reply and press Bookmark to keep it here.'));
    for (const bm of [...(state.bookmarks || [])].reverse()) {
      const row = h('div', 'bm', `<div class="prose"></div><div class="bm-actions"><button class="btn ghost">${icon('copy', 13)} Copy</button></div>`);
      row.querySelector('.prose').innerHTML = md(bm.text); scheduleMath(row.querySelector('.prose'));
      row.querySelector('button').onclick = () => navigator.clipboard?.writeText(bm.text).then(() => toast('Copied'));
      body.appendChild(row);
    }
  }
}
$('open-history').onclick = () => openDrawer('sessions');
$('close-drawer').onclick = () => $('drawer').classList.add('hidden');
document.querySelectorAll('[data-dtab]').forEach(t => t.onclick = () => openDrawer(t.dataset.dtab));
document.addEventListener('keydown', e => { if (e.key === 'Escape') $('drawer').classList.add('hidden'); });
function renderMcp(list) {
  const box = $('mcp-list'); box.innerHTML = '';
  if (!list.length) { box.innerHTML = '<div class="mcp-row"><small>None yet. Connect an app below, or add one with <code>bowers mcp add</code>.</small></div>'; return; }
  for (const m of list) {
    const label = { running: `${m.tools.length} tools`, error: 'failed', 'needs-approval': 'needs approval', 'needs-auth': 'sign-in needed', stopped: 'stopped' }[m.status];
    const row = h('div', 'mcp-row', `<span class="d ${m.status}"></span><span></span><small>${esc(label)}</small>`);
    row.children[1].textContent = m.name; row.title = m.error || m.command;
    if (m.status === 'needs-approval') {
      const b = h('button', 'btn', 'Approve'); b.title = `Runs: ${m.command}`;
      b.onclick = async e => { e.stopPropagation(); if (!confirm(`Start MCP server "${m.name}"?\n\nIt runs: ${m.command}`)) return; const r = await api('/api/mcp/approve', { name: m.name }); if (r.ok) renderMcp((await r.json()).mcp); else toast((await r.json()).error); };
      row.appendChild(b);
    }
    box.appendChild(row);
  }
}
async function newChat() {
  const r = await api('/api/clear', {}); if (!r.ok) toast('Stop the current task first');
}
$('new-chat').onclick = () => { showPage('home'); newChat(); };
$('open-settings').onclick = () => showPage('settings');
$('toggle-panel').onclick = () => { const closed = $('app').classList.toggle('panel-closed'); store.set('docks-panel', closed ? 'closed' : 'open'); };
if (store.get('docks-panel', 'open') === 'closed') $('app').classList.add('panel-closed');
$('gh-chip').onclick = () => { $('app').classList.remove('panel-closed'); showTab('github'); mobile('github'); };

