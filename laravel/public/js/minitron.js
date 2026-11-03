(function () {
  'use strict';
  const state = { csrf: window.__MINITRON_CSRF || '', busy: false };
  const $ = (sel) => document.querySelector(sel);
  const $$ = (sel) => document.querySelectorAll(sel);
  const chatBox = $('#messages'), input = $('#chat-input'), sendBtn = $('#send-btn'), sidebar = $('#sidebar');

  $('#menu-btn')?.addEventListener('click', () => sidebar.classList.toggle('collapsed'));

  function scrollToBottom() { chatBox.scrollTop = chatBox.scrollHeight; }

  function appendUserMessage(text) {
    chatBox.classList.remove('empty');
    const es = document.querySelector('.empty-state'); if (es) es.remove();
    const el = document.createElement('div'); el.className = 'message user';
    el.innerHTML = `<div class="bubble">${escapeHtml(text)}</div>`;
    chatBox.appendChild(el); scrollToBottom();
  }

  function appendBotTyping() {
    chatBox.classList.remove('empty');
    const el = document.createElement('div'); el.className = 'message bot'; el.id = 'typing-message';
    el.innerHTML = `<div class="bubble"><div class="typing-indicator"><span></span><span></span><span></span></div></div>`;
    chatBox.appendChild(el); scrollToBottom();
  }

  function removeBotTyping() { $('#typing-message')?.remove(); }

  // --- LLM Typewriter Effect ---
  async function appendBotMessageStreaming(blocks) {
    removeBotTyping();
    const el = document.createElement('div'); 
    el.className = 'message bot';
    const bubble = document.createElement('div');
    bubble.className = 'bubble';
    el.appendChild(bubble);
    chatBox.appendChild(el);
    
    let fullText = blocks.map(b => {
      if (b.type === 'divider') return '\n---\n';
      if (b.type === 'device_header' || b.type === 'multiple_header') return `\n### ${b.content}\n`;
      return b.content || '';
    }).join('\n\n');

    let currentText = '';
    const chunkSize = 6; 

    for (let i = 0; i < fullText.length; i += chunkSize) {
      currentText += fullText.substring(i, i + chunkSize);
      bubble.innerHTML = window.marked ? marked.parse(currentText) : escapeHtml(currentText);
      scrollToBottom();
      await new Promise(r => setTimeout(r, 15));
    }
    
    bubble.innerHTML = window.marked ? marked.parse(fullText) : escapeHtml(fullText);
    scrollToBottom();
  }

  function escapeHtml(s) { const d = document.createElement('div'); d.textContent = s; return d.innerHTML; }

  async function sendSearch(query) {
    if (state.busy) return;
    state.busy = true; sendBtn.disabled = true; input.disabled = true;
    appendUserMessage(query); appendBotTyping();
    try {
      const res = await fetch('/search', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'X-CSRF-TOKEN': state.csrf, 'Accept': 'application/json' },
        body: JSON.stringify({ query }),
      });
      if (!res.ok) throw new Error(await res.text());
      const { job_id } = await res.json();
      await pollJob(job_id);
    } catch (e) {
      removeBotTyping(); 
      appendBotMessageStreaming([{ type: 'error', content: '❌ ' + e.message }]);
    } finally {
      state.busy = false; sendBtn.disabled = false; input.disabled = false; input.focus();
    }
  }

  async function pollJob(jobId) {
    for (let i = 0; i < 240; i++) {
      await new Promise(r => setTimeout(r, 1000));
      try {
        const res = await fetch(`/jobs/${jobId}`, { headers: { 'Accept': 'application/json' } });
        if (!res.ok) throw new Error(await res.text());
        const job = await res.json();
        if (job.status === 'done') { 
          await appendBotMessageStreaming(job.result?.blocks || []); 
          return; 
        }
        if (job.status === 'error') { 
          removeBotTyping(); 
          await appendBotMessageStreaming([{ type: 'error', content: '❌ ' + (job.error || 'unknown error') }]); 
          return; 
        }
      } catch (e) {}
    }
    removeBotTyping(); 
    await appendBotMessageStreaming([{ type: 'error', content: '⏱ Timed out.' }]);
  }

  sendBtn.addEventListener('click', () => {
    const q = input.value.trim(); if (!q) return;
    input.value = ''; input.style.height = 'auto'; sendSearch(q);
  });
  input.addEventListener('keydown', (e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendBtn.click(); } });
  input.addEventListener('input', () => { input.style.height = 'auto'; input.style.height = Math.min(input.scrollHeight, 200) + 'px'; });
  
  $$('.example-prompt').forEach(el => el.addEventListener('click', () => { input.value = el.dataset.prompt || el.textContent.trim(); input.focus(); }));

  async function refreshStats() {
    try {
      const res = await fetch('/admin/stats', { headers: { 'Accept': 'application/json', 'X-CSRF-TOKEN': state.csrf } });
      if (res.status === 401) return; 
      if (!res.ok) throw new Error('HTTP ' + res.status);
      
      const s = await res.json();
      const memEl = $('#memory-stats');
      if (memEl && s.memory) {
        const m = s.memory;
        const color = m.percentage < 60 ? 'success' : (m.percentage < 80 ? 'warning' : 'error');
        memEl.className = 'sidebar-status ' + color;
        memEl.innerHTML = `💾 <strong>${m.percentage}%</strong> (${m.used_mb}MB / ${m.total_mb}MB)`;
      }
      const healthEl = $('#health-stats');
      if (healthEl && s.health) {
        let h = '<strong>🔗 Connection Status:</strong><br>';
        h += s.health.ssh_tunnel ? '🟢 Connection 1 (SSH)<br>' : '🔴 Connection 1 (SSH)<br>';
        h += s.health.direct_ping ? '🟢 Connection 2 (Ping)<br>' : '🔴 Connection 2 (Ping)<br>';
        healthEl.innerHTML = h;
      }
      const selEl = $('#selenium-stats');
      if (selEl) {
        const db = s.selenium || {};
        if (db.total > 0) {
          selEl.className = 'sidebar-status success';
          selEl.innerHTML = `✅ DB: <strong>${db.total}</strong> ONTs<br>🟢 Online: ${db.online} | 🔴 Offline: ${db.offline}`;
        } else {
          selEl.className = 'sidebar-status warning';
          selEl.textContent = '⚠️ Selenium DB: Empty. Click Update.';
        }
      }
      const cdataEl = $('#cdata-stats');
      if (cdataEl) {
        const mon = s.cdata_monitor || {};
        cdataEl.className = 'sidebar-status ' + (mon.running ? 'info' : 'success');
        cdataEl.innerHTML = `📡 OLTs: <strong>${s.cdata_olt_count || 0}</strong><br>${mon.running ? '🔄 ' + (mon.progress || 'running') : (mon.last_run ? '✅ Last: ' + mon.last_run : 'ℹ️ No runs')}`;
      }
      const netEl = $('#network-info');
      if (netEl) netEl.innerHTML = `Local: <code>http://localhost:${location.port || 80}</code>`;
    } catch (e) { console.warn('stats refresh failed:', e); }
  }
  
  refreshStats(); 
  setInterval(() => { if (!document.hidden) refreshStats(); }, 3000);

  async function sidebarFetch(url, opts = {}) {
    const res = await fetch(url, { headers: { 'Accept': 'application/json', 'X-CSRF-TOKEN': state.csrf, 'Content-Type': 'application/json', ...(opts.headers || {}) }, ...opts });
    if (!res.ok) { let m = `HTTP ${res.status}`; try { m = await res.text(); } catch (_) {} throw new Error(m); }
    return res.json();
  }

  $('#selenium-update-btn')?.addEventListener('click', async () => {
    const btn = $('#selenium-update-btn');
    btn.disabled = true;
    try { await sidebarFetch('/admin/selenium/update', { method: 'POST', body: '{}' }); } catch (e) { alert(e.message); }
    finally { btn.disabled = false; setTimeout(refreshStats, 1000); }
  });
  $('#cdata-monitor-btn')?.addEventListener('click', async () => {
    const btn = $('#cdata-monitor-btn'), oltId = $('#cdata-olt-input')?.value.trim();
    if (!oltId) { alert('Enter a CDATA OLT ID'); return; }
    btn.disabled = true;
    try { await sidebarFetch('/admin/cdata/monitor', { method: 'POST', body: JSON.stringify({ olt_id: oltId }) }); } catch (e) { alert(e.message); }
    finally { btn.disabled = false; setTimeout(refreshStats, 1000); }
  });
  $('#phpsessid-btn')?.addEventListener('click', async () => {
    const inp = $('#phpsessid-input'), val = inp?.value.trim(); if (!val) return;
    try { await sidebarFetch('/admin/diameter/session', { method: 'POST', body: JSON.stringify({ phpsessid: val }) }); inp.value = ''; } catch (e) { alert(e.message); }
  });
})();
