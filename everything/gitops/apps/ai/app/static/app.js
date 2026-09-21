const $ = s => document.querySelector(s);

function applyTheme(t) {
  document.documentElement.dataset.theme = t;
  try { localStorage.setItem('theme', t); } catch (_) {}
  const d = document.getElementById('hljs-dark');
  const l = document.getElementById('hljs-light');
  if (d && l) { d.disabled = t === 'light'; l.disabled = t !== 'light'; }
}

function bindTheme() {
  const btn = $('#theme-toggle');
  if (!btn) return;
  applyTheme(document.documentElement.dataset.theme || 'dark');
  btn.onclick = () => {
    const cur = document.documentElement.dataset.theme || 'dark';
    applyTheme(cur === 'dark' ? 'light' : 'dark');
  };
}

function render(md) {
  const html = marked.parse(md || '', { breaks: true, gfm: true });
  return DOMPurify.sanitize(html);
}

function highlight(root) {
  root.querySelectorAll('pre code').forEach(el => {
    if (!el.dataset.highlighted) {
      hljs.highlightElement(el);
      el.dataset.highlighted = '1';
    }
  });
}

function fmtCost(n) {
  n = Number(n || 0);
  if (n >= 1) return '$' + n.toFixed(2);
  return '$' + n.toFixed(4);
}

function fmtTok(n) {
  n = Number(n || 0);
  if (n >= 1e6) return (n / 1e6).toFixed(1) + 'M';
  if (n >= 1e3) return (n / 1e3).toFixed(1) + 'K';
  return String(n);
}

function tokTitle(x) {
  return [
    '입력 ' + fmtTok(x.input),
    '출력 ' + fmtTok(x.output),
    '캐시쓰기 ' + fmtTok(x.cache_write),
    '캐시읽기 ' + fmtTok(x.cache_read),
  ].join(' · ');
}

function usageBlock(label, x) {
  const reqs = x.requests || 0;
  return '<div class="usage-block" title="' + tokTitle(x) + '">' +
    '<span class="label">' + label + '</span>' +
    '<span class="val">' + reqs + '회 · ' + fmtCost(x.cost) + '</span>' +
    '</div>';
}

async function refreshStats() {
  try {
    const s = await fetch('/api/stats').then(r => r.json());
    const t = s.today || {};
    const a = s.total || {};
    $('#usage').innerHTML = usageBlock('오늘', t) + usageBlock('누적', a);
  } catch {}
}

// ── Sidebar / History ─────────────────────────────────

let currentHistoryId = null;

function toggleSidebar(show) {
  const sb = $('#sidebar');
  if (show === undefined) show = sb.classList.contains('collapsed');
  sb.classList.toggle('collapsed', !show);
  try { localStorage.setItem('sidebar', show ? 'open' : 'closed'); } catch (_) {}
}

function initSidebar() {
  const saved = localStorage.getItem('sidebar');
  const sb = $('#sidebar');
  if (saved === 'closed') sb.classList.add('collapsed');

  $('#sidebar-open').onclick = () => toggleSidebar(true);
  $('#sidebar-close').onclick = () => toggleSidebar(false);
  $('#new-chat').onclick = () => newChat();
}

function formatHistoryDate(iso) {
  const d = new Date(iso);
  const now = new Date();
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  const itemDate = new Date(d.getFullYear(), d.getMonth(), d.getDate());
  const diff = (today - itemDate) / (1000 * 60 * 60 * 24);

  if (diff === 0) return '오늘';
  if (diff === 1) return '어제';
  if (diff <= 7) return '이번 주';
  if (diff <= 30) return '이번 달';
  return d.getFullYear() + '년 ' + (d.getMonth() + 1) + '월';
}

async function loadHistory() {
  const list = $('#history-list');
  try {
    const items = await fetch('/api/history').then(r => r.json());
    if (!items.length) {
      list.innerHTML = '<div class="history-empty">대화 기록이 없습니다</div>';
      return;
    }

    let html = '';
    let lastGroup = '';
    for (const item of items) {
      const group = formatHistoryDate(item.updated_at || item.created_at);
      if (group !== lastGroup) {
        html += '<div class="history-date-group">' + group + '</div>';
        lastGroup = group;
      }
      const active = item.id === currentHistoryId ? ' active' : '';
      const title = DOMPurify.sanitize(item.title || '(제목 없음)');
      html += '<div class="history-item' + active + '" data-id="' + item.id + '">' +
        '<span class="history-title">' + title + '</span>' +
        '<button class="history-delete" title="삭제" data-id="' + item.id + '">' +
          '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M3 6h18M19 6v14a2 2 0 01-2 2H7a2 2 0 01-2-2V6m3 0V4a2 2 0 012-2h4a2 2 0 012 2v2"/></svg>' +
        '</button>' +
        '</div>';
    }
    list.innerHTML = html;

    // Bind clicks
    list.querySelectorAll('.history-item').forEach(el => {
      el.addEventListener('click', (e) => {
        if (e.target.closest('.history-delete')) return;
        viewHistory(el.dataset.id);
      });
    });
    list.querySelectorAll('.history-delete').forEach(btn => {
      btn.addEventListener('click', (e) => {
        e.stopPropagation();
        deleteHistory(btn.dataset.id);
      });
    });
  } catch {
    list.innerHTML = '<div class="history-empty">불러오기 실패</div>';
  }
}

function appendUserMsg(text) {
  const el = document.createElement('div');
  el.className = 'msg user';
  el.textContent = text;
  $('#output').appendChild(el);
  return el;
}

function appendAssistantMsg(markdownOrNull, meta) {
  const output = $('#output');
  const asst = document.createElement('div');
  asst.className = 'msg assistant';
  if (markdownOrNull == null) {
    asst.innerHTML = '<span class="thinking-dots" aria-label="생각 중"><span></span><span></span><span></span></span>';
  } else {
    asst.innerHTML = render(markdownOrNull);
    highlight(asst);
  }
  output.appendChild(asst);
  const metaEl = document.createElement('div');
  metaEl.className = 'meta';
  if (meta) {
    const parts = [];
    if (meta.cost_usd != null) parts.push(fmtCost(meta.cost_usd));
    if (meta.duration_ms != null) parts.push((meta.duration_ms / 1000).toFixed(1) + 's');
    metaEl.textContent = parts.join(' · ');
  }
  output.appendChild(metaEl);
  return { asst, metaEl };
}

async function viewHistory(id) {
  try {
    const data = await fetch('/api/history/' + id).then(r => {
      if (!r.ok) throw new Error(r.status);
      return r.json();
    });
    currentHistoryId = id;

    const output = $('#output');
    output.innerHTML = '';

    const turns = data.turns || [];
    for (let i = 0; i < turns.length; i++) {
      const t = turns[i];
      if (t.role === 'user') {
        appendUserMsg(t.content || '');
      } else {
        appendAssistantMsg(t.content || '', {
          cost_usd: t.cost_usd, duration_ms: t.duration_ms,
        });
      }
    }

    output.scrollTop = 0;
    $('#status').textContent = '이어서 질문하면 이 대화가 계속됩니다';
    $('#prompt').value = '';

    // Update active state in sidebar
    document.querySelectorAll('.history-item').forEach(el => {
      el.classList.toggle('active', el.dataset.id === id);
    });

    // Mobile: close sidebar after selecting
    if (window.innerWidth <= 768) toggleSidebar(false);
  } catch {
    $('#status').textContent = '기록을 불러올 수 없습니다';
  }
}

async function deleteHistory(id) {
  try {
    await fetch('/api/history/' + id, { method: 'DELETE' });
    if (currentHistoryId === id) {
      currentHistoryId = null;
      newChat();
    }
    loadHistory();
  } catch {}
}

function newChat() {
  currentHistoryId = null;
  const output = $('#output');
  output.innerHTML = '<div class="placeholder">Claude Opus에게 무엇이든 물어보세요.</div>';
  $('#status').textContent = '';
  $('#prompt').value = '';
  $('#prompt').focus();
  document.querySelectorAll('.history-item').forEach(el => el.classList.remove('active'));
}

// ── Main init ─────────────────────────────────────────

async function init() {
  bindTheme();
  let me;
  try {
    me = await fetch('/api/me').then(r => r.json());
  } catch {
    me = { authenticated: false };
  }
  if (!me.authenticated) {
    document.body.classList.add('logged-out');
    $('#login').hidden = false;
    return;
  }
  document.body.classList.add('logged-in');
  $('#me').innerHTML = me.email + ' · <a href="#" id="logout">로그아웃</a>';
  $('#logout').onclick = async e => {
    e.preventDefault();
    try {
      await fetch('/auth/logout', { method: 'POST', redirect: 'manual', credentials: 'same-origin' });
    } catch (_) {}
    window.location.replace('/');
  };
  $('#app').hidden = false;
  initSidebar();
  refreshStats();
  loadHistory();
  attach();
}

function attach() {
  const form = $('#composer');
  const promptEl = $('#prompt');
  const filesInput = $('#files');
  const fileList = $('#file-list');
  const output = $('#output');
  const sendBtn = $('#send');
  const cancelBtn = $('#cancel');
  const status = $('#status');

  promptEl.addEventListener('keydown', e => {
    if (e.key === 'Enter' && !e.shiftKey && !e.isComposing) {
      e.preventDefault();
      form.requestSubmit();
    }
  });

  filesInput.addEventListener('change', () => {
    fileList.textContent = [...filesInput.files].map(f => f.name).join(', ');
  });

  let ctrl = null;
  cancelBtn.onclick = () => ctrl && ctrl.abort();

  form.addEventListener('submit', async e => {
    e.preventDefault();
    const p = promptEl.value.trim();
    if (!p) return;

    // currentHistoryId set → continue that conversation (append, keep
    // transcript visible). Null → fresh conversation (clear screen); the
    // server-assigned id arrives via the `conversation` SSE event.
    const continuing = !!currentHistoryId;

    const sentFiles = [...filesInput.files];
    promptEl.value = '';
    filesInput.value = '';
    fileList.textContent = '';

    if (!continuing) output.innerHTML = '';
    appendUserMsg(p);
    const { asst, metaEl: meta } = appendAssistantMsg(null);
    output.scrollTop = output.scrollHeight;

    const fd = new FormData();
    fd.append('prompt', p);
    if (currentHistoryId) fd.append('conversation_id', currentHistoryId);
    for (const f of sentFiles) fd.append('files', f);

    sendBtn.disabled = true;
    cancelBtn.hidden = false;
    status.textContent = '생각 중...';

    ctrl = new AbortController();
    let acc = '';

    try {
      const resp = await fetch('/api/ask', {
        method: 'POST', body: fd, signal: ctrl.signal,
      });
      if (!resp.ok) {
        const t = await resp.text();
        throw new Error(resp.status + ' ' + t);
      }
      const reader = resp.body.getReader();
      const decoder = new TextDecoder();
      let buf = '';
      while (true) {
        const { value, done } = await reader.read();
        if (done) break;
        buf += decoder.decode(value, { stream: true });
        const parts = buf.split('\n\n');
        buf = parts.pop();
        for (const part of parts) {
          const lines = part.split('\n');
          const evLine = lines.find(l => l.startsWith('event: '));
          const dataLine = lines.find(l => l.startsWith('data: '));
          if (!evLine || !dataLine) continue;
          const ev = evLine.slice(7).trim();
          let payload;
          try { payload = JSON.parse(dataLine.slice(6)); } catch { continue; }

          if (ev === 'conversation') {
            if (payload.id) currentHistoryId = payload.id;
          } else if (ev === 'delta') {
            acc += payload.text || '';
            asst.innerHTML = render(acc);
            highlight(asst);
            output.scrollTop = output.scrollHeight;
            status.textContent = '응답 중...';
          } else if (ev === 'result') {
            if (payload.text && !acc) {
              acc = payload.text;
              asst.innerHTML = render(acc);
              highlight(asst);
            }
            const cost = payload.cost_usd != null
              ? fmtCost(payload.cost_usd) : '—';
            const secs = payload.duration_ms != null
              ? (payload.duration_ms / 1000).toFixed(1) + 's' : '—';
            meta.textContent = cost + ' · ' + secs;
            if (payload.is_error) {
              meta.textContent += ' · ⚠ error';
            }
          } else if (ev === 'error') {
            meta.textContent = '⚠ ' + payload.message;
          } else if (ev === 'end') {
            status.textContent = '완료';
            refreshStats();
            // Reload history to show new conversation
            loadHistory();
          }
        }
      }
    } catch (err) {
      if (err.name === 'AbortError') {
        status.textContent = '중지됨';
      } else {
        status.textContent = '오류: ' + err.message;
      }
    } finally {
      sendBtn.disabled = false;
      cancelBtn.hidden = true;
      ctrl = null;
      promptEl.focus();
    }
  });
}

init();
