// Монтажная — фронтенд. Субтитры рисует движок Captions Studio (/cs/engine.js): превью = рендер.
import * as E from '/cs/engine.js';

const $ = id => document.getElementById(id);
const main = $('main');
const S = { page: 'projects', pid: null, p: null, presets: [], styles: [], fonts: [], words: null, timers: [] };
const esc = s => String(s ?? '').replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
const fmt = t => { t = Math.max(0, t || 0); const m = Math.floor(t / 60); return `${m}:${(t % 60).toFixed(1).padStart(4, '0')}`; };
const media = p => `/api/media?path=${encodeURIComponent(p)}`;

async function api(url, opt = {}) {
  const o = { method: opt.method || (opt.json ? 'POST' : 'GET'), headers: {} };
  if (opt.json !== undefined) { o.body = JSON.stringify(opt.json); o.headers['Content-Type'] = 'application/json'; }
  const r = await fetch(url, o);
  const data = await r.json().catch(() => ({}));
  if (!r.ok) { const e = new Error(data.detail || r.statusText); e.status = r.status; e.data = data; throw e; }
  return data;
}
function toast(msg, ms = 3200) {
  const d = document.createElement('div'); d.className = 'toast'; d.textContent = msg; document.body.append(d);
  setTimeout(() => d.remove(), ms);
}
function ask(html, buttons) {
  return new Promise(res => {
    $('dlgBody').innerHTML = html; $('dlgBtns').innerHTML = '';
    for (const [label, val, cls] of buttons) {
      const b = document.createElement('button'); b.className = 'btn ' + (cls || ''); b.textContent = label;
      b.onclick = () => { $('dlg').close(); res(val); }; $('dlgBtns').append(b);
    }
    $('dlg').showModal();
  });
}
async function pollJob(job, el) {
  while (true) {
    const j = await api(`/api/jobs/${job.id}`);
    if (el) el.innerHTML = `<div class="jobline"><div class="small">${esc(j.message || '…')}</div><div class="progress"><div style="width:${(j.progress * 100).toFixed(1)}%"></div></div></div>`;
    if (j.status === 'done') { if (el) el.innerHTML = ''; return j.result; }
    if (j.status === 'error') { if (el) el.innerHTML = `<div class="small" style="color:var(--danger)">${esc(j.error)}</div>`; throw new Error(j.error); }
    await new Promise(r => setTimeout(r, 700));
  }
}

// ================================================================ навигация
document.querySelectorAll('#nav button').forEach(b => b.onclick = () => go(b.dataset.page));
function go(page) {
  S.page = page; stopPlayer();
  document.querySelectorAll('#nav button').forEach(b => b.classList.toggle('active', b.dataset.page === page));
  const needP = ['sources', 'cleanup', 'montage', 'render'].includes(page);
  if (needP && !S.p) { main.innerHTML = `<div class="page"><h1>Сначала выберите проект</h1><p class="sub">Раздел «Проекты» → новый ролик или существующий.</p><button class="btn primary" id="toP">К проектам</button></div>`; $('toP').onclick = () => go('projects'); return; }
  ({ projects: pgProjects, sources: pgSources, cleanup: pgCleanup, montage: pgMontage, render: pgRender, styles: pgStyles, rules: pgRules })[page]();
}
async function openProject(pid) {
  S.pid = pid; S.p = await api(`/api/projects/${pid}`); S.words = null;
  try { localStorage.setItem('mt_pid', pid); } catch {}
  $('pname').textContent = S.p.title;
}
async function saveP(fields) { S.p = await api(`/api/projects/${S.pid}`, { method: 'PUT', json: fields }); return S.p; }

const STAGE = { sources: 'Исходники', prepare: 'Подготовка', transcribe: 'Распознавание', cleanup: 'Чистка', montage: 'Монтаж', preview: 'Превью', final: 'Финал' };
const stageChips = st => Object.entries(STAGE).map(([k, n]) => `<span class="st ${st?.[k] || ''}">${n}</span>`).join('');

// ================================================================ 0. Проекты
async function pgProjects() {
  const list = await api('/api/projects');
  main.innerHTML = `<div class="page"><div class="row"><div class="grow"><h1>Проекты</h1><p class="sub">Ролики в работе и готовые. Статус каждого этапа.</p></div>
    <input type="text" id="newTitle" placeholder="Название ролика"><button class="btn primary" id="newP">+ Новый ролик</button></div>
    <div class="grid" id="plist">${list.map(p => `<div class="card proj" data-id="${p.id}">
      <div class="row"><b class="grow">${esc(p.title)}</b>${p.id === S.pid ? '<span class="chip ok">открыт</span>' : ''}</div>
      <div class="small muted">${new Date(p.updated * 1000).toLocaleString('ru')}</div>
      <div class="stages">${stageChips(p.stages)}</div>
      ${p.renders?.length ? `<div class="small">Готово: ${p.renders.filter(r => r.kind === 'final').length} финал, ${p.renders.filter(r => r.kind !== 'final').length} превью</div>` : ''}
      <div class="row"><button class="btn sm" data-del="${p.id}">Удалить проект</button></div></div>`).join('') || '<p class="muted">Пока пусто. Создайте первый ролик.</p>'}</div></div>`;
  $('newP').onclick = async () => {
    const p = await api('/api/projects', { json: { title: $('newTitle').value.trim() || 'Новый ролик' } });
    await openProject(p.id); go('sources');
  };
  main.querySelectorAll('.proj').forEach(c => c.onclick = async e => {
    if (e.target.dataset.del) {
      if (await ask('Удалить проект и его временные файлы в work\\? Исходники и готовые ролики в output\\ не трогаются.', [['Отмена', false], ['Удалить', true, 'primary']])) {
        await api(`/api/projects/${e.target.dataset.del}`, { method: 'DELETE' }); if (S.pid === e.target.dataset.del) { S.pid = S.p = null; $('pname').textContent = 'Проект не выбран'; } pgProjects();
      }
      return;
    }
    await openProject(c.dataset.id);
    const st = S.p.stages;
    go(st.cleanup === 'done' ? 'montage' : st.transcribe === 'done' ? 'cleanup' : 'sources');
  });
}

// ================================================================ 1. Исходники
async function scanFolder(path) {
  try { return await api('/api/sources/scan', { json: { path } }); }
  catch (e) {
    if (e.status === 403 && e.data?.need_permission) {
      const ok = await ask(`<h3 style="margin-top:0">Доступ к папке</h3><p>Разрешить Монтажной <b>читать</b> папку?</p><p><code>${esc(e.data.path)}</code></p><p class="small muted">Исходники только читаются: ничего не меняется и не удаляется. Копии и временные файлы — в D:\\Монтаж\\work.</p>`, [['Нет', false], ['Разрешить чтение', true, 'primary']]);
      if (!ok) return null;
      await api('/api/sources/allow', { json: { path: e.data.path } });
      return api('/api/sources/scan', { json: { path } });
    }
    throw e;
  }
}
async function pgSources() {
  const allowed = await api('/api/sources/allowed');
  const sel = [...(S.p.sources || [])];
  main.innerHTML = `<div class="page"><h1>Исходники</h1><p class="sub">Папка с видео. Выберите один или несколько клипов, порядок — по клику.</p>
    <div class="row"><input type="text" id="folder" class="grow" placeholder="D:\\Видео\\Съёмка 15.11" value="${esc(localStorage.getItem('mt_folder') || '')}">
      <button class="btn" id="scan">Открыть папку</button>
      <select id="lang"><option value="ru">Русский</option><option value="uk">Українська</option><option value="en">English</option><option value="cs">Čeština</option><option value="auto">Авто</option></select></div>
    <div class="row small muted" style="margin:8px 0 14px">Разрешённые папки: ${allowed.map(a => `<a href="#" data-dir="${esc(a)}">${esc(a)}</a>`).join(' · ') || 'пока нет'}</div>
    <div class="grid" id="clips"></div>
    <div class="card" style="margin-top:16px"><div class="row"><div class="grow"><b>В ролике:</b> <span id="selList"></span></div>
      <button class="btn primary" id="prep">Подготовить и распознать →</button></div><div id="job" style="margin-top:10px"></div>
      <p class="hint">Подготовка: копия 1080×1920, 30 к/с, горизонталь кадрируется по лицу. Затем распознавание речи (whisper Captions Studio) и поиск правок.</p></div></div>`;
  $('lang').value = S.p.lang || 'ru';
  let items = [];
  const drawSel = () => { $('selList').textContent = sel.length ? sel.map((s, i) => `${i + 1}. ${s.name}`).join('  ') : 'ничего не выбрано'; };
  const drawClips = () => {
    $('clips').innerHTML = items.map(c => { const i = sel.findIndex(s => s.path === c.path);
      return `<div class="card clip ${i >= 0 ? 'sel' : ''}" data-path="${esc(c.path)}">${i >= 0 ? `<div class="order">${i + 1}</div>` : ''}
        <img loading="lazy" src="/api/thumb?path=${encodeURIComponent(c.path)}"><div class="meta"><b>${esc(c.name)}</b><br>
        <span class="muted">${c.error ? esc(c.error) : `${fmt(c.duration)} · ${c.width}×${c.height} · ${c.fps} fps${c.hdr ? ' · HDR' : ''}`}</span></div></div>`; }).join('');
    $('clips').querySelectorAll('.clip').forEach(el => el.onclick = () => {
      const c = items.find(x => x.path === el.dataset.path); const i = sel.findIndex(s => s.path === c.path);
      if (i >= 0) sel.splice(i, 1); else sel.push({ path: c.path, name: c.name, duration: c.duration, width: c.width, height: c.height });
      drawClips(); drawSel();
    });
  };
  const open = async path => {
    if (!path) return; localStorage.setItem('mt_folder', path); $('folder').value = path;
    const r = await scanFolder(path).catch(e => { toast(e.message); return null; });
    if (r) { items = r; drawClips(); if (!r.length) toast('В папке нет видео'); }
  };
  $('scan').onclick = () => open($('folder').value.trim());
  main.querySelectorAll('[data-dir]').forEach(a => a.onclick = e => { e.preventDefault(); open(a.dataset.dir); });
  drawSel();
  if (sel.length) { const dir = sel[0].path.replace(/[\\/][^\\/]+$/, ''); if (allowed.some(a => dir.toLowerCase().startsWith(a.toLowerCase()))) open(dir); }
  $('prep').onclick = async () => {
    if (!sel.length) return toast('Выберите хотя бы один клип');
    await saveP({ sources: sel, lang: $('lang').value });
    $('prep').disabled = true;
    try { const r = await pollJob(await api(`/api/projects/${S.pid}/prepare`, { json: {} }), $('job'));
      toast(`Распознано слов: ${r.words}, найдено правок: ${r.edits}`); await openProject(S.pid); go('cleanup'); }
    catch (e) { toast(e.message); } finally { $('prep').disabled = false; }
  };
}

// ================================================================ 2. Чистка
const TYPE = { pause: 'пауза', filler: 'паразит', dup: 'дубль', falsestart: 'фальстарт' };
async function pgCleanup() {
  if (S.p.stages.transcribe !== 'done') { main.innerHTML = `<div class="page"><h1>Чистка</h1><p class="sub">Сначала подготовьте и распознайте исходники.</p><button class="btn primary" id="b">К исходникам</button></div>`; $('b').onclick = () => go('sources'); return; }
  const W = (await api(`/api/projects/${S.pid}/words`)).raw;
  let filter = 'all';
  main.innerHTML = `<div class="page"><h1>Чистка</h1><p class="sub">Паузы, паразиты, дубли и фальстарты. ▶ — послушать как есть, ⏭ — как будет после склейки. ✓/✗ — принять или отклонить.</p>
    <div class="split"><div class="vbox"><video id="v" src="/api/projects/${S.pid}/file/raw.mp4" controls preload="auto"></video>
      <div class="card" style="margin-top:10px"><div class="small muted">Транскрипт (клик — перейти)</div><div class="transcript" id="tr"></div></div></div>
    <div><div class="row" style="margin-bottom:10px"><select id="flt"><option value="all">Все</option>${Object.entries(TYPE).map(([k, v]) => `<option value="${k}">${v}</option>`).join('')}</select>
      <span class="grow muted small" id="cnt"></span><button class="btn sm" id="refind">Найти заново</button><button class="btn sm" id="rejAll">Отклонить всё</button><button class="btn sm ok" id="accAll">✓ Принять всё</button></div>
      <div class="card" style="padding:0;max-height:58vh;overflow:auto"><table class="edits"><thead><tr><th>Тип</th><th>Время</th><th>Что</th><th></th></tr></thead><tbody id="eb"></tbody></table></div>
      <div class="row" style="margin-top:12px"><span class="grow small muted" id="gain"></span><button class="btn primary" id="apply">Собрать чистое видео →</button></div><div id="job"></div></div></div></div>`;
  const v = $('v'); let stopAt = null, jumpAt = null;
  v.ontimeupdate = () => {
    if (jumpAt && v.currentTime >= jumpAt[0]) { v.currentTime = jumpAt[1]; jumpAt = null; }
    if (stopAt && v.currentTime >= stopAt) { v.pause(); stopAt = null; }
  };
  const save = () => saveP({ edits: S.p.edits });
  const inCut = (t, onlyAcc) => S.p.edits.find(e => (onlyAcc ? e.accepted : e.accepted !== false) && t >= e.start - 0.001 && t <= e.end + 0.001);
  const draw = () => {
    const E_ = S.p.edits.filter(e => filter === 'all' || e.type === filter);
    $('eb').innerHTML = E_.map(e => `<tr class="${e.accepted === true ? 'acc' : e.accepted === false ? 'rej' : ''}" data-id="${e.id}">
      <td><span class="tag ${e.type}">${TYPE[e.type]}</span></td><td class="small">${fmt(e.start)}<br><span class="muted">${(e.end - e.start).toFixed(2)} с</span></td>
      <td>${esc(e.text)}${e.reason ? `<div class="small muted">${esc(e.reason)}</div>` : ''}</td>
      <td style="white-space:nowrap"><button class="btn sm" data-a="play">▶</button><button class="btn sm" data-a="skip">⏭</button>
      <button class="btn sm ${e.accepted === true ? 'on' : ''}" data-a="yes">✓</button><button class="btn sm ${e.accepted === false ? 'off' : ''}" data-a="no">✗</button></td></tr>`).join('');
    const acc = S.p.edits.filter(e => e.accepted), pend = S.p.edits.filter(e => e.accepted == null);
    $('cnt').textContent = `${S.p.edits.length} правок · принято ${acc.length} · ждут ${pend.length}`;
    $('gain').textContent = `Вырежется ≈ ${acc.reduce((s, e) => s + e.end - e.start, 0).toFixed(1)} с`;
    $('tr').innerHTML = W.map((w, i) => { const m = (w.start + w.end) / 2; const c = inCut(m, true) ? 'cut' : inCut(m, false) ? 'sugg' : '';
      return `<span class="${c}" data-t="${w.start}">${esc(w.text)}</span>`; }).join(' ');
    $('tr').querySelectorAll('span').forEach(s => s.onclick = () => { v.currentTime = +s.dataset.t; v.play(); });
    $('eb').querySelectorAll('tr').forEach(tr => tr.querySelectorAll('button').forEach(b => b.onclick = () => {
      const e = S.p.edits.find(x => x.id === tr.dataset.id); const a = b.dataset.a;
      if (a === 'play') { jumpAt = null; v.currentTime = Math.max(0, e.start - 1.0); stopAt = e.end + 0.8; v.play(); }
      else if (a === 'skip') { v.currentTime = Math.max(0, e.start - 1.5); jumpAt = [e.start, e.end]; stopAt = e.end + 1.5; v.play(); }
      else { e.accepted = a === 'yes' ? (e.accepted === true ? null : true) : (e.accepted === false ? null : false); save(); draw(); }
    }));
  };
  $('flt').onchange = () => { filter = $('flt').value; draw(); };
  $('accAll').onclick = () => { S.p.edits.forEach(e => { if (filter === 'all' || e.type === filter) e.accepted = true; }); save(); draw(); };
  $('rejAll').onclick = () => { S.p.edits.forEach(e => { if (filter === 'all' || e.type === filter) e.accepted = false; }); save(); draw(); };
  $('refind').onclick = async () => { if (await ask('Найти правки заново по текущим «Моим правилам»? Решения ✓/✗ сбросятся.', [['Отмена', false], ['Найти', true, 'primary']])) { S.p = await api(`/api/projects/${S.pid}/refind`, { json: {} }); draw(); } };
  $('apply').onclick = async () => {
    const pend = S.p.edits.filter(e => e.accepted == null).length;
    if (pend && !(await ask(`${pend} правок без решения — они <b>не</b> будут применены. Продолжить?`, [['Назад', false], ['Собрать', true, 'primary']]))) return;
    $('apply').disabled = true;
    try { const r = await pollJob(await api(`/api/projects/${S.pid}/apply_cuts`, { json: {} }), $('job'));
      toast(`Чистое видео: ${fmt(r.duration)}, кусков: ${r.ranges}`); await openProject(S.pid); go('montage'); }
    catch (e) { toast(e.message); } finally { $('apply').disabled = false; }
  };
  draw();
}

// ================================================================ 3. Монтаж
let player = null;
function stopPlayer() { if (player) { player.stop(); player = null; } }

async function ensureEngine() {
  if (S.fonts.length) return;
  S.fonts = await api('/api/fonts');
  await E.loadFonts(S.fonts); await E.loadEmoji();
  await Promise.all(S.fonts.map(f => E.ensureFont(f.family)));
}
function hookLen() { return S.p.hook ? S.p.hook.end - S.p.hook.start : 0; }
function segments() {
  const segs = []; let t = 0;
  if (S.p.hook) { const L = hookLen(); segs.push({ t0: 0, t1: L, src0: S.p.hook.start, zoom: 1.2, hook: true }); t = L; }
  for (const pc of S.p.punch || []) { const L = pc.end - pc.start; segs.push({ t0: t, t1: t + L, src0: pc.start, zoom: pc.zoom, ref: pc }); t += L; }
  return segs;
}
function totalDur() { const s = segments(); return s.length ? s[s.length - 1].t1 : 0; }
function captionStyle() {
  const pr = S.presets.find(x => x.id === S.p.caption_preset) || S.presets[0];
  const st = { ...(pr?.style || {}) };
  const cs_ = S.p.caption_style || {};
  const scale = cs_.scale ?? S.rules?.caption_font_scale ?? 1;
  st.fontSize = Math.round((st.fontSize || 92) * scale);
  const pos = cs_.position || S.rules?.caption_position; if (pos) st.position = pos;
  if (cs_.emojiAuto != null) st.emojiAuto = cs_.emojiAuto;
  st.safeZone = true;
  return st;
}
function phrases() {
  if (S.p.phrases_override?.length) return S.p.phrases_override;
  return E.buildPhrases(S.words.final, { maxWords: captionStyle().maxWords || 3 });
}
function scene() { return E.compile(phrases(), captionStyle(), 1080, 1920, totalDur(), null); }

async function pgMontage() {
  if (S.p.stages.cleanup !== 'done') { main.innerHTML = `<div class="page"><h1>Монтаж</h1><p class="sub">Сначала соберите чистое видео в «Чистке».</p><button class="btn primary" id="b">К чистке</button></div>`; $('b').onclick = () => go('cleanup'); return; }
  await ensureEngine();
  S.p = await api(`/api/projects/${S.pid}`);
  [S.presets, S.words, S.styles, S.music] =await Promise.all([api('/api/presets'), api(`/api/projects/${S.pid}/words`), api('/api/styles'), api('/api/music')]);
  S.lib = S.lib || []; api('/api/motion/library').then(l => { S.lib = l; }).catch(() => {});   // библиотека грузится в фоне
  S.rules = (await api('/api/rules')).params;
  main.innerHTML = `<div class="page"><div class="row"><div class="grow"><h1>Монтаж</h1><p class="sub">Хук, punch-in, субтитры, графика на словах, музыка. Клик по видео-куску на таймлайне — вкл/выкл punch-in, графику можно тянуть.</p></div>
      <button class="btn" id="rPrev">Превью 720p</button><button class="btn primary" id="rFin">Финал 1080×1920</button></div><div id="job"></div>
    <div class="montage"><div><div class="stage" id="stage"><video id="pv" src="/api/projects/${S.pid}/file/clean.mp4" preload="auto" playsinline></video>
        <div class="ov" id="ov"></div><canvas id="cv" width="1080" height="1920"></canvas><div class="safe" id="safe" hidden></div></div>
      <div class="ctrls"><button class="btn sm" id="play">▶</button><span class="small" id="tm">0:00.0</span><span class="grow"></span><label class="small"><input type="checkbox" id="safeT"> зона UI</label></div></div>
    <div><div class="tabs" id="tabs"><button data-t="cap" class="active">Субтитры</button><button data-t="hook">Хук</button><button data-t="gfx">Графика</button><button data-t="mus">Музыка и стиль</button></div><div id="tab"></div></div></div>
    <canvas id="timeline"></canvas><div class="hint">Дорожки: видео (розовый — хук, фиолетовый — punch-in), субтитры, моушн (зелёный — принято, жёлтый — предложено), музыка.</div></div>`;
  const fx = (await fetch(`/api/projects/${S.pid}/file/face.json`).then(r => r.json()).catch(() => ({ cx: .5, cy: .4 })));
  $('pv').style.setProperty('--fx', `${fx.cx * 100}%`); $('pv').style.setProperty('--fy', `${fx.cy * 100}%`);
  $('safeT').onchange = () => { $('safe').hidden = !$('safeT').checked; };
  let tab = 'cap';
  $('tabs').querySelectorAll('button').forEach(b => b.onclick = () => { tab = b.dataset.t; $('tabs').querySelectorAll('button').forEach(x => x.classList.toggle('active', x === b)); drawTab(); });
  player = makePlayer();
  const changed = async (fields, recompile = true) => { await saveP(fields); if (recompile) player.recompile(); };

  function drawTab() {
    const el = $('tab');
    if (tab === 'cap') {
      const ph = phrases();
      el.innerHTML = `<div class="row"><select id="pre">${S.presets.map(p => `<option value="${p.id}">${esc(p.name)}${p.builtin ? '' : ' (мой)'}</option>`).join('')}</select>
        <label class="small">Размер <input type="number" id="sc" step="0.05" min="0.5" max="2" style="width:70px" value="${S.p.caption_style?.scale ?? S.rules.caption_font_scale}"></label>
        <select id="pos"><option value="">позиция пресета</option><option value="top">вверху</option><option value="center">по центру</option><option value="bottom">внизу</option></select>
        <label class="small"><input type="checkbox" id="emo"> авто-эмодзи</label>
        <button class="btn sm" id="resplit">Пересобрать фразы</button></div>
        <p class="hint">Клик по слову — ключевое слово (цвет). Двойной клик по фразе — правка текста. Правый клик по слову — эмодзи.</p>
        <div class="list" id="phl">${ph.map((p, i) => `<div class="item phrase" data-i="${i}"><span class="small muted" style="width:52px">${fmt(p.words[0].start)}</span><span class="grow">${p.words.map((w, j) => `<span class="w ${w.hl ? 'hl' : ''}" data-j="${j}">${esc(w.text)}${w.emoji ? ' ' + w.emoji : ''}</span>`).join(' ')}</span></div>`).join('')}</div>`;
      $('pre').value = S.p.caption_preset; $('pos').value = S.p.caption_style?.position || ''; $('emo').checked = !!S.p.caption_style?.emojiAuto;
      $('pre').onchange = () => changed({ caption_preset: $('pre').value });
      const cst = () => ({ ...(S.p.caption_style || {}), scale: +$('sc').value, position: $('pos').value, emojiAuto: $('emo').checked });
      $('sc').onchange = $('pos').onchange = $('emo').onchange = () => changed({ caption_style: cst() });
      $('resplit').onclick = async () => { await changed({ phrases_override: null }); drawTab(); };
      const commit = async list => { await changed({ phrases_override: list }); drawTab(); };
      $('phl').querySelectorAll('.phrase').forEach(row => {
        const i = +row.dataset.i;
        row.querySelectorAll('.w').forEach(s => {
          s.onclick = () => { const list = structuredClone(phrases()); const w = list[i].words[+s.dataset.j]; w.hl = !w.hl; commit(list); };
          s.oncontextmenu = async ev => { ev.preventDefault(); const em = prompt('Эмодзи для слова (пусто — убрать):', ''); if (em === null) return;
            const list = structuredClone(phrases()); list[i].words[+s.dataset.j].emoji = em.trim() || undefined; commit(list); };
        });
        row.ondblclick = () => {
          const list = structuredClone(phrases()); const p = list[i];
          const txt = prompt('Текст фразы:', p.words.map(w => w.text).join(' ')); if (txt == null) return;
          const parts = txt.trim().split(/\s+/).filter(Boolean); if (!parts.length) { list.splice(i, 1); return commit(list); }
          if (parts.length === p.words.length) parts.forEach((t, k) => p.words[k].text = t);
          else { const s0 = p.words[0].start, e0 = p.words[p.words.length - 1].end, tot = parts.reduce((a, t) => a + t.length, 0); let t = s0;
            p.words = parts.map(x => { const d = (e0 - s0) * x.length / tot; const w = { text: x, start: +t.toFixed(2), end: +(t + d).toFixed(2) }; t += d; return w; }); }
          commit(list);
        };
        row.querySelector('.small').onclick = () => player.seek(phrases()[i].words[0].start);
      });
    } else if (tab === 'hook') {
      const hs = S.words.hooks || [];
      el.innerHTML = `<p class="hint">Самая сильная фраза (числа, вопрос, «ошибка», «секрет»…) копируется в начало ролика с punch-in. Можно выбрать другую или отключить.</p>
        <div class="list">${[{ text: 'Без хука', none: true }, ...hs].map((h, i) => `<label class="item ${S.p.hook && !h.none && Math.abs(S.p.hook.start - h.start) < .01 || (!S.p.hook && h.none) ? 'acc' : ''}"><input type="radio" name="hk" value="${i}" ${S.p.hook && !h.none && Math.abs(S.p.hook.start - h.start) < .01 || (!S.p.hook && h.none) ? 'checked' : ''}>
          <span class="grow">${esc(h.text)}</span>${h.none ? '' : `<span class="small muted">${fmt(h.start)} · ${(h.end - h.start).toFixed(1)} с · оценка ${h.score}</span>`}</label>`).join('')}</div>`;
      el.querySelectorAll('input[name=hk]').forEach(r => r.onchange = async () => {
        const h = [{ none: true }, ...hs][+r.value];
        await saveP({ hook: h.none ? null : { start: h.start, end: h.end, text: h.text }, phrases_override: null });
        S.words = await api(`/api/projects/${S.pid}/words`); player.recompile(); drawTab();
      });
    } else if (tab === 'gfx') {
      const M = S.p.motion || [];
      el.innerHTML = `<p class="hint">Я предлагаю графику на словах (числа, названия, призыв в конце). ✓ — поставить, ✗ — убрать. Время — в секундах ролика без хука. Клипы — из Моушн-студии.</p>
        <div class="list">${M.map((g, i) => `<div class="item ${g.accepted ? 'acc' : g.accepted === false ? 'rej' : ''}" data-i="${i}">
          <span class="tag">${g.source === 'clip' ? 'клип' : { number: 'число', title: 'название', cta: 'CTA' }[g.kind] || g.kind}</span>
          ${g.source === 'clip' ? `<span class="grow small">${esc(g.name)}</span>` : `<input type="text" data-k="text" value="${esc(g.text)}">`}
          <input type="number" data-k="t" step="0.1" style="width:72px" value="${g.t}"><input type="number" data-k="dur" step="0.1" style="width:60px" value="${g.dur}">
          <button class="btn sm ${g.accepted ? 'on' : ''}" data-a="yes">✓</button><button class="btn sm ${g.accepted === false ? 'off' : ''}" data-a="no">✗</button></div>`).join('') || '<p class="muted">Предложений нет.</p>'}</div>
        <div class="row" style="margin-top:12px"><select id="addKind"><option value="title">+ название</option><option value="number">+ число</option><option value="cta">+ CTA</option></select><input type="text" id="addText" placeholder="Текст" class="grow"><button class="btn sm" id="add">Добавить на текущее время</button></div>
        <div class="row" style="margin-top:8px"><select id="clip" class="grow">${S.lib.map((c, i) => `<option value="${i}">${esc(c.name)} · ${c.mode === 'alpha' ? 'прозрачный' : c.mode === 'green' ? 'хромакей' : 'полный кадр'} · ${c.duration ?? '?'} с</option>`).join('') || '<option>Библиотека пуста</option>'}</select><button class="btn sm" id="addClip">+ Клип из библиотеки</button></div>
        <div class="row small muted" style="margin-top:8px">Моушн-студия: <span id="mst">…</span><button class="btn sm" id="mStart">Открыть Моушн-студию</button></div>`;
      api('/api/motion/status').then(s => $('mst').textContent = s.running ? 'запущена' : 'не запущена');
      $('mStart').onclick = async () => { const s = await api('/api/motion/start', { json: {} }); setTimeout(() => window.open(s.url, '_blank'), s.running ? 0 : 6000); toast(s.running ? 'Открываю' : 'Запускаю Моушн-студию… Готовые клипы из её output\\ появятся здесь.'); };
      const upd = () => changed({ motion: M });
      el.querySelectorAll('.item').forEach(row => { const g = M[+row.dataset.i];
        row.querySelectorAll('input').forEach(inp => inp.onchange = () => { g[inp.dataset.k] = inp.type === 'number' ? +inp.value : inp.value; upd(); });
        row.querySelectorAll('button').forEach(b => b.onclick = () => { g.accepted = b.dataset.a === 'yes' ? (g.accepted ? null : true) : (g.accepted === false ? null : false); upd(); drawTab(); });
      });
      const nowClean = () => Math.max(0, player.time() - hookLen());
      $('add').onclick = () => { if (!$('addText').value.trim()) return toast('Введите текст');
        M.push({ id: Math.random().toString(36).slice(2, 10), kind: $('addKind').value, text: $('addText').value.trim().toUpperCase(), t: +nowClean().toFixed(2), dur: 1.8, y: 0.2, source: 'card', accepted: true }); upd(); drawTab(); };
      $('addClip').onclick = () => { const c = S.lib[+$('clip').value]; if (!c) return;
        M.push({ id: Math.random().toString(36).slice(2, 10), kind: 'clip', name: c.name, file: c.file, mode: c.mode, t: +nowClean().toFixed(2), dur: Math.min(c.duration || 2, 4), y: 0.3, source: 'clip', accepted: true }); upd(); drawTab(); };
    } else {
      el.innerHTML = `<div class="row"><label class="small">Стиль монтажа</label><select id="sty">${S.styles.map(s => `<option value="${s.name}">${esc(s.title || s.name)}</option>`).join('')}</select></div>
        <div class="row" style="margin-top:10px"><label><input type="checkbox" id="men"> Музыка</label><select id="mf">${S.music.map(m => `<option value="${esc(m.file)}">${esc(m.file)} (${m.source === 'kit' ? 'кит' : 'моушн-студия'})</option>`).join('')}</select>
          <label class="small">Громкость <input type="number" id="mv" step="0.02" min="0" max="1" style="width:70px" value="${S.p.music.volume}"></label><button class="btn sm" id="mplay">▶ послушать</button></div>
        <div class="row" style="margin-top:10px"><label><input type="checkbox" id="sfx"> Звуки на графике и хуке (whoosh, pop)</label></div>
        <p class="hint">Музыка приглушается под голосом (ducking), итог нормализуется до ${S.rules.lufs} LUFS. Punch-in в стиле: ×${S.rules.punch_in}.</p><audio id="aud"></audio>`;
      $('sty').value = S.p.style; $('men').checked = S.p.music.enabled; $('mf').value = S.p.music.file; $('sfx').checked = S.p.sfx !== false;
      $('sty').onchange = () => changed({ style: $('sty').value }, false);
      const mus = () => changed({ music: { file: $('mf').value, volume: +$('mv').value, enabled: $('men').checked } }, false);
      $('men').onchange = $('mf').onchange = $('mv').onchange = mus;
      $('sfx').onchange = () => changed({ sfx: $('sfx').checked }, false);
      $('mplay').onclick = () => { const a = $('aud'); if (!a.paused) return a.pause(); a.src = `/api/music/file?name=${encodeURIComponent($('mf').value)}`; a.volume = Math.min(1, +$('mv').value * 3); a.play(); };
    }
  }
  drawTab();
  $('rPrev').onclick = () => doRender('preview');
  $('rFin').onclick = () => doRender('final');
}

// Согласование анимаций: без «Подходит» анимация в рендер не попадает.
async function reviewMotion() {
  S.p = await api(`/api/projects/${S.pid}`);
  const M = S.p.motion || [];
  const pend = M.filter(g => g.accepted == null);
  if (!pend.length) return true;
  if (!S.lib?.length) S.lib = await api('/api/motion/library').catch(() => []);
  for (let i = 0; i < pend.length; i++) {
    const g = pend[i];
    const prev = g.source === 'clip'
      ? `<video src="${media(g.file)}" autoplay loop muted style="width:100%;max-height:300px;background:#000;border-radius:8px"></video>`
      : `<div style="background:#000;border-radius:8px;padding:14px;text-align:center"><img src="/api/projects/${S.pid}/card/${g.id}?v=${encodeURIComponent(g.text)}" style="max-width:100%;max-height:220px"></div>`;
    const ctx = (S.words?.clean || []).filter(w => w.start >= g.t - 2 && w.start <= g.t + 2.5).map(w => w.start >= g.t - 0.05 && w.start <= g.t + 0.05 ? `<b>${esc(w.text)}</b>` : esc(w.text)).join(' ');
    const ans = await ask(`<h3 style="margin-top:0">Анимация ${i + 1} из ${pend.length}: подходит к ролику?</h3>${prev}
      <p class="small">На ${fmt(g.t)} (${g.dur} с), слова: «…${ctx}…»</p>
      <div class="row"><select id="rpKind"><option value="">Заменить на…</option><option value="title">карточку-название</option><option value="number">карточку-число</option><option value="cta">кнопку CTA</option>${S.lib.map((c, k) => `<option value="clip:${k}">клип: ${esc(c.name)}</option>`).join('')}</select>
      <input type="text" id="rpText" class="grow" placeholder="Текст карточки" value="${esc(g.text || '')}"></div>`,
      [['Остановить', 'stop'], ['Не подходит', 'no', 'no'], ['Заменить', 'swap'], ['Подходит', 'yes', 'primary']]);
    if (ans === 'stop') return false;
    if (ans === 'yes') g.accepted = true;
    else if (ans === 'no') g.accepted = false;
    else if (ans === 'swap') {
      const v = document.getElementById('rpKind').value, txt = document.getElementById('rpText').value.trim();
      if (v.startsWith('clip:')) { const c = S.lib[+v.slice(5)]; Object.assign(g, { source: 'clip', kind: 'clip', name: c.name, file: c.file, mode: c.mode, dur: Math.min(c.duration || 2, 4), y: 0.3 }); }
      else if (v) Object.assign(g, { source: 'card', kind: v, text: (txt || g.text || '').toUpperCase() });
      else if (txt) g.text = txt.toUpperCase();
      i--;                     // показать заменённую ещё раз на согласование
    }
    await saveP({ motion: M });
  }
  if (player) player.recompile();
  return true;
}

async function doRender(kind) {
  if (!(await reviewMotion())) return toast('Рендер отменён: не все анимации согласованы');
  const sc = scene();
  const job = await api(`/api/projects/${S.pid}/render`, { json: { kind, ass: E.toASS(sc), emojis: E.emojiOverlays(sc) } });
  toast(kind === 'final' ? 'Финал поставлен в очередь' : 'Превью поставлено в очередь');
  const el = $('job');
  try { const r = await pollJob(job, el); toast('Готово: ' + r.file); await openProject(S.pid); if (S.page === 'render') pgRender(); else go('render'); }
  catch (e) { toast(e.message); }
}

function makePlayer() {
  const v = $('pv'), cv = $('cv'), ctx = cv.getContext('2d'), ov = $('ov'), tl = $('timeline');
  let sc = scene(), segs = segments(), D = totalDur(), T = 0, playing = false, raf = 0, drag = null, boxes = [];
  const cards = new Map();
  const segAt = t => segs.find(s => t >= s.t0 && t < s.t1) || segs[segs.length - 1];
  function placeVideo(t) {
    const s = segAt(t); if (!s) return;
    const want = s.src0 + (t - s.t0);
    if (Math.abs(v.currentTime - want) > 0.12) v.currentTime = want;
    v.style.transform = `scale(${s.zoom})`;
  }
  function overlays(t) {
    const H = hookLen(); const on = (S.p.motion || []).filter(g => g.accepted && t >= g.t + H && t < g.t + H + g.dur);
    const ids = new Set(on.map(g => g.id));
    for (const [id, el] of cards) if (!ids.has(id)) { el.remove(); cards.delete(id); }
    for (const g of on) {
      let el = cards.get(g.id);
      if (!el) {
        if (g.source === 'clip') { el = document.createElement('video'); el.src = media(g.file); el.muted = true; if (g.mode === 'full') el.className = 'fullclip'; else { el.style.cssText = `position:absolute;left:50%;width:${(g.scale || 0.8) * 100}%;transform:translate(-50%,-50%)`; } }
        else { el = document.createElement('img'); el.src = `/api/projects/${S.pid}/card/${g.id}?v=${encodeURIComponent(g.text)}`; el.style.width = 'auto'; el.style.height = 'auto'; el.style.maxWidth = '92%'; el.style.zoom = '0.3'; }
        ov.append(el); cards.set(g.id, el);
      }
      const k = (t - g.t - H);
      if (g.source !== 'clip' || g.mode !== 'full') el.style.top = `${(g.y || 0.2) * 100 + Math.max(0, 1 - k / 0.18) * 3}%`;
      el.style.opacity = Math.min(1, k / 0.15, (g.dur - k) / 0.2);
      if (el.tagName === 'VIDEO') { if (Math.abs(el.currentTime - k) > 0.2) el.currentTime = k; playing ? el.play().catch(() => {}) : el.pause(); }
    }
  }
  function frame() {
    if (playing) {
      const s = segAt(T);
      T = s.t0 + (v.currentTime - s.src0);
      if (T >= s.t1 - 0.02) { const nx = segs[segs.indexOf(s) + 1]; if (!nx) { pause(); T = D; } else { T = nx.t0; placeVideo(T); } }
      else v.style.transform = `scale(${s.zoom})`;
    }
    ctx.clearRect(0, 0, 1080, 1920); E.drawFrame(ctx, sc, T); overlays(T);
    $('tm').textContent = `${fmt(T)} / ${fmt(D)}`; drawTimeline();
    raf = requestAnimationFrame(frame);
  }
  function play() { if (T >= D - 0.05) T = 0; placeVideo(T); v.play(); playing = true; $('play').textContent = '❚❚'; }
  function pause() { v.pause(); playing = false; $('play').textContent = '▶'; }
  $('play').onclick = () => playing ? pause() : play();
  function seek(t) { T = Math.max(0, Math.min(D, t)); placeVideo(T); }
  // ---- таймлайн
  const rows = { video: [8, 30], cap: [44, 22], mo: [72, 30], mus: [108, 14] };
  function drawTimeline() {
    const r = tl.getBoundingClientRect(); const dpr = devicePixelRatio || 1;
    if (tl.width !== Math.round(r.width * dpr)) { tl.width = Math.round(r.width * dpr); tl.height = Math.round(150 * dpr); }
    const c = tl.getContext('2d'); c.setTransform(dpr, 0, 0, dpr, 0, 0); const Wd = r.width, X = t => 60 + (Wd - 70) * t / Math.max(D, 0.1);
    c.clearRect(0, 0, Wd, 150); c.font = '11px Segoe UI'; boxes = [];
    const lab = (txt, y) => { c.fillStyle = '#8b90a0'; c.fillText(txt, 6, y); };
    lab('Видео', 27); lab('Субтитры', 59); lab('Моушн', 91); lab('Музыка', 119);
    for (const s of segs) { const x0 = X(s.t0), x1 = X(s.t1);
      c.fillStyle = s.hook ? '#9d2f6b' : s.zoom > 1.001 ? '#4c3a8a' : '#2a2e39'; c.fillRect(x0, rows.video[0], Math.max(1, x1 - x0 - 1), rows.video[1]);
      c.fillStyle = '#e8eaf0'; if (x1 - x0 > 34) c.fillText(s.hook ? 'ХУК' : s.zoom > 1.001 ? `×${s.zoom}` : '×1', x0 + 4, rows.video[0] + 19);
      if (!s.hook) boxes.push({ kind: 'seg', s, x0, x1, y0: rows.video[0], y1: rows.video[0] + rows.video[1] }); }
    for (const p of sc.phrases.filter(p => p.kind === 'main' || !p.kind)) { const x0 = X(p.start), x1 = X(p.end);
      c.fillStyle = '#1f3b4a'; c.fillRect(x0, rows.cap[0], Math.max(1, x1 - x0 - 1), rows.cap[1]); }
    const H = hookLen();
    for (const g of S.p.motion || []) { if (g.accepted === false) continue; const x0 = X(g.t + H), x1 = X(g.t + H + g.dur);
      c.fillStyle = g.accepted ? '#1f6b44' : '#7a5a17'; c.fillRect(x0, rows.mo[0], Math.max(3, x1 - x0), rows.mo[1]);
      c.fillStyle = '#fff'; if (x1 - x0 > 24) c.fillText((g.text || g.name || '').slice(0, Math.floor((x1 - x0) / 7)), x0 + 3, rows.mo[0] + 19);
      boxes.push({ kind: 'mo', g, x0, x1, y0: rows.mo[0], y1: rows.mo[0] + rows.mo[1] }); }
    if (S.p.music?.enabled) { c.fillStyle = '#2d4a2a'; c.fillRect(X(0), rows.mus[0], X(D) - X(0), rows.mus[1]); c.fillStyle = '#cfe'; c.fillText(S.p.music.file, X(0) + 4, rows.mus[0] + 11); }
    c.fillStyle = '#ffe14d'; c.fillRect(X(T) - 1, 0, 2, 150);
    tl._X = X; tl._inv = x => (x - 60) / (Wd - 70) * Math.max(D, 0.1);
  }
  tl.onmousedown = e => {
    const r = tl.getBoundingClientRect(), x = e.clientX - r.left, y = e.clientY - r.top;
    const b = boxes.find(b => x >= b.x0 && x <= b.x1 && y >= b.y0 && y <= b.y1);
    if (b?.kind === 'mo') { drag = { g: b.g, dx: tl._inv(x) - (b.g.t + hookLen()), moved: false }; return; }
    if (b?.kind === 'seg') { b.s.ref.zoom = b.s.ref.zoom > 1.001 ? 1.0 : (S.rules.punch_in || 1.15); segs = segments(); placeVideo(T); saveP({ punch: S.p.punch }).then(() => { segs = segments(); }); return; }
    seek(tl._inv(x));
  };
  window.onmousemove = e => { if (!drag) return; const r = tl.getBoundingClientRect(); drag.g.t = +Math.max(0, tl._inv(e.clientX - r.left) - drag.dx - hookLen()).toFixed(2); drag.moved = true; };
  window.onmouseup = () => { if (drag?.moved) saveP({ motion: S.p.motion }); drag = null; };
  v.onloadeddata = () => seek(T);
  raf = requestAnimationFrame(frame);
  return {
    stop() { cancelAnimationFrame(raf); pause(); window.onmousemove = window.onmouseup = null; },
    recompile() { sc = scene(); segs = segments(); D = totalDur(); for (const el of cards.values()) el.remove(); cards.clear(); seek(Math.min(T, D)); },
    seek, time: () => T,
  };
}

// ================================================================ 4. Рендер
async function pgRender() {
  await openProject(S.pid);
  const jobs = (await api('/api/jobs')).filter(j => j.kind.startsWith('render') && j.status === 'running');
  const R = [...(S.p.renders || [])].reverse();
  main.innerHTML = `<div class="page"><h1>Рендер</h1><p class="sub">Быстрое превью 720p → ваши правки → финал 1080×1920, H.264 + AAC (пресет Instagram / TikTok / Facebook из Captions Studio). Финал — в D:\\Монтаж\\output.</p>
    <div class="row"><button class="btn" id="rPrev">Превью 720p</button><button class="btn primary" id="rFin">Финал 1080×1920</button></div><div id="job" style="margin:10px 0"></div>
    ${jobs.map(j => `<div class="card" data-j="${j.id}"><b>${j.kind === 'render_final' ? 'Финал' : 'Превью'}</b><div class="jl"></div></div>`).join('')}
    <div class="grid" style="grid-template-columns:repeat(auto-fill,minmax(260px,1fr));margin-top:14px">${R.map(r => `<div class="card"><video src="${media(r.file)}" controls style="width:100%;aspect-ratio:9/16;background:#000;border-radius:8px"></video>
      <div class="row" style="margin-top:6px"><b class="grow">${r.kind === 'final' ? 'Финал' : 'Превью'}</b><span class="small muted">${fmt(r.duration)} · ${new Date(r.time * 1000).toLocaleTimeString('ru')}</span></div>
      <div class="small muted" style="word-break:break-all">${esc(r.file)}</div><button class="btn sm" data-rev="${esc(r.file)}">Показать в папке</button></div>`).join('') || '<p class="muted">Пока ничего не отрендерено.</p>'}</div>
    <div class="card" style="margin-top:16px"><b>Что поправить?</b><p class="hint">Напишите замечание («паузы длиннее», «субтитры крупнее», «не режь "смотрите"») — оно попадёт в «Мои правила» и применится ко всем следующим роликам.</p>
      <div class="row"><input type="text" id="note" class="grow" placeholder="Замечание"><button class="btn" id="addNote">Запомнить</button></div><div id="noteRes" class="small"></div></div></div>`;
  jobs.forEach(j => pollJob(j, main.querySelector(`[data-j="${j.id}"] .jl`)).then(() => pgRender()).catch(() => {}));
  main.querySelectorAll('[data-rev]').forEach(b => b.onclick = () => api('/api/reveal', { json: { path: b.dataset.rev } }));
  const need = async kind => { if (S.p.stages.cleanup !== 'done') return toast('Сначала соберите чистое видео');
    await ensureEngine(); [S.presets, S.words] = await Promise.all([api('/api/presets'), api(`/api/projects/${S.pid}/words`)]); S.rules = (await api('/api/rules')).params; doRender(kind); };
  $('rPrev').onclick = () => need('preview'); $('rFin').onclick = () => need('final');
  $('addNote').onclick = async () => { const r = await api('/api/rules/add', { json: { note: $('note').value } }); $('noteRes').textContent = r.understood.length ? 'Понял: ' + r.understood.join('; ') : 'Записал в журнал (автоматически не разобрал — учту при следующей правке).'; $('note').value = ''; };
}

// ================================================================ ★ Референсы и стили
async function pgStyles() {
  [S.styles, S.presets] = await Promise.all([api('/api/styles'), api('/api/presets')]);
  main.innerHTML = `<div class="page"><h1>Референсы и стили</h1><p class="sub">Ролики, монтаж которых нравится → замеры (склейки, темп, паузы, громкость) + кадры для просмотра → карточка стиля в D:\\Монтаж\\styles.</p>
    <div class="card"><b>Новый стиль</b><div class="row" style="margin-top:8px"><input type="text" id="stTitle" placeholder="Название стиля"><input type="text" id="stFolder" class="grow" placeholder="Папка с роликами-референсами"><button class="btn" id="stScan">Открыть</button></div>
      <div class="grid" id="stClips" style="margin-top:10px"></div><div class="row" style="margin-top:10px"><button class="btn primary" id="stGo">Разобрать выбранные</button></div><div id="stJob"></div></div>
    <div id="stList" style="display:flex;flex-direction:column;gap:14px;margin-top:16px"></div></div>`;
  let items = [], sel = new Set();
  $('stScan').onclick = async () => { const r = await scanFolder($('stFolder').value.trim()).catch(e => toast(e.message)); if (!r) return; items = r; sel.clear(); drawC(); };
  const drawC = () => { $('stClips').innerHTML = items.map(c => `<div class="card clip ${sel.has(c.path) ? 'sel' : ''}" data-p="${esc(c.path)}"><img src="/api/thumb?path=${encodeURIComponent(c.path)}"><div class="meta">${esc(c.name)}<br><span class="muted">${fmt(c.duration)}</span></div></div>`).join('');
    $('stClips').querySelectorAll('.clip').forEach(el => el.onclick = () => { sel.has(el.dataset.p) ? sel.delete(el.dataset.p) : sel.add(el.dataset.p); drawC(); }); };
  $('stGo').onclick = async () => { if (!sel.size) return toast('Выберите 2–5 роликов');
    try { await pollJob(await api('/api/styles/analyze', { json: { paths: [...sel], title: $('stTitle').value || 'Мой стиль' } }), $('stJob')); toast('Стиль сохранён'); pgStyles(); } catch (e) { toast(e.message); } };
  $('stList').innerHTML = S.styles.map(s => `<div class="card" data-n="${s.name}"><div class="row"><b class="grow">${esc(s.title || s.name)}</b>${s.builtin ? '<span class="chip">встроенный</span>' : `<span class="chip">styles\\${esc(s.name)}.json</span>`}</div>
    ${s.metrics ? `<div class="kv" style="margin-top:8px"><div>Средний план</div><div>${s.metrics.avg_shot} с (${s.metrics.cuts_per_10s} склеек / 10 с)</div><div>Темп речи</div><div>${s.metrics.wpm} слов/мин</div>
      <div>Паузы</div><div>в среднем ${s.metrics.pause_avg} с, p90 ${s.metrics.pause_p90} с</div><div>Громкость</div><div>${s.metrics.lufs} LUFS, музыка ниже голоса на ${s.metrics.music_under_voice_db ?? '—'} дБ</div><div>SFX</div><div>${s.metrics.sfx_per_10s} на 10 с</div></div>` : ''}
    ${(s.refs || []).map(r => `<div style="margin-top:10px"><div class="small muted">${esc(r.name)} · ${fmt(r.duration)} · хук: «${esc(r.first_words)}»</div><img class="sheet" src="/api/img?path=${encodeURIComponent(r.sheet)}"></div>`).join('')}
    <div style="margin-top:10px">${['captions', 'zoom', 'plates', 'hook', 'cta'].map(k => `<div class="row" style="margin-top:4px"><span class="small muted" style="width:90px">${{ captions: 'Субтитры', zoom: 'Зумы', plates: 'Плашки', hook: 'Хук', cta: 'CTA' }[k]}</span><input type="text" class="grow" data-v="${k}" value="${esc(s.visual?.[k] || '')}" ${s.builtin ? 'disabled' : ''}></div>`).join('')}</div>
    <div class="row" style="margin-top:8px"><span class="small muted" style="width:90px">Пресет субтитров</span><select data-pre ${s.builtin ? 'disabled' : ''}>${S.presets.map(p => `<option value="${p.id}" ${p.id === s.params?.caption_preset ? 'selected' : ''}>${esc(p.name)}</option>`).join('')}</select>
      <span class="small muted">Параметры: пауза от ${s.params?.pause_min} с · punch-in ×${s.params?.punch_in} · музыка ${s.params?.music_volume}</span></div>
    ${s.builtin ? '' : `<div class="row" style="margin-top:8px"><textarea data-sum rows="2" placeholder="Кратко о стиле">${esc(s.summary || '')}</textarea><button class="btn sm" data-save>Сохранить</button></div>`}
    ${s.builtin ? `<p class="small muted">${esc(s.summary)}</p>` : ''}</div>`).join('');
  $('stList').querySelectorAll('[data-save]').forEach(b => b.onclick = async () => { const card = b.closest('[data-n]'); const st = S.styles.find(x => x.name === card.dataset.n);
    const visual = {}; card.querySelectorAll('[data-v]').forEach(i => visual[i.dataset.v] = i.value);
    await api(`/api/styles/${st.name}`, { method: 'PUT', json: { visual, summary: card.querySelector('[data-sum]').value, params: { ...st.params, caption_preset: card.querySelector('[data-pre]').value } } }); toast('Сохранено'); });
}

// ================================================================ ✎ Мои правила
async function pgRules() {
  const r = await api('/api/rules');
  main.innerHTML = `<div class="page"><h1>Мои правила</h1><p class="sub">Всё, что вы поправляете, записывается в <code>${esc(r.file)}</code> и применяется ко всем следующим роликам. Параметры для программы — в блоке json.</p>
    <div class="row"><input type="text" id="note" class="grow" placeholder="Например: паузы длиннее · субтитры крупнее · не режь «смотрите» · музыку тише"><button class="btn primary" id="add">Добавить правило</button></div><div id="res" class="small" style="margin:6px 0 12px"></div>
    <textarea id="txt" rows="26">${esc(r.text)}</textarea><div class="row" style="margin-top:8px"><button class="btn primary" id="save">Сохранить</button><span class="small muted" id="st"></span></div></div>`;
  $('add').onclick = async () => { if (!$('note').value.trim()) return; const x = await api('/api/rules/add', { json: { note: $('note').value } });
    $('res').textContent = x.understood.length ? 'Понял: ' + x.understood.join('; ') : 'Записал в журнал (параметры не изменились).'; $('txt').value = x.text; $('note').value = ''; };
  $('save').onclick = async () => { try { await api('/api/rules', { method: 'PUT', json: { text: $('txt').value } }); $('st').textContent = 'Сохранено'; } catch (e) { $('st').textContent = e.message; } };
}

// ================================================================ старт
(async () => {
  const info = await api('/api/info').catch(() => ({}));
  $('chips').innerHTML = [[info.gpu ? info.gpu.replace('NVIDIA GeForce ', '') : 'CPU', !!info.gpu], ['ffmpeg', info.ffmpeg], ['Captions Studio', info.captions], ['Моушн-студия', info.motion?.running], ['кит монтажа', info.kit]]
    .map(([n, ok]) => `<span class="chip ${ok ? 'ok' : 'bad'}">${esc(n)}</span>`).join('');
  let pid = null; try { pid = localStorage.getItem('mt_pid'); } catch {}
  if (pid) { try { await openProject(pid); } catch { S.pid = null; } }
  go('projects');
})();
