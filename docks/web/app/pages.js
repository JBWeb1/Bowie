// Bowers web app: Pages: home, models, projects, library, tasks, studio, explore, settings, onboarding.
// Plain scripts that share one global scope, loaded in order by app.html.
// ---------------------------------------------------------------- start
// ================================================================ Bowers: pages, home, Bowie, models
let page = 'home', profileName = '';
const PAGES = ['projects', 'tasks', 'library', 'motion', 'forge', 'care', 'labs', 'integrations', 'graph', 'explore', 'settings'];
function showPage(name) {
  if (name === 'studio') name = 'motion';
  if (name === 'graph' && !isAether()) { toast('The Knowledge Graph is part of Bowers Aether. Switch models to use it.'); name = 'home'; }
  page = name;
  const brand = { motion: 'Motion', forge: 'Forge', care: 'Care', graph: 'Aether', labs: 'Labs', integrations: 'Labs' }[name];
  $('side-sub').textContent = brand ? ' ' + brand : '';
  const home = name === 'home';
  $('app').classList.toggle('hidden', !home);
  for (const p of PAGES) $('page-' + p).classList.toggle('hidden', p !== name);
  document.querySelectorAll('.side-nav button[data-page]').forEach(b => b.classList.toggle('on', b.dataset.page === name));
  if (document.querySelector(`.side-more [data-page="${name}"]`)) $('side-more').open = true;
  $('more-sheet').classList.add('hidden');
  ({ projects: loadProjects, tasks: loadTasks, library: loadLibrary, motion: renderMotion, forge: renderForgePage, care: renderCare, labs: renderLabs, integrations: renderIntegrations, graph: renderGraph, explore: renderExplore, settings: openSettings })[name]?.();
  if (home) { $('app').classList.remove('show-panel'); }
}
const closeSide = () => document.body.classList.remove('side-open');
document.querySelectorAll('.side-nav button[data-page]').forEach(b => b.onclick = () => { showPage(b.dataset.page); closeSide(); });
$('side-new').onclick = () => { showPage('home'); newChat(); closeSide(); };
$('side-logo').onclick = () => { showPage('home'); closeSide(); };
$('side-search').onclick = () => { closeSide(); openCmdk(); };
$('side-me').onclick = () => { showPage('settings'); closeSide(); };
$('open-side').onclick = () => document.body.classList.add('side-open');
$('side-scrim').onclick = closeSide;

// Bowie's moods follow what Bowers is doing
let mood = 'happy', moodTimer = null, idleTimer = null;
const MOOD_TEXT = { thinking: 'Thinking…', focused: 'Working on it…', curious: 'Waiting for you…', happy: 'Working on it…' };
function setMood(m, revertAfter = 0) {
  mood = m; clearTimeout(moodTimer); clearTimeout(idleTimer);
  document.querySelectorAll('img.bowie-live').forEach(i => { i.src = BOWIE(m); });
  const label = typing?.querySelector('.t-label'); if (label) label.textContent = MOOD_TEXT[m] || 'Working on it…';
  if (revertAfter) moodTimer = setTimeout(() => setMood(state.busy ? 'thinking' : 'happy'), revertAfter);
  if (!state.busy && m === 'happy') idleTimer = setTimeout(() => setMood('relaxed'), 180000);
}

// Greeting home
const greetWord = () => { const hr = new Date().getHours(); return hr < 5 ? 'Good evening' : hr < 12 ? 'Good morning' : hr < 18 ? 'Good afternoon' : 'Good evening'; };
function setHome(on) {
  $('chat').classList.toggle('home', on);
  $('app').classList.toggle('home-mode', on);
  $('deploy-top').classList.toggle('hidden', on);
  $('toggle-panel').classList.toggle('hidden', on);
}
const HOME_CHIPS = [
  ['globe', 'Build a website', () => prefill('Build a website for ')],
  ['chart', 'Run my business', () => openBusiness()],
  ['image', 'Create an image', () => openStudioTool('image')],
  ['smartphone', 'Build an app', () => prefill('Build an app that ')],
];
function prefill(text) { showPage('home'); const t = $('input'); t.value = text; autosize(); t.focus(); t.setSelectionRange(t.value.length, t.value.length); }
function renderHomeExtra() {
  const box = $('home-extra'); box.innerHTML = '';
  const chips = h('div', 'quick-chips');
  for (const [ic, label, fn] of HOME_CHIPS) { const b = h('button', 'chip', `${icon(ic, 14)}${esc(label)}`); b.onclick = fn; chips.appendChild(b); }
  box.append(h('div', 'brain-banner hidden', ''), chips);
}
renderHomeExtra();

// The model chip and the model picker
const MODEL_ART = { syntra: 'focused', aether: 'thinking', solace: 'relaxed', local: 'chilling' };
const MODEL_BADGE = { syntra: ['Recommended', ''], aether: ['Most capable', ''], solace: ['Calm and clear', 'mint'], local: ['Free · no key', 'mint'] };
function modelCard(m, current, onPick) {
  const art = MODEL_ART[m.id] || 'happy', [badge, tone] = MODEL_BADGE[m.id] || [m.group === 'Engines' ? 'Engine' : '', 'mint'];
  const c = h('button', 'mcard' + (m.id === current ? ' on' : ''), `<img src="${BOWIE(art)}" alt=""><b></b><p></p>${badge ? `<span class="badge-soft ${tone}">${esc(badge)}</span>` : ''}`);
  c.querySelector('b').textContent = m.label; c.querySelector('p').textContent = m.note;
  c.onclick = () => onPick(m.id); return c;
}
async function pickModel(id) {
  const r = await api('/api/settings', { model: id });
  if (!r.ok) { toast((await r.json()).error || 'Could not switch'); return false; }
  applyState(await r.json()); toast('Now using ' + state.model_label); return true;
}
function openModelPicker() {
  const modal = h('div', 'modal', `<div class="modal-box"><div class="page-head"><h2>Select model</h2><span class="spacer"></span><button class="btn ghost icon-only" aria-label="Close">✕</button></div><div class="filters"><button class="on" data-g="Bowers">Bowers family</button><button data-g="Engines">Engines</button></div><div class="model-cards"></div><div class="mfeat"></div></div>`);
  const grid = modal.querySelector('.model-cards');
  const show = g => {
    modal.querySelectorAll('.filters button').forEach(b => b.classList.toggle('on', b.dataset.g === g));
    grid.innerHTML = ''; (state.models || []).filter(m => m.group === g).forEach(m => grid.appendChild(modelCard(m, state.model, async id => { if (await pickModel(id)) modal.remove(); })));
  };
  modal.querySelectorAll('.filters button').forEach(b => b.onclick = () => show(b.dataset.g));
  modal.querySelector('.mfeat').innerHTML = [['code', 'Text and code'], ['image', 'Image generation'], ['file', 'File analysis'], ['globe', 'Web search'], ['eye', 'Sees screenshots']].map(([i, t]) => `<span>${icon(i, 18)}${t}</span>`).join('');
  modal.onclick = e => { if (e.target === modal || e.target.closest('.page-head button')) modal.remove(); };
  document.body.appendChild(modal); show((state.models || []).find(m => m.id === state.model)?.group || 'Bowers');
}
$('model-chip').onclick = openModelPicker;
$('deploy-top').onclick = () => { showPage('home'); deploy(); };
function showModelState() {
  const lbl = state.model_label || 'Bowers', short = lbl.replace(/^Bowers /, '');
  $('model-chip-text').innerHTML = short !== lbl ? `<span class="m-prefix">Bowers </span>${esc(short)}` : esc(lbl);
  $('me-model').textContent = state.model_label || '';
  const m = (state.models || []).find(x => x.id === state.model);
  $('model-chip').querySelector('img').src = BOWIE(MODEL_ART[state.model] || 'happy');
  if ($('model-note')) $('model-note').textContent = m ? m.note : '';
}

// Sidebar: recent conversations
async function loadRecent() {
  const r = await api('/api/sessions'); if (!r.ok) return;
  const { sessions, current } = await r.json(), box = $('side-recent'); box.innerHTML = '';
  if (!sessions.length) return;
  const head = h('div', 'side-h', 'Recents<button class="link">All chats</button>'); head.querySelector('button').onclick = () => { closeSide(); openDrawer('sessions'); };
  box.appendChild(head);
  for (const sn of sessions.slice(0, 12)) {
    const b = h('button', sn.id === current ? 'on' : '', '<span></span>'); b.querySelector('span').textContent = sn.name;
    b.onclick = async () => { showPage('home'); closeSide(); if (sn.id === current) return; const rr = await api('/api/sessions/resume', { id: sn.id }); if (!rr.ok) toast((await rr.json()).error || 'Could not open it'); };
    box.appendChild(b);
  }
}

// Projects
async function loadProjects() {
  const r = await api('/api/projects'); if (!r.ok) return;
  const d = await r.json(), grid = $('project-grid'), q = ($('project-search').value || '').toLowerCase();
  grid.innerHTML = '';
  for (const p of d.projects.filter(p => p.name.toLowerCase().includes(q))) {
    const c = h('button', 'pcard', `<div class="pthumb"><span class="big"></span></div><div class="pc-body"><div><b></b><small></small></div>${p.current ? '<span class="pill here">Open</span>' : ''}</div>`);
    c.querySelector('.big').textContent = p.name.slice(0, 1).toUpperCase();
    c.querySelector('b').textContent = p.name;
    c.querySelector('small').textContent = `${p.files} file${p.files === 1 ? '' : 's'} · ${ago(p.updated)}${p.conversations ? ` · ${p.conversations} chat${p.conversations === 1 ? '' : 's'}` : ''}`;
    c.title = p.root;
    if (p.thumbnail) api('/api/projects/thumb?root=' + encodeURIComponent(p.root)).then(async rr => { if (rr.ok) { const img = h('img'); img.src = URL.createObjectURL(await rr.blob()); img.alt = ''; c.querySelector('.pthumb').replaceChildren(img); } });
    c.onclick = async () => {
      if (p.current) return showPage('home');
      if (!confirm(`Open ${p.name}?\n\n${p.root}`)) return;
      const rr = await api('/api/projects/open', { root: p.root }); if (!rr.ok) toast((await rr.json()).error);
    };
    grid.appendChild(c);
  }
  if (!grid.children.length) grid.appendChild(h('div', 'empty-page', `<img src="${BOWIE('curious')}" alt=""><b>No projects found</b>Start one with New project.`));
}
$('project-search').addEventListener('input', () => loadProjects());
$('new-project').onclick = async () => {
  const name = prompt('Name your new project'); if (!name) return;
  const r = await api('/api/projects/new', { name }); if (!r.ok) toast((await r.json()).error);
};
const ago = t => { const s = Date.now() / 1000 - t; return s < 90 ? 'just now' : s < 3600 ? `${Math.round(s / 60)} min ago` : s < 86400 ? `${Math.round(s / 3600)}h ago` : `${Math.round(s / 86400)}d ago`; };

// Library
const LIB_FILTERS = [['all', 'All'], ['design', 'Designs'], ['website', 'Websites'], ['image', 'Images'], ['document', 'Documents'], ['code', 'Code']];
let libFilter = 'all', libItems = [];
$('lib-filters').innerHTML = LIB_FILTERS.map(([k, l]) => `<button data-f="${k}"${k === 'all' ? ' class="on"' : ''}>${l}</button>`).join('');
$('lib-filters').querySelectorAll('button').forEach(b => b.onclick = () => { libFilter = b.dataset.f; $('lib-filters').querySelectorAll('button').forEach(x => x.classList.toggle('on', x === b)); renderLibrary(); });
$('lib-search').addEventListener('input', () => renderLibrary());
async function loadLibrary() { const r = await api('/api/library'); if (r.ok) { libItems = (await r.json()).items; renderLibrary(); } }
const KIND_LABEL = { design: 'Design', website: 'Website', image: 'Image', document: 'Document', code: 'Code' };
function renderLibrary() {
  const grid = $('lib-grid'), q = ($('lib-search').value || '').toLowerCase(); grid.innerHTML = '';
  let frames = 0;
  for (const it of libItems.filter(i => (libFilter === 'all' || i.kind === libFilter) && `${i.title} ${i.path || ''}`.toLowerCase().includes(q))) {
    const c = h('button', 'pcard', `<div class="pthumb"></div><div class="pc-body"><div><b></b><small></small></div></div>`);
    const th = c.querySelector('.pthumb');
    if ((it.kind === 'design' || it.kind === 'image') && it.path) { const img = h('img'); img.loading = 'lazy'; img.src = imgUrl(it.path); img.alt = ''; th.appendChild(img); }
    else if (it.kind === 'website' && it.path && frames++ < 8 && state.preview) { const f = h('iframe'); f.src = imgUrl(it.path); f.loading = 'lazy'; f.tabIndex = -1; f.setAttribute('sandbox', 'allow-scripts allow-same-origin') /* a different port: its own origin, not Bowers' */; th.appendChild(f); }
    else th.innerHTML = icon({ website: 'globe', document: 'file', code: 'code' }[it.kind] || 'file', 34);
    c.querySelector('b').textContent = it.title;
    c.querySelector('small').textContent = `${KIND_LABEL[it.kind]} · ${ago(it.updated)}`;
    c.onclick = () => openLibraryItem(it);
    grid.appendChild(c);
  }
  if (!grid.children.length) grid.appendChild(h('div', 'empty-page', `<img src="${BOWIE('relaxed')}" alt=""><b>Nothing here yet</b>Images, websites, documents and code you make show up here.`));
}
function openLibraryItem(it) {
  if (it.kind === 'design' || it.kind === 'image') return openLightbox({ path: it.path, prompt: it.title, created: it.updated });
  if (it.kind === 'website') { showPage('home'); setHome(false); $('preview-path').value = it.path; appUrl = null; previewPicked = true; reloadPreview(); showTab('preview'); mobile('preview'); return; }
  if (it.path) { showPage('home'); setHome(false); showTab('code'); mobile('code'); openFile(it.path); return; }
  const modal = h('div', 'modal', `<div class="modal-box"><div class="page-head"><h2>Bookmarked</h2><span class="spacer"></span><button class="btn">Copy</button><button class="btn ghost icon-only" aria-label="Close">✕</button></div><div class="prose"></div></div>`);
  modal.querySelector('.prose').innerHTML = md(it.text);
  modal.querySelector('.btn:not(.icon-only)').onclick = () => navigator.clipboard?.writeText(it.text).then(() => toast('Copied'));
  modal.onclick = e => { if (e.target === modal || e.target.closest('.icon-only')) modal.remove(); };
  document.body.appendChild(modal);
}

// Tasks & plans
const TASK_FILTERS = [['all', 'All'], ['active', 'Active'], ['completed', 'Completed'], ['pending', 'Pending approval']];
const TASK_STATUS = { active: 'In progress', completed: 'Completed', pending: 'Needs approval', not_started: 'Not started' };
let taskFilter = 'all', tasks = [], taskOn = null;
$('task-filters').innerHTML = TASK_FILTERS.map(([k, l]) => `<button data-f="${k}"${k === 'all' ? ' class="on"' : ''}>${l}</button>`).join('');
$('task-filters').querySelectorAll('button').forEach(b => b.onclick = () => { taskFilter = b.dataset.f; $('task-filters').querySelectorAll('button').forEach(x => x.classList.toggle('on', x === b)); renderTasks(); });
async function loadTasks() { const r = await api('/api/tasks'); if (r.ok) { tasks = (await r.json()).tasks; renderTasks(); } }
function renderTasks() {
  const list = $('task-list'); list.innerHTML = '';
  const shown = tasks.filter(t => taskFilter === 'all' || t.status === taskFilter);
  for (const t of shown) {
    const row = h('button', 'trow' + (taskOn === t.id ? ' on' : ''), `<span class="t-ic">${icon(t.status === 'completed' ? 'check' : 'box', 18)}</span><span><b></b><small></small></span><span class="prog-l"><span class="prog${t.progress === 100 ? ' done' : ''}"><i style="width:${t.progress}%"></i></span>${t.progress}%</span><span class="st ${t.status}">${TASK_STATUS[t.status]}</span>`);
    row.querySelector('b').textContent = t.title; row.querySelector('small').textContent = `${t.project}${t.live ? ' · open now' : ''} · ${ago(t.updated)}`;
    row.onclick = () => { taskOn = t.id; renderTasks(); };
    list.appendChild(row);
  }
  if (!shown.length) list.appendChild(h('div', 'empty-page', `<img src="${BOWIE('relaxed')}" alt=""><b>No tasks here</b>When Bowers plans a multi-step job, it shows up here with its progress.`));
  renderTaskDetail(shown.find(t => t.id === taskOn) || shown[0]);
}
function renderTaskDetail(t) {
  const box = $('task-detail'); box.innerHTML = '';
  if (!t) { box.appendChild(h('p', 'muted', 'Pick a task to see its plan.')); return; }
  taskOn = t.id;
  box.innerHTML = `<div class="muted">Task details</div><h3></h3><div class="muted proj"></div>
    <div class="td-row"><span>Progress</span><b>${t.progress}%</b></div><div class="prog${t.progress === 100 ? ' done' : ''}" style="margin:8px 0"><i style="width:${t.progress}%"></i></div>
    <div class="td-row"><span>Status</span><span class="st ${t.status}">${TASK_STATUS[t.status]}</span></div>
    <div class="td-row"><span>Updated</span><span>${ago(t.updated)}</span></div><ul class="td-plan"></ul><div class="td-actions"></div>`;
  box.querySelector('h3').textContent = t.title; box.querySelector('.proj').textContent = t.root;
  const ul = box.querySelector('.td-plan');
  for (const it of t.plan) { const li = h('li', it.status, `<span class="m">${it.status === 'done' ? icon('check', 10) : ''}</span><span></span>`); li.children[1].textContent = it.text; ul.appendChild(li); }
  const acts = box.querySelector('.td-actions');
  if (t.status === 'pending') {
    acts.appendChild(h('div', 'approve-box', `${icon('alert', 18)}<span><b>Approval required</b><br>Bowers is waiting for your OK before it continues.</span>`));
    const go = h('button', 'btn primary', 'Review and approve'); go.onclick = () => { showPage('home'); setHome(false); document.querySelector('.approval')?.scrollIntoView({ behavior: 'smooth', block: 'center' }); }; acts.appendChild(go);
  } else {
    const go = h('button', 'btn primary', t.live ? 'Open conversation' : 'Continue this task');
    go.onclick = async () => {
      if (!t.live) {
        if (t.root && t.root !== state.root) { const rr = await api('/api/projects/open', { root: t.root }); if (!rr.ok) return toast((await rr.json()).error); sessionStorage.setItem('bowers-resume', t.id); return; }
        const rr = await api('/api/sessions/resume', { id: t.id }); if (!rr.ok) return toast((await rr.json()).error || 'Could not open it');
      }
      showPage('home');
    };
    acts.appendChild(go);
  }
}

// Creation Studio
const STUDIO = [
  ['image', 'Image Generator', 'Create stunning images with AI', 'Real image generation', 'linear-gradient(135deg,#f0a35e,#7a3f8f)', 'image'],
  ['play', 'Video Creator', 'Animated videos and motion pieces', 'Built as code: an animated HTML video', 'linear-gradient(135deg,#1b2a6b,#6a2fb8)', 'Make a short animated video (an HTML page with CSS/canvas animation and a play button, 1920x1080, about 15 seconds) about: '],
  ['code', 'Code Editor', 'Write, debug and deploy code', 'Opens the editor', 'linear-gradient(135deg,#2b3a8f,#4f7df2)', 'code'],
  ['layout', 'Design Studio', 'UI/UX, logos and graphics', 'Designs as HTML, plus images', 'linear-gradient(135deg,#3b3b48,#8a6bd1)', 'Design a polished UI mockup as a single responsive HTML page (and make any images it needs) for: '],
  ['file', 'Document Writer', 'Docs, reports and content', 'Writes Markdown or Word files', 'linear-gradient(135deg,#3a6fe0,#8fb2ff)', 'Write a well-structured document (save it as a .docx with python-docx if available, otherwise Markdown) about: '],
  ['box', '3D Creator', '3D models and scenes', 'Built as code: a three.js scene', 'linear-gradient(135deg,#1e63c9,#38c6e8)', 'Build an interactive 3D scene with three.js (a single index.html, orbit controls, nice lighting) showing: '],
  ['zap', 'Music Studio', 'Music and sound', 'Built as code: a Tone.js player', 'linear-gradient(135deg,#4b1fa8,#c13fd6)', 'Compose a short piece of music as a web page that plays it with Tone.js (with play/stop buttons and a visualizer). The music should be: '],
  ['chart', 'Presentation Builder', 'Slides and pitch decks', 'Makes .pptx or HTML slides', 'linear-gradient(135deg,#1f4fbf,#2f8cf0)', 'Build a presentation (a .pptx with python-pptx if available, otherwise an HTML slide deck with keyboard navigation) about: '],
];
function renderStudio() {
  const grid = $('studio-grid'); if (grid.children.length) return;
  for (const [ic, title, sub, how, bg, action] of STUDIO) {
    const c = h('button', 'stool', `<div class="s-art" style="background:${bg}">${icon(ic, 40)}</div><div class="s-body"><b>${esc(title)}</b><small>${esc(sub)}</small><br><span class="how">${esc(how)}</span></div>`);
    c.onclick = () => openStudioTool(action, title);
    grid.appendChild(c);
  }
}
function openStudioTool(action, title) {
  if (action === 'image') { showPage('motion'); setMotionMode('photo'); return; }
  if (action === 'code') { showPage('home'); setHome(false); showTab('code'); mobile('code'); return; }
  const modal = h('div', 'modal', `<div class="modal-box" style="width:min(560px,100%)"><div class="page-head"><h2></h2><span class="spacer"></span><button class="btn ghost icon-only" aria-label="Close">✕</button></div><div class="studio-form"><textarea class="input" placeholder="Describe what you want…"></textarea><button class="btn primary">Start creating ${icon('arrow-right')}</button></div></div>`);
  modal.querySelector('h2').textContent = title;
  const ta = modal.querySelector('textarea');
  modal.querySelector('.btn.primary').onclick = () => { const v = ta.value.trim(); if (!v) return ta.focus(); modal.remove(); showPage('home'); send(action + v); };
  modal.onclick = e => { if (e.target === modal || e.target.closest('.icon-only')) modal.remove(); };
  document.body.appendChild(modal); ta.focus();
}

// Explore
function renderExplore() {
  const cards = $('model-cards'); cards.innerHTML = '';
  (state.models || []).filter(m => m.group === 'Bowers').forEach(m => cards.appendChild(modelCard(m, state.model, async id => { await pickModel(id); renderExplore(); })));
  const tpl = $('explore-templates');
  if (!tpl.children.length) for (const [ic, title, stack, prompt] of TEMPLATES) {
    const b = h('button', 'idea', `<span class="ic">${icon(ic, 18)}</span><span><b>${esc(title)}</b><span class="stack">${esc(stack)}</span></span>`);
    b.onclick = () => prefill(prompt); tpl.appendChild(b);
  }
  renderAppCatalog($('explore-apps'));
  const cl = $('explore-commands'); cl.innerHTML = '';
  for (const c of commands) { const b = h('button', null, `<b></b><small></small>`); b.querySelector('b').textContent = '/' + c.name; b.querySelector('small').textContent = c.description; b.onclick = () => prefill('/' + c.name + ' '); cl.appendChild(b); }
}

// Observer: checks each task's claims against what actually ran
const OBS_KIND = { unverified: 'Not verified', missed: 'Missed', broken: 'Failed step', remember: 'Worth remembering' };
function observerCard(ev) {
  const clean = !ev.findings.length;
  const card = h('div', 'obs', `<div class="obs-h"><img src="${BOWIE(clean ? 'happy' : 'curious')}" alt=""><span>Observer<small></small></span></div><ul></ul><div class="obs-acts"></div>`);
  card.querySelector('small').textContent = ev.summary;
  for (const f of ev.findings) {
    const li = h('li', null, `<span class="k ${f.kind}">${OBS_KIND[f.kind]}</span><span><span></span><small></small></span>`);
    li.querySelector('span:nth-child(2) > span').textContent = f.text;
    li.querySelector('small').textContent = f.action ? (f.kind === 'remember' ? 'Note: ' : 'Next: ') + f.action : '';
    if (f.kind === 'remember') {
      const b = h('button', 'btn ghost', 'Save note'); b.style.cssText = 'height:24px;font-size:12px;margin-left:auto;flex:none';
      b.onclick = async () => { const r = await api('/api/memory', { text: f.action || f.text }); if (r.ok) { toast('Saved to ' + (await r.json()).name); b.remove(); } else toast((await r.json()).error); };
      li.appendChild(b);
    }
    card.querySelector('ul').appendChild(li);
  }
  if (ev.fixable) {
    const acts = card.querySelector('.obs-acts');
    const fix = h('button', 'btn primary', 'Fix it'); fix.onclick = async () => { const r = await api('/api/fix', {}); if (!r.ok) toast((await r.json()).error); else fix.disabled = true; };
    acts.appendChild(fix);
  }
  return card;
}

// Replay: every step of a conversation, played back, and exported
const clipLine = (v, n = 160) => { const t = typeof v === 'string' ? v : JSON.stringify(v); return t.length > n ? t.slice(0, n) + '…' : t; };
function describeEvent(e) {
  const who = e.by ? `[${e.by}] ` : '';
  const a = Array.isArray(e.args?.items) ? `${e.args.items.filter(i => i.status === 'done').length} of ${e.args.items.length} steps done`
    : e.args && typeof e.args === 'object' ? (e.args.command || e.args.path || e.args.pattern || e.args.url || e.args.query || e.args.description || e.args) : e.args;
  switch (e.kind) {
    case 'turn_start': return ['you', '›', 'You', e.text, true];
    case 'reply': return ['', '◆', who + 'Bowers', e.text, true];
    case 'tool_call': return ['', '⚙', `${who}${e.name}  ${clipLine(a ?? '')}`, ''];
    case 'tool_result': return [e.ok ? '' : 'bad', e.ok ? '✓' : '✗', `${who}${e.name} ${e.ok ? 'done' : 'failed'}${e.ms ? ` in ${(e.ms / 1000).toFixed(1)}s` : ''}`, e.output || ''];
    case 'observer': return ['observer', '◉', 'Observer: ' + e.summary, (e.findings || []).map(f => `${OBS_KIND[f.kind]}: ${f.text}${f.action ? ' → ' + f.action : ''}`).join('\n'), true];
    case 'turn_end': return ['', '■', e.ok === false ? 'Turn stopped' : 'Turn finished', ''];
    default: return ['', '·', e.kind, ''];
  }
}
async function openReplay(id, name) {
  const r = await api('/api/sessions/events?id=' + encodeURIComponent(id)); const d = await r.json();
  if (!r.ok) return toast(d.error);
  const modal = h('div', 'modal', `<div class="modal-box" style="width:min(780px,100%)"><div class="page-head"><h2>Replay</h2><span class="spacer"></span><button class="btn" data-f="md">Markdown</button><button class="btn" data-f="html">HTML</button><button class="btn" data-f="json">JSON</button><button class="btn ghost icon-only" aria-label="Close">✕</button></div><div class="rp-meta"></div><div class="rp-list"></div><div class="rp-bar"><button class="btn" data-a="prev">◀</button><button class="btn primary" data-a="play">Play</button><button class="btn" data-a="next">▶</button><input type="range" min="0"><span class="muted"></span></div></div>`);
  const sm = d.summary;
  modal.querySelector('.rp-meta').textContent = `${name || id} · ${sm.turns} message${sm.turns === 1 ? '' : 's'} · ${sm.tool_calls} action${sm.tool_calls === 1 ? '' : 's'} · ${sm.failed} failed${sm.observer_concerns ? ` · ${sm.observer_concerns} observer notes` : ''}`;
  const list = modal.querySelector('.rp-list'), range = modal.querySelector('input'), count = modal.querySelector('.rp-bar .muted');
  const rows = d.events.map(e => {
    const [cls, ic, head, detail, prose] = describeEvent(e);
    const row = h('div', 'rp-ev ' + cls, `<div class="rp-h"><span>${esc(ic)}</span><span></span><time>${new Date(e.t * 1000).toLocaleTimeString()}</time></div>`);
    row.querySelector('.rp-h span:nth-child(2)').textContent = head; row.title = head;
    if (detail) { const b = h(prose ? 'div' : 'pre', prose ? 'txt' : null); b.textContent = detail; row.appendChild(b); }
    list.appendChild(row); return row;
  });
  if (!rows.length) list.appendChild(h('div', 'empty-state', 'This conversation was saved before Bowers kept step-by-step logs.'));
  range.max = rows.length; let timer = null;
  const show = n => { n = Math.max(0, Math.min(rows.length, n)); range.value = n; rows.forEach((row, i) => { row.classList.toggle('hidden', i >= n); row.classList.toggle('now', i === n - 1); }); count.textContent = `${n} / ${rows.length}`; rows[n - 1]?.scrollIntoView({ block: 'nearest' }); };
  const stop = () => { clearInterval(timer); timer = null; modal.querySelector('[data-a=play]').textContent = 'Play'; };
  modal.querySelector('[data-a=prev]').onclick = () => { stop(); show(+range.value - 1); };
  modal.querySelector('[data-a=next]').onclick = () => { stop(); show(+range.value + 1); };
  range.oninput = () => { stop(); show(+range.value); };
  modal.querySelector('[data-a=play]').onclick = e => {
    if (timer) return stop();
    if (+range.value >= rows.length) show(0);
    e.target.textContent = 'Pause';
    timer = setInterval(() => { if (+range.value >= rows.length) return stop(); show(+range.value + 1); }, 650);
  };
  modal.querySelectorAll('[data-f]').forEach(b => b.onclick = async () => {
    const rr = await api(`/api/sessions/export?id=${encodeURIComponent(id)}&format=${b.dataset.f}`);
    if (!rr.ok) return toast((await rr.json()).error);
    const a = document.createElement('a'); a.href = URL.createObjectURL(await rr.blob()); a.download = `bowers-${id}.${b.dataset.f}`; a.click(); setTimeout(() => URL.revokeObjectURL(a.href), 2000);
  });
  modal.onclick = e => { if (e.target === modal || e.target.closest('.icon-only')) { stop(); modal.remove(); } };
  document.body.appendChild(modal); show(rows.length);
}

// Connect apps (MCP catalog)
const APP_STATUS = { running: 'Connected', 'needs-auth': 'Sign in needed', waiting: 'Waiting for sign-in…', error: 'Problem', 'needs-approval': 'Needs approval', stopped: 'Stopped', 'not-connected': '' };
let appsBoxes = new Set();
async function renderAppCatalog(box) {
  appsBoxes.add(box);
  const r = await api('/api/mcp/apps'); if (!r.ok) { box.innerHTML = '<div class="muted">Could not load apps</div>'; return; }
  const { apps, logins } = await r.json(); box.innerHTML = '';
  // 150+ apps: search and a category filter keep it usable
  const prev = box.dataset.q || '', prevCat = box.dataset.cat || '';
  const cats = [...new Set(apps.map(a => a.category))];
  const bar = h('div', 'apps-bar', `<input class="input" type="search" placeholder="Search ${apps.length} apps…" aria-label="Search apps"><select class="input" aria-label="Category"><option value="">All categories</option>${cats.map(c => `<option>${esc(c)}</option>`).join('')}</select><small class="muted"></small>`);
  const [q, sel, count] = bar.children; q.value = prev; sel.value = prevCat;
  box.appendChild(bar);
  const grid = h('div', 'apps-grid'); box.appendChild(grid);
  const filter = () => {
    box.dataset.q = q.value; box.dataset.cat = sel.value;
    const t = q.value.trim().toLowerCase(); let n = 0;
    for (const c of grid.children) { const show = (!t || c.dataset.text.includes(t)) && (!sel.value || c.dataset.cat === sel.value); c.classList.toggle('hidden', !show); n += show; }
    count.textContent = `${n} shown`;
  };
  q.oninput = filter; sel.onchange = filter;
  for (const a of apps) {
    const st = logins[a.id]?.status === 'waiting' && a.status !== 'running' ? 'waiting' : a.status;
    const card = h('div', 'app-card', `<div class="app-top"><span class="logo">${esc(a.name[0])}</span><span><b>${esc(a.name)}</b><small>${esc(a.category)}</small></span>${APP_STATUS[st] ? `<span class="pill ${st}">${APP_STATUS[st]}</span>` : ''}</div><p>${esc(a.description)}</p><div class="acts"></div>`);
    const acts = card.querySelector('.acts');
    const btn = (label, primary, fn) => { const b = h('button', 'btn' + (primary ? ' primary' : ''), esc(label)); b.onclick = fn; acts.appendChild(b); };
    if (a.missing) acts.appendChild(h('small', 'muted', 'Needs ' + esc(a.missing)));
    else if (a.status === 'not-connected') btn('Connect', true, () => connectApp(a));
    else {
      if (a.status === 'needs-auth' && a.auth === 'github') btn('Connect GitHub first', true, () => { showPage('settings'); document.querySelector('[data-st=account]').click(); });
      else if (a.status === 'needs-auth') btn(st === 'waiting' ? 'Open sign-in again' : 'Sign in', true, () => signInApp(a.id, logins[a.id]));
      if (a.status === 'running' && a.auth === 'oauth') btn('Sign out', false, () => appAction('logout', a.id));
      btn('Remove', false, () => { if (confirm(`Disconnect ${a.name}?`)) appAction('remove', a.id); });
    }
    card.dataset.text = `${a.name} ${a.category} ${a.description}`.toLowerCase(); card.dataset.cat = a.category;
    if (a.source === 'community') {
      const tag = h('small', 'muted app-src', 'Community list' + (a.home ? ' · ' : ''));
      if (a.home) { const l = h('a', null, 'website'); l.href = a.home; l.target = '_blank'; l.rel = 'noopener'; tag.appendChild(l); }
      card.appendChild(tag);
    }
    grid.appendChild(card);
  }
  filter();
}
function refreshAppCatalog() { for (const b of appsBoxes) if (b.offsetParent) renderAppCatalog(b); }
async function appAction(action, name, extra = {}) {
  const r = await api('/api/mcp/' + action, { name, ...extra }); const d = await r.json();
  if (!r.ok) { toast(d.error); return null; }
  if (d.mcp) renderMcp(d.mcp); refreshAppCatalog(); return d;
}
async function connectApp(a) {
  const values = {};
  for (const i of a.inputs) { const v = prompt(i.label, i.default); if (v === null) return; values[i.key] = v; }
  if (a.auth === 'none' && !confirm(`Connect ${a.name}? Bowers will run it on this computer.`)) return;
  const d = await appAction('connect', a.id, { app: a.id, values }); if (!d) return;
  const now = d.apps.find(x => x.id === a.id);
  if (now?.status === 'needs-auth' && a.auth === 'oauth') signInApp(a.id);
  else if (now?.status === 'running') toast(`${a.name} connected`);
}
async function signInApp(name, pending) {
  const w = window.open('', '_blank');  // opened now so popup blockers allow it
  const url = pending?.url || (await appAction('login', name))?.url;
  if (!url) { w?.close(); return; }
  if (w) w.location = url; else toast('Allow pop-ups to sign in');
  refreshAppCatalog();
}

// Settings page
document.querySelectorAll('.set-tabs button').forEach(b => b.onclick = () => {
  document.querySelectorAll('.set-tabs button').forEach(x => x.classList.toggle('on', x === b));
  document.querySelectorAll('.set-panel').forEach(p => p.classList.toggle('hidden', p.dataset.sp !== b.dataset.st));
  if (b.dataset.st === 'account') renderAccount();
  if (b.dataset.st === 'tools') renderAppCatalog($('settings-apps'));
  if (b.dataset.st === 'voice') renderVoiceStudio();
});
async function openSettings() { $('profile-name').value = profileName; }
async function renderAccount() { renderKeys(); const card = $('account-card'); const g = await (await api('/api/git')).json().catch(() => ({})); card.replaceChildren(await accountCard(g)); }
$('profile-name').addEventListener('change', async () => { const r = await api('/api/profile', { name: $('profile-name').value }); if (r.ok) { setProfile((await r.json()).name); toast('Saved'); } });
$('run-doctor').onclick = async () => {
  const out = $('doctor-out'); out.innerHTML = '<div class="muted">Checking…</div>';
  const r = await api('/api/doctor'); if (!r.ok) return out.textContent = 'Could not run the checks';
  out.innerHTML = ''; const marks = { ok: '✓', warn: '!', fail: '✗' };
  for (const [st, what, detail] of (await r.json()).results) out.appendChild(h('div', 'doc-row ' + st, `<span>${marks[st]}</span><b>${esc(what)}</b><small>${esc(detail)}</small>`));
};
function setProfile(name) {
  profileName = name || '';
  $('me-name').textContent = profileName || 'You';
  const g = thread.querySelector('.greet h1 span'); if (g) g.textContent = `${greetWord()}${profileName ? ', ' + profileName : ''}`;
}

// Onboarding
async function onboarding() {
  const sp = $('splash'); sp.classList.remove('hidden');
  const copy = sp.querySelector('.splash-copy'), first = copy.innerHTML;
  const dots = n => `<div class="steps-dots">${[0, 1, 2].map(i => `<i class="${i <= n ? 'on' : ''}"></i>`).join('')}</div>`;
  copy.insertAdjacentHTML('afterbegin', '');
  copy.querySelector('#splash-go').onclick = async () => {
    const name = $('splash-name').value.trim();
    if (name) { await api('/api/profile', { name }); setProfile(name); }
    const st = await (await api('/api/onboarding')).json();
    copy.innerHTML = `${dots(1)}<h1 style="font-size:34px">How should Bowie think?</h1><p>Pick one now; you can add the other any time in Settings.</p><div class="brain-pick"></div>
      <button class="btn primary splash-go" id="ob-next">Next ${icon('arrow-right')}</button>`;
    copy.querySelector('.brain-pick').replaceChildren(brainChoices());
    copy.querySelector('#ob-next').onclick = () => {
      copy.innerHTML = `${dots(2)}<h1 style="font-size:34px">Choose your Bowers</h1><p>You can switch any time.</p><div class="ob-models"></div><button class="btn primary splash-go" id="ob-done">Start creating ${icon('arrow-right')}</button>`;
      const grid = copy.querySelector('.ob-models');
      const draw = () => { grid.innerHTML = ''; (state.models || []).filter(m => m.group === 'Bowers').forEach(m => grid.appendChild(modelCard(m, state.model, async id => { await pickModel(id); draw(); }))); };
      draw();
      copy.querySelector('#ob-done').onclick = () => { store.set('bowers-onboarded', '1'); sp.classList.add('hidden'); copy.innerHTML = first; if (thread.querySelector('.welcome')) welcome(); $('input').focus(); };
    };
  };
  setTimeout(() => $('splash-name').focus(), 200);
  $('splash-name').addEventListener('keydown', e => { if (e.key === 'Enter') $('splash-go').click(); });
}

// A card in the chat when an app starts running
const liveShown = new Set();
function liveCard(info) {
  if (liveShown.has(info.id)) return; liveShown.add(info.id);
  const c = h('div', 'live-card', `<span class="live-dot"></span><span style="flex:1;min-width:0"><b>Your app is live</b><small></small></span><button class="btn">Open preview</button><a class="btn ghost" target="_blank" rel="noopener">${icon('external')} New tab</a>`);
  c.querySelector('small').textContent = info.url;
  c.querySelector('a').href = info.url;
  c.querySelector('button').onclick = () => { setHome(false); appUrl = info.url; $('preview-path').value = info.url; renderApps(); showTab('preview'); mobile('preview'); };
  add(c);
}

(async () => {
  const res = await api('/api/state');
  if (res.status === 401) { $('gate').classList.remove('hidden'); return; }
  applyState(await res.json());
  try { setProfile((await (await api('/api/profile')).json()).name); } catch (e) {}
  if (!thread.children.length) welcome();
  loadRecent(); setMood('happy');
  if (store.get('bowers-onboarded', '') !== '1') onboarding();
  try { const again = sessionStorage.getItem('bowers-resume'); if (again) { sessionStorage.removeItem('bowers-resume'); api('/api/sessions/resume', { id: again }); } } catch (e) {}
  try {
    const draft = sessionStorage.getItem('docks-draft'), note = sessionStorage.getItem('docks-toast');
    if (draft !== null) { $('input').value = draft; autosize(); $('input').focus(); sessionStorage.removeItem('docks-draft'); }
    if (note) { toast(note); sessionStorage.removeItem('docks-toast'); }
  } catch (e) {}
  await loadFiles(); loadGit(); connect();
})();



// ================================================================ How Bowie thinks: free on this PC, or Claude with a key
const STORE_NAMES = { WinVaultKeyring: 'Windows Credential Manager', Keyring: 'the macOS Keychain', SecretServiceKeyring: 'your system keyring' };
const storeName = s => STORE_NAMES[s] || (s?.startsWith('a private file') ? 'a private file only you can read' : s || 'this computer');
function brainChoices() {
  const b = state.brain || {}, box = h('div', 'brain-cards');
  const local = h('div', 'brain-card' + (b.local ? ' ready' : ''), `<img src="${STICKER('chilling')}" alt=""><div><b>Free, on this computer</b>
    <small>Bowers Local: no key, no account, nothing leaves your PC. Good for everyday work; needs about 5 GB and 16 GB of memory.</small>
    <div class="brain-act"></div></div>`);
  const act = local.querySelector('.brain-act');
  if (b.local) act.innerHTML = `<span class="pill ok">Ready: ${esc((b.local_target || '').split('/').pop())}</span> <button class="btn">Use it</button>`;
  else act.innerHTML = `<button class="btn primary">Set it up</button><small class="muted"></small>`;
  act.querySelector('button').onclick = async e => {
    if (b.local) { await pickModel('local'); toast('Bowie is using Bowers Local'); return; }
    e.target.disabled = true; e.target.textContent = 'Setting up…';
    const r = await api('/api/integrations/install', { id: 'ollama', prereqs: true });
    act.querySelector('small').textContent = r.ok ? ' Installing Ollama and a free model. This can take 10 to 30 minutes; you can keep going.' : ' ' + ((await r.json()).error || 'Could not start');
  };
  const claude = h('div', 'brain-card' + (b.claude ? ' ready' : ''), `<img src="${STICKER('excited')}" alt=""><div><b>Claude, the best quality</b>
    <small>Paste your Anthropic key once. Bowers keeps it in your computer's secure store, not in a file or a chat. <a href="https://console.anthropic.com" target="_blank" rel="noopener">Get a key</a></small>
    <div class="brain-act">${b.claude ? '<span class="pill ok">Key saved</span>' : '<input class="input" type="password" placeholder="sk-ant-…" autocomplete="off" aria-label="Anthropic key"><button class="btn primary">Save key</button>'}</div><small class="muted brain-msg"></small></div>`);
  const save = claude.querySelector('button');
  if (save) save.onclick = async () => {
    const inp = claude.querySelector('input'), r = await api('/api/keys/save', { name: 'ANTHROPIC_API_KEY', value: inp.value }); const d = await r.json(); inp.value = '';
    if (!r.ok) { claude.querySelector('.brain-msg').textContent = d.error; return; }
    applyState(d.state); claude.querySelector('.brain-act').innerHTML = '<span class="pill ok">Key saved</span>';
    claude.querySelector('.brain-msg').textContent = 'Saved in ' + storeName(d.store) + '.';
    claude.classList.add('ready'); if (state.brain?.claude && (state.model === 'local')) pickModel('syntra');
  };
  const cloud = h('div', 'brain-card' + (b.cloud ? ' ready' : ''), `<img src="${STICKER('flying')}" alt=""><div><b>Bowers Cloud</b>
    <small>Sign in and go, like Claude or ChatGPT: no key and nothing to download. Uses credits from your Bowers Cloud account.</small>
    <div class="brain-act"></div><small class="muted brain-msg"></small></div>`);
  const cact = cloud.querySelector('.brain-act'), cmsg = cloud.querySelector('.brain-msg');
  const showAccount = async () => {
    const d = await (await api('/api/cloud')).json().catch(() => ({}));
    cact.innerHTML = `<span class="pill ok">Signed in${d.account ? ' · ' + esc(d.account.email) : ''}</span> <button class="btn">Sign out</button>`;
    cmsg.textContent = d.account ? `${d.account.credits} credits left (1 credit = 1 US cent of use).` : 'Signed in (the account details load when the server answers).';
    cact.querySelector('button').onclick = async () => { const r = await api('/api/cloud/logout', {}); applyState((await r.json()).state); cloud.classList.remove('ready'); drawSignIn(); };
  };
  const drawSignIn = () => {
    cact.innerHTML = '<input class="input" placeholder="Bowers Cloud address, https://…" aria-label="Bowers Cloud address"><button class="btn primary">Sign in</button>';
    const inp = cact.querySelector('input'); inp.value = store.get('bowers-cloud-url', '');
    cact.querySelector('button').onclick = async () => {
      store.set('bowers-cloud-url', inp.value.trim());
      const r = await api('/api/cloud/login', { url: inp.value.trim() }); const d = await r.json();
      if (!r.ok) { cmsg.textContent = d.error; return; }
      window.open(d.verify_url, '_blank', 'noopener');
      cmsg.innerHTML = `Confirm the code <b>${esc(d.user_code)}</b> in the page that opened (<a href="${esc(d.verify_url)}" target="_blank" rel="noopener">open it again</a>). Waiting…`;
      const tick = setInterval(async () => {
        const st = await (await api('/api/cloud')).json().catch(() => ({}));
        if (st.signed_in) { clearInterval(tick); await syncState(); cloud.classList.add('ready'); showAccount(); if (state.model === 'local') pickModel('syntra'); toast('Signed in to Bowers Cloud'); }
        else if (st.pending?.error) { clearInterval(tick); cmsg.textContent = st.pending.error; }
      }, 2000);
    };
  };
  b.cloud ? showAccount() : drawSignIn();
  box.append(cloud, local, claude); return box;
}
function openBrainSetup() {
  const modal = h('div', 'modal', `<div class="modal-box" style="width:min(640px,100%)"><div class="page-head"><h2>How should Bowie think?</h2><span class="spacer"></span><button class="btn ghost icon-only" aria-label="Close">✕</button></div></div>`);
  modal.querySelector('.modal-box').appendChild(brainChoices());
  modal.onclick = e => { if (e.target === modal || e.target.closest('.page-head .icon-only')) modal.remove(); };
  document.body.appendChild(modal);
}
function renderBrainBanner() {
  const el = document.querySelector('.brain-banner'); if (!el) return;
  const b = state.brain || {}, none = !b.claude && !b.local && !b.cloud;
  el.classList.toggle('hidden', !none);
  if (none) {
    el.innerHTML = `<img src="${STICKER('sad')}" alt=""><span><b>Bowie needs a brain to think with.</b> Sign in to Bowers Cloud, use a free one on this computer, or add a Claude key.</span><button class="btn primary">Set up</button>`;
    el.querySelector('button').onclick = openBrainSetup;
  }
}

// ================================================================ Run my business
const BUSINESS_IDEAS = ['Get 10 new customers this month', 'Make a website and a Google Business listing', "Write this week's social media posts",
  'Check my prices against competitors', 'Write a business plan for a bank loan', 'Chase my unpaid invoices'];
function openBusiness() {
  const modal = h('div', 'modal', `<div class="modal-box" style="width:min(600px,100%)"><div class="page-head"><img src="${STICKER('planning')}" alt="" style="width:44px;height:44px"><h2>Run my business</h2><span class="spacer"></span><button class="btn ghost icon-only" aria-label="Close">✕</button></div>
    <p class="muted" style="margin-top:-6px">Tell Bowie the goal. He plans it, does the research, writing, numbers and building himself, and saves everything in your project.</p>
    <div class="studio-form biz-form"><label>Your business<input class="input" id="biz-what" placeholder="e.g. Karoo Coffee Roasters, a coffee roaster in Cape Town selling to cafés"></label>
    <label>What should Bowie get done?<textarea class="input" id="biz-goal" rows="3" placeholder="e.g. Get 10 new café customers this month"></textarea></label>
    <div class="chip-row" id="biz-ideas"></div>
    <label class="img-check"><input type="checkbox" id="biz-auto" checked> Let Bowie work on his own. He still asks you before he spends money, sends a message, posts in public or deletes anything.</label>
    <div class="img-actions"><span class="spacer"></span><button class="btn primary" id="biz-go">Start ${icon('arrow-right')}</button></div></div></div>`);
  const what = modal.querySelector('#biz-what'), goal = modal.querySelector('#biz-goal');
  what.value = store.get('bowers-business', '');
  for (const idea of BUSINESS_IDEAS) { const c = h('button', 'chip', esc(idea)); c.onclick = () => { goal.value = idea; goal.focus(); }; modal.querySelector('#biz-ideas').appendChild(c); }
  modal.querySelector('#biz-go').onclick = async () => {
    const g = goal.value.trim(); if (!g) return goal.focus();
    const w = what.value.trim(); store.set('bowers-business', w);
    if (modal.querySelector('#biz-auto').checked) await setMode('auto');
    modal.remove(); showPage('home');
    send(`/business ${w ? 'My business: ' + w + '. ' : ''}Goal: ${g}`);
  };
  modal.onclick = e => { if (e.target === modal || e.target.closest('.page-head .icon-only')) modal.remove(); };
  document.body.appendChild(modal); (what.value ? goal : what).focus();
}

// ================================================================ Settings > Account: your keys, and Bowers access keys
async function renderKeys() {
  const card = $('keys-card'); if (!card) return;
  const d = await (await api('/api/keys')).json().catch(() => null); if (!d) return;
  card.innerHTML = `<div class="set-label">Your keys</div><p class="muted" style="margin:0 0 8px;font-size:12.5px">Kept in ${esc(storeName(d.store))}. Bowers never shows a saved key again or sends it anywhere except its own service.</p><div class="key-rows"></div>
    <div class="set-label" style="margin-top:14px">Bowers access keys</div><p class="muted" style="margin:0 0 8px;font-size:12.5px">Bowers' own keys (bwk_…) for letting another device or app use your Bowers Router. They unlock Bowers, not Claude.</p><div class="key-rows" id="access-rows"></div>
    <div class="key-row"><input class="input" id="access-name" placeholder="Name, e.g. My phone"><button class="btn" id="access-new">Make a key</button></div><div id="access-made"></div>`;
  const rows = card.querySelector('.key-rows');
  for (const k of d.keys) {
    const r = h('div', 'key-row', `<span><b>${esc(k.label)}</b><small>${esc(k.name)}${k.source ? ' · from ' + esc(k.source) : ''}</small></span>${k.set ? '<span class="pill ok">Set</span>' : '<input class="input" type="password" autocomplete="off" placeholder="Paste key">'}<button class="btn">${k.set ? (k.source === 'environment' ? 'In environment' : 'Remove') : 'Save'}</button>`);
    const btn = r.querySelector('button'); if (k.source === 'environment') btn.disabled = true;
    btn.onclick = async () => {
      const inp = r.querySelector('input');
      const res = await api(k.set ? '/api/keys/forget' : '/api/keys/save', k.set ? { name: k.name } : { name: k.name, value: inp.value });
      const out = await res.json(); if (!res.ok) return toast(out.error); applyState(out.state); toast(k.set ? 'Removed ' + k.name : 'Saved ' + k.name); renderKeys();
    };
    rows.appendChild(r);
  }
  const ar = card.querySelector('#access-rows');
  for (const a of d.access) { const r = h('div', 'key-row', `<span><b>${esc(a.name)}</b><small>${esc(a.id)}… · ${a.last_used ? 'used ' + ago(a.last_used) : 'never used'}</small></span><button class="btn danger">Revoke</button>`); r.querySelector('button').onclick = async () => { await api('/api/keys/access-revoke', { id: a.id }); renderKeys(); }; ar.appendChild(r); }
  card.querySelector('#access-new').onclick = async () => {
    const res = await api('/api/keys/access-new', { name: card.querySelector('#access-name').value }); const { key } = await res.json();
    await renderKeys(); const m = $('access-made');
    m.innerHTML = `<div class="key-made"><b>Copy it now: it won't be shown again.</b><code></code><button class="btn">Copy</button></div>`; m.querySelector('code').textContent = key;
    m.querySelector('button').onclick = () => { navigator.clipboard.writeText(key); toast('Copied'); };
  };
}
