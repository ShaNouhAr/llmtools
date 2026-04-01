(function () {
  'use strict';

  // ===== Lightweight Markdown renderer =====
  function renderMarkdown(text) {
    if (!text) return '';
    var html = text
      // <think> blocks (Handle open tags without close tags for streaming)
      .replace(/<think>([\s\S]*?)(?:<\/think>|$)/g, function(_, content) {
        var isClosed = text.includes('</think>');
        // Use a clean SVG icon instead of emoji
        var icon = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="vertical-align:-2px;margin-right:6px"><path d="M12 2v2M12 20v2M4.93 4.93l1.41 1.41M17.66 17.66l1.41 1.41M2 12h2M20 12h2M6.34 17.66l-1.41 1.41M19.07 4.93l-1.41 1.41"/></svg>';
        return '<details class="think-block" ' + (!isClosed ? 'open' : '') + '><summary>' + icon + 'Processus de réflexion</summary><div class="think-content">' + esc(content).replace(/\n/g, '<br>') + '</div></details>';
      })
      // code blocks
      .replace(/```(\w*)\n([\s\S]*?)```/g, function (_, lang, code) {
        return '<pre class="code-block" data-lang="' + esc(lang) + '"><button class="code-copy" onclick="copyCode(this)">Copier</button><code>' + esc(code.replace(/\n$/, '')) + '</code></pre>';
      })
      // inline code
      .replace(/`([^`]+)`/g, '<code>$1</code>')
      // bold
      .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
      // italic (avoid matching list items)
      .replace(/(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)/g, '<em>$1</em>')
      // headers
      .replace(/^#### (.+)$/gm, '<h4>$1</h4>')
      .replace(/^### (.+)$/gm, '<h3>$1</h3>')
      .replace(/^## (.+)$/gm, '<h2>$1</h2>')
      .replace(/^# (.+)$/gm, '<h1>$1</h1>')
      // blockquote
      .replace(/^> (.+)$/gm, '<blockquote>$1</blockquote>')
      // links: [text](url)
      .replace(/\[([^\]]+)\]\(([^)]+)\)/g, '<a href="$2" target="_blank" rel="noopener">$1</a>')
      // ordered list items
      .replace(/^\d+\. (.+)$/gm, '<li class="ol-item">$1</li>')
      // unordered list items
      .replace(/^[*\-] (.+)$/gm, '<li>$1</li>')
      // hr
      .replace(/^---$/gm, '<hr>')
      // line breaks
      .replace(/\n{2,}/g, '</p><p>')
      .replace(/\n/g, '<br>');

    // Wrap loose <li> in <ul>, ordered in <ol>
    html = html.replace(/((?:<li class="ol-item">.*?<\/li>\s*)+)/g, function (m) {
      return '<ol>' + m.replace(/ class="ol-item"/g, '') + '</ol>';
    });
    html = html.replace(/((?:<li>.*?<\/li>\s*)+)/g, '<ul>$1</ul>');
    return '<p>' + html + '</p>';
  }

  function esc(s) {
    var d = document.createElement('div');
    d.textContent = s;
    return d.innerHTML;
  }

  // Global copy handler
  window.copyCode = function (btn) {
    var code = btn.parentElement.querySelector('code');
    if (!code) return;
    navigator.clipboard.writeText(code.textContent).then(function () {
      btn.textContent = 'Copié !';
      setTimeout(function () { btn.textContent = 'Copier'; }, 1500);
    });
  };

  // ===== DOM references =====
  var chatForm = document.getElementById('chatForm');
  var chatScroll = document.getElementById('chatScroll');
  var chatMessages = document.getElementById('chatMessages');
  var chatWelcome = document.getElementById('chatWelcome');
  var messageInput = document.getElementById('messageInput');
  var sendBtn = document.getElementById('sendBtn');
  var chatListEl = document.getElementById('chatList');
  var suggestions = document.querySelectorAll('.chat-suggestion');

  var agentModeToggle = document.getElementById('agentModeToggle');
  var autoModeToggle = document.getElementById('autoModeToggle');
  var autoToggleWrap = document.getElementById('autoToggleWrap');

  var CHAT_ID = window.CHAT_ID || null;
  var WORKSPACE_CHAT_ID = null;
  var CHAT_MESSAGES = Array.isArray(window.CHAT_MESSAGES) ? window.CHAT_MESSAGES.slice() : [];
  var STREAM_URL = window.CHAT_STREAM_URL || '/api/chat/stream';
  var AGENT_URL = window.AGENT_STREAM_URL || '/api/agent/stream';
  var APPROVE_URL = window.AGENT_APPROVE_URL || '/api/agent/approve';
  var MODULE_ID = window.MODULE_ID || '';

  // Module selector
  var moduleSelect = document.getElementById('moduleSelect');
  if (moduleSelect) {
    moduleSelect.addEventListener('change', function () {
      MODULE_ID = moduleSelect.value;
      // Update URL and reload the page to refresh the chat history context
      var newUrl = '/chat' + (MODULE_ID ? '?module=' + MODULE_ID : '');
      window.location.href = newUrl;
    });
  }

  // Files panel DOM
  var filesPanel = document.getElementById('filesPanel');
  var filesPanelToggle = document.getElementById('filesPanelToggle');
  var filesPanelClose = document.getElementById('filesPanelClose');
  var filesPanelBody = document.getElementById('filesPanelBody');
  var filesTree = document.getElementById('filesTree');
  var filesEmpty = document.getElementById('filesEmpty');
  var filesPreview = document.getElementById('filesPreview');
  var filesPreviewName = document.getElementById('filesPreviewName');
  var filesPreviewBack = document.getElementById('filesPreviewBack');
  var filesPreviewContent = document.getElementById('filesPreviewContent');

  // Show/hide auto toggle based on agent mode
  if (agentModeToggle) {
    agentModeToggle.addEventListener('change', function () {
      if (autoToggleWrap) autoToggleWrap.classList.toggle('hidden', !agentModeToggle.checked);
    });
  }

  function isAgentMode() { return agentModeToggle && agentModeToggle.checked; }
  function isAutoMode() { return !autoModeToggle || autoModeToggle.checked; }

  // ===== Auto-resize textarea =====
  function autoResize() {
    if (!messageInput) return;
    messageInput.style.height = 'auto';
    messageInput.style.height = Math.min(messageInput.scrollHeight, 200) + 'px';
  }

  if (messageInput) {
    messageInput.addEventListener('input', autoResize);
    messageInput.addEventListener('keydown', function (e) {
      if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        if (chatForm) chatForm.dispatchEvent(new Event('submit', { cancelable: true }));
      }
    });
  }

  // ===== Scroll to bottom =====
  function scrollToBottom(smooth) {
    if (!chatScroll) return;
    if (smooth) {
      chatScroll.scrollTo({ top: chatScroll.scrollHeight, behavior: 'smooth' });
    } else {
      chatScroll.scrollTop = chatScroll.scrollHeight;
    }
  }

  // ===== Create message DOM =====
  function createMsgEl(role, html) {
    var div = document.createElement('div');
    div.className = 'msg msg-' + role;
    var avatarLabel = role === 'user' ? 'U' : 'AI';
    div.innerHTML =
      '<div class="msg-avatar">' + avatarLabel + '</div>' +
      '<div class="msg-body">' +
        '<div class="msg-name">' + (role === 'user' ? 'Vous' : 'LLMTools') + '</div>' +
        '<div class="msg-content">' + html + '</div>' +
      '</div>';
    return div;
  }

  function hideWelcome() {
    if (chatWelcome) chatWelcome.style.display = 'none';
  }

  function appendUserMsg(text) {
    hideWelcome();
    var el = createMsgEl('user', renderMarkdown(text));
    chatMessages.appendChild(el);
    scrollToBottom(true);
  }

  function createAssistantMsg() {
    hideWelcome();
    var el = createMsgEl('assistant',
      '<div class="typing-indicator"><span class="typing-dot"></span><span class="typing-dot"></span><span class="typing-dot"></span></div>'
    );
    chatMessages.appendChild(el);
    scrollToBottom(true);
    return el.querySelector('.msg-content');
  }

  // ===== Clear messages from DOM =====
  function clearMessages() {
    if (!chatMessages) return;
    var msgs = chatMessages.querySelectorAll('.msg');
    msgs.forEach(function (m) { m.remove(); });
  }

  // ===== Render all messages from CHAT_MESSAGES =====
  function renderAllMessages() {
    clearMessages();
    if (CHAT_MESSAGES.length === 0) {
      if (chatWelcome) chatWelcome.style.display = '';
      return;
    }
    hideWelcome();
    CHAT_MESSAGES.forEach(function (m) {
      var el = createMsgEl(m.role || 'user', renderMarkdown((m.content || '').trim()));
      chatMessages.appendChild(el);
    });
    setTimeout(function () { scrollToBottom(false); }, 50);
  }

  // Render on initial load
  renderAllMessages();

  // ===== Load a chat by ID (SPA, no page reload) =====
  function loadChat(chatId) {
    fetch('/api/chats/' + chatId)
      .then(function (r) { if (!r.ok) throw new Error('Introuvable'); return r.json(); })
      .then(function (data) {
        CHAT_ID = data.id;
        CHAT_MESSAGES = (data.messages || []).slice();
        window.history.pushState(null, '', '/chat/' + data.id);
        renderAllMessages();
        refreshChatList();
        if (messageInput) { messageInput.disabled = false; messageInput.focus(); }
        if (sendBtn) sendBtn.disabled = false;
      })
      .catch(function () {
        resetToNewChat();
      });
  }

  // ===== Reset to new chat state (without page reload) =====
  function resetToNewChat() {
    CHAT_ID = null;
    CHAT_MESSAGES = [];
    window.history.pushState(null, '', '/chat');
    clearMessages();
    if (chatWelcome) chatWelcome.style.display = '';
    if (messageInput) { messageInput.value = ''; messageInput.disabled = false; messageInput.focus(); }
    if (sendBtn) sendBtn.disabled = false;
    refreshChatList();
  }

  // "Nouveau chat" button handler
  var newChatBtn = document.querySelector('.chat-sidebar-new');
  if (newChatBtn) {
    newChatBtn.addEventListener('click', function (e) {
      e.preventDefault();
      resetToNewChat();
    });
  }

  // ===== Suggestions =====
  suggestions.forEach(function (btn) {
    btn.addEventListener('click', function () {
      if (messageInput) {
        messageInput.value = btn.getAttribute('data-text');
        messageInput.focus();
        autoResize();
      }
    });
  });

  // ===== Delete a chat =====
  function deleteChat(chatId) {
    fetch('/api/chats/' + chatId, { method: 'DELETE' })
      .then(function (r) {
        if (!r.ok) return;
        if (CHAT_ID === chatId) resetToNewChat();
        else refreshChatList();
      });
  }

  // ===== Chat list refresh =====
  function refreshChatList() {
    fetch('/api/chats').then(function (r) { return r.json(); }).then(function (data) {
      if (!chatListEl) return;
      var chats = data.chats || [];
      chatListEl.innerHTML = chats.map(function (c) {
        var date = (c.updated_at || c.created_at || '').slice(0, 10);
        var active = CHAT_ID && c.id === CHAT_ID ? ' active' : '';
        return '<li class="chat-list-li">' +
          '<a href="/chat/' + c.id + '" class="chat-list-item' + active + '" data-chat-id="' + c.id + '">' +
            '<span class="chat-list-title">' + esc(c.title) + '</span>' +
            '<span class="chat-list-meta">' + date + '</span>' +
          '</a>' +
          '<button class="chat-delete-btn" data-delete-id="' + c.id + '" title="Supprimer">' +
            '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="3 6 5 6 21 6"/><path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6"/><path d="M10 11v6"/><path d="M14 11v6"/><path d="M9 6V4a1 1 0 0 1 1-1h4a1 1 0 0 1 1 1v2"/></svg>' +
          '</button>' +
        '</li>';
      }).join('');
      bindChatListClicks();
    }).catch(function () {});
  }

  // ===== Custom Confirm Modal =====
  function customConfirm(message, onConfirm) {
    var overlay = document.createElement('div');
    overlay.className = 'modal';
    overlay.innerHTML =
      '<div class="modal-content" style="max-width: 350px;">' +
        '<h3>Confirmation</h3>' +
        '<p style="margin-bottom: 1.5rem; color: var(--text-secondary);">' + esc(message) + '</p>' +
        '<div class="modal-actions">' +
          '<button class="btn btn-ghost" id="confirmCancel">Annuler</button>' +
          '<button class="btn btn-danger" id="confirmOk">Supprimer</button>' +
        '</div>' +
      '</div>';
    document.body.appendChild(overlay);

    function close() { if(overlay.parentNode) document.body.removeChild(overlay); }

    overlay.querySelector('#confirmCancel').addEventListener('click', close);
    overlay.querySelector('#confirmOk').addEventListener('click', function() {
      close();
      onConfirm();
    });
  }

  function bindChatListClicks() {
    if (!chatListEl) return;
    chatListEl.querySelectorAll('.chat-list-item').forEach(function (link) {
      link.addEventListener('click', function (e) {
        e.preventDefault();
        var id = link.getAttribute('data-chat-id') || link.getAttribute('data-id');
        if (id) loadChat(id);
      });
    });
    chatListEl.querySelectorAll('.chat-delete-btn').forEach(function (btn) {
      btn.addEventListener('click', function (e) {
        e.preventDefault();
        e.stopPropagation();
        var id = btn.getAttribute('data-delete-id');
        if (id) {
          customConfirm('Voulez-vous vraiment supprimer cette conversation ?', function() {
            deleteChat(id);
          });
        }
      });
    });
  }

  // Bind initial sidebar links (rendered server-side)
  bindChatListClicks();

  // Handle browser back/forward
  window.addEventListener('popstate', function () {
    var path = window.location.pathname;
    var match = path.match(/^\/chat\/(.+)$/);
    if (match) loadChat(match[1]);
    else if (path === '/chat') resetToNewChat();
  });

  // ===== Abort controller for stopping streams =====
  var currentAbort = null;

  function abortStream() {
    if (currentAbort) {
      currentAbort.abort();
      currentAbort = null;
    }
  }

  // ===== Stop button =====
  var stopBtn = document.getElementById('stopBtn');

  function setLoading(on) {
    if (on) {
      if (sendBtn) sendBtn.classList.add('hidden');
      if (stopBtn) stopBtn.classList.remove('hidden');
      if (messageInput) messageInput.disabled = true;
    } else {
      if (sendBtn) { sendBtn.classList.remove('hidden'); sendBtn.disabled = false; }
      if (stopBtn) stopBtn.classList.add('hidden');
      if (messageInput) messageInput.disabled = false;
      currentAbort = null;
    }
  }

  if (stopBtn) {
    stopBtn.addEventListener('click', function () {
      abortStream();
      setLoading(false);
      if (messageInput) messageInput.focus();
    });
  }

  // ===== Files panel logic =====
  function toggleFilesPanel() {
    if (!filesPanel) return;
    var hidden = filesPanel.classList.contains('hidden');
    filesPanel.classList.toggle('hidden', !hidden);
    if (hidden) refreshFilesPanel();
  }

  if (filesPanelToggle) filesPanelToggle.addEventListener('click', toggleFilesPanel);
  if (filesPanelClose) filesPanelClose.addEventListener('click', function () {
    if (filesPanel) filesPanel.classList.add('hidden');
  });

  var _fileRefreshTimer = null;
  function debouncedRefreshFiles() {
    if (_fileRefreshTimer) clearTimeout(_fileRefreshTimer);
    _fileRefreshTimer = setTimeout(refreshFilesPanel, 500);
  }

  function refreshFilesPanel() {
    var wid = WORKSPACE_CHAT_ID || CHAT_ID;
    if (!wid || !filesTree) return;
    fetch('/api/workspace/' + wid)
      .then(function (r) { return r.json(); })
      .then(function (data) {
        var files = data.files || [];
        if (files.length === 0) {
          if (filesEmpty) filesEmpty.classList.remove('hidden');
          filesTree.innerHTML = '';
          return;
        }
        if (filesEmpty) filesEmpty.classList.add('hidden');
        renderFilesTree(files, wid);
      })
      .catch(function () {});
  }

  function renderFilesTree(files, wid) {
    if (!filesTree) return;
    var dirs = {};
    files.forEach(function (f) {
      var d = f.dir || '';
      if (!dirs[d]) dirs[d] = [];
      dirs[d].push(f);
    });

    var html = '';
    var dirOrder = Object.keys(dirs).sort();
    dirOrder.forEach(function (d) {
      var icon = getDirIcon(d);
      if (d) {
        html += '<div class="files-dir-label">' + icon + ' ' + esc(d) + '/</div>';
      }
      dirs[d].forEach(function (f) {
        var fname = f.path.split('/').pop();
        var sizeStr = formatFileSize(f.size);
        html +=
          '<button class="files-item" data-path="' + esc(f.path) + '" data-wid="' + esc(wid) + '">' +
            '<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/></svg>' +
            '<span>' + esc(fname) + '</span>' +
            '<span class="files-item-size">' + sizeStr + '</span>' +
          '</button>';
      });
    });
    filesTree.innerHTML = html;

    filesTree.querySelectorAll('.files-item').forEach(function (btn) {
      btn.addEventListener('click', function () {
        var path = btn.getAttribute('data-path');
        var w = btn.getAttribute('data-wid');
        openFilePreview(w, path);
      });
    });
  }

  function getDirIcon(dir) {
    var icons = {
      'scans': '<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/></svg>',
      'vulns': '<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>',
      'exploits': '<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"/></svg>',
      'loot': '<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="11" width="18" height="11" rx="2" ry="2"/><path d="M7 11V7a5 5 0 0 1 10 0v4"/></svg>',
    };
    return icons[dir] || '<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"/></svg>';
  }

  function formatFileSize(bytes) {
    if (bytes < 1024) return bytes + ' B';
    if (bytes < 1048576) return (bytes / 1024).toFixed(1) + ' KB';
    return (bytes / 1048576).toFixed(1) + ' MB';
  }

  function openFilePreview(wid, path) {
    if (!filesPreview || !filesPanelBody) return;
    filesPanelBody.classList.add('hidden');
    filesPreview.classList.remove('hidden');
    if (filesPreviewName) filesPreviewName.textContent = path;
    if (filesPreviewContent) {
      filesPreviewContent.textContent = 'Chargement...';
      filesPreviewContent.className = 'files-preview-content';
    }

    fetch('/api/workspace/' + wid + '/' + path)
      .then(function (r) {
        if (!r.ok) throw new Error('Fichier introuvable');
        return r.text();
      })
      .then(function (text) {
        if (!filesPreviewContent) return;
        if (path.endsWith('.md')) {
          filesPreviewContent.innerHTML = renderMarkdown(text);
          filesPreviewContent.className = 'files-preview-content files-preview-md';
        } else {
          filesPreviewContent.textContent = text;
          filesPreviewContent.className = 'files-preview-content';
        }
      })
      .catch(function (err) {
        if (filesPreviewContent) filesPreviewContent.textContent = 'Erreur: ' + err.message;
      });
  }

  if (filesPreviewBack) {
    filesPreviewBack.addEventListener('click', function () {
      if (filesPreview) filesPreview.classList.add('hidden');
      if (filesPanelBody) filesPanelBody.classList.remove('hidden');
    });
  }

  // ===== Agent status banner =====
  function createStatusBanner() {
    var el = document.createElement('div');
    el.className = 'agent-status-bar';
    el.innerHTML =
      '<div class="agent-status-pulse"></div>' +
      '<span class="agent-status-text">Demarrage...</span>';
    return el;
  }

  function updateStatusBanner(banner, text) {
    if (!banner) return;
    var txt = banner.querySelector('.agent-status-text');
    if (txt) txt.textContent = text;
  }

  function removeStatusBanner(banner) {
    if (banner && banner.parentNode) {
      banner.classList.add('agent-status-bar-done');
      setTimeout(function () { if (banner.parentNode) banner.remove(); }, 400);
    }
  }

  // ===== Tool block rendering (dynamic) =====
  function createToolBlock(toolName, args, cmdPreview) {
    var div = document.createElement('div');
    div.className = 'tool-block';
    div.innerHTML =
      '<div class="tool-header">' +
        '<div class="tool-header-left">' +
          '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="4 17 10 11 4 5"/><line x1="12" y1="19" x2="20" y2="19"/></svg>' +
          '<span class="tool-name">' + esc(toolName) + '</span>' +
        '</div>' +
        '<span class="tool-status tool-status-pending">En attente</span>' +
      '</div>' +
      '<div class="tool-cmd">' +
        '<span class="tool-cmd-prompt">$</span> ' + esc(cmdPreview || toolName) +
      '</div>';
    return div;
  }

  function setToolRunning(toolBlock) {
    if (!toolBlock) return;
    var st = toolBlock.querySelector('.tool-status');
    if (st) {
      st.className = 'tool-status tool-status-running';
      st.innerHTML = '<span class="tool-spinner"></span> Execution...';
    }
  }

  function addToolOutput(toolBlock, output, duration) {
    if (!toolBlock) return;
    var st = toolBlock.querySelector('.tool-status');
    var exitCode = output.exit_code || 0;
    var isError = exitCode !== 0;
    if (st) {
      st.className = 'tool-status ' + (isError ? 'tool-status-error' : 'tool-status-done');
      st.textContent = (isError ? 'Erreur' : 'OK') + (duration != null ? ' (' + duration + 's)' : '');
    }

    var stdout = (output.stdout || '').trim();
    var stderr = (output.stderr || '').trim();
    var text = stdout;
    if (stderr) text += (text ? '\n' : '') + stderr;
    if (!text) text = '(pas de sortie)';
    if (output.truncated) text += '\n[... sortie tronquee]';

    var outDiv = document.createElement('div');
    outDiv.className = 'tool-output' + (isError ? ' tool-output-error' : '');

    if (text.length > 800) {
      var preview = text.slice(0, 400);
      outDiv.innerHTML =
        '<pre class="tool-output-pre">' + esc(preview) + '</pre>' +
        '<button class="tool-output-toggle">Voir tout (' + text.length + ' car.)</button>';
      var full = document.createElement('pre');
      full.className = 'tool-output-pre tool-output-full hidden';
      full.textContent = text;
      outDiv.appendChild(full);
      outDiv.querySelector('.tool-output-toggle').addEventListener('click', function () {
        var btn = this;
        var previewEl = outDiv.querySelector('.tool-output-pre:not(.tool-output-full)');
        if (full.classList.contains('hidden')) {
          full.classList.remove('hidden');
          if (previewEl) previewEl.classList.add('hidden');
          btn.textContent = 'Masquer';
        } else {
          full.classList.add('hidden');
          if (previewEl) previewEl.classList.remove('hidden');
          btn.textContent = 'Voir tout (' + text.length + ' car.)';
        }
      });
    } else {
      outDiv.innerHTML = '<pre class="tool-output-pre">' + esc(text) + '</pre>';
    }
    toolBlock.appendChild(outDiv);
  }

  function addApprovalButtons(toolBlock, sessionId, toolName) {
    var wrap = document.createElement('div');
    wrap.className = 'tool-approval';
    wrap.innerHTML =
      '<span class="tool-approval-label">Autoriser cette commande ?</span>' +
      '<button class="btn btn-primary btn-sm btn-approve">Approuver</button>' +
      '<button class="btn btn-danger btn-sm btn-reject">Refuser</button>';
    toolBlock.appendChild(wrap);

    return new Promise(function (resolve) {
      wrap.querySelector('.btn-approve').addEventListener('click', function () {
        wrap.remove();
        fetch(APPROVE_URL, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ session_id: sessionId, approved: true }),
        });
        setToolRunning(toolBlock);
        resolve(true);
      });
      wrap.querySelector('.btn-reject').addEventListener('click', function () {
        wrap.remove();
        fetch(APPROVE_URL, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ session_id: sessionId, approved: false }),
        });
        var st = toolBlock.querySelector('.tool-status');
        if (st) { st.className = 'tool-status tool-status-rejected'; st.textContent = 'Refuse'; }
        resolve(false);
      });
    });
  }

  // ===== Create conversation if needed =====  // Get SSH credentials if SSH diagnostic module
  function getSSHPrefix() {
    if (MODULE_ID !== 'ssh_diag') return '';
    var host = document.getElementById('sshHost');
    var port = document.getElementById('sshPort');
    var user = document.getElementById('sshUser');
    var pass = document.getElementById('sshPassword');
    if (!host || !host.value.trim()) return '';
    var prefix = '[SSH] host=' + host.value.trim();
    if (port && port.value) prefix += ' port=' + port.value;
    if (user && user.value.trim()) prefix += ' user=' + user.value.trim();
    if (pass && pass.value) prefix += ' password=' + pass.value;
    prefix += '\n\n';
    return prefix;
  }

  async function ensureConversation(text) {
    if (CHAT_ID) return true;
    var title = text.length > 50 ? text.slice(0, 47) + '...' : text;
    try {
      var res = await fetch('/api/chats', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ title: title, messages: CHAT_MESSAGES, module_id: MODULE_ID }),
      });
      if (!res.ok) throw new Error('Erreur creation');
      var created = await res.json();
      CHAT_ID = created.id;
      window.history.replaceState(null, '', '/chat/' + CHAT_ID);
      refreshChatList();
      return true;
    } catch (err) {
      var errEl = createAssistantMsg();
      errEl.innerHTML = '<div class="chat-error">' + esc(err.message) + '</div>';
      return false;
    }
  }

  function saveMessages() {
    if (!CHAT_ID) return;
    fetch('/api/chats/' + CHAT_ID, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ messages: CHAT_MESSAGES }),
    }).then(function () { refreshChatList(); }).catch(function () {});
  }

  // ===== Parse SSE stream =====
  async function* parseSSE(response) {
    var reader = response.body.getReader();
    var decoder = new TextDecoder();
    var buffer = '';
    while (true) {
      var result = await reader.read();
      if (result.done) break;
      buffer += decoder.decode(result.value, { stream: true });
      var parts = buffer.split('\n');
      buffer = parts.pop();
      for (var i = 0; i < parts.length; i++) {
        if (parts[i].startsWith('data: ')) {
          try { yield JSON.parse(parts[i].slice(6)); } catch (_) {}
        }
      }
    }
  }

  // ===== Chat mode handler =====
  async function handleChatMode() {
    var contentEl = createAssistantMsg();
    var full = '';
    currentAbort = new AbortController();
    try {
      var res = await fetch(STREAM_URL, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ messages: CHAT_MESSAGES, module_id: MODULE_ID }),
        signal: currentAbort.signal,
      });
      if (!res.ok) throw new Error(res.statusText);
      for await (var data of parseSSE(res)) {
        if (currentAbort && currentAbort.signal.aborted) break;
        if (data.error) {
          contentEl.innerHTML = '<div class="chat-error">' + esc(data.error) + '</div>';
          return;
        }
        if (data.token) {
          full += data.token;
          contentEl.innerHTML = renderMarkdown(full);
          scrollToBottom(false);
        }
        if (data.done && data.full) full = data.full;
      }
      if (full) {
        contentEl.innerHTML = renderMarkdown(full);
        CHAT_MESSAGES.push({ role: 'assistant', content: full });
        saveMessages();
      }
    } catch (err) {
      if (err.name === 'AbortError') {
        if (full) {
          contentEl.innerHTML = renderMarkdown(full + '\n\n*(arrete par l\'utilisateur)*');
          CHAT_MESSAGES.push({ role: 'assistant', content: full });
          saveMessages();
        } else {
          contentEl.innerHTML = '<div class="chat-error chat-stopped">Generation arretee.</div>';
        }
      } else {
        contentEl.innerHTML = '<div class="chat-error">Erreur : ' + esc(err.message) + '</div>';
      }
    }
  }

  // ===== Agent mode handler =====
  async function handleAgentMode() {
    hideWelcome();
    var auto = isAutoMode();
    var agentMsg = createMsgEl('assistant', '');
    chatMessages.appendChild(agentMsg);
    var contentArea = agentMsg.querySelector('.msg-content');
    contentArea.innerHTML = '';

    var statusBanner = createStatusBanner();
    contentArea.appendChild(statusBanner);
    scrollToBottom(true);

    var fullResponse = '';
    var tokenBuffer = '';
    var agentLog = '';
    var responseDiv = null;
    var currentToolBlock = null;
    var toolsContainer = document.createElement('div');
    toolsContainer.className = 'agent-steps';
    contentArea.appendChild(toolsContainer);

    currentAbort = new AbortController();
    try {
      var res = await fetch(AGENT_URL, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ messages: CHAT_MESSAGES, auto_mode: auto, chat_id: CHAT_ID, module_id: MODULE_ID }),
        signal: currentAbort.signal,
      });
      if (!res.ok) throw new Error(res.statusText);

      for await (var evt of parseSSE(res)) {
        if (currentAbort && currentAbort.signal.aborted) break;

        if (evt.type === 'workspace') {
          WORKSPACE_CHAT_ID = evt.chat_id;
        }

        if (evt.type === 'status') {
          updateStatusBanner(statusBanner, evt.content);
          scrollToBottom(false);
        }

        if (evt.type === 'thinking') {
          agentLog += evt.content + '\n';
          var thinkDiv = document.createElement('div');
          thinkDiv.className = 'agent-thinking';
          thinkDiv.innerHTML =
            '<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><path d="M12 6v6l4 2"/></svg> ' +
            esc(evt.content);
          toolsContainer.appendChild(thinkDiv);
          scrollToBottom(false);
        }

        if (evt.type === 'tool_call') {
          agentLog += '[Outil: ' + evt.tool + '] ' + (evt.command || evt.tool) + '\n';
          currentToolBlock = createToolBlock(evt.tool, evt.args, evt.command || evt.tool);
          toolsContainer.appendChild(currentToolBlock);
          scrollToBottom(false);
        }

        if (evt.type === 'tool_start' && currentToolBlock) {
          setToolRunning(currentToolBlock);
          var skipBtn = document.createElement('button');
          skipBtn.className = 'tool-skip-btn';
          skipBtn.innerHTML = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M5 3l14 9-14 9V3z"/></svg> Skip';
          skipBtn.addEventListener('click', function() {
            var cid = WORKSPACE_CHAT_ID || (typeof CHAT_ID !== 'undefined' ? CHAT_ID : '');
            if (!cid) return;
            fetch('/api/agent/skip', {
              method: 'POST',
              headers: {'Content-Type': 'application/json'},
              body: JSON.stringify({chat_id: cid})
            });
            skipBtn.disabled = true;
            skipBtn.textContent = 'Skipping...';
          });
          var toolHeader = currentToolBlock.querySelector('.tool-header');
          if (toolHeader) toolHeader.appendChild(skipBtn);
          scrollToBottom(false);
        }

        if (evt.type === 'approval_needed' && currentToolBlock) {
          var approvalSt = currentToolBlock.querySelector('.tool-status');
          if (approvalSt) {
            approvalSt.className = 'tool-status tool-status-approval';
            approvalSt.textContent = 'Approbation requise';
          }
          await addApprovalButtons(currentToolBlock, evt.session_id, evt.tool);
          scrollToBottom(false);
        }

        if (evt.type === 'approval_rejected' && currentToolBlock) {
          var rejSt = currentToolBlock.querySelector('.tool-status');
          if (rejSt) { rejSt.className = 'tool-status tool-status-rejected'; rejSt.textContent = 'Refuse'; }
        }

        if (evt.type === 'tool_output') {
          if (currentToolBlock) {
            var oldSkip = currentToolBlock.querySelector('.tool-skip-btn');
            if (oldSkip) oldSkip.remove();
          }
          var _stdout = (evt.output.stdout || '').trim();
          var _stderr = (evt.output.stderr || '').trim();
          var _outText = _stdout || _stderr || '(pas de sortie)';
          if (_outText.length > 500) _outText = _outText.slice(0, 500) + '...';
          agentLog += 'Résultat: ' + _outText + '\n\n';
          addToolOutput(currentToolBlock, evt.output, evt.duration);
          currentToolBlock = null;
          scrollToBottom(false);
          if (filesPanel && !filesPanel.classList.contains('hidden')) debouncedRefreshFiles();
        }

        if (evt.type === 'token') {
          removeStatusBanner(statusBanner);
          if (!responseDiv) {
            responseDiv = document.createElement('div');
            responseDiv.className = 'agent-final-response';
            contentArea.appendChild(responseDiv);
          }
          tokenBuffer += evt.content;
          responseDiv.innerHTML = renderMarkdown(tokenBuffer);
          scrollToBottom(false);
        }

        if (evt.type === 'done') {
          removeStatusBanner(statusBanner);
          fullResponse = evt.content;
          if (responseDiv) {
            responseDiv.innerHTML = renderMarkdown(evt.content);
          } else {
            var doneDiv = document.createElement('div');
            doneDiv.className = 'agent-final-response';
            doneDiv.innerHTML = renderMarkdown(evt.content);
            contentArea.appendChild(doneDiv);
          }
          scrollToBottom(false);
        }

        if (evt.type === 'error') {
          removeStatusBanner(statusBanner);
          var errorDiv = document.createElement('div');
          errorDiv.className = 'chat-error';
          errorDiv.textContent = evt.content;
          contentArea.appendChild(errorDiv);
          scrollToBottom(false);
        }
      }

      var savedContent = '';
      if (agentLog.trim()) savedContent += '[Actions agent]\n' + agentLog.trim() + '\n\n';
      if (fullResponse) savedContent += fullResponse;
      else if (tokenBuffer) savedContent += tokenBuffer;
      if (savedContent.trim()) {
        CHAT_MESSAGES.push({ role: 'assistant', content: savedContent.trim() });
        saveMessages();
      }
      refreshFilesPanel();
    } catch (err) {
      removeStatusBanner(statusBanner);
      if (err.name === 'AbortError') {
        var stoppedDiv = document.createElement('div');
        stoppedDiv.className = 'chat-error chat-stopped';
        stoppedDiv.textContent = 'Agent arrete par l\'utilisateur.';
        contentArea.appendChild(stoppedDiv);
        var stoppedContent = '';
        if (agentLog.trim()) stoppedContent += '[Actions agent]\n' + agentLog.trim() + '\n\n';
        if (fullResponse) stoppedContent += fullResponse;
        else if (tokenBuffer) stoppedContent += tokenBuffer;
        if (!stoppedContent.trim() && agentLog.trim()) stoppedContent = '[Actions agent]\n' + agentLog.trim();
        if (stoppedContent.trim()) {
          CHAT_MESSAGES.push({ role: 'assistant', content: stoppedContent.trim() });
          saveMessages();
        }
      } else {
        contentArea.innerHTML = '<div class="chat-error">Erreur agent : ' + esc(err.message) + '</div>';
      }
    }
  }

  // ===== Main chat submit =====
  if (chatForm) {
    chatForm.addEventListener('submit', async function (e) {
      e.preventDefault();
      var text = (messageInput ? messageInput.value : '').trim();
      if (!text) return;

      // Prepend SSH credentials for first message if SSH diagnostic module
      var sshPrefix = '';
      if (CHAT_MESSAGES.length === 0) {
        sshPrefix = getSSHPrefix();
      }

      messageInput.value = '';
      autoResize();
      var fullText = sshPrefix + text;
      CHAT_MESSAGES.push({ role: 'user', content: fullText });
      appendUserMsg(text);
      setLoading(true);

      var ok = await ensureConversation(text);
      if (!ok) { setLoading(false); return; }

      try {
        if (isAgentMode()) {
          await handleAgentMode();
        } else {
          await handleChatMode();
        }
      } finally {
        setLoading(false);
        if (messageInput) messageInput.focus();
      }
    });
  }

  // ===== Config page =====
  var modelsUrl = window.CONFIG_MODELS_URL;
  var selectUrl = window.CONFIG_SELECT_URL;
  var configInfoUrl = window.CONFIG_INFO_URL;
  var modelListEl = document.getElementById('modelList');
  var currentModelEl = document.getElementById('currentModel');
  var refreshModelsBtn = document.getElementById('refreshModelsBtn');
  var modelStatusEl = document.getElementById('modelStatus');

  function showModelStatus(text, ok) {
    if (!modelStatusEl) return;
    modelStatusEl.textContent = text;
    modelStatusEl.className = 'config-status ' + (ok ? 'config-status-ok' : 'config-status-err');
    modelStatusEl.classList.remove('hidden');
    setTimeout(function () { modelStatusEl.classList.add('hidden'); }, 3000);
  }
  // ===== Header Model Picker (global dropdown) =====
  var modelPickerBtn = document.getElementById('modelPickerBtn');
  var modelPickerDropdown = document.getElementById('modelPickerDropdown');
  var modelPickerList = document.getElementById('modelPickerList');
  var modelPickerLabel = document.getElementById('modelPickerLabel');
  var modelPickerRefresh = document.getElementById('modelPickerRefresh');

  function loadPickerModels() {
    if (!modelPickerList) return;
    modelPickerList.innerHTML = '<div class="model-picker-loading"><span class="typing-dot"></span><span class="typing-dot"></span><span class="typing-dot"></span></div>';
    fetch('/api/models')
      .then(function (r) { return r.json(); })
      .then(function (data) {
        var models = data.models || [];
        var current = data.current || '';
        if (models.length === 0) {
          modelPickerList.innerHTML = '<div class="model-picker-empty">Aucun modele charge dans LM Studio</div>';
          return;
        }
        modelPickerList.innerHTML = models.map(function (m) {
          var isActive = m.id === current;
          return '<button class="model-picker-item' + (isActive ? ' active' : '') + '" data-model-id="' + esc(m.id) + '">' +
            '<span class="model-picker-name">' + esc(m.id) + '</span>' +
            (isActive ? '<span class="model-picker-check"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"></polyline></svg></span>' : '') +
          '</button>';
        }).join('');
        modelPickerList.querySelectorAll('.model-picker-item').forEach(function (item) {
          item.addEventListener('click', function () {
            var mid = item.getAttribute('data-model-id');
            pickModel(mid);
          });
        });
      })
      .catch(function () {
        modelPickerList.innerHTML = '<div class="model-picker-empty">Erreur de connexion</div>';
      });
  }

  function pickModel(modelId) {
    fetch('/api/models/select', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ model_id: modelId }),
    })
      .then(function (r) { return r.json(); })
      .then(function (data) {
        if (data.ok) {
          if (modelPickerLabel) modelPickerLabel.textContent = modelId;
          if (modelPickerDropdown) modelPickerDropdown.classList.add('hidden');
          // Also update model store if on that page
          if (window.MODELS_STORE_MODE) loadStoreModels();
          loadPickerModels();
        }
      })
      .catch(function () {});
  }

  if (modelPickerBtn && modelPickerDropdown) {
    modelPickerBtn.addEventListener('click', function (e) {
      e.stopPropagation();
      var isHidden = modelPickerDropdown.classList.contains('hidden');
      modelPickerDropdown.classList.toggle('hidden');
      if (isHidden) loadPickerModels();
    });
    document.addEventListener('click', function (e) {
      if (!modelPickerDropdown.contains(e.target) && e.target !== modelPickerBtn) {
        modelPickerDropdown.classList.add('hidden');
      }
    });
  }

  if (modelPickerRefresh) {
    modelPickerRefresh.addEventListener('click', function (e) {
      e.stopPropagation();
      loadPickerModels();
    });
  }

  // ===== Models Store page =====
  var modelsGrid = document.getElementById('modelsGrid');
  var modelsStatus = document.getElementById('modelsStatus');

  function loadStoreModels() {
    if (!modelsGrid) return;
    modelsGrid.innerHTML = '';
    if (modelsStatus) {
      modelsStatus.innerHTML = '<div class="models-status-icon"><span class="typing-dot"></span><span class="typing-dot"></span><span class="typing-dot"></span></div><span>Chargement des modeles...</span>';
      modelsStatus.className = 'models-status';
    }
    fetch('/api/models')
      .then(function (r) { return r.json(); })
      .then(function (data) {
        var models = data.models || [];
        var current = data.current || '';
        if (modelsStatus) {
          if (models.length > 0) {
            modelsStatus.innerHTML = '<div class="models-status-icon models-status-ok"><svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"/><polyline points="22 4 12 14.01 9 11.01"/></svg></div><span>Connecte a LM Studio — ' + models.length + ' modele(s) disponible(s)</span>';
            modelsStatus.className = 'models-status models-status-connected';
          } else {
            modelsStatus.innerHTML = '<div class="models-status-icon models-status-warn"><svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/></svg></div><span>Aucun modele charge dans LM Studio. Chargez un modele pour commencer.</span>';
            modelsStatus.className = 'models-status models-status-warning';
          }
        }
        if (models.length === 0) {
          modelsGrid.innerHTML = '<div class="models-empty"><p>Chargez un modele dans LM Studio pour le voir apparaitre ici.</p></div>';
          return;
        }
        modelsGrid.innerHTML = models.map(function (m) {
          var isActive = m.id === current;
          var shortName = m.id.split('/').pop().replace(/\.gguf$/i, '');
          return '<div class="model-card' + (isActive ? ' model-card-active' : '') + '" data-model-id="' + esc(m.id) + '">' +
            '<div class="model-card-icon">' +
              '<svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><path d="M21 16V8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16z"/><polyline points="3.27 6.96 12 12.01 20.73 6.96"/><line x1="12" y1="22.08" x2="12" y2="12"/></svg>' +
            '</div>' +
            '<div class="model-card-info">' +
              '<div class="model-card-name">' + esc(shortName) + '</div>' +
              '<div class="model-card-id">' + esc(m.id) + '</div>' +
              (m.owned_by ? '<div class="model-card-owner">' + esc(m.owned_by) + '</div>' : '') +
            '</div>' +
            '<div class="model-card-actions">' +
              (isActive
                ? '<span class="model-card-badge-active">Actif</span>'
                : '<button class="btn btn-primary btn-sm model-use-btn">Utiliser</button>'
              ) +
            '</div>' +
          '</div>';
        }).join('');
        modelsGrid.querySelectorAll('.model-card').forEach(function (card) {
          var useBtn = card.querySelector('.model-use-btn');
          if (useBtn) {
            useBtn.addEventListener('click', function () {
              var mid = card.getAttribute('data-model-id');
              pickModel(mid);
            });
          }
        });
      })
      .catch(function (err) {
        if (modelsStatus) {
          modelsStatus.innerHTML = '<div class="models-status-icon models-status-err"><svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><line x1="15" y1="9" x2="9" y2="15"/><line x1="9" y1="9" x2="15" y2="15"/></svg></div><span>Erreur de connexion a LM Studio</span>';
          modelsStatus.className = 'models-status models-status-error';
        }
        modelsGrid.innerHTML = '<div class="models-empty"><p>Impossible de se connecter a LM Studio. Verifiez que le serveur est demarre.</p></div>';
      });
  }

  // HUB Search functionality
  var modelSearchInput = document.getElementById('modelSearchInput');
  var modelSearchBtn = document.getElementById('modelSearchBtn');
  var hubSection = document.getElementById('hubSection');
  var hubModelsGrid = document.getElementById('hubModelsGrid');
  var searchStatus = document.getElementById('searchStatus');

  function searchHubModels(query) {
    if (!query) return;
    if (hubSection) hubSection.classList.remove('hidden');
    if (searchStatus) {
      searchStatus.classList.remove('hidden');
      searchStatus.innerHTML = '<div class="models-status-icon"><span class="typing-dot"></span><span class="typing-dot"></span><span class="typing-dot"></span></div><span>Recherche en cours...</span>';
    }
    if (hubModelsGrid) hubModelsGrid.innerHTML = '';

    fetch(window.HUB_SEARCH_URL + '?query=' + encodeURIComponent(query))
      .then(function(res) { return res.json(); })
      .then(function(data) {
        if (searchStatus) searchStatus.classList.add('hidden');
        var results = data.results || [];
        if (results.length === 0) {
          hubModelsGrid.innerHTML = '<div class="models-empty"><p>Aucun modèle GGUF ne correspond à cette recherche.</p></div>';
          return;
        }

        hubModelsGrid.innerHTML = results.map(function(m) {
          var shortName = m.id.split('/').pop().replace(/\.gguf$/i, '');
          var author = m.author || m.id.split('/')[0];
          return '<div class="model-card" data-hub-id="' + esc(m.id) + '">' +
            '<div class="model-card-icon">' +
              '<svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><path d="M21 16V8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16z"/><polyline points="3.27 6.96 12 12.01 20.73 6.96"/><line x1="12" y1="22.08" x2="12" y2="12"/></svg>' +
            '</div>' +
            '<div class="model-card-info">' +
              '<div class="model-card-name">' + esc(shortName) + '</div>' +
              '<div class="model-card-id">' + esc(m.id) + '</div>' +
              '<div class="model-card-owner">@' + esc(author) + '</div>' +
            '</div>' +
            '<div class="model-card-meta">' +
              '<span><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg> ' + m.downloads + '</span>' +
              '<span><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M20.84 4.61a5.5 5.5 0 0 0-7.78 0L12 5.67l-1.06-1.06a5.5 5.5 0 0 0-7.78 7.78l1.06 1.06L12 21.23l7.78-7.78 1.06-1.06a5.5 5.5 0 0 0 0-7.78z"/></svg> ' + m.likes + '</span>' +
            '</div>' +
            '<div class="model-card-actions">' +
              '<button class="btn btn-primary btn-sm btn-download model-download-btn">Installer (LM Studio)</button>' +
            '</div>' +
          '</div>';
        }).join('');

        hubModelsGrid.querySelectorAll('.model-download-btn').forEach(function(btn) {
          btn.addEventListener('click', function(e) {
            var card = e.target.closest('.model-card');
            var hubId = card.getAttribute('data-hub-id');
            downloadHubModel(hubId, btn);
          });
        });
      })
      .catch(function(err) {
        if (searchStatus) {
          searchStatus.innerHTML = '<div class="models-status-icon models-status-err"><svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><line x1="15" y1="9" x2="9" y2="15"/><line x1="9" y1="9" x2="15" y2="15"/></svg></div><span>Erreur lors de la recherche sur le Hub.</span>';
        }
      });
  }

  function downloadHubModel(modelId, btnElement) {
    btnElement.disabled = true;
    btnElement.textContent = 'Téléchargement...';
    btnElement.style.opacity = '0.7';

    fetch(window.HUB_DOWNLOAD_URL, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ model_id: modelId })
    })
    .then(function(res) { return res.json(); })
    .then(function(data) {
      if (data.ok) {
        btnElement.textContent = 'Lancé (Voir LM Studio)';
        btnElement.style.background = 'var(--green)';
        btnElement.style.color = '#fff';
      } else {
        btnElement.textContent = 'Erreur';
        btnElement.style.background = 'var(--red)';
        btnElement.disabled = false;
        alert("Erreur de téléchargement : " + (data.detail || data.message || "inconnue"));
      }
    })
    .catch(function(err) {
      btnElement.textContent = 'Erreur';
      btnElement.disabled = false;
      alert("Erreur réseau lors du lancement du téléchargement.");
    });
  }

  if (modelSearchBtn && modelSearchInput) {
    modelSearchBtn.addEventListener('click', function() {
      searchHubModels(modelSearchInput.value.trim());
    });
    modelSearchInput.addEventListener('keypress', function(e) {
      if (e.key === 'Enter') {
        e.preventDefault();
        searchHubModels(modelSearchInput.value.trim());
      }
    });
  }

  // Config page compatibility (old page still works)
  // The variables modelsUrl, selectUrl, configInfoUrl, modelListEl, currentModelEl, refreshModelsBtn, modelStatusEl are already declared above.
  // The showModelStatus function is also already declared above.

  function loadModels() {
    if (!modelListEl || !modelsUrl) return;
    modelListEl.innerHTML = '<div class="config-loading"><span class="typing-dot"></span><span class="typing-dot"></span><span class="typing-dot"></span> Chargement...</div>';

    fetch(modelsUrl)
      .then(function (r) { return r.json(); })
      .then(function (data) {
        var models = data.models || [];
        var current = data.current || '';
        if (currentModelEl) currentModelEl.textContent = current;

        if (models.length === 0) {
          modelListEl.innerHTML = '<div class="config-error">Aucun modele trouve.</div>';
          return;
        }

        modelListEl.innerHTML = models.map(function (m) {
          var isActive = m.id === current;
          return '<div class="config-model-item' + (isActive ? ' active' : '') + '" data-model-id="' + esc(m.id) + '">' +
            '<div>' +
              '<div class="config-model-name">' + esc(m.id) + '</div>' +
              (m.owned_by ? '<div class="config-model-owner">' + esc(m.owned_by) + '</div>' : '') +
            '</div>' +
            (isActive ? '<span class="config-model-active-badge">Actif</span>' : '') +
          '</div>';
        }).join('');

        modelListEl.querySelectorAll('.config-model-item').forEach(function (item) {
          item.addEventListener('click', function () {
            var mid = item.getAttribute('data-model-id');
            pickModel(mid);
            showModelStatus('Modele change : ' + mid, true);
            loadModels();
          });
        });
      })
      .catch(function (err) {
        modelListEl.innerHTML = '<div class="config-error">Erreur : ' + esc(err.message) + '</div>';
      });
  }

  // ===== LM Studio URL connection =====
  var setUrlEndpoint = window.CONFIG_SET_URL;
  var lmStudioUrlInput = document.getElementById('lmStudioUrl');
  var saveUrlBtn = document.getElementById('saveUrlBtn');
  var urlStatusEl = document.getElementById('urlStatus');

  function showUrlStatus(text, ok) {
    if (!urlStatusEl) return;
    urlStatusEl.textContent = text;
    urlStatusEl.className = 'models-connection-status ' + (ok ? 'models-connection-status-ok' : 'models-connection-status-err');
    urlStatusEl.classList.remove('hidden');
  }

  if (saveUrlBtn && lmStudioUrlInput && setUrlEndpoint) {
    saveUrlBtn.addEventListener('click', function () {
      var raw = lmStudioUrlInput.value.trim();
      if (!raw) return;
      var url = raw.match(/^https?:\/\//) ? raw : 'http://' + raw;

      saveUrlBtn.disabled = true;
      saveUrlBtn.textContent = 'Connexion...';
      showUrlStatus('Test de connexion en cours...', true);

      fetch(setUrlEndpoint, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ url: url }),
      })
        .then(function (r) { return r.json(); })
        .then(function (data) {
          if (data.ok && data.connected) {
            showUrlStatus('Connecte a LM Studio sur ' + data.url, true);
            if (window.MODELS_STORE_MODE) loadStoreModels();
            else loadModels();
            loadConfigInfo();
            if (modelPickerLabel) loadPickerModels();
          } else if (data.ok) {
            showUrlStatus('URL enregistree (' + data.url + ') mais LM Studio ne repond pas. Verifiez que le serveur est demarre.', false);
            loadConfigInfo();
          } else {
            showUrlStatus('Erreur lors de la configuration.', false);
          }
        })
        .catch(function (err) {
          showUrlStatus('Erreur reseau : ' + err.message, false);
        })
        .finally(function () {
          saveUrlBtn.disabled = false;
          saveUrlBtn.innerHTML = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"/><polyline points="22 4 12 14.01 9 11.01"/></svg> Connecter';
        });
    });

    lmStudioUrlInput.addEventListener('keypress', function (e) {
      if (e.key === 'Enter') {
        e.preventDefault();
        saveUrlBtn.click();
      }
    });
  }

  function loadConfigInfo() {
    if (!configInfoUrl) return;
    fetch(configInfoUrl)
      .then(function (r) { return r.json(); })
      .then(function (data) {
        var urlEl = document.getElementById('infoUrl');
        var timeoutEl = document.getElementById('infoTimeout');
        var iterEl = document.getElementById('infoIterations');
        if (urlEl) urlEl.textContent = data.lm_studio_url || '-';
        if (timeoutEl) timeoutEl.textContent = data.tool_timeout + 's';
        if (iterEl) iterEl.textContent = data.max_iterations;
        // Pre-fill URL input with current URL (strip http:// and /v1)
        if (lmStudioUrlInput && data.lm_studio_url) {
          var cleanUrl = data.lm_studio_url
            .replace(/\s*\(.*\)$/, '')
            .replace(/^https?:\/\//, '')
            .replace(/\/v1\/?$/, '')
            .trim();
          if (cleanUrl && !lmStudioUrlInput.value) {
            lmStudioUrlInput.value = cleanUrl;
          }
        }
      })
      .catch(function () {});
  }

  if (refreshModelsBtn) {
    refreshModelsBtn.addEventListener('click', function () {
      if (window.MODELS_STORE_MODE) loadStoreModels();
      else loadModels();
    });
  }

  if (window.MODELS_STORE_MODE) {
    loadStoreModels();
    loadConfigInfo();
  } else if (modelListEl && modelsUrl) {
    loadModels();
    loadConfigInfo();
  }

  // ===== Dashboard =====
  var dashboardUrl = window.DASHBOARD_URL;
  if (dashboardUrl) {
    fetch(dashboardUrl)
      .then(function (r) { return r.json(); })
      .then(function (data) {
        var lm = data.lm_studio || {};
        var statusLm = document.getElementById('statusLm');
        var statusLmValue = document.getElementById('statusLmValue');
        var statusChats = document.getElementById('statusChats');
        var statusReports = document.getElementById('statusReports');
        var statusModel = document.getElementById('statusModel');

        if (statusLm) {
          var icon = statusLm.querySelector('.status-icon');
          if (lm.connected) {
            if (icon) { icon.className = 'status-icon status-ok'; icon.innerHTML = '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"/><polyline points="22 4 12 14.01 9 11.01"/></svg>'; }
            if (statusLmValue) statusLmValue.textContent = 'Connecte — ' + lm.model_count + ' modele(s)';
          } else {
            if (icon) { icon.className = 'status-icon status-err'; icon.innerHTML = '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><line x1="15" y1="9" x2="9" y2="15"/><line x1="9" y1="9" x2="15" y2="15"/></svg>'; }
            if (statusLmValue) statusLmValue.textContent = 'Deconnecte';
          }
        }
        if (statusChats) statusChats.textContent = data.chats_count || 0;
        if (statusReports) statusReports.textContent = data.reports_count || 0;
        if (statusModel) statusModel.textContent = (lm.current_model || '—');
      })
      .catch(function () {
        var statusLmValue = document.getElementById('statusLmValue');
        if (statusLmValue) statusLmValue.textContent = 'Erreur de connexion';
      });
  }

  // ===== Auto-scroll: follows content, pauses when user scrolls up =====
  var _autoScroll = true;
  var _lastScrollTop = 0;

  if (chatScroll) {
    chatScroll.addEventListener('scroll', function () {
      var atBottom = chatScroll.scrollHeight - chatScroll.scrollTop - chatScroll.clientHeight < 150;
      if (chatScroll.scrollTop < _lastScrollTop && !atBottom) {
        _autoScroll = false;
      }
      if (atBottom) {
        _autoScroll = true;
      }
      _lastScrollTop = chatScroll.scrollTop;
    });
  }

  var _origScrollToBottom = scrollToBottom;
  scrollToBottom = function (smooth) {
    if (_autoScroll) _origScrollToBottom(smooth);
  };

  // Force scroll when user sends a message
  var _origAddUserMsg = addUserMsg;
  addUserMsg = function (text) {
    _autoScroll = true;
    _origAddUserMsg(text);
  };
})();
