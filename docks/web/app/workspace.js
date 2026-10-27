// Bowers web app: The side panel: preview, code, GitHub, images, and the animated background.
// Plain scripts that share one global scope, loaded in order by app.html.
// ---------------------------------------------------------------- side panel
let currentTab = 'preview';
function showTab(name) {
  currentTab = name;
  document.querySelectorAll('.tab[data-tab]').forEach(t => t.classList.toggle('on', t.dataset.tab === name));
  if (name === 'images') { showPage('motion'); setMotionMode('photo'); return; }
  for (const v of ['preview', 'code', 'github', 'terminal']) $('view-' + v).classList.toggle('hidden', v !== name);
  if (name === 'preview') reloadPreview(); if (name === 'github') loadGit(); if (name === 'terminal') panelTerminal();
}
document.querySelectorAll('.tab[data-tab]').forEach(t => t.onclick = () => showTab(t.dataset.tab));
function mobile(which) {
  if (which === 'more') { $('more-sheet').classList.remove('hidden'); return; }
  $('more-sheet').classList.add('hidden');
  if (which === 'history') { openDrawer('sessions'); return; }
  if (PAGES.includes(which)) { showPage(which); return; }
  if (page !== 'home') showPage('home');
  $('app').classList.toggle('show-panel', which !== 'chat');
  if (which !== 'chat') { setHome(false); showTab(which); } else if (thread.querySelector('.welcome')) setHome(true);
}
document.querySelectorAll('.sheet-grid button').forEach(b => b.onclick = () => mobile(b.dataset.m));
$('more-sheet').onclick = e => { if (e.target.id === 'more-sheet') $('more-sheet').classList.add('hidden'); };

let files = [], changed = new Set(), previewPicked = false;
function refreshAll() { loadFiles(); loadGit(); if (currentTab === 'preview') reloadPreview(); }

async function loadFiles() {
  const res = await api('/api/files'); if (!res.ok) return;
  files = (await res.json()).files; renderTree(); autoPreview();
}
function renderTree() {
  const tree = $('tree'); tree.innerHTML = '';
  if (!files.length) { tree.innerHTML = `<div class="empty-state" style="padding:16px">No files yet</div>`; return; }
  let prev = [];
  for (const f of files) {
    const parts = f.split('/'), dirs = parts.slice(0, -1);
    dirs.forEach((d, i) => { if (prev[i] !== d) { prev = prev.slice(0, i); const r = h('div', 'row dir', `${icon('folder', 15)}<span>${esc(d)}</span>`); r.style.paddingLeft = (8 + i * 14) + 'px'; tree.appendChild(r); } });
    prev = dirs;
    const r = h('div', 'row' + (f === openPath ? ' sel' : ''), `${icon('file', 15)}<span>${esc(parts.at(-1))}</span>${changed.has(f) ? '<span class="m">M</span>' : ''}`);
    r.style.paddingLeft = (8 + dirs.length * 14) + 'px'; r.title = f; r.onclick = () => openFile(f);
    tree.appendChild(r);
  }
}
let openPath = null;
async function openFile(path, silent) {
  const res = await api('/api/file?path=' + encodeURIComponent(path)); if (!res.ok) return;
  const { text } = await res.json();
  openPath = path; $('file-name').textContent = path;
  const lines = $('lines'); lines.innerHTML = '';
  const frag = document.createDocumentFragment();
  for (const l of text.split('\n')) { const d = h('div'); d.textContent = l || ' '; frag.appendChild(d); }
  lines.appendChild(frag);
  renderTree();
  if (!silent) { showTab('code'); mobile('code'); }
}

// Preview shows either a project file (static) or a running app (dev server started by Bowers).
let processes = {}, appUrl = null;
function previewUrl() {
  if (appUrl) return appUrl.replace('localhost', location.hostname);
  const p = state.preview || {}; return `${location.protocol}//${location.hostname}:${p.port}${p.prefix || '/'}${$('preview-path').value.replace(/^\/+/, '')}`;
}
function onProcess(info) {
  processes[info.id] = info;
  if (info.url && info.running && appUrl !== info.url) { appUrl = info.url; $('preview-path').value = info.url; showTab('preview'); }
  if (!info.running && appUrl === info.url) { appUrl = null; $('preview-path').value = ''; autoPreview(); }
  renderApps(); reloadPreview();
}
function renderApps() {
  $('live-badge').classList.toggle('hidden', !Object.values(processes).some(p => p.running && p.url));
  const box = $('apps'); box.innerHTML = '';
  for (const p of Object.values(processes)) {
    if (!p.running || !p.url) continue;
    const pill = h('div', 'app-pill' + (appUrl === p.url ? ' on' : ''), `<span class="live"></span><span></span><button class="x" title="Stop this app" aria-label="Stop">${icon('stop', 12)}</button>`);
    pill.children[1].textContent = p.url.replace(/^https?:\/\//, '').replace(/\/$/, '');
    pill.onclick = e => { if (e.target.closest('.x')) return; appUrl = p.url; $('preview-path').value = p.url; renderApps(); reloadPreview(); };
    pill.querySelector('.x').onclick = () => api('/api/process/stop', { id: p.id });
    box.appendChild(pill);
  }
}
function autoPreview() {
  if (previewPicked || appUrl) return;
  const html = files.filter(f => /\.html?$/i.test(f));
  const pick = ['index.html', 'public/index.html', 'dist/index.html', 'src/index.html'].find(f => html.includes(f)) || html[0];
  if (pick && $('preview-path').value !== pick) { $('preview-path').value = pick; if (currentTab === 'preview') reloadPreview(); }
}
function reloadPreview() {
  const path = $('preview-path').value.trim();
  const has = !!appUrl || (path && files.includes(path.replace(/^\/+/, '')));
  $('preview').classList.toggle('hidden', !has); $('preview-empty').classList.toggle('hidden', has);
  if (has && state.preview) $('preview').src = previewUrl();
}
$('preview-reload').onclick = reloadPreview;
$('preview-path').addEventListener('keydown', e => {
  if (e.key !== 'Enter') return;
  const v = $('preview-path').value.trim();
  appUrl = /^https?:\/\//.test(v) ? v : null; previewPicked = !appUrl; renderApps(); reloadPreview();
});
$('preview-open').onclick = () => { if (state.preview) window.open(previewUrl(), '_blank', 'noopener'); };
$('dev-desktop').onclick = () => { $('stage').classList.remove('phone'); $('dev-desktop').classList.add('on'); $('dev-phone').classList.remove('on'); };
$('dev-phone').onclick = () => { $('stage').classList.add('phone'); $('dev-phone').classList.add('on'); $('dev-desktop').classList.remove('on'); };

// ---------------------------------------------------------------- Images
const IMG = { model: 'fast', size: 'square', n: 1, edit: [], images: [], loaded: false };
const STYLES = [['Photo', 'photorealistic, natural light, shallow depth of field'], ['Illustration', 'clean digital illustration, soft shading'],
  ['3D', '3D render, soft studio lighting, subtle shadows'], ['Icon', 'flat vector icon, simple shapes, centered, no text'],
  ['Watercolor', 'watercolor painting, gentle textures'], ['Pixel art', 'pixel art, limited palette, crisp edges']];
const imgUrl = path => { const p = state.preview || {}; return `${location.protocol}//${location.hostname}:${p.port}${p.prefix || '/'}${path.split('/').map(encodeURIComponent).join('/')}`; };
function segment(id, key) {
  $(id).querySelectorAll('button').forEach(b => b.onclick = () => { IMG[key] = b.dataset.v; $(id).querySelectorAll('button').forEach(x => x.classList.toggle('on', x === b)); });
}
segment('img-model', 'model'); segment('img-size', 'size');
$('img-styles').innerHTML = STYLES.map(([n]) => `<button class="chip" data-s="${esc(n)}">${esc(n)}</button>`).join('');
$('img-styles').querySelectorAll('button').forEach(b => b.onclick = () => {
  const style = STYLES.find(x => x[0] === b.dataset.s)[1], t = $('img-prompt');
  t.value = t.value.trim() ? `${t.value.trim().replace(/[.,]$/, '')}, ${style}` : ''; if (!t.value) { t.placeholder = `Describe it… (${style})`; IMG.style = style; }
  t.focus();
});
const setN = n => { IMG.n = Math.max(1, Math.min(4, n)); $('img-n').textContent = IMG.n; };
$('img-less').onclick = () => setN(IMG.n - 1); $('img-more').onclick = () => setN(IMG.n + 1);
function renderEditSource() {
  const box = $('img-edit'); box.classList.toggle('hidden', !IMG.edit.length); box.innerHTML = '';
  if (!IMG.edit.length) return;
  box.appendChild(h('span', 'muted', 'Editing'));
  for (const path of IMG.edit) { const im = h('img'); im.src = imgUrl(path); im.alt = path; box.appendChild(im); }
  const x = h('button', 'btn ghost', 'Start fresh'); x.onclick = () => { IMG.edit = []; renderEditSource(); }; box.appendChild(x);
  $('img-prompt').placeholder = 'What should change? e.g. make the sky purple, add a cat on the counter…';
}
async function loadImages() {
  const r = await api('/api/images'); if (!r.ok) return;
  const d = await r.json(); IMG.images = d.images; IMG.available = d.available;
  $('img-go').disabled = !d.available;
  $('img-hint').innerHTML = d.available ? 'Saved in your project under <code>assets/generated</code>' : 'Needs <code>OPENAI_API_KEY</code> in your environment';
  renderGallery();
}
function renderGallery(pending = 0) {
  const grid = $('img-grid'); grid.innerHTML = '';
  for (let i = 0; i < pending; i++) grid.appendChild(h('div', 'img-card shimmer', `<div class="img-wait"><span data-icon="sparkle"></span>Creating…</div>`));
  if (!pending && !IMG.images.length) {
    grid.appendChild(h('div', 'img-empty', IMG.available === false
      ? `<b>Connect OpenAI to make images</b><p>Add <code>OPENAI_API_KEY</code> to your environment, then restart Bowers.</p>`
      : `<b>Your images show up here</b><p>Describe one above, or ask Bowers in the chat: “make a hero image for the landing page”.</p>`));
  }
  for (const im of IMG.images) {
    const card = h('figure', 'img-card', `<img loading="lazy" alt=""><figcaption></figcaption><div class="img-tools"></div>`);
    const img = card.querySelector('img'); img.src = imgUrl(im.path) + '?v=' + Math.round(im.created); img.alt = im.prompt;
    img.onload = () => card.classList.add('ready'); img.onclick = () => openLightbox(im);
    card.querySelector('figcaption').textContent = im.prompt;
    const tools = card.querySelector('.img-tools');
    for (const [label, fn] of imageActions(im)) { const b = h('button', null, esc(label)); b.onclick = e => { e.stopPropagation(); fn(); }; tools.appendChild(b); }
    grid.appendChild(card);
  }
  hydrateIcons(grid);
}
function imageActions(im) {
  return [
    ['Use in chat', () => { const t = $('input'); t.value = `${t.value}${t.value && !t.value.endsWith(' ') ? ' ' : ''}@${im.path} `; autosize(); mobile('chat'); t.focus(); closeLightbox(); }],
    ['Edit', () => { IMG.edit = [im.path]; renderEditSource(); closeLightbox(); $('img-prompt').focus(); }],
    ['Download', () => { const a = h('a'); a.href = imgUrl(im.path); a.download = im.path.split('/').pop(); a.click(); }],
    ['Delete', async () => { if (!confirm(`Delete ${im.path}?`)) return; const r = await api('/api/images/delete', { path: im.path, delete_file: true }); if (r.ok) { IMG.images = (await r.json()).images; renderGallery(); closeLightbox(); } }],
  ];
}
function openLightbox(im) {
  const lb = $('lightbox'); lb.querySelector('img').src = imgUrl(im.path) + '?v=' + Math.round(im.created);
  lb.querySelector('.lb-prompt').textContent = im.prompt; lb.querySelector('.lb-path').textContent = im.path;
  const acts = lb.querySelector('.lb-actions'); acts.innerHTML = '';
  for (const [label, fn] of imageActions(im)) { const b = h('button', 'btn' + (label === 'Use in chat' ? ' primary' : ''), esc(label)); b.onclick = fn; acts.appendChild(b); }
  lb.classList.remove('hidden'); requestAnimationFrame(() => lb.classList.add('open'));
}
function closeLightbox() { const lb = $('lightbox'); lb.classList.remove('open'); setTimeout(() => lb.classList.add('hidden'), 180); }
$('lightbox').onclick = e => { if (e.target.id === 'lightbox' || e.target.closest('.lb-close')) closeLightbox(); };
document.addEventListener('keydown', e => { if (e.key === 'Escape' && !$('lightbox').classList.contains('hidden')) closeLightbox(); });
$('img-prompt').addEventListener('keydown', e => { if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) $('img-go').click(); });
$('img-go').onclick = async () => {
  let prompt = $('img-prompt').value.trim();
  if (!prompt) { $('img-prompt').focus(); return toast('Describe the image first'); }
  if (IMG.style && !prompt.includes(IMG.style)) prompt += ', ' + IMG.style;
  const btn = $('img-go'); btn.disabled = true; btn.classList.add('working'); btn.lastChild.textContent = 'Creating…';
  renderGallery(IMG.n);
  const r = await api('/api/images/generate', { prompt, size: IMG.size, quality: $('img-quality').value, n: IMG.n,
    background: $('img-transparent').checked ? 'transparent' : 'auto', detailed: IMG.model === 'detailed', edit: IMG.edit });
  btn.disabled = false; btn.classList.remove('working'); btn.lastChild.textContent = 'Generate';
  const d = await r.json();
  if (!r.ok) { toast(d.error); renderGallery(); return; }
  IMG.images = d.images; IMG.style = ''; renderGallery(); toast(`Saved ${d.made.map(m => m.path.split('/').pop()).join(', ')}`);
  alertUser('Your image is ready');
};

// ---------------------------------------------------------------- GitHub account, repos, PRs, context repos
async function accountCard(g) {
  const r = await api('/api/github/account'); const a = r.ok ? await r.json() : {};
  const c = h('div', 'card');
  if (a.account) {
    c.innerHTML = `<h3>${icon('github')} Your GitHub account</h3><div class="repo-line"><b></b><span class="pill">via ${esc(a.account.source || 'docks')}</span><button class="btn ghost">Sign out</button></div>`;
    c.querySelector('b').textContent = a.account.login;
    c.querySelector('button').onclick = async () => { await api('/api/github/logout', {}); loadGit(); };
    if (a.account.source !== 'docks') c.querySelector('button').remove();
    return c;
  }
  c.innerHTML = `<h3>${icon('github')} Connect GitHub</h3><p>Give Bowers access to your repositories: browse branches, track pull requests, fix issues and review code.</p>
    <div class="row gh-device"><button class="btn primary">Sign in with GitHub</button></div>
    <p class="muted" style="margin:10px 0 6px">Or paste a personal access token (<a target="_blank" rel="noopener" href="${esc((a.web || 'https://github.com') + '/settings/tokens')}">create one</a>: scopes repo, read:org, workflow). It stays on this computer.</p>
    <div class="row"><input class="input" type="password" autocomplete="off" placeholder="ghp_… or github_pat_…"><button class="btn">Connect</button></div>`;
  const device = c.querySelector('.gh-device button');
  if (!a.device_login) { device.disabled = true; device.title = 'Needs DOCKS_GITHUB_CLIENT_ID (see the README); use a token for now'; }
  device.onclick = async () => {
    const rr = await api('/api/github/login', {}); const j = await rr.json();
    if (!rr.ok) return toast(j.error);
    c.querySelector('.gh-device').innerHTML = `<p>Open <a target="_blank" rel="noopener" href="${esc(j.login.verification_uri)}">${esc(j.login.verification_uri)}</a> and enter <b class="code"></b>. Waiting for you to approve…</p>`;
    c.querySelector('.code').textContent = j.login.user_code;
    window.open(j.login.verification_uri, '_blank', 'noopener');
  };
  const tok = c.querySelector('input[type=password]');
  c.querySelectorAll('.row')[1].querySelector('button').onclick = async () => {
    if (!tok.value.trim()) return;
    const rr = await api('/api/github/login', { token: tok.value.trim() }); tok.value = '';
    if (rr.ok) { toast('Connected as ' + (await rr.json()).account.login); loadGit(); } else toast((await rr.json()).error);
  };
  return c;
}
function branchesCard() {
  const c = h('div', 'card', `<h3>${icon('pr')} Branches</h3><div class="muted">Loading…</div>`);
  api('/api/github/branches').then(async r => {
    const d = await r.json(); const body = c.querySelector('.muted'); body.remove();
    if (!r.ok) return c.appendChild(h('p', null, esc(d.error)));
    const list = h('div', 'gh-list');
    for (const b of d.branches) {
      const row = h('div', 'gh-row', `<span></span>${b.name === d.default ? '<span class="pill">default</span>' : ''}${b.protected ? '<span class="pill">protected</span>' : ''}<span class="spacer"></span>`);
      row.querySelector('span').textContent = b.name;
      if (b.name === d.current) row.appendChild(h('span', 'pill ok', 'checked out'));
      else { const sw = h('button', 'btn ghost', 'Switch'); sw.onclick = async () => { const rr = await api('/api/github/switch', { branch: b.name }); if (rr.ok) { toast('Switched to ' + b.name); refreshAll(); } else toast((await rr.json()).error); }; row.appendChild(sw); }
      list.appendChild(row);
    }
    c.appendChild(list);
  });
  return c;
}
const CHECK = { success: ['✓', 'ok'], failure: ['✗', 'bad'], pending: ['●', 'wait'], none: ['·', ''] };
function prsCard(g) {
  const c = h('div', 'card', `<h3>${icon('pr')} Pull requests</h3><div class="muted">Loading…</div>`);
  api('/api/github/prs').then(async r => {
    const d = await r.json(); c.querySelector('.muted').remove();
    if (!r.ok) return c.appendChild(h('p', null, esc(d.error)));
    const watched = new Set(d.watched.map(w => `${w.repo}#${w.number}`));
    const row = (p, showRepo) => {
      const key = `${p.repo}#${p.number}`, [mark, cls] = CHECK[p.checks || 'none'];
      const el = h('div', 'gh-row', `<span class="chk ${cls}" title="checks: ${esc(p.checks || 'unknown')}">${mark}</span><a target="_blank" rel="noopener"></a><small></small><span class="spacer"></span>`);
      el.querySelector('a').href = p.url; el.querySelector('a').textContent = `${showRepo ? p.repo : ''}#${p.number} ${p.title}`;
      el.querySelector('small').textContent = [p.author, p.draft ? 'draft' : ''].filter(Boolean).join(' · ');
      const w = h('button', 'btn ghost', watched.has(key) ? 'Watching' : 'Watch');
      w.title = 'Get told when checks finish, reviews come in, or it is merged';
      w.onclick = async () => { const on = !watched.has(key); const rr = await api('/api/github/watch', { repo: p.repo, number: p.number, on }); if (rr.ok) { on ? watched.add(key) : watched.delete(key); w.textContent = on ? 'Watching' : 'Watch'; toast(on ? `Watching ${key}` : `Stopped watching ${key}`); } };
      el.appendChild(w);
      if (p.repo === g.repo) { const rv = h('button', 'btn ghost', 'Review'); rv.onclick = async () => { const rr = await api('/api/github', { action: 'review', number: p.number }); if (rr.ok) { mobile('chat'); toast('Bowers is reviewing it'); } }; el.appendChild(rv); }
      return el;
    };
    const section = (title, items, showRepo) => { c.appendChild(h('div', 'gh-sub', esc(title))); if (!items.length) c.appendChild(h('div', 'muted', 'None')); items.forEach(p => c.appendChild(row(p, showRepo))); };
    section(`Open in ${g.repo}`, d.here, false);
    section('Yours, everywhere', d.mine.authored, true);
    section('Waiting for your review', d.mine.review_requested, true);
  });
  return c;
}
function reposCard() {
  const c = h('div', 'card', `<h3>${icon('github')} Your repositories</h3><div class="row"><input class="input" placeholder="Search your repositories"></div><div class="gh-list"></div>`);
  const list = c.querySelector('.gh-list'), input = c.querySelector('input');
  const load = async () => {
    list.innerHTML = '<div class="muted">Loading…</div>';
    const r = await api('/api/github/repos?q=' + encodeURIComponent(input.value.trim())); const d = await r.json(); list.innerHTML = '';
    if (!r.ok) return list.appendChild(h('p', null, esc(d.error)));
    for (const repo of d.repos.slice(0, 40)) {
      const el = h('div', 'gh-row', `<a target="_blank" rel="noopener"></a>${repo.private ? '<span class="pill">private</span>' : ''}<small></small><span class="spacer"></span>`);
      el.querySelector('a').href = repo.url; el.querySelector('a').textContent = repo.repo; el.querySelector('small').textContent = repo.description.slice(0, 80);
      const add = h('button', 'btn ghost', 'Use as context'); add.title = 'Let Bowers read this repository while it works here';
      add.onclick = async () => { add.disabled = true; add.textContent = 'Adding…'; const rr = await api('/api/context-repos', { action: 'add', repo: repo.repo }); if (rr.ok) { toast('Added ' + repo.repo); loadGit(); } else { toast((await rr.json()).error); add.disabled = false; add.textContent = 'Use as context'; } };
      const copy = h('button', 'btn ghost', 'Clone'); copy.title = 'Copy the command that clones it and opens Bowers there';
      copy.onclick = () => navigator.clipboard?.writeText(`bowers clone ${repo.repo}`).then(() => toast('Copied: bowers clone ' + repo.repo));
      el.append(add, copy); list.appendChild(el);
    }
  };
  let t; input.addEventListener('input', () => { clearTimeout(t); t = setTimeout(load, 400); });
  load();
  return c;
}
function contextCard() {
  const c = h('div', 'card', `<h3>${icon('book')} Context repositories</h3><p>Other repositories Bowers can read while it works here, like files in a Claude Project. They stay in sync and Bowers never edits them.</p><div class="gh-list"></div><div class="row"><input class="input" placeholder="owner/repo"><button class="btn">Add</button><button class="btn ghost">Sync now</button></div>`);
  const list = c.querySelector('.gh-list');
  const render = repos => {
    list.innerHTML = '';
    if (!repos.length) list.appendChild(h('div', 'muted', 'None yet.'));
    for (const r of repos) {
      const el = h('div', 'gh-row', `<b></b><small></small><span class="spacer"></span>`);
      el.querySelector('b').textContent = r.repo + (r.branch ? ' @' + r.branch : ''); el.querySelector('small').textContent = r.present ? 'synced' : 'downloading…';
      const rm = h('button', 'btn ghost', 'Remove'); rm.onclick = async () => { const rr = await api('/api/context-repos', { action: 'remove', repo: r.repo }); if (rr.ok) render((await rr.json()).repos); };
      el.appendChild(rm); list.appendChild(el);
    }
  };
  api('/api/context-repos').then(async r => r.ok && render((await r.json()).repos));
  const [addBtn, syncBtn] = c.querySelectorAll('.row button');
  addBtn.onclick = async () => { const v = c.querySelector('.row input').value.trim(); if (!v) return; addBtn.disabled = true; const rr = await api('/api/context-repos', { action: 'add', repo: v }); addBtn.disabled = false; if (rr.ok) { c.querySelector('.row input').value = ''; render((await rr.json()).repos); toast('Added ' + v); } else toast((await rr.json()).error); };
  syncBtn.onclick = async () => { syncBtn.disabled = true; const rr = await api('/api/context-repos', { action: 'sync' }); syncBtn.disabled = false; if (rr.ok) { render((await rr.json()).repos); toast('Synced'); } };
  return c;
}

// ---------------------------------------------------------------- GitHub
async function loadGit() {
  const res = await api('/api/git'); if (!res.ok) return;
  const g = await res.json();
  changed = new Set(g.changes.map(c => c.path));
  $('changes-badge').textContent = g.changes.length; $('changes-badge').classList.toggle('hidden', !g.changes.length);
  $('branch-chip').innerHTML = g.branch ? `${icon('pr', 12)} ${esc(g.branch)}` : ''; $('branch-chip').classList.toggle('hidden', !g.branch);
  renderTree();
  if (currentTab !== 'github') return;  // the cards below talk to GitHub: only build them when they're shown
  const gh = $('gh'); gh.innerHTML = '';

  const repoCard = h('div', 'card');
  repoCard.innerHTML = `<h3>${icon('github')} Repository</h3><div class="repo-line">${g.repo ? `<b>${esc(g.repo)}</b>` : g.is_repo ? '<span>Local git repository (no GitHub remote)</span>' : '<span>Not a git repository</span>'}${g.branch ? `<span class="pill">${icon('pr', 12)} ${esc(g.branch)}</span>` : ''}${g.connected ? `<span class="pill ok">Connected</span>` : `<span class="pill off">Not connected</span>`}</div>`;
  gh.appendChild(repoCard);
  gh.appendChild(await accountCard(g));
  if (g.connected) {
    if (g.repo) { gh.appendChild(branchesCard()); gh.appendChild(prsCard(g)); }
    gh.appendChild(reposCard()); gh.appendChild(contextCard());
  }

  if (!g.is_repo) {
    const c = h('div', 'card', `<h3>${icon('github')} Start from a GitHub repo</h3><p>Clone a repository into this empty folder and start working on it.</p><div class="row"><input class="input" id="clone-repo" placeholder="owner/repo or https://github.com/…"><button class="btn primary" id="clone-go">Clone</button></div>`);
    gh.appendChild(c);
    c.querySelector('#clone-go').onclick = async () => {
      const btn = c.querySelector('#clone-go'); btn.disabled = true; btn.textContent = 'Cloning…';
      const r = await api('/api/clone', { repo: c.querySelector('#clone-repo').value });
      if (!r.ok) { toast((await r.json()).error); btn.disabled = false; btn.textContent = 'Clone'; } else refreshAll();
    };
    return;
  }

  const action = (ic, title, desc, placeholder, act) => {
    const c = h('div', 'card', `<h3>${icon(ic)} ${esc(title)}</h3><p>${esc(desc)}</p><div class="row">${placeholder ? `<input class="input" type="number" min="1" placeholder="${esc(placeholder)}">` : ''}<button class="btn primary">${esc(title.split(' ')[0])}</button></div>`);
    c.querySelector('button').onclick = async () => {
      const n = placeholder ? parseInt(c.querySelector('input').value, 10) : undefined;
      if (placeholder && !(n > 0)) { toast('Enter a number first'); return; }
      const r = await api('/api/github', { action: act, number: n });
      if (r.ok) { mobile('chat'); toast('Bowers is on it'); } else toast((await r.json()).error);
    };
    c.querySelector('input')?.addEventListener('keydown', e => { if (e.key === 'Enter') c.querySelector('button').click(); });
    if (!g.repo || !g.connected) c.querySelectorAll('button,input').forEach(x => x.disabled = true);
    return c;
  };
  gh.appendChild(action('issue', 'Fix an issue', 'Bowers reads the issue, makes the fix on a new branch, runs the tests and opens a pull request.', 'Issue #', 'fix'));
  gh.appendChild(action('review', 'Review a pull request', 'Bowers reads the changes and posts a review with comments on the exact lines.', 'Pull request #', 'review'));
  gh.appendChild(action('pr', 'Open a pull request', 'Bowers commits the current changes on a branch and opens a pull request that explains them.', null, 'pr'));

  const bot = h('div', 'card', `<h3>${icon('sparkle')} @docks on GitHub</h3><p>Let anyone with write access mention <b>@docks</b> in an issue or pull request, like with Claude Code and Codex. Bowers runs in GitHub Actions and replies in the thread.</p>${files.includes('.github/workflows/docks.yml') ? `<span class="pill ok">Installed</span><p style="margin:10px 0 0">Add your <code>ANTHROPIC_API_KEY</code> as a repo secret, allow Actions to create pull requests (Settings → Actions → General), then commit and push the workflow.</p>` : '<button class="btn primary">Add to this repo</button>'}`);
  bot.querySelector('button')?.addEventListener('click', async () => { const r = await api('/api/install-github', {}); if (r.ok) { toast('Workflow added'); refreshAll(); } else toast('Could not add the workflow'); });
  gh.appendChild(bot);

  const ch = h('div', 'card', `<h3>${icon('code')} Changes <span class="pill">${g.changes.length}</span></h3>`);
  if (!g.changes.length) ch.appendChild(h('p', null, 'No uncommitted changes.'));
  else {
    const list = h('div', 'changes');
    const LABEL = { '??': 'new', A: 'new', M: 'changed', D: 'deleted', R: 'renamed' };
    for (const c of g.changes) { const r = h('div', null, `<b style="width:62px">${esc(LABEL[c.status] || c.status)}</b><span></span>`); r.querySelector('span').textContent = c.path; list.appendChild(r); }
    ch.appendChild(list);
    if (g.diff) { const d = unifiedDiff(g.diff); d.style.marginTop = '10px'; ch.appendChild(d); }
  }
  gh.appendChild(ch);
}

// ---------------------------------------------------------------- animated background
// Lines of code drift upward in three depth layers; some type themselves out. Soft colored glows move behind.
const Background = (() => {
  const canvas = $('bg'), ctx = canvas.getContext('2d');
  const SNIPPETS = [
    "const app = createApp({ name: 'docks' })", "export default function App() {", "  const [todos, setTodos] = useState([])",
    "return <Layout title=\"Dashboard\">", "async function deploy(site) {", "  await build({ minify: true })",
    "def create_app():", "    app = FastAPI(title=\"api\")", "@app.get(\"/items/{id}\")", "    return {\"ok\": True}",
    "git commit -m \"feat: ship it\"", "npm run dev  # localhost:5173", "SELECT * FROM users WHERE active = 1;",
    "<div className=\"grid gap-4 md:grid-cols-3\">", "fetch('/api/chat', { method: 'POST' })", "for (const f of files) render(f)",
    "class Agent:", "    def run(self, task):", "        while not done: step()", "// TODO: make it beautiful",
    "body { display: grid; place-items: center; }", "if (score > best) save(score)", "await page.goto(previewUrl)",
    "pip install docks", "bowers fix 42", "export const config = { runtime: 'edge' }", "router.post('/login', auth)",
    "const ws = new WebSocket(url)", "useEffect(() => subscribe(), [])", "tests: 128 passed in 2.4s",
  ];
  const KW = /^(const|let|var|function|return|export|default|import|from|async|await|def|class|if|else|for|while|of|in|new|SELECT|FROM|WHERE|not)$/;
  let colors = {}, lines = [], orbs = [], w = 0, hgt = 0, dpr = 1, last = 0, raf = 0, enabled = true;
  const reduced = matchMedia('(prefers-reduced-motion: reduce)');

  function readColors() {
    const cs = getComputedStyle(document.documentElement), v = n => cs.getPropertyValue(n).trim();
    const dark = matchMedia('(prefers-color-scheme: dark)').matches && document.documentElement.dataset.theme !== 'light' || document.documentElement.dataset.theme === 'dark';
    colors = { kw: v('--accent'), str: v('--ok'), num: v('--warn'), cm: v('--muted'), id: v('--fg-2'), pn: v('--muted'),
               orbs: [v('--accent'), '#c25bd6', '#e07a3f'], strength: dark ? 1 : 0.75 };
  }
  function tokenize(src) {
    const out = [], re = /(\/\/.*|#\s.*$)|("[^"]*"|'[^']*')|(\b\d+(?:\.\d+)?\b)|([A-Za-z_]\w*)|(\s+)|(.)/g;
    let m;
    while ((m = re.exec(src))) {
      const [t] = m;
      out.push([t, m[1] ? 'cm' : m[2] ? 'str' : m[3] ? 'num' : m[4] ? (KW.test(t) ? 'kw' : 'id') : 'pn']);
    }
    return out;
  }
  function spawn(initial) {
    const layer = Math.random() < 0.5 ? 0 : Math.random() < 0.6 ? 1 : 2;
    const size = [11, 13, 15.5][layer];
    const text = SNIPPETS[Math.floor(Math.random() * SNIPPETS.length)];
    ctx.font = `${size}px ui-monospace, SFMono-Regular, Menlo, monospace`;
    const width = ctx.measureText(text).width;
    return { text, tokens: tokenize(text), size, layer, width,
             x: Math.random() * Math.max(10, w - width * 0.6) - width * 0.2,
             y: initial ? Math.random() * hgt : hgt + 20 + Math.random() * 60,
             speed: [9, 15, 24][layer] * (0.8 + Math.random() * 0.4),
             alpha: [0.22, 0.34, 0.5][layer],
             typing: Math.random() < 0.35, typed: 0, cps: 14 + Math.random() * 18 };
  }
  function resize() {
    const r = canvas.getBoundingClientRect();
    dpr = Math.min(window.devicePixelRatio || 1, 2); w = r.width; hgt = r.height;
    canvas.width = Math.round(w * dpr); canvas.height = Math.round(hgt * dpr);
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    const target = Math.round(Math.min(70, Math.max(18, (w * hgt) / 16000)));
    while (lines.length < target) lines.push(spawn(true));
    lines.length = Math.min(lines.length, target);
    if (!orbs.length) orbs = [0, 1, 2].map(i => ({ i, a: Math.random() * 6.28, r: 0.28 + i * 0.07, s: 0.05 + i * 0.03 }));
  }
  function frame(t) {
    raf = 0;
    const dt = Math.min(0.05, (t - (last || t)) / 1000); last = t;
    ctx.clearRect(0, 0, w, hgt);
    // glows
    for (const o of orbs) {
      o.a += o.s * dt;
      const cx = w * (0.5 + Math.cos(o.a + o.i * 2.1) * 0.35), cy = hgt * (0.45 + Math.sin(o.a * 1.3 + o.i) * 0.3);
      const rad = Math.max(w, hgt) * o.r;
      const g = ctx.createRadialGradient(cx, cy, 0, cx, cy, rad);
      g.addColorStop(0, colors.orbs[o.i]); g.addColorStop(1, 'transparent');
      ctx.globalAlpha = 0.10 * colors.strength; ctx.fillStyle = g; ctx.fillRect(0, 0, w, hgt);
    }
    // code
    for (let k = 0; k < lines.length; k++) {
      const L = lines[k];
      L.y -= L.speed * dt;
      if (L.typing) L.typed = Math.min(L.text.length, L.typed + L.cps * dt);
      if (L.y < -30) { lines[k] = spawn(false); continue; }
      const edge = Math.min(1, L.y / (hgt * 0.18), (hgt - L.y) / (hgt * 0.12));
      ctx.globalAlpha = Math.max(0, edge) * L.alpha * colors.strength;
      ctx.font = `${L.size}px ui-monospace, SFMono-Regular, Menlo, monospace`;
      let x = L.x, left = L.typing ? Math.floor(L.typed) : Infinity;
      for (const [txt, kind] of L.tokens) {
        if (left <= 0) break;
        const part = txt.slice(0, left); left -= txt.length;
        ctx.fillStyle = colors[kind]; ctx.fillText(part, x, L.y);
        x += ctx.measureText(part).width;
      }
      if (L.typing && L.typed < L.text.length && Math.floor(t / 450) % 2 === 0) { ctx.fillStyle = colors.kw; ctx.fillRect(x + 1, L.y - L.size * 0.8, 2, L.size); }
    }
    ctx.globalAlpha = 1;
    schedule();
  }
  function schedule() { if (!raf && enabled && !document.hidden && !reduced.matches) raf = requestAnimationFrame(frame); }
  function drawStatic() { cancelAnimationFrame(raf); raf = 0; last = 0; frame(performance.now()); cancelAnimationFrame(raf); raf = 0; }
  function setEnabled(on) {
    enabled = on; canvas.classList.toggle('hidden', !on);
    if (on) { reduced.matches ? drawStatic() : schedule(); } else { cancelAnimationFrame(raf); raf = 0; }
  }
  readColors(); resize();
  new ResizeObserver(() => { resize(); if (reduced.matches && enabled) drawStatic(); }).observe(canvas);
  document.addEventListener('visibilitychange', () => { last = 0; schedule(); });
  new MutationObserver(readColors).observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme'] });
  matchMedia('(prefers-color-scheme: dark)').addEventListener('change', readColors);
  return { setEnabled };
})();
$('anim').checked = store.get('docks-anim', 'off') === 'on';
Background.setEnabled($('anim').checked);
$('anim').onchange = () => { store.set('docks-anim', $('anim').checked ? 'on' : 'off'); Background.setEnabled($('anim').checked); };

