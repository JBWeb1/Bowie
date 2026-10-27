// Bowers web app: Integrations: installing the open-source projects Bowers works with.
// Plain scripts that share one global scope, loaded in order by app.html.
// ---------------------------------------------------------------- Integrations: install the linked open-source projects
const INT_KINDS = [['all', 'All'], ['plugin', 'Plugins & skills'], ['tool', 'Tools'], ['app', 'Apps'], ['template', 'Templates'], ['system', 'Programs'], ['library', 'Libraries'], ['link', 'Links']];
const INT_LABEL = { plugin: 'Plugin', collection: 'Skill collection', tool: 'Tool', app: 'App', template: 'Template', system: 'Program', library: 'Library', link: 'Link' };
let INT = { items: [], filter: 'all', logs: {}, installing: {} };
async function renderIntegrations() {
  const r = await api('/api/integrations'); if (!r.ok) return; const d = await r.json();
  INT.items = d.items; INT.installing = Object.fromEntries(Object.entries(d.installing).map(([k, v]) => [k, true]));
  for (const [k, v] of Object.entries(d.installing)) INT.logs[k] = v;
  $('int-skipped').textContent = Object.entries(d.skipped).map(([k, v]) => `Not included: ${k}. ${v}`).join(' ');
  const f = $('int-filters'); if (!f.children.length) for (const [k, label] of INT_KINDS) { const b = h('button', k === INT.filter ? 'on' : null, esc(label)); b.onclick = () => { INT.filter = k; f.querySelectorAll('button').forEach(x => x.classList.toggle('on', x === b)); paintIntegrations(); }; f.appendChild(b); }
  paintIntegrations();
}
function paintIntegrations() {
  const q = ($('int-search').value || '').toLowerCase(), grid = $('int-grid'); grid.innerHTML = '';
  const inst = INT.items.filter(i => i.status === 'installed').length;
  $('int-sub').textContent = `${inst} of ${INT.items.filter(i => i.kind !== 'link').length} installed on this computer. Each one installs the way its own project says.`;
  for (const it of INT.items) {
    const kind = it.kind === 'collection' ? 'plugin' : it.kind;
    if (INT.filter !== 'all' && kind !== INT.filter) continue;
    if (q && !(it.name + ' ' + it.id + ' ' + (it.notes || '') + ' ' + (it.agent || '')).toLowerCase().includes(q)) continue;
    const busy = INT.installing[it.id];
    const c = h('div', 'int', `<div class="int-top"><b></b><span class="kind">${INT_LABEL[it.kind]}</span>${busy ? '<span class="pill installing">Installing…</span>' : it.status === 'installed' ? '<span class="pill installed">Installed</span>' : ''}</div><p></p><div class="meta"></div><div class="acts"></div>`);
    c.querySelector('b').textContent = it.name; c.querySelector('p').textContent = it.notes || '';
    const meta = c.querySelector('.meta');
    if (it.agent) meta.appendChild(h('span', null, `Used by ${esc(agentTitle(it.agent))}`));
    if (it.license) meta.appendChild(h('span', null, esc(it.license)));
    if (it.url) { const a = h('a', null, 'Source'); a.href = it.url; a.target = '_blank'; a.rel = 'noopener'; meta.appendChild(a); }
    if (it.keys?.length) c.appendChild(h('div', 'need', `Needs: ${esc(it.keys.join(', '))}`));
    if (it.missing?.length && it.status !== 'installed') c.appendChild(h('div', 'need', 'First install ' + it.missing.map(m => `<b>${esc(m.name)}</b>: <code>${esc(m.how)}</code>`).join(' · ')));
    const acts = c.querySelector('.acts'), btn = (label, primary, fn) => { const b = h('button', 'btn' + (primary ? ' primary' : ''), esc(label)); b.onclick = fn; acts.appendChild(b); };
    if (it.kind === 'link') btn('Open', true, () => window.open(it.url, '_blank', 'noopener'));
    else if (busy) btn('Show log', false, () => c.querySelector('pre.log')?.scrollIntoView({ block: 'nearest' }));
    else if (it.kind === 'collection') btn(it.status === 'installed' ? 'Add more skills' : 'Pick skills', true, () => pickSkills(it));
    else if (it.status !== 'installed') btn('Install', true, () => confirmInstall(it));
    if (it.status === 'installed' && it.runnable) btn('Start', true, async () => { const r = await api('/api/integrations/run', { id: it.id }); const d = await r.json(); if (!r.ok) return toast(d.error); toast(`${it.name} is starting`); if (d.open) setTimeout(() => window.open(d.open, '_blank', 'noopener'), 4000); });
    if (it.status === 'installed' && it.hooks_held?.length) btn('Review hooks', false, () => reviewHooks(it));
    if (it.status === 'installed' && it.agent) btn('Use', false, () => { const ag = (state.extensions?.agents || []).find(a => a.name === it.agent); if (ag) useAgent(ag); });
    if (it.status === 'installed' && it.kind !== 'link') btn('Remove', false, async () => { if (!confirm(`Remove ${it.name}?`)) return; const r = await api('/api/integrations/remove', { id: it.id }); if (r.ok) { INT.items = (await r.json()).items; paintIntegrations(); syncState(); } });
    if (INT.logs[it.id]?.length) { const pre = h('pre', 'log'); pre.textContent = INT.logs[it.id].slice(-60).join('\n'); c.appendChild(pre); setTimeout(() => { pre.scrollTop = 1e9; }, 0); }
    grid.appendChild(c);
  }
  if (!grid.children.length) grid.appendChild(h('div', 'empty-page', `<img src="${STICKER('searching')}" alt=""><b>Nothing matches</b>Try another search.`));
}
$('int-search').addEventListener('input', paintIntegrations);
function confirmInstall(it, then) {
  const modal = h('div', 'modal', `<div class="modal-box" style="width:min(620px,100%)"><div class="page-head"><h2></h2><span class="spacer"></span><button class="btn ghost icon-only" aria-label="Close">✕</button></div><p class="muted" style="margin:-6px 0 0"></p><div class="int-plan"></div>${it.missing?.some(m => m.auto) ? '<label class="img-check"><input type="checkbox" id="int-prereq" checked> Also install ' + it.missing.filter(m => m.auto).map(m => esc(m.name)).join(', ') + '</label>' : ''}<div class="row" style="display:flex;gap:8px;justify-content:flex-end;margin-top:10px"><button class="btn ghost" data-x>Cancel</button><button class="btn primary" data-go>Install</button></div></div>`);
  modal.querySelector('h2').textContent = 'Install ' + it.name;
  modal.querySelector('p').textContent = 'These steps run on your computer:';
  modal.querySelector('.int-plan').textContent = it.plan.map(l => '• ' + l).join('\n');
  modal.querySelector('[data-go]').onclick = async () => { const prereqs = !!modal.querySelector('#int-prereq')?.checked; modal.remove(); await startInstall(it, prereqs); then?.(); };
  modal.onclick = e => { if (e.target === modal || e.target.closest('.icon-only') || e.target.closest('[data-x]')) modal.remove(); };
  document.body.appendChild(modal);
}
async function startInstall(it, prereqs, skills) {
  INT.logs[it.id] = []; INT.installing[it.id] = true; paintIntegrations();
  const r = await api('/api/integrations/install', { id: it.id, prereqs, skills });
  if (!r.ok) { INT.installing[it.id] = false; toast((await r.json()).error); paintIntegrations(); }
}
async function pickSkills(it) {
  const modal = h('div', 'modal', `<div class="modal-box" style="width:min(680px,100%)"><div class="page-head"><h2></h2><span class="spacer"></span><button class="btn ghost icon-only" aria-label="Close">✕</button></div><input class="input" placeholder="Filter skills…" style="width:100%"><div class="skill-pick"><div class="muted">Loading the collection…</div></div><div style="display:flex;justify-content:flex-end;gap:8px"><span class="muted" data-count style="margin-right:auto;align-self:center"></span><button class="btn primary" data-go>Install selected</button></div></div>`);
  modal.querySelector('h2').textContent = it.name;
  modal.onclick = e => { if (e.target === modal || e.target.closest('.icon-only')) modal.remove(); };
  document.body.appendChild(modal);
  const r = await api('/api/integrations/skills?id=' + encodeURIComponent(it.id)); const d = await r.json();
  const box = modal.querySelector('.skill-pick'), chosen = new Set();
  const paint = () => { const q = modal.querySelector('input').value.toLowerCase(); box.innerHTML = '';
    for (const sk of d.skills || []) { if (q && !(sk.name + sk.description).toLowerCase().includes(q)) continue;
      const l = h('label', null, `<input type="checkbox"><span><b></b><small></small></span>`); l.querySelector('b').textContent = sk.name; l.querySelector('small').textContent = sk.description;
      const cb = l.querySelector('input'); cb.checked = chosen.has(sk.path); cb.onchange = () => { cb.checked ? chosen.add(sk.path) : chosen.delete(sk.path); modal.querySelector('[data-count]').textContent = `${chosen.size} selected`; };
      box.appendChild(l); } };
  modal.querySelector('input').oninput = paint; paint();
  modal.querySelector('[data-go]').onclick = () => { if (!chosen.size) return toast('Pick at least one skill'); modal.remove(); startInstall(it, false, [...chosen]); };
}
async function reviewHooks(it) {
  const r = await api('/api/integrations/hooks', { id: it.id }); const d = await r.json();
  const modal = h('div', 'modal', `<div class="modal-box" style="width:min(720px,100%)"><div class="page-head"><h2></h2><span class="spacer"></span><button class="btn ghost icon-only" aria-label="Close">✕</button></div><p class="muted" style="margin:-6px 0 0">Hooks run these commands automatically on your computer when Bowers works. They are off until you turn them on.</p><div class="int-plan"></div><div style="display:flex;gap:8px;justify-content:flex-end"><button class="btn ghost" data-x>Keep them off</button><button class="btn primary" data-go>Turn hooks on</button></div></div>`);
  modal.querySelector('h2').textContent = it.name + ' hooks';
  modal.querySelector('.int-plan').textContent = (d.hooks || []).map(x => `[${x.event}${x.matcher ? ' ' + x.matcher : ''}] ${x.command}`).join('\n\n') || 'No hooks.';
  modal.querySelector('[data-go]').onclick = async () => { const rr = await api('/api/integrations/enable-hooks', { id: it.id }); modal.remove(); if (rr.ok) { INT.items = (await rr.json()).items; paintIntegrations(); syncState(); toast('Hooks on'); } };
  modal.onclick = e => { if (e.target === modal || e.target.closest('.icon-only') || e.target.closest('[data-x]')) modal.remove(); };
  document.body.appendChild(modal);
}
$('int-all-plugins').onclick = async () => {
  const todo = INT.items.filter(i => i.kind === 'plugin' && i.status !== 'installed');
  if (!todo.length) return toast('Every plugin is already installed');
  if (!confirm(`Install ${todo.length} plugins and skill packs?\n\n${todo.map(i => '• ' + i.name).join('\n')}`)) return;
  for (const it of todo) { await startInstall(it, false); while (INT.installing[it.id]) await new Promise(r => setTimeout(r, 500)); }
};
function onIntegrationEvent(ev) {
  if (ev.line != null) { (INT.logs[ev.id] ||= []).push(ev.line); const card = [...document.querySelectorAll('#int-grid .int')].find(c => c.querySelector('b')?.textContent === INT.items.find(i => i.id === ev.id)?.name);
    let pre = card?.querySelector('pre.log'); if (card && !pre) { pre = h('pre', 'log'); card.appendChild(pre); } if (pre) { pre.textContent = INT.logs[ev.id].slice(-60).join('\n'); pre.scrollTop = 1e9; } }
  if (ev.done) { INT.installing[ev.id] = false; const name = INT.items.find(i => i.id === ev.id)?.name || ev.id;
    toast(ev.error ? `${name}: ${ev.error}` : `${name} is installed`); if (!ev.error) syncState(); if (page === 'integrations') renderIntegrations(); }
}
function panelTerminal() { const box = $('panel-term'); if (box.children.length) return; ideTab('term'); box.replaceChildren(...$('ide-pane').childNodes); }
