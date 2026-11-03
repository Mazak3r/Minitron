@if(!session('minitron_admin'))
  {{-- LOCKED STATE --}}
  <div class="sidebar collapsed" id="sidebar">
    <h2>🔒 Sidebar Locked</h2>
    <div class="sidebar-status info">
      Authentication required to access system controls.
    </div>

    <form method="POST" action="{{ route('admin.login') }}" style="margin-top: 15px;">
      @csrf
      <label class="sidebar-label">Password</label>
      <input type="password" name="password" class="sidebar-input" placeholder="Enter password..." required>
      <button type="submit" class="sidebar-btn primary" style="margin-top: 10px;">
        🔓 Unlock
      </button>
    </form>

    @if(session('error'))
      <div class="sidebar-status error" style="margin-top: 10px;">
        ❌ {{ session('error') }}
      </div>
    @endif
  </div>
@else
  {{-- UNLOCKED STATE --}}
  <div class="sidebar collapsed" id="sidebar">
    <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 15px;">
      <h2 style="margin: 0; border: none;">System Status</h2>
      <form method="POST" action="{{ route('admin.logout') }}" style="margin: 0;">
        @csrf
        <button type="submit" class="sidebar-btn" style="width: auto; padding: 4px 8px; font-size: 0.75rem;">
          🔒 Lock
        </button>
      </form>
    </div>

    <div class="sidebar-status info" id="health-stats">Loading...</div>
    <div class="sidebar-status info" id="memory-stats">Loading...</div>

    <h2>🔄 Selenium OLT Status</h2>
    <div class="sidebar-status info" id="selenium-stats">Loading...</div>

    <h2>📡 CDATA OLT Status</h2>
    <div class="sidebar-status info" id="cdata-stats">Loading...</div>

    <h2>🔄 Manual Update</h2>
    <button class="sidebar-btn primary" id="selenium-update-btn">🔄 Update Selenium OLTs Now</button>
    <div class="sidebar-status info" id="selenium-update-progress" style="display:none;"></div>

    <h2>📡 CDATA Monitoring</h2>
    <label class="sidebar-label">OLT ID</label>
    <input type="text" class="sidebar-input" id="cdata-olt-input" placeholder="e.g. cdata1">
    <label class="sidebar-label">Ports (comma-separated)</label>
    <input type="text" class="sidebar-input" id="cdata-ports-input" value="1,2,3,4,5,6,7,8">
    <button class="sidebar-btn" id="cdata-monitor-btn">🚀 Run CDATA Monitoring</button>

    <h2>🔑 Diameter Session</h2>
    <label class="sidebar-label">PHPSESSID</label>
    <input type="text" class="sidebar-input" id="phpsessid-input" placeholder="Paste PHPSESSID">
    <button class="sidebar-btn" id="phpsessid-btn">💾 Save Session</button>

    <h2>🌐 Network Access</h2>
    <div class="sidebar-status info" id="network-info">Loading...</div>
  </div>
@endif
