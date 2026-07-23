/* DOM COPILOT overlay — injected into the game page (or served standalone).
   Talks to the local copilot service at 127.0.0.1:8787. Idempotent. */
(function () {
  if (window.__domCopilot) return;
  window.__domCopilot = true;

  var API = 'http://127.0.0.1:8787';
  var lastNudgeTs = 0;

  // ---- styles ----
  var css = document.createElement('style');
  css.textContent = [
    '#dom-copilot-bubble{position:fixed;bottom:16px;left:16px;z-index:99999;font-family:"JetBrains Mono",monospace;',
    'background:rgba(10,10,12,.95);border:1px solid #FFD700;border-radius:12px;color:#eee;width:300px;',
    'box-shadow:0 8px 30px rgba(0,0,0,.6);overflow:hidden;transition:height .2s}',
    '#dom-copilot-head{display:flex;align-items:center;gap:8px;padding:8px 12px;cursor:pointer;background:rgba(255,215,0,.08)}',
    '#dom-copilot-head b{color:#FFD700;font-size:11px;letter-spacing:1px;flex:1}',
    '#dom-copilot-dot{width:8px;height:8px;border-radius:4px;background:#9ae66e;box-shadow:0 0 6px #9ae66e}',
    '#dom-copilot-body{display:none;flex-direction:column;height:300px}',
    '#dom-copilot-bubble.open #dom-copilot-body{display:flex}',
    '#dom-copilot-feed{flex:1;overflow-y:auto;padding:8px;font-size:12px;line-height:1.45}',
    '.dc-msg{margin-bottom:8px;padding:6px 8px;border-radius:8px;max-width:92%}',
    '.dc-dom{background:rgba(255,215,0,.1);border-left:2px solid #FFD700}',
    '.dc-you{background:rgba(255,255,255,.07);border-left:2px solid #666;margin-left:auto}',
    '.dc-who{font-size:9px;color:#FFD700;letter-spacing:1px;margin-bottom:2px}',
    '.dc-you .dc-who{color:#999}',
    '#dom-copilot-inputrow{display:flex;border-top:1px solid rgba(255,215,0,.25)}',
    '#dom-copilot-input{flex:1;background:transparent;border:none;color:#eee;padding:10px;font-family:inherit;font-size:12px;outline:none}',
    '#dom-copilot-send{background:#FFD700;border:none;color:#000;font-weight:700;padding:0 14px;cursor:pointer;font-family:inherit;font-size:11px}'
  ].join('\n');
  document.head.appendChild(css);

  // ---- markup ----
  var box = document.createElement('div');
  box.id = 'dom-copilot-bubble';
  box.innerHTML =
    '<div id="dom-copilot-head"><span id="dom-copilot-dot"></span><b>DOM COPILOT</b><span style="font-size:9px;color:#888">local</span></div>' +
    '<div id="dom-copilot-body">' +
    '  <div id="dom-copilot-feed"></div>' +
    '  <div id="dom-copilot-inputrow">' +
    '    <input id="dom-copilot-input" placeholder="Ask Dom anything..." />' +
    '    <button id="dom-copilot-send">SEND</button>' +
    '  </div>' +
    '</div>';
  document.body.appendChild(box);

  var feed = box.querySelector('#dom-copilot-feed');
  var input = box.querySelector('#dom-copilot-input');

  box.querySelector('#dom-copilot-head').addEventListener('click', function () {
    box.classList.toggle('open');
  });

  function addMsg(who, text) {
    var d = document.createElement('div');
    d.className = 'dc-msg ' + (who === 'DOM' ? 'dc-dom' : 'dc-you');
    d.innerHTML = '<div class="dc-who">' + who + '</div>';
    var span = document.createElement('span');
    span.textContent = text;
    d.appendChild(span);
    feed.appendChild(d);
    feed.scrollTop = feed.scrollHeight;
    if (!box.classList.contains('open') && who === 'DOM') {
      box.classList.add('open'); // nudges open the panel so they're seen
    }
  }

  // ---- nudges (poll) ----
  function pollNudges() {
    fetch(API + '/nudges?since=' + lastNudgeTs)
      .then(function (r) { return r.json(); })
      .then(function (data) {
        (data.nudges || []).forEach(function (n) {
          if (n.ts > lastNudgeTs) {
            lastNudgeTs = n.ts;
            addMsg('DOM', n.text);
          }
        });
      })
      .catch(function () { /* service down — stay quiet */ })
      .finally(function () { setTimeout(pollNudges, 4000); });
  }
  pollNudges();

  // ---- chat ----
  function send() {
    var text = input.value.trim();
    if (!text) return;
    input.value = '';
    addMsg('YOU', text);
    fetch(API + '/chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ text: text })
    })
      .then(function (r) { return r.json(); })
      .then(function (data) { addMsg('DOM', data.reply || '(silence)'); })
      .catch(function () { addMsg('DOM', '(copilot offline — is the runner up?)'); });
  }
  box.querySelector('#dom-copilot-send').addEventListener('click', send);
  input.addEventListener('keydown', function (e) { if (e.key === 'Enter') send(); });
})();
