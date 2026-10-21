// TaskSprint To-do web view (Phase 13, workshop-v1.1). Read-mostly view of demo-001 for the projector.
// It uses only the application role's existing routes (Architecture A8): POST /v1/app/commands
// (list, status, add <title>, complete <ID>) and GET /v1/releases. The application token is held only in
// this tab's sessionStorage; it is never written to a cookie, the URL, persistent storage or the page.
'use strict';
(function () {
  var TOKEN_KEY = 'tasksprint.appToken';
  var WORKSPACE = 'demo-001';
  var POLL_MS = 3000;
  var LOG_SIZE = 5;

  var memoryToken = null;   // used only when sessionStorage is unavailable (private mode); lost on reload
  var timer = null;
  var polling = false;
  var connected = false;
  var completionMuted = true;
  var responses = [];

  function $(id) { return document.getElementById(id); }

  function getToken() {
    try { var t = window.sessionStorage.getItem(TOKEN_KEY); if (t) { return t; } } catch (e) { /* unavailable */ }
    return memoryToken;
  }
  function setToken(t) {
    memoryToken = null;
    try { window.sessionStorage.setItem(TOKEN_KEY, t); } catch (e) { memoryToken = t; }
  }
  function clearToken() {
    memoryToken = null;
    try { window.sessionStorage.removeItem(TOKEN_KEY); } catch (e) { /* unavailable */ }
  }

  function setText(id, text, cls) {
    var el = $(id);
    el.textContent = text;
    if (cls !== undefined) { el.className = cls; }
  }

  function clock() {
    var d = new Date();
    function p(n) { return (n < 10 ? '0' : '') + n; }
    return p(d.getHours()) + ':' + p(d.getMinutes()) + ':' + p(d.getSeconds());
  }

  // One request to the lab. Resolves to {status, ok, code, message, data, requestId}; never rejects.
  function request(method, path, body) {
    var token = getToken() || '';
    var init = {
      method: method,
      headers: { 'Authorization': 'Bearer ' + token, 'X-TaskSprint-Workspace': WORKSPACE },
      cache: 'no-store', credentials: 'omit', redirect: 'error'
    };
    if (body !== undefined) {
      init.headers['Content-Type'] = 'application/json';
      init.body = JSON.stringify(body);
    }
    return fetch(path, init).then(function (resp) {
      var rid = resp.headers.get('x-request-id') || '';
      return resp.json().catch(function () { return {}; }).then(function (j) {
        if (resp.status >= 400 || j.error) {
          var err = j.error || {};
          return { status: resp.status, ok: false, code: err.code || ('HTTP_' + resp.status),
                   message: err.message || '', data: null, requestId: rid };
        }
        return { status: resp.status, ok: j.ok !== false, code: j.code || 'OK', message: j.message || '',
                 data: j.data !== undefined ? j.data : j, requestId: rid };
      });
    }).catch(function () {
      return { status: 0, ok: false, code: 'LAB_UNREACHABLE', message: 'the lab did not answer', data: null,
               requestId: '' };
    });
  }

  function command(text) { return request('POST', '/v1/app/commands', { command: text }); }

  // rendering
  function renderStatus(status, releases) {
    if (status && status.ok && status.data) {
      var h = status.data;
      setText('s-cand', h.active_candidate_id || '–');
      setText('s-hash', h.active_sha256 ? h.active_sha256.slice(0, 12) : '–');
      setText('s-rev', h.release_revision !== undefined ? String(h.release_revision) : '–');
      var healthy = h.status === 'healthy';
      setText('s-health', h.status || '–', healthy ? 'good' : 'bad');
      var feature = (h.features && h.features.complete) || '';
      completionMuted = !healthy || feature.indexOf('FEATURE_UNAVAILABLE') !== -1;
    }
    if (releases && releases.ok && releases.data && releases.data.active) {
      var a = releases.data.active;
      setText('s-origin', [a.label, a.origin ? '(' + a.origin + ')' : ''].join(' ').trim() || '–');
    }
  }

  function renderTasks(list) {
    if (!list || !list.ok || !list.data) { return; }
    var tasks = list.data.tasks || [];
    var tbody = $('rows');
    while (tbody.firstChild) { tbody.removeChild(tbody.firstChild); }
    tasks.forEach(function (t) {
      var tr = document.createElement('tr');
      var id = document.createElement('td'); id.className = 'id data'; id.textContent = t.id;
      var title = document.createElement('td'); title.textContent = t.title;
      var done = document.createElement('td'); done.className = 'c'; done.textContent = t.completed ? '✓' : '–';
      var rev = document.createElement('td'); rev.className = 'mono data'; rev.textContent = String(t.revision);
      var cell = document.createElement('td'); cell.className = 'r';
      var btn = document.createElement('button');
      btn.type = 'button';
      btn.textContent = 'Complete';
      btn.className = completionMuted ? 'ghost muted-btn' : 'ghost';
      btn.title = completionMuted ? 'The last status says completion is unavailable; the click still asks the lab.' : '';
      btn.addEventListener('click', function () { act('complete ' + t.id); });
      cell.appendChild(btn);
      tr.appendChild(id); tr.appendChild(title); tr.appendChild(done); tr.appendChild(rev); tr.appendChild(cell);
      tbody.appendChild(tr);
    });
    $('empty').hidden = tasks.length !== 0;
  }

  function renderLog() {
    var ol = $('log');
    while (ol.firstChild) { ol.removeChild(ol.firstChild); }
    responses.forEach(function (r) {
      var li = document.createElement('li');
      var code = document.createElement('span');
      code.className = 'mono ' + (r.ok ? 'good' : 'bad');
      code.textContent = r.code;
      li.appendChild(document.createTextNode(r.time + '  ' + r.command + '  →  '));
      li.appendChild(code);
      if (r.message) { li.appendChild(document.createTextNode('  ' + r.message)); }
      ol.appendChild(li);
    });
  }

  function firstLine(text) { return String(text || '').split('\n')[0].slice(0, 160); }

  // polling and actions
  function poll() {
    if (!connected || polling) { return Promise.resolve(); }
    if (document.hidden) { return Promise.resolve(); }
    polling = true;
    return Promise.all([command('list'), command('status'), request('GET', '/v1/releases')]).then(function (r) {
      polling = false;
      if (r.some(function (x) { return x.status === 401; })) {
        disconnect('Token refused (UNAUTHENTICATED). Paste the application token again.');
        return;
      }
      renderStatus(r[1], r[2]);
      renderTasks(r[0]);
      var failed = r.filter(function (x) { return !x.ok; }).map(function (x) { return x.code; });
      setText('poll', failed.length ? 'Refresh at ' + clock() + ' incomplete: ' + failed.join(', ')
                                    : 'Updated ' + clock() + ' · refreshes every 3 s', failed.length ? 'bad small' : 'muted small');
    });
  }

  function act(text) {
    return command(text).then(function (r) {
      if (r.status === 401) { disconnect('Token refused (UNAUTHENTICATED).'); return; }
      setText('last-code', r.code, 'mono ' + (r.ok ? 'good' : 'bad'));
      setText('last-msg', firstLine(r.message));
      responses.unshift({ time: clock(), command: text, code: r.code, ok: r.ok, message: firstLine(r.message) });
      responses = responses.slice(0, LOG_SIZE);
      renderLog();
      return poll();
    });
  }

  function schedule() {
    if (timer) { window.clearInterval(timer); }
    timer = window.setInterval(poll, POLL_MS);
  }

  function connect() {
    connected = true;
    $('gate').hidden = true;
    $('view').hidden = false;
    $('disconnect').hidden = false;
    poll();
    schedule();
  }

  function disconnect(message) {
    connected = false;
    if (timer) { window.clearInterval(timer); timer = null; }
    clearToken();
    $('view').hidden = true;
    $('disconnect').hidden = true;
    $('gate').hidden = false;
    setText('gate-msg', message || '');
    $('token').value = '';
    $('token').focus();
  }

  document.addEventListener('DOMContentLoaded', function () {
    $('gate-form').addEventListener('submit', function (ev) {
      ev.preventDefault();
      var field = $('token');
      var value = (field.value || '').trim();
      field.value = '';
      if (!value) { return; }
      setToken(value);
      setText('gate-msg', '');
      connect();
    });
    $('disconnect').addEventListener('click', function (ev) {
      ev.preventDefault();
      disconnect('Disconnected. The token was removed from this tab.');
    });
    $('add-form').addEventListener('submit', function (ev) {
      ev.preventDefault();
      var field = $('add-title');
      var title = (field.value || '').trim();
      if (!title) { return; }
      field.value = '';
      act('add ' + title);
    });
    document.addEventListener('visibilitychange', function () { if (!document.hidden) { poll(); } });
    if (getToken()) { connect(); } else { disconnect(''); }
  });
})();
