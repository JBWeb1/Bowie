// Bowers web app: Bowers sections: Motion, Forge, Care, Labs, Knowledge Graph, Ctrl+K, voice and Aether.
// Plain scripts that share one global scope, loaded in order by app.html.
// ================================================================ Bowers ecosystem: Motion, Forge, Care, Labs, Aether
const STICKER = n => `/assets/bowie/${n}.webp`;
const isAether = () => state.model === 'aether';
const once = fn => { let done = false; return (...a) => { if (!done) { done = true; fn(...a); } }; };

// Bowie's activity states follow what Bowers is doing (thinking, coding, testing, exploring, creating…)
const TOOL_MOOD = { write_file: 'coding', edit_file: 'coding', read_file: 'reading', list_files: 'searching', grep: 'searching', glob: 'searching',
  web_search: 'research', web_fetch: 'research', browser: 'exploring', generate_image: 'generating', generate_video: 'animating',
  system_check: 'debugging', delegate: 'collaborating', code_intel: 'analyzing', update_plan: 'planning', start_process: 'running' };
const _handle = handle;
handle = ev => {
  _handle(ev);
  if (ev.type === 'tool_call') {
    let m = TOOL_MOOD[ev.name];
    if (ev.name === 'bash') m = /\b(test|pytest|jest|vitest|lint|check|tsc)\b/.test(ev.summary || '') ? 'analyzing' : 'coding';
    if (m) document.querySelectorAll('img.bowie-live').forEach(i => { i.src = STICKER(m); });
  }
  if (ev.type === 'idle') document.querySelectorAll('img.bowie-live').forEach(i => { i.src = STICKER('celebrating'); setTimeout(() => { i.src = BOWIE('happy'); }, 3500); });
  if (ev.type === 'motion') onMotionJob(ev);
  if (ev.type === 'integration') onIntegrationEvent(ev);
  hudEvent(ev);
};

// Aether-only things (the Knowledge Graph) show while the Bowers Aether model is chosen
const _applyState = applyState;
applyState = s => {
  _applyState(s);
  document.body.classList.toggle('is-aether', isAether());
  const brand = { motion: 'Motion', forge: 'Forge', care: 'Care', graph: 'Aether', labs: 'Labs' }[page];
  $('side-sub').textContent = brand ? ' ' + brand : '';
  if (page === 'graph' && !isAether()) showPage('home');
};

// ---------------------------------------------------------------- theme: dark / light
function currentTheme() { const t = store.get('docks-theme', 'system'); return t === 'system' ? (matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light') : t; }
function paintThemeBtn() { $('theme-btn').innerHTML = icon(currentTheme() === 'dark' ? 'sun' : 'moon', 17); $('theme-btn').title = currentTheme() === 'dark' ? 'Switch to light mode' : 'Switch to dark mode'; }
$('theme-btn').onclick = () => { const next = currentTheme() === 'dark' ? 'light' : 'dark'; store.set('docks-theme', next); applyTheme(next); $('theme').value = next; paintThemeBtn(); };
$('theme').addEventListener('change', paintThemeBtn); paintThemeBtn();

// ---------------------------------------------------------------- Bowers Motion
const MO = { mode: 'video', image: null, info: null, jobs: {} };
const MO_TEMPLATES = [
  ['Cinematic Travel', 'Turn landscapes into stories', 'linear-gradient(135deg,#f28a4a,#5b2a5e 70%,#1d1730)', 'exploring', 'Sweeping aerial drone shot over misty mountain peaks at golden hour, a lone traveler on a ridge, slow forward glide, cinematic color grade, gentle wind and distant birds', {}],
  ['Character Animation', 'Bring characters to life', 'linear-gradient(135deg,#ff9b5c,#c2462a 60%,#3a1a12)', 'animating', 'A fluffy orange mascot character waves hello and hops happily in a sunny forest clearing, Pixar-style 3D animation, soft light, cheerful music', {}],
  ['Product Showcase', 'Showcase your products', 'linear-gradient(135deg,#2c3a66,#0f1626)', 'build', 'Premium product shot: a sleek black sports car on a wet neon-lit street at night, slow orbit camera, reflections, deep bass engine hum', {}],
  ['Cinematic Portrait', 'Create stunning portraits', 'linear-gradient(135deg,#e8a06b,#6b3a2a 65%,#211510)', 'create-image', 'Close-up portrait of a woman in warm sunset light, wind in her hair, shallow depth of field, slow push-in, film grain, soft ambient music', {}],
  ['Social Short', 'Vertical clips for Reels and TikTok', 'linear-gradient(135deg,#ff5f8f,#7a2fd6)', 'share', 'Energetic vertical clip: a barista pours latte art in slow motion, then a quick cut to steam rising, upbeat lo-fi beat', { aspect: '9:16' }],
  ['Logo Reveal', 'Intros for your brand', 'linear-gradient(135deg,#ff6b2c,#2a120a)', 'inspire', 'A glowing orange logo assembles from sparks and light streaks on a dark background, camera pulls back, cinematic whoosh and impact sound', {}],
];
function moSelects() {
  const pro = $('mo-model').value === 'pro', lim = MO.info?.limits?.[pro ? 'ltx-2-5-pro' : 'ltx-2-5-fast'];
  const secs = lim ? lim.durations : [6, 8, 10], ress = lim ? lim.resolutions : ['720p', '1080p'];
  const keepS = $('mo-seconds').value || '8', keepR = $('mo-res').value || '1080p';
  $('mo-seconds').innerHTML = (pro ? '' : '<option value="auto">Auto</option>') + secs.map(s => `<option value="${s}">${s}s</option>`).join('');
  $('mo-res').innerHTML = ress.map(r => `<option value="${r}">${r === '4k' ? '4K (2160p)' : r}</option>`).join('');
  $('mo-seconds').value = [...$('mo-seconds').options].some(o => o.value === keepS) ? keepS : '8';
  $('mo-res').value = ress.includes(keepR) ? keepR : '1080p';
}
$('mo-model').onchange = moSelects;
function setMotionMode(mode) {
  MO.mode = mode;
  document.querySelectorAll('.mo-mode').forEach(b => b.classList.toggle('on', b.dataset.mode === mode));
  $('mo-video').classList.toggle('hidden', mode !== 'video'); $('mo-photo').classList.toggle('hidden', mode !== 'photo');
  if (mode === 'photo') { loadImages(); setTimeout(() => $('img-prompt')?.focus(), 50); } else $('mo-prompt').focus();
}
document.querySelectorAll('.mo-mode').forEach(b => b.onclick = () => setMotionMode(b.dataset.mode));
$('mo-create').onclick = () => { $('mo-card').scrollIntoView({ behavior: 'smooth', block: 'start' }); (MO.mode === 'video' ? $('mo-prompt') : $('img-prompt')).focus(); };
$('mo-attach').onclick = () => $('mo-file').click();
$('mo-file').onchange = () => {
  const f = $('mo-file').files[0]; if (!f) return;
  if (f.size > 5e6) return toast('Pick an image up to 5 MB');
  const rd = new FileReader(); rd.onload = () => { MO.image = rd.result; $('mo-ref').classList.remove('hidden'); $('mo-ref').querySelector('img').src = rd.result; }; rd.readAsDataURL(f);
  $('mo-file').value = '';
};
$('mo-ref-x').onclick = () => { MO.image = null; $('mo-ref').classList.add('hidden'); };
$('mo-go').onclick = async () => {
  const prompt = $('mo-prompt').value.trim(); if (!prompt) { $('mo-prompt').focus(); return toast('Describe your video first'); }
  const body = { prompt, image: MO.image || '', seconds: $('mo-seconds').value, aspect: $('mo-aspect').value, resolution: $('mo-res').value,
    pro: $('mo-model').value === 'pro', sound: $('mo-sound').value === '1' };
  $('mo-go').disabled = true;
  const r = await api('/api/motion/generate', body); const d = await r.json(); $('mo-go').disabled = false;
  if (!r.ok) return toast(d.error);
  MO.jobs[d.id] = d; renderJobs(); toast('Bowie is making your video');
};
function renderJobs() {
  const box = $('mo-jobs'); box.innerHTML = '';
  for (const j of Object.values(MO.jobs).sort((a, b) => b.started - a.started)) {
    if (j.status === 'done' && Date.now() / 1000 - j.started > 30) continue;
    const err = j.status === 'error';
    const row = h('div', 'job' + (err ? ' error' : ''), `<img src="${STICKER(err ? 'sad' : j.status === 'done' ? 'celebrating' : 'animating')}" alt=""><div style="min-width:0;flex:2"><b></b><small></small></div>${err || j.status === 'done' ? '' : '<div class="bar"><i></i></div>'}`);
    row.querySelector('b').textContent = j.prompt.slice(0, 90);
    row.querySelector('small').textContent = err ? j.error : j.status === 'done' ? 'Done! It\'s in Recent Creations.' : `${j.status}… (${Math.round(Date.now() / 1000 - j.started)}s)`;
    box.appendChild(row);
  }
}
setInterval(() => { if (page === 'motion' && Object.values(MO.jobs).some(j => !['done', 'error'].includes(j.status))) renderJobs(); }, 1000);
function onMotionJob(ev) {
  MO.jobs[ev.id] = { ...(MO.jobs[ev.id] || {}), ...ev };
  if (ev.status === 'done') { toast('Your video is ready'); alertUser('Your Bowers Motion video is ready'); if (page === 'motion') renderCreations(); }
  if (ev.status === 'error') toast(ev.error);
  if (page === 'motion') renderJobs();
}
async function renderCreations() {
  const [v, i] = await Promise.all([api('/api/motion').then(r => r.json()).catch(() => ({})), api('/api/images').then(r => r.json()).catch(() => ({}))]);
  MO.info = v; moSelects();
  for (const j of v.jobs || []) MO.jobs[j.id] = { ...(MO.jobs[j.id] || {}), ...j };
  renderJobs();
  const note = $('mo-note');
  note.classList.toggle('warn', !v.available);
  note.innerHTML = v.available ? `${icon('sparkle', 13)} Powered by LTX-2.5 with sound. Videos are saved in your project under assets/videos.`
    : `${icon('alert', 13)} To make videos, add an <b>LTX_API_KEY</b> (from ltx.io) to your environment, then restart Bowers. Photos use <b>OPENAI_API_KEY</b>.`;
  const items = [...(v.videos || []).map(x => ({ ...x, kind: 'video' })), ...(i.images || []).map(x => ({ ...x, kind: 'image' }))].sort((a, b) => b.created - a.created);
  const grid = $('mo-creations'); grid.innerHTML = '';
  for (const it of items.slice(0, 8)) {
    const c = h('div', 'cre', `${it.kind === 'video' ? '<video muted loop playsinline preload="metadata"></video>' : '<img alt="">'}<div class="cre-body"><div><b></b><small></small></div></div>`);
    const media = c.querySelector(it.kind === 'video' ? 'video' : 'img'); media.src = imgUrl(it.path);
    if (it.kind === 'video') { media.onmouseenter = () => media.play().catch(() => {}); media.onmouseleave = () => media.pause(); media.onclick = () => window.open(imgUrl(it.path)); }
    else media.onclick = () => { setMotionMode('photo'); };
    c.querySelector('b').textContent = it.prompt; c.title = it.prompt;
    c.querySelector('small').textContent = `${it.kind === 'video' ? 'Video' : 'Photo'} · ${it.kind === 'video' ? (it.seconds ? it.seconds + 's · ' : '') + (it.resolution || '') : ''} · ${ago(it.created)}`.replace(' ·  · ', ' · ');
    grid.appendChild(c);
  }
  if (!items.length) grid.appendChild(h('div', 'empty-page', `<img src="${STICKER('create-video')}" alt=""><b>Nothing here yet</b>Your videos and photos will appear here.`));
}
$('mo-all').onclick = () => showPage('library');
const moInit = once(() => {
  $('mo-photo').appendChild(document.querySelector('.img-studio'));  // the photo generator lives in Motion now
  const q = $('mo-quick');
  for (const [st, title, sub, fn] of [
    ['create-video', 'Text to Video', 'Turn text into videos', () => { setMotionMode('video'); $('mo-prompt').focus(); }],
    ['animating', 'Image to Video', 'Animate your images', () => { setMotionMode('video'); $('mo-file').click(); }],
    ['editing', 'Photo Studio', 'Create and edit photos', () => setMotionMode('photo')],
    ['designing', 'Templates', 'Start from a template', () => $('mo-templates').scrollIntoView({ behavior: 'smooth' })],
    ['love', 'Emote Maker', 'Stickers for Twitch and Discord', () => openLab('emotes')],
    ['running', 'Video Clipper', 'Long video to short clips', () => openLab('clipper')],
  ]) { const b = h('button', 'qa', `<img src="${STICKER(st)}" alt=""><span><b>${esc(title)}</b><small>${esc(sub)}</small></span>`); b.onclick = fn; q.appendChild(b); }
  const t = $('mo-templates');
  for (const [title, sub, bg, st, prompt, opts] of MO_TEMPLATES) {
    const b = h('button', 'tpl', `<div class="tpl-art" style="background:${bg}"><img class="st" src="${STICKER(st)}" alt=""><span class="play">${icon('play', 13)}</span></div><div class="tpl-body"><b>${esc(title)}</b><small>${esc(sub)}</small></div>`);
    b.onclick = () => { setMotionMode('video'); $('mo-prompt').value = prompt; if (opts.aspect) $('mo-aspect').value = opts.aspect; $('mo-card').scrollIntoView({ behavior: 'smooth' }); $('mo-prompt').focus(); };
    t.appendChild(b);
  }
});
function renderMotion() { moInit(); renderStudio(); renderCreations(); }

// ---------------------------------------------------------------- Bowers Forge
const STARTERS = [
  ['layout', 'SaaS starter', 'Next.js, auth, Stripe billing, dashboard', 'Build a SaaS starter app (like nextjs/saas-starter): Next.js App Router, Postgres with Drizzle, email/password auth, Stripe subscriptions, a pricing page and a team dashboard. Its product is: '],
  ['box', 'Online store', 'Products, cart, checkout', 'Build an online store (like yournextstore): product catalog, product pages, cart, Stripe checkout and an admin page to add products. The store sells: '],
  ['chart', 'Banking dashboard', 'Accounts, transactions, transfers', 'Build a banking dashboard web app (like adrianhajdin/banking): sign-in, linked accounts overview, transaction history with categories, charts, and money transfers (use sample data and Plaid sandbox placeholders). Theme: '],
  ['zap', 'Payments', 'Checkout with several providers', 'Add a payments layer to this project (inspired by juspay/hyperswitch): one checkout API that can route payments to Stripe or PayPal, webhooks, refunds and a payments dashboard. Details: '],
  ['smartphone', 'Mobile app', 'Expo React Native app', 'Build a mobile app with Expo (React Native) that runs on iOS and Android, with tab navigation, a polished UI and the main screens for: '],
  ['users', 'Project manager', 'Issues, boards, docs', 'Build a team project manager web app (inspired by Huly and Doable): projects, issues on a kanban board, a calendar, simple docs and comments. Focus on: '],
  ['box', '3D editor', 'three.js scene editor', 'Build a browser 3D scene editor with three.js (inspired by three-editor and PlayCanvas): add/move/rotate/scale primitives and lights with gizmos, an outliner, a properties panel, import GLB, and save/load the scene as JSON. Extra: '],
  ['sparkle', 'Animated UI kit', 'React Bits and Magic UI style', 'Build a landing page with polished animated components in the style of React Bits and Magic UI (animated gradients, marquee, number tickers, bento grid, shimmer buttons), responsive and accessible. It is for: '],
  ['chat', 'Shopping agent', 'An AI agent that sells for you', 'Build an AI shopping assistant for a store (inspired by anthropics/commerce-agents): a chat widget that searches products, answers questions, compares items and adds to cart, using the Claude API. The store sells: '],
];
async function renderForge() {
  const r = await api('/api/projects'); const d = r.ok ? await r.json() : { projects: [] };
  const grid = $('forge-projects'); grid.innerHTML = '';
  for (const p of d.projects.slice(0, 6)) {
    const c = h('button', 'pcard', `<div class="pthumb"><span class="big"></span></div><div class="pc-body"><div><b></b><small></small></div>${p.current ? '<span class="pill here">Open</span>' : ''}</div>`);
    c.querySelector('.big').textContent = p.name.slice(0, 1).toUpperCase(); c.querySelector('b').textContent = p.name;
    c.querySelector('small').textContent = `${p.files} files · ${ago(p.updated)}`;
    if (p.thumbnail) api('/api/projects/thumb?root=' + encodeURIComponent(p.root)).then(async rr => { if (rr.ok) { const img = h('img'); img.src = URL.createObjectURL(await rr.blob()); c.querySelector('.pthumb').replaceChildren(img); } });
    c.onclick = async () => { if (p.current) return openWorkspace(); if (!confirm(`Open ${p.name}?`)) return; const rr = await api('/api/projects/open', { root: p.root }); if (!rr.ok) toast((await rr.json()).error); };
    grid.appendChild(c);
  }
  $('ide-project').textContent = (state.root || '').split(/[\\/]/).pop();
  const fr = await api('/api/files'); const list = fr.ok ? (await fr.json()).files : [];
  const tree = $('ide-tree'); tree.innerHTML = '';
  for (const f of list.slice(0, 400)) { const b = h('button', null); b.textContent = f; b.title = f; b.onclick = () => ideOpen(f, b); tree.appendChild(b); }
  if (!list.length) tree.innerHTML = '<div class="muted">No files yet</div>';
  ideTab(ideCurrent);
}
async function ideOpen(path, btn) {
  document.querySelectorAll('#ide-tree button').forEach(b => b.classList.toggle('on', b === btn));
  const r = await api('/api/file?path=' + encodeURIComponent(path)); if (!r.ok) return;
  const d = await r.json(); $('ide-file').textContent = '· ' + path;
  const code = $('ide-code'); code.innerHTML = '';
  d.text.split('\n').slice(0, 3000).forEach((line, i) => { const ln = h('div', 'ln', `<i>${i + 1}</i><span></span>`); ln.lastChild.textContent = line; code.appendChild(ln); });
}
let ideCurrent = 'term', termLog = [];
function ideTab(name) {
  ideCurrent = name;
  document.querySelectorAll('.ide-tabs button').forEach(b => b.classList.toggle('on', b.dataset.it === name));
  const pane = $('ide-pane'); pane.innerHTML = '';
  if (name === 'term') {
    const t = h('div', 'term', `<pre></pre><form><input class="input" placeholder="${state.root && /\\/.test(state.root) ? 'PowerShell' : 'Shell'} command…" aria-label="Command"><button class="btn">Run</button></form>`);
    const pre = t.querySelector('pre'); const paint = () => { pre.innerHTML = termLog.map(([c, o]) => `<span class="cmd">$ ${esc(c)}</span>\n${esc(o)}`).join('\n') || '<span class="muted">Commands run in your project folder. Bowers can also run them for you.</span>'; pre.scrollTop = 1e9; };
    paint();
    t.querySelector('form').onsubmit = async e => { e.preventDefault(); const inp = t.querySelector('input'); const cmd = inp.value.trim(); if (!cmd) return; inp.value = ''; termLog.push([cmd, '…']); paint();
      const r = await api('/api/terminal', { command: cmd }); const d = await r.json(); termLog[termLog.length - 1][1] = d.output ?? d.error; paint(); };
    pane.appendChild(t); setTimeout(() => t.querySelector('input').focus(), 30);
  } else if (name === 'ai') {
    const t = h('div', 'term', `<div class="muted" style="font-family:var(--sans)">Ask Bowie to build, explain or fix something in this project.</div><form><input class="input" placeholder="e.g. Add a dark mode toggle"><button class="btn primary">Ask</button></form>`);
    t.querySelector('form').onsubmit = e => { e.preventDefault(); const v = t.querySelector('input').value.trim(); if (!v) return; openWorkspace(); send(v); };
    pane.appendChild(t);
  } else {
    const src = $('preview').getAttribute('src');
    pane.innerHTML = src ? `<iframe src="${esc(src)}" style="width:100%;height:280px;border:0;border-radius:8px;background:#fff" sandbox="allow-scripts allow-same-origin allow-forms"></iframe>` : '<div class="muted" style="font-family:var(--sans)">Run the app to see it here.</div>';
  }
}
document.querySelectorAll('.ide-tabs button').forEach(b => b.onclick = () => ideTab(b.dataset.it));
function openWorkspace(tab) { showPage('home'); setHome(false); if (tab) { showTab(tab); mobile(tab); } }
$('forge-open').onclick = () => openWorkspace('code');
$('ide-run').onclick = () => { openWorkspace('preview'); send('Start this project so I can see it in the preview (install what it needs first).'); };
$('ide-deploy').onclick = () => deploy();
$('forge-new').onclick = () => $('new-project').click();
document.querySelectorAll('[data-goto]').forEach(b => b.onclick = () => showPage(b.dataset.goto));
const forgeInit = once(() => {
  const f = $('forge-feats');
  for (const [st, title, sub, fn] of [['helping', 'AI-Powered Assistant', 'Get help with your code', () => openWorkspace()], ['collaborating', 'Collaborate', 'Work with your team on GitHub', () => openWorkspace('github')],
    ['flying', 'Deploy Instantly', 'From code to production', () => deploy()], ['reading', 'Docs & Examples', 'Learn and get started', () => showPage('explore')]]) {
    const b = h('button', 'qa', `<img src="${STICKER(st)}" alt=""><span><b>${esc(title)}</b><small>${esc(sub)}</small></span>`); b.onclick = fn; f.appendChild(b);
  }
  const s = $('forge-starters');
  for (const [ic, title, sub, prompt] of STARTERS) { const b = h('button', 'idea', `<span class="ic">${icon(ic, 18)}</span><span><b>${esc(title)}</b><span class="stack">${esc(sub)}</span></span>`); b.onclick = () => prefill(prompt); s.appendChild(b); }
});
function renderForgePage() { forgeInit(); renderForge(); }

// ---------------------------------------------------------------- Bowers Care
const CARE_PROBLEMS = [
  ['analyzing', 'My computer is slow'], ['searching', 'No internet or Wi-Fi'], ['uploading', 'My disk is full'], ['debugging', 'An app keeps crashing'],
  ['fixing', 'Updates won\'t install'], ['listening', 'No sound or a device isn\'t working'], ['running', 'Startup takes forever'], ['solving', 'I see a strange error message'],
];
const CARE_CHECKS = [['overview', 'Overview'], ['errors', 'System errors'], ['services', 'Failed services'], ['disk', 'Disk usage'], ['network', 'Network'], ['processes', 'Busy programs'], ['updates', 'Pending updates']];
const gb = n => (n / 1024 ** 3).toFixed(1) + ' GB';
function careSend(text) { showPage('home'); send(`My computer has a problem: ${text}\nFind the cause with system_check, explain it in plain words, then fix it step by step (ask me before each change).`); }
async function renderCare() {
  careInit();
  const r = await api('/api/care'); if (!r.ok) return; const s = await r.json();
  const box = $('care-stats'); box.innerHTML = '';
  const meter = (free, total) => { const used = 1 - free / total; return `<div class="meter ${used > .9 ? 'high' : used > .75 ? 'mid' : ''}"><i style="width:${Math.round(used * 100)}%"></i></div>`; };
  const stat = (label, value, extra = '') => { const c = h('div', 'stat', `<small>${esc(label)}</small><b></b>${extra}`); c.querySelector('b').textContent = value; box.appendChild(c); };
  stat('System', s.os); stat('Up for', `${s.uptime} · ${s.cpus} CPU threads`, s.load ? `<small>Load ${s.load.map(x => x.toFixed(2)).join(' · ')}</small>` : '');
  if (s.memory) stat('Memory', `${gb(s.memory.total - s.memory.free)} of ${gb(s.memory.total)} used`, meter(s.memory.free, s.memory.total));
  for (const d of s.disks) stat(`Disk ${d.mount}`, `${gb(d.free)} free of ${gb(d.total)}`, meter(d.free, d.total));
  $('care-warn').innerHTML = s.warnings.length ? `<div class="warn-list">${icon('alert', 14)} ${s.warnings.map(esc).join(' · ')} <button class="btn" id="care-warn-fix" style="margin-left:8px;height:28px">Fix this</button></div>`
    : `<div class="warn-list ok">${icon('check', 14)} No problems found in the quick check. Shell: ${esc(s.shell)}.</div>`;
  if (s.warnings.length) $('care-warn-fix').onclick = () => careSend(s.warnings.join('; '));
}
async function careCheck(sections) {
  const out = $('care-out'); out.textContent = 'Checking… (read-only)';
  const r = await api('/api/care/check', { sections }); const d = await r.json(); out.textContent = d.text || d.error;
}
const careInit = once(() => {
  const g = $('care-problems');
  for (const [st, text] of CARE_PROBLEMS) { const b = h('button', 'qa', `<img src="${STICKER(st)}" alt=""><span><b>${esc(text)}</b></span>`); b.onclick = () => careSend(text); g.appendChild(b); }
  const c = $('care-checks');
  for (const [k, label] of CARE_CHECKS) { const b = h('button', 'chip', esc(label)); b.onclick = () => careCheck([k]); c.appendChild(b); }
  $('care-fix').onclick = () => { const v = $('care-text').value.trim(); if (!v) return $('care-text').focus(); careSend(v); $('care-text').value = ''; };
  $('care-code-go').onclick = () => { const v = $('care-code').value.trim(); if (!v) return $('care-code').focus(); showPage('home');
    send(`Fix this error. Find where it comes from in this project, explain the cause, fix it, and run it again to prove it's fixed:\n\n${v}`); $('care-code').value = ''; };
  $('care-scan').onclick = () => { renderCare(); careCheck(['overview', 'errors', 'services']); };
});

// ---------------------------------------------------------------- Labs (features inspired by open-source projects)
const LABS = [
  ['trading', 'nav/trading', 'Trading Desk', 'A team of AI analysts researches a stock or crypto: fundamentals, news, technicals, bull vs bear debate, risk.', 'TradingAgents, QuantDinger'],
  ['math', 'bowie/solving', 'Math Lab', 'Solve, simplify, differentiate, integrate and plot equations step by step.', 'SymPy, nerdamer, JSXGraph'],
  ['arena', 'bowie/celebrating', 'Model Arena', 'Ask two models the same thing side by side and vote for the better answer.', 'LMArena, promptfoo'],
  ['emotes', 'bowie/love', 'Emote Maker', 'Turn an image into emotes and stickers sized for Twitch, Discord, Slack and YouTube.', 'emote-forge, emojimaker, emoteresizer'],
  ['interior', 'bowie/designing', 'Interior Restyler', 'Upload a room photo and restyle it, or virtually stage an empty home for sale.', 'AI interior restyler, Roomsmith, real-estate stager'],
  ['studio3d', 'bowie/build', '3D Studio', 'Build interactive 3D scenes, games and editors with three.js or PlayCanvas, or Blender scripts.', 'three-editor, PlayCanvas, Blender'],
  ['clipper', 'bowie/running', 'Video Clipper', 'Turn a long video into short highlight clips with captions, or a script into a storyboard.', 'AutoClip, OpenMontage, SkyReels, ArcReel'],
  ['audit', 'bowie/searching', 'Site Audit', 'Lighthouse performance, accessibility and SEO audit of a site, with fixes.', 'Lighthouse, claude-seo, Clinic.js'],
  ['ci', 'bowie/fixing', 'Local CI', 'Run this repo\'s GitHub Actions on your computer before you push.', 'nektos/act'],
  ['crawl', 'bowie/exploring', 'Web Crawler', 'Crawl a website into clean Markdown for research or a knowledge base.', 'Firecrawl'],
  ['skills', 'bowie/inspire', 'Skill Packs', 'Install skills, agents and plugins from GitHub into Bowers.', 'superpowers, awesome-claude-skills, agency-agents'],
  ['resources', 'bowie/reading', 'Free Resources', 'Free tools, self-hosted apps and programming books, curated by the community.', 'free-for-dev, awesome-selfhosted, free-programming-books'],
];
const AGENT_ART = { 'codebase-cartographer': 'analyzing', 'model-router': 'share', 'launch-film-director': 'animating', 'video-producer': 'create-video', 'emote-artist': 'love',
  'autonomous-engineer': 'flying', 'prompt-evaluator': 'celebrating', 'property-visualizer': 'designing', 'performance-auditor': 'searching', 'mobile-app-builder': 'build',
  'project-ops': 'planning', 'ui-designer': 'editing', 'workflow-architect': 'collaborating', 'rag-engineer': 'research', 'commerce-builder': 'save', 'scenario-simulator': 'discovering',
  'trading-analyst': 'analyzing', 'local-model-engineer': 'coding', 'geo-visualizer': 'exploring', 'reverse-engineer': 'debugging', 'lean-coder': 'fixing', 'tdd-engineer': 'solving',
  'growth-marketer': 'inspire', 'reality-checker': 'curious', 'math-tutor': 'reading', 'game-3d-builder': 'jumping', 'ci-runner': 'running', 'learning-guide': 'reading' };
const agentTitle = n => n.split('-').map(w => ['ci', 'ui', 'tdd', 'rag', '3d'].includes(w) ? w.toUpperCase() : w[0].toUpperCase() + w.slice(1)).join(' ');
function useAgent(a) {
  const modal = h('div', 'modal', `<div class="modal-box" style="width:min(580px,100%)"><div class="page-head"><img src="${STICKER(AGENT_ART[a.name] || 'helping')}" alt="" style="width:44px;height:44px"><h2></h2><span class="spacer"></span><button class="btn ghost icon-only" aria-label="Close">✕</button></div><p class="muted" style="margin-top:-6px"></p><div class="studio-form"><textarea class="input" placeholder="What should this agent do?"></textarea><button class="btn primary">Start ${icon('arrow-right')}</button></div></div>`);
  modal.querySelector('h2').textContent = agentTitle(a.name); modal.querySelector('p').textContent = a.description;
  const ta = modal.querySelector('textarea');
  modal.querySelector('.btn.primary').onclick = () => { const v = ta.value.trim(); if (!v) return ta.focus(); modal.remove(); showPage('home');
    send(`Hand this to your "${a.name}" helper (use delegate with agent "${a.name}"), then check its work and report back:\n\n${v}`); };
  modal.onclick = e => { if (e.target === modal || e.target.closest('.icon-only')) modal.remove(); };
  document.body.appendChild(modal); ta.focus();
}
function renderAgents() {
  const g = $('agents-grid'); g.innerHTML = '';
  const list = (state.extensions?.agents || []).slice().sort((x, y) => x.name.localeCompare(y.name));
  for (const a of list) {
    const b = h('button', 'lab', `<div class="lab-top"><img src="${STICKER(AGENT_ART[a.name] || 'helping')}" alt=""><b></b></div><p></p>`);
    b.querySelector('b').textContent = agentTitle(a.name); b.querySelector('p').textContent = a.description.replace(/\s*\(like [^)]*\)\s*$/, '');
    const src = a.description.match(/\(like ([^)]*)\)/); if (src) b.appendChild(h('span', 'src', 'Inspired by ' + esc(src[1])));
    b.onclick = () => useAgent(a); g.appendChild(b);
  }
  if (!list.length) g.appendChild(h('div', 'muted', 'No helper agents found.'));
}
function renderLabs() {
  renderAgents();
  const g = $('labs-grid'); if (g.children.length) return;
  for (const [id, art, title, text, src] of LABS) {
    const b = h('button', 'lab', `<div class="lab-top"><img src="/assets/${art}.webp" alt=""><b>${esc(title)}</b></div><p>${esc(text)}</p><span class="src">Inspired by ${esc(src)}</span>`);
    b.onclick = () => openLab(id); g.appendChild(b);
  }
}
function pickImage(cb) { const i = h('input'); i.type = 'file'; i.accept = 'image/png,image/jpeg,image/webp'; i.onchange = () => { const f = i.files[0]; if (!f) return; const r = new FileReader(); r.onload = () => cb(r.result, f.name); r.readAsDataURL(f); }; i.click(); }
function labRun(prompt) { showPage('home'); send(prompt); }
function openLab(id) {
  if (page !== 'labs') showPage('labs');
  const pane = $('lab-pane'); pane.classList.remove('hidden'); pane.innerHTML = '';
  const lab = LABS.find(l => l[0] === id); pane.appendChild(h('div', 'sec-title', `<img src="/assets/${lab[1]}.webp" alt="" style="width:34px;height:34px"><h3>${esc(lab[2])}</h3><span class="spacer"></span><button class="btn ghost icon-only" aria-label="Close">✕</button>`));
  pane.querySelector('.icon-only').onclick = () => pane.classList.add('hidden');
  const body = h('div'); pane.appendChild(body); (LAB_UI[id] || (() => {}))(body);
  pane.scrollIntoView({ behavior: 'smooth', block: 'start' });
}
const LAB_UI = {
  trading(b) {
    b.innerHTML = `<p class="muted">Research only, not financial advice. Bowers never places trades.</p><div class="row"><input class="input" id="tr-sym" placeholder="Ticker or coin, e.g. NVDA or BTC" style="max-width:260px"><select class="input" id="tr-h" style="max-width:200px"><option>next few weeks</option><option>next 6-12 months</option><option>long term (3+ years)</option></select><button class="btn primary" id="tr-go">Analyze</button></div>`;
    b.querySelector('#tr-go').onclick = () => { const s = b.querySelector('#tr-sym').value.trim(); if (!s) return;
      labRun(`Run a multi-agent trading research report on ${s} for the ${b.querySelector('#tr-h').value} (inspired by TradingAgents). Use delegate to run these analysts in parallel with web_search: 1) fundamentals (financials, valuation, earnings), 2) news and sentiment, 3) technical analysis (trend, support/resistance, momentum), 4) macro and sector. Then hold a short bull vs bear debate, then a risk manager review (position sizing ideas, what would invalidate the thesis). Finish with a clear summary table and a one-line overall view. Cite sources with dates. This is research only, not financial advice, and never place trades.`); };
  },
  math(b) {
    b.innerHTML = `<div class="row"><input class="input" id="mx" placeholder="e.g. x^2 - 5x + 6 = 0, sin(x)/x, integrate x*e^x" style="flex:1"><select class="input" id="mop" style="max-width:170px"><option value="solve">Solve</option><option value="simplify">Simplify</option><option value="diff">Differentiate</option><option value="integrate">Integrate</option><option value="factor">Factor</option><option value="expand">Expand</option><option value="plot">Plot</option></select><button class="btn primary" id="mgo">Go</button><button class="btn" id="mexp">Explain steps</button></div><div class="lab-out" id="mout"></div><canvas class="plot hidden" id="mplot"></canvas>`;
    const go = async () => { const expr = b.querySelector('#mx').value.trim(); if (!expr) return; const op = b.querySelector('#mop').value;
      const r = await api('/api/math', { expr, op }); const d = await r.json(); const out = b.querySelector('#mout');
      if (!r.ok) { out.innerHTML = `<pre>${esc(d.error)}</pre>`; return; }
      out.innerHTML = `<pre>${esc(d.text)}</pre>`; if (d.latex) { const p = h('div', 'prose'); p.innerHTML = md('$$' + d.latex + '$$'); out.appendChild(p); scheduleMath(p); }
      const cv = b.querySelector('#mplot'); cv.classList.toggle('hidden', !d.points); if (d.points) drawPlot(cv, d.points, expr); };
    b.querySelector('#mgo').onclick = go; b.querySelector('#mx').onkeydown = e => { if (e.key === 'Enter') go(); };
    b.querySelector('#mexp').onclick = () => { const v = b.querySelector('#mx').value.trim(); if (v) labRun(`Solve this step by step, explaining each step simply, and check the answer (use sympy in Python if it helps): ${v}`); };
  },
  arena(b) {
    const opts = (state.models || []).map(m => `<option value="${esc(m.id)}">${esc(m.label)}</option>`).join('');
    b.innerHTML = `<textarea class="input" id="ar-p" rows="3" placeholder="Ask both models the same question…" style="width:100%"></textarea><div class="row"><select class="input" id="ar-a" style="max-width:240px">${opts}</select><span class="muted">vs</span><select class="input" id="ar-b" style="max-width:240px">${opts}</select><button class="btn primary" id="ar-go">Battle</button><button class="btn ghost" id="ar-board">Leaderboard</button></div><div class="arena" id="ar-out"></div>`;
    const ids = (state.models || []).map(m => m.id); b.querySelector('#ar-a').value = 'syntra'; b.querySelector('#ar-b').value = ids.includes('solace') ? 'solace' : ids[1];
    b.querySelector('#ar-go').onclick = async () => { const p = b.querySelector('#ar-p').value.trim(); if (!p) return; const out = b.querySelector('#ar-out');
      out.innerHTML = `<div class="side-ans"><h4>Model A</h4>Thinking…</div><div class="side-ans"><h4>Model B</h4>Thinking…</div>`;
      const r = await api('/api/arena', { prompt: p, a: b.querySelector('#ar-a').value, b: b.querySelector('#ar-b').value }); const d = await r.json();
      if (!r.ok) { out.innerHTML = `<pre>${esc(d.error)}</pre>`; return; }
      out.innerHTML = ''; for (const [k, ans] of [['A', d.a], ['B', d.b]]) { const c = h('div', 'side-ans', `<h4>Model ${k} <span class="muted">(hidden until you vote)</span></h4><div class="prose"></div>`); c.querySelector('.prose').innerHTML = md(ans.text || ans.error || ''); out.appendChild(c); }
      const votes = h('div', 'row', ''); for (const [v, label] of [['a', 'A is better'], ['b', 'B is better'], ['tie', 'Tie']]) { const vb = h('button', 'btn', label); vb.onclick = async () => { const rr = await api('/api/arena/vote', { id: d.id, winner: v }); const vd = await rr.json(); out.querySelectorAll('h4').forEach((el, i) => { el.textContent = `Model ${i ? 'B' : 'A'}: ${i ? vd.b : vd.a}`; }); votes.replaceChildren(h('span', 'muted', 'Thanks! Vote saved.')); }; votes.appendChild(vb); }
      out.appendChild(votes); votes.style.gridColumn = '1 / -1'; };
    b.querySelector('#ar-board').onclick = async () => { const d = await (await api('/api/arena')).json(); b.querySelector('#ar-out').innerHTML = `<pre style="grid-column:1/-1">${esc(d.board.map((x, i) => `${i + 1}. ${x.model}  wins ${x.wins}  losses ${x.losses}  ties ${x.ties}`).join('\n') || 'No votes yet.')}</pre>`; };
  },
  emotes(b) {
    b.innerHTML = `<p class="muted">Pick a square-ish image (a transparent PNG works best). Bowers makes every size each platform asks for and saves them in assets/emotes.</p><div class="row"><button class="btn primary" id="em-pick">Choose image</button><button class="btn" id="em-make">Design an emote with AI</button></div><div class="emote-row" id="em-out"></div>`;
    b.querySelector('#em-pick').onclick = () => pickImage(async (data, name) => { const r = await api('/api/emotes', { image: data, name }); const d = await r.json(); const out = b.querySelector('#em-out');
      if (!r.ok) { out.textContent = d.error; return; }
      out.innerHTML = d.sizes.map(s => `<figure><img src="${imgUrl(s.path)}" width="${Math.min(s.size, 112)}" height="${Math.min(s.size, 112)}" alt=""><figcaption>${esc(s.platform)}<br>${s.size}px</figcaption></figure>`).join('') + `<div class="muted" style="width:100%">Saved in ${esc(d.folder)}</div>`; });
    b.querySelector('#em-make').onclick = () => { setMotionMode('photo'); showPage('motion'); $('img-prompt').value = 'Cute expressive emote of '; $('img-prompt').focus(); document.getElementById('img-transparent').checked = true; };
  },
  interior(b) {
    const styles = ['Scandinavian', 'Japandi', 'Modern luxury', 'Mid-century modern', 'Industrial loft', 'Bohemian', 'Coastal', 'Minimalist', 'Virtual staging (furnish an empty room)'];
    b.innerHTML = `<div class="row"><button class="btn" id="in-pick">Choose room photo</button><span class="muted" id="in-name">No photo yet</span><select class="input" id="in-style" style="max-width:280px">${styles.map(s => `<option>${s}</option>`).join('')}</select><button class="btn primary" id="in-go">Restyle</button></div><div class="emote-row" id="in-out"></div>`;
    let photo = null; b.querySelector('#in-pick').onclick = () => pickImage((d, n) => { photo = d; b.querySelector('#in-name').textContent = n; });
    b.querySelector('#in-go').onclick = async () => { if (!photo) return toast('Choose a room photo first'); const style = b.querySelector('#in-style').value; const out = b.querySelector('#in-out'); out.textContent = 'Restyling… (about a minute)';
      const up = await api('/api/upload', { data: photo, folder: 'rooms' }); const u = await up.json(); if (!up.ok) { out.textContent = u.error; return; }
      const prompt = style.startsWith('Virtual') ? 'Virtually stage this empty room for a real-estate listing: add tasteful, realistic furniture, rugs, plants and lighting. Keep walls, windows, floor and the camera angle exactly the same.'
        : `Redesign this room in ${style} interior style: new furniture, colors, textiles and decor, photorealistic. Keep the room layout, walls, windows and camera angle exactly the same.`;
      const r = await api('/api/images/generate', { prompt, edit: [u.path], quality: 'high' }); const d = await r.json();
      out.innerHTML = r.ok ? d.made.map(m => `<figure><img src="${imgUrl(m.path)}" style="max-width:100%;width:520px;height:auto;border-radius:12px" alt=""><figcaption>${esc(style)}</figcaption></figure>`).join('') : esc(d.error); };
  },
  studio3d(b) { simpleLab(b, 'Describe the 3D scene, game or tool…', v => `Build this in 3D with three.js (a single index.html, orbit controls, good lighting, responsive, 60fps). If it's an editor, include gizmos, an outliner and save/load (inspired by three-editor/PlayCanvas). If I mention Blender, also write a Blender Python (bpy) script I can run with "blender --background --python". Open it in the browser tool to check it works: ${v}`); },
  clipper(b) { simpleLab(b, 'Path to a video in this project, or a YouTube/URL, plus what clips you want…', v => `Turn this long video into short highlight clips (inspired by AutoClip/OpenMontage): use ffmpeg (install it if missing), transcribe with whisper if available, find the 3-6 most engaging moments, cut 15-60s vertical 9:16 clips with burned-in captions, and save them under assets/clips with a list of timestamps and titles. If I give a script instead of a video, write a shot-by-shot storyboard and make each shot with generate_video. Input: ${v}`); },
  audit(b) { simpleLab(b, 'Website URL (or leave empty for this project\'s running app)…', v => `Audit ${v || 'this project\'s running site'} like Lighthouse plus an SEO expert (inspired by claude-seo): run "npx lighthouse <url> --output=json --quiet --chrome-flags=--headless" if Node is available, otherwise check with the browser tool. Report performance (LCP, CLS, INP), accessibility, SEO (titles, meta, headings, structured data, sitemap, robots) and best practices, ranked by impact, then fix what you can in this project.`, true); },
  ci(b) { simpleLab(b, 'Which workflow or job? (leave empty for all)', v => `Run this repo's GitHub Actions locally with nektos/act before pushing: check act and Docker are installed (explain how to install them for my OS if not), list jobs with "act -l", run ${v || 'the push workflows'}, and fix any failures you find in the code.`, true); },
  crawl(b) { simpleLab(b, 'Website to crawl, e.g. https://docs.example.com', v => `Crawl ${v} into clean Markdown (inspired by Firecrawl): fetch the pages (respect robots.txt, stay on the same site, at most 40 pages), strip navigation and ads, save each page under knowledge/<site>/ as .md with its URL and title at the top, and write an index.md summarizing what's there.`); },
  skills(b) {
    const packs = [['obra/superpowers', 'Superpowers: TDD, debugging and planning skills'], ['ComposioHQ/awesome-claude-skills', 'Awesome Claude Skills collection'], ['msitarzewski/agency-agents', 'Agency agents: specialist helper roles'],
      ['anthropics/knowledge-work-plugins', 'Knowledge work plugins'], ['nextlevelbuilder/ui-ux-pro-max-skill', 'UI/UX Pro Max design skill'], ['AgriciDaniel/claude-seo', 'SEO skills']];
    b.innerHTML = `<p class="muted">Skills and plugins in the Claude Code format work in Bowers. Third-party packs can include commands and hooks: Bowers asks before running any hook.</p><div class="row"><input class="input" id="sk-src" placeholder="owner/repo or a git URL" style="flex:1"><button class="btn primary" id="sk-go">Install</button></div><div id="sk-list"></div><div class="lab-out" id="sk-out"></div>`;
    const list = b.querySelector('#sk-list');
    for (const [repo, label] of packs) { const r = h('div', 'mcp-row', `<span>${esc(label)}</span><small>${esc(repo)}</small>`); const btn = h('button', 'btn', 'Install'); btn.onclick = () => install(repo); r.appendChild(btn); list.appendChild(r); }
    const install = async src => { if (!confirm(`Install skills from ${src}?\n\nOnly install packs you trust.`)) return; const out = b.querySelector('#sk-out'); out.innerHTML = '<pre>Installing…</pre>';
      const r = await api('/api/skills/install', { source: src }); const d = await r.json(); out.innerHTML = `<pre>${esc(r.ok ? 'Installed: ' + (d.installed.join(', ') || 'nothing new') : d.error)}</pre>`;
      if (r.ok && d.hooks?.length) { const p = h('div', 'lab-out', `<p class="muted">This pack has hooks (commands that run automatically). They're off. Turn them on only if you trust these:</p><pre></pre>`);
        p.querySelector('pre').textContent = d.hooks.map(x => `[${x.event}${x.matcher ? ' ' + x.matcher : ''}] ${x.command}`).join('\n\n');
        const on = h('button', 'btn', 'Turn hooks on'); on.onclick = async () => { const rr = await api('/api/integrations/enable-hooks', { id: 'custom' }); if (rr.ok) { toast('Hooks on'); on.remove(); } }; p.appendChild(on); out.appendChild(p); } };
    b.querySelector('#sk-go').onclick = () => { const v = b.querySelector('#sk-src').value.trim(); if (v) install(v); };
  },
  resources(b) {
    b.innerHTML = `<p class="muted">Thousands of free things, from three community lists: free tiers for developers (free-for-dev), apps you can host yourself (awesome-selfhosted), and free programming books and courses (free-programming-books). Searchable offline.</p>
      <div class="row"><input class="input" id="rs-q" type="search" placeholder="e.g. email API, password manager, rust book, postgres hosting" style="flex:1"><select class="input" id="rs-s" style="max-width:240px"><option value="">All lists</option></select></div>
      <div id="rs-out" class="rs-out"></div><div class="row"><button class="btn" id="rs-ask">Ask Bowie to pick the best one for…</button></div>`;
    let timer = null;
    const run = async () => {
      const r = await api('/api/resources?q=' + encodeURIComponent(b.querySelector('#rs-q').value) + '&s=' + encodeURIComponent(b.querySelector('#rs-s').value));
      const d = await r.json(); const out = b.querySelector('#rs-out'); out.innerHTML = '';
      const sel = b.querySelector('#rs-s'); if (sel.options.length === 1) for (const [k, v] of Object.entries(d.sources)) sel.appendChild(new Option(v, k));
      if (!d.items.length) { out.appendChild(h('div', 'muted', 'Nothing matched. Try fewer words.')); return; }
      for (const it of d.items) {
        const row = h('div', 'mcp-row rs-row', `<a target="_blank" rel="noopener"><b></b></a><small></small>`);
        const a = row.querySelector('a'); a.href = it.url; a.querySelector('b').textContent = it.name;
        row.querySelector('small').textContent = [it.category, it.description].filter(Boolean).join(' · ');
        out.appendChild(row);
      }
    };
    b.querySelector('#rs-q').oninput = () => { clearTimeout(timer); timer = setTimeout(run, 180); };
    b.querySelector('#rs-s').onchange = run; run();
    b.querySelector('#rs-ask').onclick = () => prefill('Search the free resources (run `bowers resources <words>`) and recommend the best free or self-hosted option for ');
  },
};
function simpleLab(b, placeholder, make, optional = false) {
  b.innerHTML = `<div class="row"><input class="input" placeholder="${esc(placeholder)}" style="flex:1"><button class="btn primary">Start</button></div>`;
  const go = () => { const v = b.querySelector('input').value.trim(); if (!v && !optional) return b.querySelector('input').focus(); labRun(make(v)); };
  b.querySelector('button').onclick = go; b.querySelector('input').onkeydown = e => { if (e.key === 'Enter') go(); };
}
function drawPlot(cv, pts, label) {
  const dpr = devicePixelRatio || 1, W = cv.clientWidth, H = cv.clientHeight; cv.width = W * dpr; cv.height = H * dpr;
  const c = cv.getContext('2d'); c.scale(dpr, dpr); c.clearRect(0, 0, W, H);
  const xs = pts.map(p => p[0]), ys = pts.map(p => p[1]).filter(y => y != null && isFinite(y));
  if (!ys.length) return;
  const x0 = Math.min(...xs), x1 = Math.max(...xs); let y0 = Math.min(...ys), y1 = Math.max(...ys); if (y0 === y1) { y0 -= 1; y1 += 1; }
  const pad = 30, X = x => pad + (x - x0) / (x1 - x0) * (W - 2 * pad), Y = y => H - pad - (y - y0) / (y1 - y0) * (H - 2 * pad);
  const css = getComputedStyle(document.documentElement);
  c.strokeStyle = css.getPropertyValue('--line'); c.lineWidth = 1; c.beginPath();
  if (y0 < 0 && y1 > 0) { c.moveTo(pad, Y(0)); c.lineTo(W - pad, Y(0)); } if (x0 < 0 && x1 > 0) { c.moveTo(X(0), pad); c.lineTo(X(0), H - pad); } c.stroke();
  c.strokeStyle = css.getPropertyValue('--accent'); c.lineWidth = 2.2; c.beginPath(); let pen = false;
  for (const [x, y] of pts) { if (y == null || !isFinite(y)) { pen = false; continue; } pen ? c.lineTo(X(x), Y(y)) : c.moveTo(X(x), Y(y)); pen = true; } c.stroke();
  if (y0 < 0 && y1 > 0) for (let i = 1; i < pts.length; i++) {  // mark where it crosses zero
    const [xa, ya] = pts[i - 1], [xb, yb] = pts[i]; if (ya == null || yb == null || Math.sign(ya) === Math.sign(yb) || ya === 0) continue;
    const xr = xa - ya * (xb - xa) / (yb - ya); c.fillStyle = css.getPropertyValue('--accent'); c.beginPath(); c.arc(X(xr), Y(0), 5, 0, 7); c.fill();
    c.fillStyle = css.getPropertyValue('--fg'); c.font = '600 13px sans-serif'; c.fillText(`x = ${+xr.toFixed(3)}`, X(xr) - 22, Y(0) - 12);
  }
  c.fillStyle = css.getPropertyValue('--muted'); c.font = '12px sans-serif'; c.fillText(`y = ${label}`, pad, 18); c.fillText(`x: ${+x0.toFixed(2)} … ${+x1.toFixed(2)}`, W - 150, H - 8);
}

// ---------------------------------------------------------------- Knowledge Graph (Bowers Aether)
const KG_ICON = { you: 'users', memories: 'brain', projects: 'folder', files: 'image', tools: 'grid', knowledge: 'book', goals: 'check', motion: 'play', forge: 'code', history: 'history' };
let KG = null;
async function renderGraph() {
  const r = await api('/api/graph'); if (!r.ok) return toast('Could not load the graph'); KG = await r.json();
  drawGraph(); kgSide();
  $('kg-thinking').textContent = `Bowie is connected to ${KG.stats.connections.toLocaleString()} pieces of your work`;
}
function kgBody(n) {
  if (n.items?.length) return `<ul>${n.items.slice(0, 4).map(i => `<li>${esc(i)}</li>`).join('')}</ul>`;
  if (n.goals?.length) return `<ul>${n.goals.slice(0, 4).map(g => `<li>${g.done ? '✓ ' : ''}${esc(g.text)}</li>`).join('')}</ul>`;
  if (n.counts) return `<ul><li>${n.counts.image} images · ${n.counts.video} videos</li><li>${n.counts.doc} docs · ${n.counts.code} code files</li></ul>`;
  if (n.media?.length) return `<div class="thumbs">${n.media.slice(0, 4).map(p => /\.(mp4|webm|mov)$/i.test(p) ? `<video src="${imgUrl(p)}" muted></video>` : `<img src="${imgUrl(p)}" alt="">`).join('')}</div>`;
  return '';
}
function drawGraph() {
  const box = $('kg'); if (!KG || box.classList.contains('hidden')) return;
  box.innerHTML = `<svg aria-hidden="true"></svg><div class="kg-core"><img src="/assets/art/aether-hero.webp" alt="Bowie"><div class="lbl"><b>${esc(KG.center.title)}</b><small>${esc(KG.center.sub)}</small></div></div>`;
  const W = box.clientWidth, H = box.clientHeight, cx = W / 2, cy = H / 2, rx = W / 2 - 120, ry = H / 2 - 80;
  const svg = box.querySelector('svg'); svg.setAttribute('viewBox', `0 0 ${W} ${H}`);
  const n = KG.nodes.length; let paths = '';
  KG.nodes.forEach((node, i) => {
    const a = -Math.PI / 2 + i * 2 * Math.PI / n, x = cx + rx * Math.cos(a), y = cy + ry * Math.sin(a);
    const mx = cx + (x - cx) * .55 + Math.sin(a) * 30, my = cy + (y - cy) * .55 - Math.cos(a) * 30;
    paths += `<path d="M${cx},${cy} Q${mx},${my} ${x},${y}" stroke="url(#kgl)" stroke-width="1.6" fill="none" opacity=".85"/><circle cx="${x}" cy="${y}" r="3" fill="#ff8a4d"/><text class="kg-edge-label" x="${(cx + x) / 2 + Math.sin(a) * 18}" y="${(cy + y) / 2 - Math.cos(a) * 18}" text-anchor="middle">${esc(node.link)}</text>`;
    const el = h('button', 'kg-node', `<div class="kh"><span class="ki">${icon(KG_ICON[node.kind] || 'sparkle', 16)}</span><div style="min-width:0"><b></b><small></small></div></div>${kgBody(node)}`);
    el.querySelector('b').textContent = node.title; el.querySelector('small').textContent = node.sub;
    el.style.left = x + 'px'; el.style.top = y + 'px';
    el.onclick = () => node.page ? showPage(node.page) : node.kind === 'history' ? openDrawer('sessions') : node.kind === 'memories' || node.kind === 'you' ? showMemory() : prefill(`Using what you know about my ${node.title.toLowerCase()}, `);
    box.appendChild(el);
  });
  svg.innerHTML = `<defs><linearGradient id="kgl" x1="0" x2="1"><stop offset="0" stop-color="#ff6b2c" stop-opacity=".9"/><stop offset="1" stop-color="#ffb38a" stop-opacity=".3"/></linearGradient></defs>${paths}`;
  for (let k = 0; k < 40; k++) svg.insertAdjacentHTML('beforeend', `<circle cx="${Math.random() * W}" cy="${Math.random() * H}" r="${Math.random() * 1.4 + .3}" fill="#ff9a62" opacity="${Math.random() * .6 + .2}"/>`);
}
function kgSide() {
  const act = $('kg-actions'); act.innerHTML = '';
  for (const [ic, label, fn] of [['chat', 'Ask Bowie', () => openHud()], ['search', 'Find related files', () => openCmdk('')], ['layout', 'Show project context', () => showContext()], ['plus', 'Create new project', () => $('new-project').click()]]) {
    const b = h('button', 'qa', `${icon(ic, 16)}<span><b>${esc(label)}</b></span>`); b.style.width = '100%'; b.onclick = fn; act.appendChild(b);
  }
  $('kg-recent').innerHTML = KG.recent.map(r => `<div class="stat-row"><span>${esc(r.title)}</span><small>${ago(r.time)}</small></div>`).join('') || '<div class="muted" style="font-size:13px;margin-top:6px">Your chats will connect here.</div>';
  const s = KG.stats; $('kg-stats').innerHTML = [['Projects', s.projects], ['Files & Assets', s.files.toLocaleString()], ['Connections', s.connections.toLocaleString()], ['Last Updated', ago(s.updated)]].map(([k, v]) => `<div class="stat-row"><span>${k}</span><b>${v}</b></div>`).join('');
}
addEventListener('resize', () => { if (page === 'graph') drawGraph(); });
document.querySelectorAll('#kg-tabs button').forEach(b => b.onclick = () => {
  document.querySelectorAll('#kg-tabs button').forEach(x => x.classList.toggle('on', x === b));
  const code = b.dataset.v === 'code'; $('kg').classList.toggle('hidden', code); $('kg-code').classList.toggle('hidden', !code);
  if (code) codeMap(); else drawGraph();
});
let CM = null;
function codeMap() {
  if (!KG) return; const cv = $('kg-canvas'), W = cv.clientWidth, H = cv.clientHeight, dpr = devicePixelRatio || 1; cv.width = W * dpr; cv.height = H * dpr;
  const nodes = KG.code.nodes.map((n, i) => ({ ...n, x: W / 2 + Math.cos(i * 2.4) * (40 + 6 * i), y: H / 2 + Math.sin(i * 2.4) * (40 + 6 * i), vx: 0, vy: 0 }));
  if (!nodes.length) { const c2 = cv.getContext('2d'); c2.setTransform(dpr, 0, 0, dpr, 0, 0); c2.clearRect(0, 0, W, H); c2.fillStyle = '#b8aca3'; c2.font = '14px sans-serif'; c2.fillText('No code files yet: the map appears as Bowers writes code.', 24, 40); return; }
  const idx = Object.fromEntries(nodes.map((n, i) => [n.id, i])); const edges = KG.code.edges.map(([a, b]) => [idx[a], idx[b]]).filter(([a, b]) => a != null && b != null);
  const groups = [...new Set(nodes.map(n => n.group))], hue = g => (groups.indexOf(g) * 67 + 18) % 360;
  CM = { nodes, edges, scale: 1, ox: 0, oy: 0, hover: null, tick: 0 };
  const ctx = cv.getContext('2d');
  const step = () => {
    if (!CM || CM.nodes !== nodes) return;
    if (CM.tick++ < 260) {
      for (let i = 0; i < nodes.length; i++) for (let j = i + 1; j < nodes.length; j++) {
        const a = nodes[i], b = nodes[j]; let dx = a.x - b.x, dy = a.y - b.y, d2 = Math.max(dx * dx + dy * dy, 100); const f = 140 / d2;
        a.vx += dx * f; a.vy += dy * f; b.vx -= dx * f; b.vy -= dy * f; }
      for (const [i, j] of edges) { const a = nodes[i], b = nodes[j], dx = b.x - a.x, dy = b.y - a.y; a.vx += dx * .012; a.vy += dy * .012; b.vx -= dx * .012; b.vy -= dy * .012; }
      for (const n of nodes) { n.vx += (W / 2 - n.x) * .004; n.vy += (H / 2 - n.y) * .004; const sp = Math.hypot(n.vx, n.vy); if (sp > 8) { n.vx *= 8 / sp; n.vy *= 8 / sp; }
        n.x = Math.min(W - 20, Math.max(20, n.x + n.vx)); n.y = Math.min(H - 20, Math.max(20, n.y + n.vy)); n.vx *= .82; n.vy *= .82; }
    }
    ctx.setTransform(dpr * CM.scale, 0, 0, dpr * CM.scale, dpr * CM.ox, dpr * CM.oy); ctx.clearRect(-1e4, -1e4, 3e4, 3e4);
    ctx.strokeStyle = 'rgba(255,140,80,.22)'; ctx.lineWidth = 1 / CM.scale; ctx.beginPath();
    for (const [i, j] of edges) { ctx.moveTo(nodes[i].x, nodes[i].y); ctx.lineTo(nodes[j].x, nodes[j].y); } ctx.stroke();
    for (const n of nodes) { ctx.fillStyle = `hsl(${hue(n.group)} 80% 62%)`; ctx.beginPath(); ctx.arc(n.x, n.y, 3 + Math.min(9, n.degree), 0, 7); ctx.fill(); }
    ctx.fillStyle = '#e9ddd3'; ctx.font = `${11 / CM.scale}px sans-serif`;
    for (const n of nodes) if (n.degree > 4 || n === CM.hover) ctx.fillText(n.id.split('/').pop(), n.x + 8, n.y + 3);
    requestAnimationFrame(step);
  };
  step();
  const at = e => { const r = cv.getBoundingClientRect(), x = (e.clientX - r.left - CM.ox) / CM.scale, y = (e.clientY - r.top - CM.oy) / CM.scale; return nodes.find(n => (n.x - x) ** 2 + (n.y - y) ** 2 < 120); };
  let drag = null;
  cv.onmousedown = e => { drag = { x: e.clientX, y: e.clientY, ox: CM.ox, oy: CM.oy, moved: false }; };
  cv.onmousemove = e => { if (drag) { CM.ox = drag.ox + e.clientX - drag.x; CM.oy = drag.oy + e.clientY - drag.y; drag.moved = true; } else { CM.hover = at(e); cv.title = CM.hover ? `${CM.hover.id} (${CM.hover.degree} links)` : ''; } };
  cv.onmouseup = e => { if (drag && !drag.moved) { const n = at(e); if (n) { showPage('forge'); setTimeout(() => ideOpen(n.id), 300); } } drag = null; };
  cv.onwheel = e => { e.preventDefault(); const k = e.deltaY < 0 ? 1.12 : 1 / 1.12; const r = cv.getBoundingClientRect(), mx = e.clientX - r.left, my = e.clientY - r.top; CM.ox = mx - (mx - CM.ox) * k; CM.oy = my - (my - CM.oy) * k; CM.scale *= k; };
}

// ---------------------------------------------------------------- Ctrl+K command palette
let cmdkItems = [], cmdkSel = 0, cmdkProjects = null;
function cmdkActions() {
  const a = [
    ['create-video', 'Create a video', 'Motion', () => { showPage('motion'); setMotionMode('video'); }],
    ['create-image', 'Create an image', 'Motion', () => { showPage('motion'); setMotionMode('photo'); }],
    ['coding', 'Open Bowers Forge', 'Forge', () => showPage('forge')],
    ['fixing', 'Fix my computer', 'Care', () => showPage('care')],
    ['debugging', 'Fix a code error', 'Care', () => { showPage('care'); setTimeout(() => $('care-code').focus(), 200); }],
    ['flying', 'Deploy to production', 'Deploy', () => deploy()],
    ['planning', 'New project', 'Projects', () => $('new-project').click()],
    ['reading', 'Go to library', 'Library', () => showPage('library')],
    ['inspire', 'Open Labs', 'Labs', () => showPage('labs')],
    ['uploading', 'Install integrations', 'Integrations', () => showPage('integrations')],
    ['hello', 'New chat', 'Chat', () => { showPage('home'); newChat(); }],
    ['listening', 'Talk to Bowers Aether', 'Aether', () => openHud()],
    ['discovering', 'Knowledge Graph', 'Aether', () => { if (!isAether()) return toast('Switch to Bowers Aether to use the Knowledge Graph'); showPage('graph'); }],
    ['chilling', 'Toggle dark / light mode', 'Theme', () => $('theme-btn').click()],
    ['analyzing', 'Choose a model', 'Model', () => openModelPicker()],
    ['helping', 'Settings', 'Settings', () => showPage('settings')],
  ];
  for (const [id, , title] of LABS) a.push(['inspire', title, 'Labs', () => openLab(id)]);
  for (const ag of state.extensions?.agents || []) a.push([AGENT_ART[ag.name] || 'helping', agentTitle(ag.name) + ' agent', 'Agent', () => useAgent(ag)]);
  for (const p of cmdkProjects || []) a.push(['projects', 'Open project: ' + p.name, 'Projects', async () => { if (p.current) return; const r = await api('/api/projects/open', { root: p.root }); if (!r.ok) toast((await r.json()).error); }]);
  for (const f of (files || []).slice(0, 3000)) a.push(['searching', f, 'File', () => { showPage('forge'); setTimeout(() => ideOpen(f), 300); }]);
  return a;
}
function openCmdk(q = '') {
  $('cmdk').classList.remove('hidden'); $('cmdk-input').value = q; renderCmdk(); $('cmdk-input').focus();
  if (!cmdkProjects) api('/api/projects').then(r => r.json()).then(d => { cmdkProjects = d.projects; renderCmdk(); }).catch(() => {});
}
function closeCmdk() { $('cmdk').classList.add('hidden'); }
function renderCmdk() {
  const q = $('cmdk-input').value.toLowerCase().trim();
  const all = cmdkActions();
  cmdkItems = (q ? all.filter(([, t, tag]) => (t + ' ' + tag).toLowerCase().includes(q)) : all.filter(x => x[2] !== 'File')).slice(0, 40);
  cmdkSel = Math.min(cmdkSel, Math.max(0, cmdkItems.length - 1));
  const list = $('cmdk-list'); list.innerHTML = '';
  cmdkItems.forEach(([st, title, tag, fn], i) => { const b = h('button', 'cmdk-item' + (i === cmdkSel ? ' on' : ''), `<img src="${STICKER(st === 'projects' ? 'planning' : st)}" alt=""><span></span><span class="tag">${esc(tag)}</span>`); b.querySelector('span').textContent = title; b.onclick = () => { closeCmdk(); fn(); }; list.appendChild(b); });
  if (!cmdkItems.length) list.appendChild(h('div', 'muted', '<div style="padding:14px">Nothing found. Press Enter to ask Bowie.</div>'));
}
$('cmdk-input').oninput = () => { cmdkSel = 0; renderCmdk(); };
$('cmdk-input').onkeydown = e => {
  if (e.key === 'ArrowDown' || e.key === 'ArrowUp') { e.preventDefault(); cmdkSel = (cmdkSel + (e.key === 'ArrowDown' ? 1 : -1) + cmdkItems.length) % Math.max(1, cmdkItems.length); renderCmdk(); $('cmdk-list').children[cmdkSel]?.scrollIntoView({ block: 'nearest' }); }
  else if (e.key === 'Enter') { e.preventDefault(); const it = cmdkItems[cmdkSel]; closeCmdk(); if (it) it[3](); else if ($('cmdk-input').value.trim()) { showPage('home'); send($('cmdk-input').value.trim()); } }
  else if (e.key === 'Escape') closeCmdk();
};
$('cmdk').onclick = e => { if (e.target.id === 'cmdk') closeCmdk(); };
$('top-search').onclick = () => openCmdk();
document.addEventListener('keydown', e => { if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'k') { e.preventDefault(); $('cmdk').classList.contains('hidden') ? openCmdk() : closeCmdk(); } });

// ---------------------------------------------------------------- Bowie's voice (voice studio)
const VOICE = { get engine() { return store.get('bowie-voice-engine', '') || (voiceInfo?.local ? 'local' : 'browser'); }, get name() { return store.get('bowie-voice-name', ''); },
  get pitch() { return +store.get('bowie-voice-pitch', '1.35'); }, get rate() { return +store.get('bowie-voice-rate', '1.05'); }, get eleven() { return store.get('bowie-voice-eleven', ''); },
  get local() { return store.get('bowie-voice-local', 'am_puck'); }, get localSpeed() { return +store.get('bowie-voice-local-speed', '1'); } };
let voiceAudio = null, voiceInfo = null;
async function loadVoiceInfo() { try { voiceInfo = await (await api('/api/voice')).json(); } catch (e) { voiceInfo = { available: false, voices: [] }; } return voiceInfo; }
function playVoice(blob, onEnd) { voiceAudio = new Audio(URL.createObjectURL(blob)); voiceAudio.onended = () => onEnd?.(); voiceAudio.play().catch(() => onEnd?.()); }
function speakable(text) { return text.replace(/```[\s\S]*?```/g, ' (code on screen) ').replace(/`([^`]+)`/g, '$1').replace(/\[([^\]]+)\]\([^)]+\)/g, '$1').replace(/[#*_>|~-]{1,3}/g, ' ').replace(/\s+/g, ' ').trim().slice(0, 1200); }
async function speak(text, onEnd) {
  text = speakable(text); if (!text) { onEnd?.(); return; }
  stopSpeaking();
  if (VOICE.engine === 'local') {
    const r = await api('/api/voice/speak', { text, engine: 'local', voice: VOICE.local, speed: VOICE.localSpeed });
    if (r.ok) return playVoice(await r.blob(), onEnd);
    toast((await r.json()).error + ' (using the built-in voice)');
  } else if (VOICE.engine === 'eleven' && VOICE.eleven) {
    const r = await api('/api/voice/speak', { text, voice: VOICE.eleven });
    if (r.ok) return playVoice(await r.blob(), onEnd);
    toast((await r.json()).error + ' (using the built-in voice)');
  }
  if (!('speechSynthesis' in window)) { onEnd?.(); return; }
  const u = new SpeechSynthesisUtterance(text); const v = speechSynthesis.getVoices().find(x => x.name === VOICE.name) || bowieDefaultVoice();
  if (v) u.voice = v; u.pitch = VOICE.pitch; u.rate = VOICE.rate; u.onend = () => onEnd?.(); u.onerror = () => onEnd?.(); speechSynthesis.speak(u);
}
function stopSpeaking() { try { speechSynthesis.cancel(); } catch (e) {} if (voiceAudio) { voiceAudio.pause(); voiceAudio = null; } }
function bowieDefaultVoice() {  // a bright, friendly voice in the page's language
  const vs = speechSynthesis.getVoices(), lang = (navigator.language || 'en').slice(0, 2);
  return vs.find(v => /aria|jenny|samantha|google us english|zira|ava|karen/i.test(v.name) && v.lang.startsWith(lang)) || vs.find(v => v.lang.startsWith(lang)) || vs[0];
}
async function renderVoiceStudio() {
  const p = document.querySelector('[data-sp="voice"]'); if (!p) return;
  const vs = ('speechSynthesis' in window) ? speechSynthesis.getVoices() : [];
  const ev = await loadVoiceInfo();
  p.innerHTML = `<div class="set-card"><div class="voice-hero"><img src="${STICKER('listening')}" alt=""><div><b>Bowie's voice</b><br><small class="muted">Used by Bowers Aether voice mode and "Read aloud". Pick a voice that suits Bowie: small, warm and friendly.</small></div></div>
    <label>Voice engine<select class="input" id="vs-engine"><option value="browser">Built-in browser voice (free)</option><option value="local" ${ev.local ? '' : 'disabled'}>Kokoro on this computer (free, offline, natural)${ev.local ? '' : ' (install in Integrations)'}</option><option value="eleven" ${ev.available ? '' : 'disabled'}>ElevenLabs ${ev.available ? '' : '(add ELEVENLABS_API_KEY)'}</option></select></label>
    <div id="vs-local" class="hidden"><label>Kokoro voice<select class="input" id="vs-lv">${(ev.local_voices || []).map(v => `<option value="${esc(v.id)}" ${v.id === VOICE.local ? 'selected' : ''}>${esc(v.name)}</option>`).join('')}</select></label>
      <div class="voice-row"><label>Speed <input type="range" id="vs-lspeed" min="0.7" max="1.4" step="0.05" value="${VOICE.localSpeed}"></label></div>
      <small class="muted">Runs on your computer with the open Kokoro model. Nothing you say leaves this machine.</small></div>
    <div id="vs-browser"><label>Voice<select class="input" id="vs-name"><option value="">Bowie's pick</option>${vs.map(v => `<option ${v.name === VOICE.name ? 'selected' : ''}>${esc(v.name)}</option>`).join('')}</select></label>
      <div class="voice-row"><label>Pitch <input type="range" id="vs-pitch" min="0.6" max="2" step="0.05" value="${VOICE.pitch}"></label><label>Speed <input type="range" id="vs-rate" min="0.6" max="1.6" step="0.05" value="${VOICE.rate}"></label></div></div>
    <div id="vs-eleven" class="hidden"><label>ElevenLabs voice<select class="input" id="vs-el">${(ev.voices || []).map(v => `<option value="${esc(v.id)}" ${v.id === VOICE.eleven ? 'selected' : ''}>${esc(v.name)}${v.category ? ' (' + esc(v.category) + ')' : ''}</option>`).join('') || '<option value="">No voices found</option>'}</select></label>
      <small class="muted">${ev.error ? esc(ev.error) : 'Tip: in ElevenLabs Voice Design, describe "a small, cheerful, fluffy orange mascot with a warm, slightly high, playful voice", save it, and pick it here.'}</small></div>
    <div class="voice-row"><button class="btn primary" id="vs-test">${icon('play', 13)} Hear Bowie</button><button class="btn ghost" id="vs-stop">Stop</button></div></div>`;
  const engine = p.querySelector('#vs-engine'); engine.value = (VOICE.engine === 'eleven' && !ev.available) || (VOICE.engine === 'local' && !ev.local) ? 'browser' : VOICE.engine;
  const sync = () => { for (const k of ['browser', 'local', 'eleven']) p.querySelector('#vs-' + k).classList.toggle('hidden', engine.value !== k); };
  engine.onchange = () => { store.set('bowie-voice-engine', engine.value); sync(); }; sync();
  p.querySelector('#vs-name').onchange = e => store.set('bowie-voice-name', e.target.value);
  p.querySelector('#vs-pitch').oninput = e => store.set('bowie-voice-pitch', e.target.value);
  p.querySelector('#vs-rate').oninput = e => store.set('bowie-voice-rate', e.target.value);
  p.querySelector('#vs-el').onchange = e => store.set('bowie-voice-eleven', e.target.value);
  p.querySelector('#vs-lv').onchange = e => store.set('bowie-voice-local', e.target.value);
  p.querySelector('#vs-lspeed').oninput = e => store.set('bowie-voice-local-speed', e.target.value);
  if (ev.available && !VOICE.eleven && ev.voices?.[0]) store.set('bowie-voice-eleven', ev.voices[0].id);
  p.querySelector('#vs-test').onclick = () => speak(`Hi${profileName ? ' ' + profileName : ''}! I'm Bowie. I can build apps, make videos, fix your computer, and remember what matters to you.`);
  p.querySelector('#vs-stop').onclick = stopSpeaking;
}
loadVoiceInfo();
if ('speechSynthesis' in window) speechSynthesis.onvoiceschanged = () => { if (document.querySelector('[data-sp="voice"]:not(.hidden)')) renderVoiceStudio(); };

// ---------------------------------------------------------------- Bowers Aether: voice assistant (Jarvis-style)
const HUD = { open: false, listening: false, rec: null, hands: false, muted: store.get('hud-muted', '0') === '1', reply: {}, last: null, waiting: false };
function hudStatus(text) { $('hud-status').textContent = text; }
function hudLine(text, cls = '') { const l = h('div', 'hl ' + cls); l.textContent = text; $('hud-log').appendChild(l); while ($('hud-log').children.length > 30) $('hud-log').firstChild.remove(); l.scrollIntoView({ block: 'end' }); return l; }
async function openHud() {
  if (!isAether() && !(await pickModel('aether'))) return;
  if (!voiceInfo) loadVoiceInfo();
  HUD.open = true; $('hud').classList.remove('hidden');
  $('hud-bowie').src = '/assets/art/aether-hero.webp';
  if (!$('hud-chips').children.length) for (const [label, prompt] of [["What's next?", 'Looking at this project and what we did recently, what should I do next? Give me the top three.'],
    ['Check my computer', 'Check my computer\'s health with system_check and tell me if anything needs attention.'], ['Make a video', null],
    ['Summarize my week', 'Summarize what I worked on this week from our recent conversations and the git history.']]) {
    const b = h('button', null, esc(label)); b.onclick = () => prompt ? hudAsk(prompt, label) : (closeHud(), showPage('motion')); $('hud-chips').appendChild(b); }
  $('hud-mute').textContent = HUD.muted ? '🔇' : '🔊';
  hudStatus(`${greetWord()}${profileName ? ', ' + profileName : ''}. Tap the mic and talk to me, or type below.`);
  $('hud-input').focus();
}
function closeHud() { HUD.open = false; $('hud').classList.add('hidden'); stopListening(); stopSpeaking(); HUD.hands = false; $('hud-hands').checked = false; }
async function hudAsk(text, shown) {
  if (!text.trim()) return;
  hudLine(shown || text, 'you'); hudStatus('Thinking…'); $('hud-bowie').src = '/assets/aether/thinking.webp'; HUD.waiting = true; HUD.reply = {};
  const r = await api('/api/chat', { message: text, voice: true });
  if (!r.ok) { hudStatus((await r.json()).error); HUD.waiting = false; }
}
function hudEvent(ev) {
  if (!HUD.open || !HUD.waiting) return;
  if (ev.type === 'tool_call') { hudLine('· ' + (ev.summary || ev.name), 'step'); hudStatus('Working on it…'); $('hud-bowie').src = '/assets/aether/focused.webp'; }
  if (ev.type === 'text') { HUD.reply[ev.id] = (HUD.reply[ev.id] || '') + ev.text; HUD.last = ev.id; }
  if (ev.type === 'approval') hudStatus('I need your OK in the chat window for that step.');
  if (ev.type === 'idle') {
    HUD.waiting = false; const text = HUD.last ? HUD.reply[HUD.last] : '';
    $('hud-bowie').src = '/assets/aether/celebrating.webp';
    if (text) hudLine(text);
    hudStatus(text ? 'Done.' : 'Done. Details are in the chat.');
    if (text && !HUD.muted) { $('hud').classList.add('speaking'); speak(text, () => { $('hud').classList.remove('speaking'); if (HUD.hands) startListening(true); }); }
    else if (HUD.hands) startListening(true);
    setTimeout(() => { if (!HUD.waiting) $('hud-bowie').src = '/assets/art/aether-hero.webp'; }, 4000);
  }
}
function startListening(handsFree = false) {
  const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
  if (!SR) { if (voiceInfo?.stt && navigator.mediaDevices && window.MediaRecorder) return recordAndTranscribe(); hudStatus('Voice input needs Chrome or Edge, or the faster-whisper integration. You can still type.'); return; }
  stopSpeaking(); stopListening();
  const rec = new SR(); HUD.rec = rec; rec.lang = navigator.language || 'en-US'; rec.interimResults = true; rec.continuous = handsFree;
  let finalText = '';
  rec.onstart = () => { HUD.listening = true; $('hud').classList.add('listening'); hudStatus(handsFree ? 'Listening for "Hey Bowie"…' : 'Listening…'); };
  rec.onresult = e => {
    let interim = ''; for (let i = e.resultIndex; i < e.results.length; i++) { const t = e.results[i][0].transcript; e.results[i].isFinal ? finalText += t : interim += t; }
    if (!handsFree) { hudStatus(interim || finalText || 'Listening…'); return; }
    const said = (finalText + ' ' + interim).toLowerCase(); const m = said.match(/(?:hey |hi |ok )?bowie[,.!]?\s+(.+)/);
    if (m && finalText) { const cmd = finalText.replace(/^.*?bowie[,.!]?\s*/i, ''); finalText = ''; if (cmd.trim()) { stopListening(); hudAsk(cmd); } }
  };
  rec.onerror = e => { if (e.error !== 'no-speech' && e.error !== 'aborted') hudStatus('Microphone: ' + e.error); };
  rec.onend = () => { HUD.listening = false; $('hud').classList.remove('listening'); if (!handsFree && finalText.trim()) hudAsk(finalText.trim()); else if (handsFree && HUD.hands && !HUD.waiting) setTimeout(() => startListening(true), 300); };
  try { rec.start(); } catch (e) { hudStatus('Could not start the microphone'); }
}
async function recordAndTranscribe() {  // faster-whisper on this computer: tap the mic to start, tap again to send
  stopSpeaking();
  let stream; try { stream = await navigator.mediaDevices.getUserMedia({ audio: true }); } catch (e) { hudStatus('Microphone: ' + e.message); return; }
  const chunks = [], mr = new MediaRecorder(stream);
  HUD.rec = { stop: () => mr.state !== 'inactive' && mr.stop() }; HUD.listening = true; $('hud').classList.add('listening'); hudStatus('Listening… tap the mic when you\'re done.');
  const limit = setTimeout(() => HUD.rec?.stop(), 30000);
  mr.ondataavailable = e => e.data.size && chunks.push(e.data);
  mr.onstop = async () => {
    clearTimeout(limit); stream.getTracks().forEach(t => t.stop()); HUD.listening = false; $('hud').classList.remove('listening');
    if (!chunks.length || !HUD.open) return;
    hudStatus('Understanding…');
    const blob = new Blob(chunks, { type: mr.mimeType || 'audio/webm' });
    const audio = await new Promise(res => { const fr = new FileReader(); fr.onload = () => res(fr.result); fr.readAsDataURL(blob); });
    const r = await api('/api/voice/transcribe', { audio }); const d = await r.json();
    if (!r.ok) return hudStatus(d.error); if (d.text) hudAsk(d.text); else hudStatus("I didn't catch that. Try again?");
  };
  mr.start();
}
function stopListening() { if (HUD.rec) { const r = HUD.rec; HUD.rec = null; r.onend = null; try { r.stop(); } catch (e) {} } HUD.listening = false; $('hud').classList.remove('listening'); }
$('hud-mic').onclick = () => HUD.listening ? stopListening() : startListening(false);
$('hud-send').onclick = () => { const v = $('hud-input').value; $('hud-input').value = ''; hudAsk(v); };
$('hud-input').onkeydown = e => { if (e.key === 'Enter') $('hud-send').click(); if (e.key === 'Escape') closeHud(); };
$('hud-close').onclick = closeHud;
$('hud-mute').onclick = () => { HUD.muted = !HUD.muted; store.set('hud-muted', HUD.muted ? '1' : '0'); $('hud-mute').textContent = HUD.muted ? '🔇' : '🔊'; if (HUD.muted) stopSpeaking(); };
$('hud-hands').onchange = e => { HUD.hands = e.target.checked; if (HUD.hands) startListening(true); else stopListening(); };
$('hud-brief').onclick = () => hudAsk("Give me a short spoken briefing: what's going on in this project (git status and recent work), any open pull requests, any computer health warnings (system_check overview), and what you suggest I do next.", 'Brief me');
$('hud-graph').onclick = () => { closeHud(); showPage('graph'); };
$('side-aether').onclick = () => openHud(); $('top-aether').onclick = () => openHud();

// deep links from the installed app's shortcuts (#motion, #forge, #care)
addEventListener('load', () => { const want = location.hash.slice(1); if (['motion', 'forge', 'care', 'labs'].includes(want)) setTimeout(() => showPage(want), 400); });
if ('serviceWorker' in navigator && location.protocol === 'http:' && /^(127\.0\.0\.1|localhost)$/.test(location.hostname)) navigator.serviceWorker.register('/sw.js').catch(() => {});


const syncState = () => api('/api/state').then(r => r.json()).then(applyState).catch(() => {});
