<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>MINITRON v0.008</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Rajdhani:wght@400;500;600;700&display=swap" rel="stylesheet">
<link rel="stylesheet" href="{{ asset('css/minitron.css') }}">
<script src="https://cdn.jsdelivr.net/npm/marked@12/marked.min.js"></script>
</head>
<body>
<div class="layout">
  @include('partials.sidebar')
  <div class="chat-area">
    <div class="chat-header">
      <button class="menu-btn" id="menu-btn" title="Toggle sidebar">☰</button>
      <h1>MINITRON <span class="version">v0.008</span></h1>
    </div>
    <div class="messages empty" id="messages">
      <div class="empty-state" style="text-align:center; margin-top: 10vh;">
        <img src="/images/mechamaru-avatar.png" style="width: 120px; height: 120px; border-radius: 50%; border: 2px solid var(--accent); box-shadow: 0 0 20px rgba(0,255,204,0.4); margin-bottom: 20px;">
        <h2 style="font-size: 2rem; color: #fff; text-shadow: 0 0 15px rgba(0,255,204,0.5); margin-bottom: 8px;">MINITRON</h2>
        <p style="color: var(--accent); letter-spacing: 0.1em; text-transform: uppercase; font-size: 0.85rem; margin-bottom: 24px;">Network Diagnostic Assistant</p>
        <p style="color: var(--text-muted); font-size: 1rem;">Enter a <strong>username</strong>, <strong>GPON serial number</strong>, or <strong>MAC address</strong> to diagnose.</p>
        <div class="example-prompts" style="display: flex; gap: 12px; justify-content: center; margin-top: 32px;">
          <div class="example-prompt" data-prompt="john_doe">👤 Try: john_doe</div>
          <div class="example-prompt" data-prompt="HWTC1234ABCD">💻 Try: HWTC1234ABCD</div>
          <div class="example-prompt" data-prompt="AA:BB:CC:DD:EE:FF">📡 Try a MAC address</div>
        </div>
      </div>
    </div>
    <div class="input-area">
      <div class="input-container">
        <textarea id="chat-input" class="chat-input" placeholder="Enter username or serial number..." rows="1"></textarea>
        <button id="send-btn" class="send-btn" title="Send">
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5">
            <line x1="12" y1="19" x2="12" y2="5"></line>
            <polyline points="5 12 12 5 19 12"></polyline>
          </svg>
        </button>
      </div>
      <div class="hint">Press Enter to search · Shift+Enter for new line</div>
    </div>
  </div>
</div>
<script>window.__MINITRON_CSRF = '{{ csrf_token() }}';</script>
<script src="{{ asset('js/minitron.js') }}"></script>
</body>
</html>
