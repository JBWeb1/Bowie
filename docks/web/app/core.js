// Bowers web app: Icons, helpers, the API client, theme and markdown.
// Plain scripts that share one global scope, loaded in order by app.html.
// ---------------------------------------------------------------- icons
const ICONS = {
  logo: '<path d="m8 7-5 5 5 5M16 7l5 5-5 5M13.5 4.5l-3 15"/>',
  play: '<path d="M7 5v14l11-7z"/>',
  mic: '<rect x="9" y="3" width="6" height="11" rx="3"/><path d="M5 11a7 7 0 0 0 14 0M12 18v3"/>',
  sun: '<circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/>',
  moon: '<path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8z"/>',
  plus: '<path d="M12 5v14M5 12h14"/>',
  panel: '<rect x="3" y="4" width="18" height="16" rx="2"/><path d="M14 4v16"/>',
  gear: '<circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.8-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1.1-1.5 1.7 1.7 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.5-1.1 1.7 1.7 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.8.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.8V9a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1z"/>',
  'arrow-up': '<path d="M12 19V5M5 12l7-7 7 7"/>',
  stop: '<rect x="7" y="7" width="10" height="10" rx="1.5" fill="currentColor"/>',
  eye: '<path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7S2 12 2 12z"/><circle cx="12" cy="12" r="3"/>',
  code: '<path d="m16 18 6-6-6-6M8 6l-6 6 6 6"/>',
  github: '<path d="M9 19c-4.3 1.4-4.3-2.5-6-3m12 5v-3.5c0-1 .1-1.4-.5-2 2.8-.3 5.5-1.4 5.5-6a4.6 4.6 0 0 0-1.3-3.2 4.2 4.2 0 0 0-.1-3.2s-1.1-.3-3.5 1.3a12.3 12.3 0 0 0-6.2 0C6.5 2.8 5.4 3.1 5.4 3.1a4.2 4.2 0 0 0-.1 3.2A4.6 4.6 0 0 0 4 9.5c0 4.6 2.7 5.7 5.5 6-.6.6-.6 1.2-.5 2V21"/>',
  refresh: '<path d="M21 12a9 9 0 1 1-2.6-6.4L21 8"/><path d="M21 3v5h-5"/>',
  globe: '<circle cx="12" cy="12" r="9"/><path d="M3 12h18M12 3a14 14 0 0 1 0 18M12 3a14 14 0 0 0 0 18"/>',
  monitor: '<rect x="3" y="4" width="18" height="12" rx="2"/><path d="M8 20h8M12 16v4"/>',
  phone: '<rect x="7" y="2" width="10" height="20" rx="2"/><path d="M11 18h2"/>',
  external: '<path d="M14 4h6v6M20 4l-9 9M18 14v5a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V7a1 1 0 0 1 1-1h5"/>',
  file: '<path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z"/><path d="M14 3v5h5"/>',
  folder: '<path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/>',
  terminal: '<path d="m5 8 4 4-4 4M12 16h7"/><rect x="2" y="3" width="20" height="18" rx="2"/>',
  pencil: '<path d="M4 20h4L19 9l-4-4L4 16z"/><path d="m13.5 6.5 4 4"/>',
  search: '<circle cx="11" cy="11" r="7"/><path d="m20 20-4-4"/>',
  brain: '<path d="M12 5a3 3 0 0 0-5.8 1A3 3 0 0 0 4 11a3 3 0 0 0 2 5 3 3 0 0 0 6 1V5zM12 5a3 3 0 0 1 5.8 1A3 3 0 0 1 20 11a3 3 0 0 1-2 5 3 3 0 0 1-6 1"/>',
  pr: '<circle cx="6" cy="6" r="2.5"/><circle cx="6" cy="18" r="2.5"/><circle cx="18" cy="18" r="2.5"/><path d="M6 8.5v7M18 15.5V9a3 3 0 0 0-3-3h-4M13 3.5 10.5 6 13 8.5"/>',
  issue: '<circle cx="12" cy="12" r="9"/><circle cx="12" cy="12" r="1.5" fill="currentColor"/>',
  review: '<path d="M21 12a8 8 0 0 1-11.7 7.1L4 21l1.9-5.3A8 8 0 1 1 21 12z"/><path d="m9 12 2 2 4-4"/>',
  comment: '<path d="M21 12a8 8 0 0 1-11.7 7.1L4 21l1.9-5.3A8 8 0 1 1 21 12z"/>',
  chev: '<path d="m9 6 6 6-6 6"/>',
  shield: '<path d="M12 3 5 6v5c0 4.5 3 8.5 7 10 4-1.5 7-5.5 7-10V6z"/>',
  zap: '<path d="M13 2 4 14h7l-1 8 9-12h-7z"/>',
  chat: '<path d="M21 12a8 8 0 0 1-11.7 7.1L4 21l1.9-5.3A8 8 0 1 1 21 12z"/>',
  alert: '<path d="M12 9v4M12 17h.01"/><path d="M10.3 3.9 2.4 18a2 2 0 0 0 1.7 3h15.8a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0z"/>',
  sparkle: '<path d="M12 3v4M12 17v4M3 12h4M17 12h4M6 6l2.5 2.5M15.5 15.5 18 18M6 18l2.5-2.5M15.5 8.5 18 6"/>',
  layout: '<rect x="3" y="3" width="18" height="18" rx="2"/><path d="M3 9h18M9 21V9"/>',
  game: '<rect x="2" y="7" width="20" height="11" rx="4"/><path d="M7 11v3M5.5 12.5h3M15 12h.01M18 13h.01"/>',
  bug: '<path d="M8 8V6a4 4 0 0 1 8 0v2"/><rect x="6" y="8" width="12" height="12" rx="6"/><path d="M12 12v8M3 13h3M18 13h3M4 7l3 2M20 7l-3 2M4 19l3-2M20 19l-3-2"/>',
  book: '<path d="M4 19V5a2 2 0 0 1 2-2h13v16H6a2 2 0 0 0-2 2zm0 0a2 2 0 0 0 2 2h13"/>',
  history: '<path d="M3 12a9 9 0 1 0 3-6.7L3 8"/><path d="M3 3v5h5M12 7v5l3 2"/>',
  star: '<path d="m12 3 2.7 5.6 6.1.9-4.4 4.3 1 6.1L12 17l-5.4 2.9 1-6.1L3.2 9.5l6.1-.9z"/>',
  copy: '<rect x="9" y="9" width="12" height="12" rx="2"/><path d="M5 15H4a1 1 0 0 1-1-1V4a1 1 0 0 1 1-1h10a1 1 0 0 1 1 1v1"/>',
  question: '<circle cx="12" cy="12" r="9"/><path d="M9.5 9a2.5 2.5 0 1 1 3.5 2.3c-.6.3-1 .9-1 1.6V14M12 17h.01"/>',
  users: '<circle cx="9" cy="8" r="3.5"/><path d="M2.5 20a6.5 6.5 0 0 1 13 0M16 4.5a3.5 3.5 0 0 1 0 7M18.5 20a6.5 6.5 0 0 0-3-5.5"/>',
  undo: '<path d="M9 14 4 9l5-5"/><path d="M4 9h11a5 5 0 0 1 0 10h-3"/>',
  check: '<path d="m5 12 5 5L20 7"/>',
  image: '<rect x="3" y="3" width="18" height="18" rx="2"/><circle cx="9" cy="9" r="2"/><path d="m21 15-5-5L5 21"/>',
  rocket: '<path d="M5 15c-1.5 1.3-2 5-2 5s3.7-.5 5-2c.7-.8.7-2.1-.1-2.9a2.2 2.2 0 0 0-2.9-.1z"/><path d="m12 15-3-3a22 22 0 0 1 2-4A12.9 12.9 0 0 1 22 2c0 2.7-.8 7.5-6 11a22.4 22.4 0 0 1-4 2z"/><path d="M9 12H4s.6-3 2-4c1.6-1.1 5 0 5 0M12 15v5s3-.6 4-2c1.1-1.6 0-5 0-5"/>',
  plug: '<path d="M12 22v-5M9 8V2M15 8V2M18 8v5a4 4 0 0 1-4 4h-4a4 4 0 0 1-4-4V8z"/>',
  play: '<path d="m7 4 13 8-13 8z"/>',
  server: '<rect x="3" y="4" width="18" height="7" rx="2"/><rect x="3" y="13" width="18" height="7" rx="2"/><path d="M7 7.5h.01M7 16.5h.01"/>',
  chart: '<path d="M3 3v18h18M7 15l4-4 3 3 5-6"/>',
  smartphone: '<rect x="6" y="2" width="12" height="20" rx="2"/><path d="M11 18h2"/>',
  puzzle: '<path d="M9 3h6v3a2 2 0 1 0 4 0V9h2v6h-3a2 2 0 1 0 0 4h3v2H9v-3a2 2 0 1 0-4 0v3H3V9h3a2 2 0 1 0 0-4H3V3z"/>',
  home: '<path d="M3 11.5 12 4l9 7.5"/><path d="M5.5 10v9.5h13V10"/><path d="M10 19.5v-5h4v5"/>',
  library: '<rect x="3" y="4" width="18" height="16" rx="2.5"/><path d="M3 9h18M8 14h3"/>',
  compass: '<circle cx="12" cy="12" r="9"/><path d="m15.5 8.5-2 5-5 2 2-5z"/>',
  grid: '<rect x="4" y="4" width="6.5" height="6.5" rx="1.5"/><rect x="13.5" y="4" width="6.5" height="6.5" rx="1.5"/><rect x="4" y="13.5" width="6.5" height="6.5" rx="1.5"/><rect x="13.5" y="13.5" width="6.5" height="6.5" rx="1.5"/>',
  chevron: '<path d="m9 6 6 6-6 6"/>',
  'chevron-down': '<path d="m6 9 6 6 6-6"/>',
  bell: '<path d="M6 16V11a6 6 0 1 1 12 0v5l1.5 2h-15z"/><path d="M10 20a2 2 0 0 0 4 0"/>',
  'arrow-right': '<path d="M5 12h14M13 6l6 6-6 6"/>',
  box: '<path d="M12 3 4 7v10l8 4 8-4V7z"/><path d="m4 7 8 4 8-4M12 11v10"/>',
  bulb: '<path d="M9 18h6M10 21h4"/><path d="M12 3a6 6 0 0 0-3.5 10.9c.6.5 1 1.2 1 2.1h5c0-.9.4-1.6 1-2.1A6 6 0 0 0 12 3z"/>',
  dots: '<circle cx="5" cy="12" r="1.3"/><circle cx="12" cy="12" r="1.3"/><circle cx="19" cy="12" r="1.3"/>',
};
const MARK = 'M100 72Q100 55 117 55H388C448 55 482 95 482 150C482 190 462 220 434 238C476 256 500 292 500 342C500 406 456 455 390 455H372Q355 455 355 438V384Q355 366 337 366H322Q305 366 305 384V438Q305 455 288 455H252Q235 455 235 438V384Q235 366 217 366H198Q180 366 180 384V438Q180 455 163 455H117Q100 455 100 438V322H30Q12 322 12 304V256Q12 238 30 238H100ZM188 148H230Q236 148 236 154V230Q236 236 230 236H188Q182 236 182 230V154Q182 148 188 148Z';
const markSvg = (size = 22) => `<svg viewBox="4 45 504 420" width="${size}" height="${Math.round(size * 420 / 504)}" aria-hidden="true"><path fill="currentColor" fill-rule="evenodd" d="${MARK}"/></svg>`;
const BOWIE = mood => `/assets/bowie/${{ focused: 'coding', relaxed: 'chilling' }[mood] || mood}.webp`;
const icon = (name, size = 16) => `<svg class="icon" viewBox="0 0 24 24" width="${size}" height="${size}" aria-hidden="true">${ICONS[name] || ''}</svg>`;
document.querySelectorAll('[data-icon]').forEach(e => { e.innerHTML = icon(e.dataset.icon, e.classList.contains('ic') ? 24 : e.classList.contains('logo-mark') ? 18 : 16); });
document.querySelectorAll('[data-mark]').forEach(e => { e.innerHTML = markSvg(e.closest('.splash') ? 40 : 24); });
function hydrateIcons(root) { root.querySelectorAll('[data-icon]').forEach(e => { if (!e.innerHTML) e.innerHTML = icon(e.dataset.icon, 16); }); }

// ---------------------------------------------------------------- basics
const $ = id => document.getElementById(id);
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const h = (tag, cls, html) => { const e = document.createElement(tag); if (cls) e.className = cls; if (html != null) e.innerHTML = html; return e; };
const store = { get(k, d) { try { return localStorage.getItem(k) ?? d; } catch (e) { return d; } }, set(k, v) { try { localStorage.setItem(k, v); } catch (e) {} } };

let token = '';
try {
  const m = location.hash.match(/token=([\w-]+)/);
  if (m) { token = m[1]; sessionStorage.setItem('docks-token', token); localStorage.setItem('bowers-app-token', token); history.replaceState(null, '', location.pathname); }
  else token = sessionStorage.getItem('docks-token') || localStorage.getItem('bowers-app-token') || '';
} catch (e) {}
const api = (path, body) => fetch(path, {
  method: body ? 'POST' : 'GET',
  headers: { 'x-docks-token': token, ...(body ? { 'content-type': 'application/json' } : {}) },
  body: body ? JSON.stringify(body) : undefined,
});
function toast(text) { const t = h('div', 'toast'); t.textContent = text; document.body.appendChild(t); setTimeout(() => t.remove(), 2600); }

// Theme (a per-browser preference)
function applyTheme(v) { if (v === 'system') document.documentElement.removeAttribute('data-theme'); else document.documentElement.dataset.theme = v; }
$('theme').value = store.get('docks-theme', 'system'); applyTheme($('theme').value);
$('theme').onchange = () => { store.set('docks-theme', $('theme').value); applyTheme($('theme').value); };

// ---------------------------------------------------------------- markdown
function md(src) {
  const blocks = [];
  let s = esc(src).replace(/```([\w+-]*)\n?([\s\S]*?)(```|$)/g, (_, lang, code) => {
    blocks.push(`<div class="codeblock"><div class="cb-head"><span>${lang || 'code'}</span><button class="btn ghost copy">Copy</button></div><pre><code>${code.replace(/\n$/, '')}</code></pre></div>`);
    return `\n\u0000${blocks.length - 1}\u0000\n`;
  });
  const inline = t => t.replace(/`([^`\n]+)`/g, '<code>$1</code>')
    .replace(/\*\*([^*\n]+)\*\*/g, '<strong>$1</strong>')
    .replace(/\[([^\]\n]+)\]\((https?:\/\/[^)\s]+)\)/g, '<a href="$2" target="_blank" rel="noopener">$1</a>');
  const out = [];
  for (const para of s.split(/\n{2,}/)) {
    const lines = para.split('\n').filter(l => l.trim() !== '');
    if (!lines.length) continue;
    let list = null, buf = [];
    const flush = () => { if (buf.length) { out.push(`<p>${buf.map(inline).join('<br>')}</p>`); buf = []; } };
    const closeList = () => { if (list) { out.push(`<${list.tag}>${list.items.map(i => `<li>${inline(i)}</li>`).join('')}</${list.tag}>`); list = null; } };
    for (const line of lines) {
      let m;
      if ((m = line.match(/^\u0000(\d+)\u0000$/))) { flush(); closeList(); out.push(blocks[m[1]]); }
      else if ((m = line.match(/^#{1,6}\s+(.*)$/))) { flush(); closeList(); out.push(`<h3>${inline(m[1])}</h3>`); }
      else if ((m = line.match(/^\s*[-*]\s+(.*)$/))) { flush(); if (list?.tag !== 'ul') { closeList(); list = { tag: 'ul', items: [] }; } list.items.push(m[1]); }
      else if ((m = line.match(/^\s*\d+[.)]\s+(.*)$/))) { flush(); if (list?.tag !== 'ol') { closeList(); list = { tag: 'ol', items: [] }; } list.items.push(m[1]); }
      else if (list && /^\s{2,}/.test(line)) { list.items[list.items.length - 1] += ' ' + line.trim(); }
      else { closeList(); buf.push(line); }
    }
    flush(); closeList();
  }
  return out.join('');
}
document.addEventListener('click', e => {
  const b = e.target.closest('.copy'); if (!b) return;
  navigator.clipboard?.writeText(b.closest('.codeblock').querySelector('pre').textContent).then(() => { b.textContent = 'Copied'; setTimeout(() => b.textContent = 'Copy', 1400); });
});

// ---------------------------------------------------------------- tool labels
const base = p => String(p || '').split('/').pop();
const TOOL = {
  bash:                { icon: 'terminal', run: 'Running a command', done: 'Ran a command', d: a => a.command },
  write_file:          { icon: 'file', run: a => `Writing ${base(a.path)}`, done: a => `Wrote ${base(a.path)}`, d: a => a.path },
  edit_file:           { icon: 'pencil', run: a => `Editing ${base(a.path)}`, done: a => `Edited ${base(a.path)}`, d: a => a.path },
  read_file:           { icon: 'eye', run: a => `Reading ${base(a.path)}`, done: a => `Read ${base(a.path)}`, d: a => a.path },
  glob:                { icon: 'search', run: 'Finding files', done: 'Found files', d: a => a.pattern },
  grep:                { icon: 'search', run: 'Searching the code', done: 'Searched the code', d: a => a.pattern },
  web_search:          { icon: 'globe', run: 'Searching the web', done: 'Searched the web', d: a => a.query },
  web_fetch:           { icon: 'globe', run: 'Reading a web page', done: 'Read a web page', d: a => a.url },
  remember:            { icon: 'brain', run: 'Saving a note', done: 'Saved a note for next time', d: a => a.note },
  github_issue:        { icon: 'issue', run: a => `Reading issue #${a.number}`, done: a => `Read issue #${a.number}`, d: () => '' },
  github_pr:           { icon: 'pr', run: a => `Reading pull request #${a.number}`, done: a => `Read pull request #${a.number}`, d: () => '' },
  create_pull_request: { icon: 'pr', run: 'Opening a pull request', done: 'Opened a pull request', d: a => a.title },
  github_comment:      { icon: 'comment', run: a => `Commenting on #${a.number}`, done: a => `Commented on #${a.number}`, d: a => a.body },
  review_pull_request: { icon: 'review', run: a => `Reviewing #${a.number}`, done: a => `Posted a review on #${a.number}`, d: a => a.body },
  delegate:            { icon: 'users', run: a => `Helper${a.background ? ' (background)' : ''}: ${a.description}`, done: a => a.background ? `Started in background: ${a.description}` : `Helper finished: ${a.description}`, d: a => a.agent || '' },
  ask_user:            { icon: 'question', run: 'Asking you a question', done: 'Asked you a question', d: () => '' },
  exit_plan_mode:      { icon: 'book', run: 'Proposing a plan', done: 'Proposed a plan', d: () => '' },
  load_skill:          { icon: 'sparkle', run: a => `Loading skill ${a.name}`, done: a => `Loaded skill: ${a.name}`, d: () => '' },
  browser:             { icon: 'eye', run: a => BROWSE[a.action]?.[0](a) || 'Using the browser', done: a => BROWSE[a.action]?.[1](a) || 'Used the browser', d: a => a.url || a.target || a.key || a.script || a.device || '' },
  code_intel:          { icon: 'search', run: a => `Looking up ${a.symbol || a.action}`, done: a => a.action === 'diagnostics' ? 'Checked for errors' : `Looked up ${a.symbol || a.action}`, d: a => a.path || a.query || '' },
  start_process:       { icon: 'play', run: 'Starting the app', done: 'Started the app', d: a => a.command },
  process_logs:        { icon: 'terminal', run: 'Checking the app output', done: 'Checked the app output', d: a => `process ${a.process_id}` },
  stop_process:        { icon: 'server', run: 'Stopping the app', done: 'Stopped the app', d: a => `process ${a.process_id}` },
};
const BROWSE = {
  open: [a => `Opening ${a.url}`, a => `Opened ${a.url}`], click: [a => `Clicking ${a.target}`, a => `Clicked ${a.target}`],
  type: [a => `Typing into ${a.target}`, a => `Typed into ${a.target}`], press: [a => `Pressing ${a.key}`, a => `Pressed ${a.key}`],
  screenshot: [() => 'Taking a screenshot', () => 'Took a screenshot'], read: [() => 'Reading the page', () => 'Read the page'],
  console: [() => 'Checking the console', () => 'Checked the console'], eval: [() => 'Running a script on the page', () => 'Ran a script on the page'],
  viewport: [a => `Switching to ${a.device || a.width + '×' + a.height}`, a => `Switched to ${a.device || a.width + '×' + a.height}`],
  close: [() => 'Closing the browser', () => 'Closed the browser'],
};
function toolInfo(name) {
  if (TOOL[name]) return TOOL[name];
  const m = String(name).match(/^mcp__(.+?)__(.+)$/);
  if (m) return { icon: 'plug', run: `Using ${m[2]} (${m[1]})`, done: `Used ${m[2]} (${m[1]})`, d: a => JSON.stringify(a) };
  return { icon: 'zap', run: name, done: name, d: a => JSON.stringify(a) };
}
const tl = (name, args, which) => { const v = toolInfo(name)[which]; return typeof v === 'function' ? v(args || {}) : v; };
const ASK = {
  bash: 'run a command',
  write_file: a => `create or replace ${base(a.path)}`,
  edit_file: a => `edit ${base(a.path)}`,
  create_pull_request: 'push this branch and open a pull request',
  github_comment: a => `comment on #${a.number}`,
  review_pull_request: a => `post a review on #${a.number}`,
  start_process: 'start a background process',
};

