/* ═══════════════════════════════════════════════════════════
   GridFront Detect — Settings Panel
   Full-screen overlay with sections for machine type, zone
   distances, detection classes, and camera management.
   Registers as GF.settings with open() / close() methods.
   ═══════════════════════════════════════════════════════════ */
(function() {
  'use strict';

  window.GF = window.GF || {};

  // ── Lucide-style inline SVG icons (no CDN dependency) ─────
  var _s = 'width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"';
  var ICONS = {
    'wheel-loader':  '<svg ' + _s + '><rect x="2" y="13" width="8" height="6" rx="1"/><circle cx="5" cy="19" r="2.5"/><circle cx="17" cy="19" r="2.5"/><path d="M14 13V7l4 6h4"/><path d="M10 16h4"/></svg>',
    'excavator':     '<svg ' + _s + '><path d="M2 20h4l3-8 5 8h8"/><path d="M17 8V5l-3-2"/><path d="M14 3l4 4-6 6"/><circle cx="6" cy="20" r="2"/><circle cx="18" cy="20" r="2"/></svg>',
    'dozer':         '<svg ' + _s + '><rect x="1" y="12" width="16" height="6" rx="1"/><path d="M17 15h4l2-5H17"/><circle cx="5" cy="18" r="2.5"/><circle cx="13" cy="18" r="2.5"/><path d="M1 12l2-4h14"/></svg>',
    'dump-truck':    '<svg ' + _s + '><path d="M1 14h12V6H1z"/><path d="M13 14h4l4-4V6h-4"/><circle cx="5" cy="17" r="2.5"/><circle cx="17" cy="17" r="2.5"/><path d="M8 17h5"/></svg>',
    'user':          '<svg ' + _s + '><circle cx="12" cy="8" r="5"/><path d="M20 21a8 8 0 0 0-16 0"/></svg>',
    'car':           '<svg ' + _s + '><path d="M5 11l1.5-4.5A2 2 0 0 1 8.4 5h7.2a2 2 0 0 1 1.9 1.5L19 11"/><path d="M3 17h18v-4a2 2 0 0 0-2-2H5a2 2 0 0 0-2 2v4z"/><circle cx="7.5" cy="17" r="2.5"/><circle cx="16.5" cy="17" r="2.5"/></svg>',
    'wrench':        '<svg ' + _s + '><path d="M14.7 6.3a1 1 0 0 0 0 1.4l1.6 1.6a1 1 0 0 0 1.4 0l3.77-3.77a6 6 0 0 1-7.94 7.94l-6.91 6.91a2.12 2.12 0 0 1-3-3l6.91-6.91a6 6 0 0 1 7.94-7.94l-3.76 3.76z"/></svg>',
    'bike':          '<svg ' + _s + '><circle cx="5.5" cy="17.5" r="3.5"/><circle cx="18.5" cy="17.5" r="3.5"/><path d="M15 6a1 1 0 1 0 0-2 1 1 0 0 0 0 2z" fill="currentColor"/><path d="M12 17.5V14l-3-3 4-3 2 3h3"/></svg>',
    'triangle':      '<svg ' + _s + '><path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/></svg>',
  };

  // ── CSS ────────────────────────────────────────────────────
  var CSS = [
    /* Backdrop */
    '#gf-settings-backdrop {',
    '  position: fixed; top: 0; left: 0; right: 0; bottom: 0;',
    '  background: rgba(0,0,0,0.5);',
    '  z-index: 1000;',
    '  opacity: 0;',
    '  pointer-events: none;',
    '  transition: opacity 0.3s ease;',
    '}',
    '#gf-settings-backdrop.gf-open {',
    '  opacity: 1;',
    '  pointer-events: all;',
    '}',

    /* Panel */
    '#gf-settings-panel {',
    '  position: fixed; top: 0; right: 0; bottom: 0;',
    '  width: 380px; max-width: 90vw;',
    '  background: #F8F8F8;',
    '  z-index: 1001;',
    '  transform: translateX(100%);',
    '  transition: transform 0.3s ease;',
    '  display: flex; flex-direction: column;',
    '  box-shadow: -4px 0 24px rgba(0,0,0,0.18);',
    '}',
    '#gf-settings-panel.gf-open {',
    '  transform: translateX(0);',
    '}',

    /* Panel header */
    '#gf-settings-header {',
    '  display: flex; align-items: center; justify-content: space-between;',
    '  padding: 16px 18px 14px;',
    '  border-bottom: 1px solid #E5E7EB;',
    '  background: #fff;',
    '  flex-shrink: 0;',
    '}',
    '#gf-settings-header h2 {',
    '  font-size: 16px; font-weight: 700; color: #22384C;',
    '  font-family: system-ui, -apple-system, sans-serif;',
    '  margin: 0;',
    '}',
    '#gf-settings-close {',
    '  width: 32px; height: 32px; border-radius: 50%;',
    '  border: none; background: #F3F4F6; cursor: pointer;',
    '  display: flex; align-items: center; justify-content: center;',
    '  color: #6B7280; font-size: 18px; line-height: 1;',
    '  transition: background 0.2s;',
    '}',
    '#gf-settings-close:active { background: #E5E7EB; }',

    /* Scrollable body */
    '#gf-settings-body {',
    '  flex: 1; overflow-y: auto; padding: 0 0 24px;',
    '  -webkit-overflow-scrolling: touch;',
    '}',

    /* Section */
    '.gf-section {',
    '  padding: 16px 18px 0;',
    '}',
    '.gf-section + .gf-section {',
    '  border-top: 1px solid #E5E7EB;',
    '  margin-top: 4px;',
    '}',
    '.gf-section-title {',
    '  font-size: 11px; font-weight: 600; text-transform: uppercase;',
    '  letter-spacing: 0.6px; color: #6B7280;',
    '  margin-bottom: 12px;',
    '  font-family: system-ui, -apple-system, sans-serif;',
    '}',

    /* Machine cards */
    '.gf-machine-grid {',
    '  display: grid; grid-template-columns: 1fr 1fr;',
    '  gap: 8px; margin-bottom: 4px;',
    '}',
    '.gf-machine-card {',
    '  border: 2px solid #E5E7EB; border-radius: 10px;',
    '  padding: 10px 12px;',
    '  cursor: pointer; background: #fff;',
    '  display: flex; align-items: center; gap: 8px;',
    '  font-family: system-ui, -apple-system, sans-serif;',
    '  font-size: 13px; font-weight: 600; color: #22384C;',
    '  transition: border-color 0.2s, background 0.2s;',
    '  -webkit-tap-highlight-color: transparent;',
    '}',
    '.gf-machine-card.gf-active {',
    '  border-color: #4A84BF; background: #EBF3FB;',
    '  color: #4A84BF;',
    '}',
    '.gf-machine-icon { font-size: 20px; line-height: 1; }',

    /* Zone sliders */
    '.gf-zone-row {',
    '  display: flex; flex-direction: column; gap: 4px;',
    '  margin-bottom: 12px;',
    '}',
    '.gf-zone-row-head {',
    '  display: flex; justify-content: space-between; align-items: baseline;',
    '}',
    '.gf-zone-label {',
    '  font-size: 13px; font-weight: 600; color: #22384C;',
    '  font-family: system-ui, -apple-system, sans-serif;',
    '}',
    '.gf-zone-value {',
    '  font-size: 13px; font-weight: 700;',
    '  font-family: system-ui, -apple-system, sans-serif;',
    '  min-width: 44px; text-align: right;',
    '}',
    '.gf-slider {',
    '  -webkit-appearance: none; appearance: none;',
    '  width: 100%; height: 6px; border-radius: 3px;',
    '  outline: none; cursor: pointer;',
    '  transition: opacity 0.2s;',
    '}',
    '.gf-slider::-webkit-slider-thumb {',
    '  -webkit-appearance: none; appearance: none;',
    '  width: 22px; height: 22px; border-radius: 50%;',
    '  background: #fff; border: 2px solid currentColor;',
    '  box-shadow: 0 1px 4px rgba(0,0,0,0.2);',
    '  cursor: pointer;',
    '}',
    '.gf-slider-danger { background: linear-gradient(to right, #EF4444 0%, #EF4444 var(--pct, 30%), #E5E7EB var(--pct, 30%)); color: #EF4444; }',
    '.gf-slider-warning { background: linear-gradient(to right, #F59E0B 0%, #F59E0B var(--pct, 50%), #E5E7EB var(--pct, 50%)); color: #F59E0B; }',
    '.gf-slider-range   { background: linear-gradient(to right, #44A5D6 0%, #44A5D6 var(--pct, 40%), #E5E7EB var(--pct, 40%)); color: #44A5D6; }',
    '.gf-save-btn {',
    '  margin-top: 4px; margin-bottom: 12px;',
    '  width: 100%; height: 40px; border-radius: 8px;',
    '  border: none; background: #4A84BF; color: #fff;',
    '  font-size: 14px; font-weight: 600;',
    '  font-family: system-ui, -apple-system, sans-serif;',
    '  cursor: pointer; transition: background 0.2s;',
    '}',
    '.gf-save-btn:active { background: #3a6fa8; }',
    '.gf-save-btn:disabled { background: #9CA3AF; cursor: default; }',

    /* Detection class toggles */
    '.gf-class-row {',
    '  display: flex; align-items: center; gap: 10px;',
    '  padding: 8px 0; border-bottom: 1px solid #F3F4F6;',
    '}',
    '.gf-class-row:last-child { border-bottom: none; }',
    '.gf-class-icon { font-size: 18px; width: 24px; text-align: center; flex-shrink: 0; }',
    '.gf-class-info { flex: 1; }',
    '.gf-class-name {',
    '  font-size: 13px; font-weight: 600; color: #22384C;',
    '  font-family: system-ui, -apple-system, sans-serif;',
    '}',
    '.gf-class-priority {',
    '  font-size: 11px; color: #9CA3AF;',
    '  font-family: system-ui, -apple-system, sans-serif;',
    '}',

    /* Toggle switch */
    '.gf-toggle {',
    '  position: relative; width: 44px; height: 26px;',
    '  flex-shrink: 0; cursor: pointer;',
    '}',
    '.gf-toggle input { opacity: 0; width: 0; height: 0; position: absolute; }',
    '.gf-toggle-track {',
    '  position: absolute; top: 0; left: 0; right: 0; bottom: 0;',
    '  background: #D1D5DB; border-radius: 13px;',
    '  transition: background 0.2s;',
    '}',
    '.gf-toggle input:checked + .gf-toggle-track { background: #22c55e; }',
    '.gf-toggle-thumb {',
    '  position: absolute; top: 3px; left: 3px;',
    '  width: 20px; height: 20px; border-radius: 50%;',
    '  background: #fff; box-shadow: 0 1px 3px rgba(0,0,0,0.3);',
    '  transition: transform 0.2s;',
    '}',
    '.gf-toggle input:checked ~ .gf-toggle-thumb { transform: translateX(18px); }',

    /* Camera list */
    '.gf-camera-item {',
    '  background: #fff; border: 1px solid #E5E7EB; border-radius: 10px;',
    '  padding: 10px 12px; margin-bottom: 8px;',
    '  display: flex; align-items: center; gap: 10px;',
    '}',
    '.gf-camera-status {',
    '  width: 10px; height: 10px; border-radius: 50%; flex-shrink: 0;',
    '}',
    '.gf-camera-status.connected { background: #22c55e; }',
    '.gf-camera-status.disconnected { background: #9CA3AF; }',
    '.gf-camera-info { flex: 1; min-width: 0; }',
    '.gf-camera-name {',
    '  font-size: 13px; font-weight: 600; color: #22384C;',
    '  font-family: system-ui, -apple-system, sans-serif;',
    '  white-space: nowrap; overflow: hidden; text-overflow: ellipsis;',
    '}',
    '.gf-camera-sub {',
    '  font-size: 11px; color: #6B7280;',
    '  font-family: system-ui, -apple-system, sans-serif;',
    '  white-space: nowrap; overflow: hidden; text-overflow: ellipsis;',
    '}',
    '.gf-icon-btn {',
    '  width: 30px; height: 30px; border-radius: 6px;',
    '  border: 1px solid #E5E7EB; background: #F9FAFB;',
    '  cursor: pointer; font-size: 14px;',
    '  display: flex; align-items: center; justify-content: center;',
    '  flex-shrink: 0; transition: background 0.2s;',
    '}',
    '.gf-icon-btn:active { background: #E5E7EB; }',
    '.gf-icon-btn.danger { border-color: #FCA5A5; color: #EF4444; }',
    '.gf-icon-btn.danger:active { background: #FEE2E2; }',

    /* Form inputs */
    '.gf-form-row { margin-bottom: 10px; }',
    '.gf-form-label {',
    '  font-size: 11px; font-weight: 600; text-transform: uppercase;',
    '  letter-spacing: 0.4px; color: #6B7280; margin-bottom: 4px;',
    '  display: block;',
    '  font-family: system-ui, -apple-system, sans-serif;',
    '}',
    '.gf-input {',
    '  width: 100%; height: 40px; border-radius: 8px;',
    '  border: 1.5px solid #D1D5DB; background: #fff;',
    '  padding: 0 12px; font-size: 14px; color: #22384C;',
    '  font-family: system-ui, -apple-system, sans-serif;',
    '  outline: none; box-sizing: border-box;',
    '  transition: border-color 0.2s;',
    '}',
    '.gf-input:focus { border-color: #4A84BF; }',
    'select.gf-input { cursor: pointer; -webkit-appearance: none; appearance: none; background-image: url("data:image/svg+xml,%3Csvg xmlns=\'http://www.w3.org/2000/svg\' width=\'12\' height=\'8\' viewBox=\'0 0 12 8\'%3E%3Cpath d=\'M1 1l5 5 5-5\' stroke=\'%236B7280\' stroke-width=\'1.5\' fill=\'none\' stroke-linecap=\'round\'/%3E%3C/svg%3E"); background-repeat: no-repeat; background-position: right 12px center; padding-right: 32px; }',
    '.gf-form-box {',
    '  background: #fff; border: 1px solid #E5E7EB; border-radius: 10px;',
    '  padding: 14px; margin-bottom: 10px;',
    '}',
    '.gf-form-actions {',
    '  display: flex; gap: 8px; margin-top: 4px;',
    '}',
    '.gf-btn {',
    '  flex: 1; height: 38px; border-radius: 8px;',
    '  border: none; font-size: 13px; font-weight: 600;',
    '  font-family: system-ui, -apple-system, sans-serif;',
    '  cursor: pointer; transition: background 0.2s;',
    '}',
    '.gf-btn-primary { background: #4A84BF; color: #fff; }',
    '.gf-btn-primary:active { background: #3a6fa8; }',
    '.gf-btn-ghost { background: #F3F4F6; color: #22384C; }',
    '.gf-btn-ghost:active { background: #E5E7EB; }',

    /* Add camera button */
    '#gf-add-camera-btn {',
    '  width: 100%; height: 40px; border-radius: 8px; margin-bottom: 4px;',
    '  border: 2px dashed #D1D5DB; background: transparent;',
    '  font-size: 13px; font-weight: 600; color: #6B7280;',
    '  font-family: system-ui, -apple-system, sans-serif;',
    '  cursor: pointer; transition: border-color 0.2s, color 0.2s;',
    '  display: flex; align-items: center; justify-content: center; gap: 6px;',
    '}',
    '#gf-add-camera-btn:active { border-color: #4A84BF; color: #4A84BF; }',

    /* Placement editor button */
    '#gf-open-placement-btn {',
    '  width: 100%; height: 40px; border-radius: 8px; margin-bottom: 4px; margin-top: 8px;',
    '  border: none; background: #4A84BF; color: #fff;',
    '  font-size: 13px; font-weight: 600;',
    '  font-family: system-ui, -apple-system, sans-serif;',
    '  cursor: pointer; transition: background 0.2s;',
    '  display: flex; align-items: center; justify-content: center; gap: 6px;',
    '}',
    '#gf-open-placement-btn:active { background: #3a6fa8; }',

    /* Status / spinner */
    '.gf-status-msg {',
    '  font-size: 12px; color: #9CA3AF; text-align: center;',
    '  padding: 8px 0;',
    '  font-family: system-ui, -apple-system, sans-serif;',
    '}',
    '.gf-error-msg {',
    '  font-size: 12px; color: #EF4444; text-align: center;',
    '  padding: 8px 0;',
    '  font-family: system-ui, -apple-system, sans-serif;',
    '}',
  ].join('\n');

  function injectStyles() {
    var style = document.createElement('style');
    style.id = 'gf-settings-styles';
    style.textContent = CSS;
    document.head.appendChild(style);
  }

  // ── DOM construction ───────────────────────────────────────
  function buildDOM() {
    // Backdrop
    var backdrop = document.createElement('div');
    backdrop.id = 'gf-settings-backdrop';
    backdrop.addEventListener('click', function() { GF.settings.close(); });

    // Panel
    var panel = document.createElement('div');
    panel.id = 'gf-settings-panel';
    panel.setAttribute('role', 'dialog');
    panel.setAttribute('aria-label', 'Settings');

    // Panel header
    var header = document.createElement('div');
    header.id = 'gf-settings-header';
    header.innerHTML =
      '<h2>Settings</h2>' +
      '<button id="gf-settings-close" aria-label="Close settings">' +
      '<svg width="14" height="14" viewBox="0 0 14 14" fill="none">' +
      '<path d="M1 1l12 12M13 1L1 13" stroke="#6B7280" stroke-width="2" stroke-linecap="round"/>' +
      '</svg></button>';

    // Scrollable body
    var body = document.createElement('div');
    body.id = 'gf-settings-body';

    // Sections
    body.appendChild(buildServerSection());
    body.appendChild(buildMachineSection());
    body.appendChild(buildZoneSection());
    body.appendChild(buildDetectionSection());
    body.appendChild(buildCameraSection());

    panel.appendChild(header);
    panel.appendChild(body);

    document.body.appendChild(backdrop);
    document.body.appendChild(panel);

    // Wire close button
    document.getElementById('gf-settings-close').addEventListener('click', function() {
      GF.settings.close();
    });

    // Escape key
    document.addEventListener('keydown', function(e) {
      if (e.key === 'Escape' && panel.classList.contains('gf-open')) {
        GF.settings.close();
      }
    });
  }

  // ─────────────────────────────────────────────────────────
  // SECTION: Server Connection
  // ─────────────────────────────────────────────────────────

  function buildServerSection() {
    var sec = document.createElement('div');
    sec.className = 'gf-section';

    var title = document.createElement('div');
    title.className = 'gf-section-title';
    title.textContent = 'Pipeline Server';
    sec.appendChild(title);

    // Status indicator
    var statusRow = document.createElement('div');
    statusRow.style.cssText = 'display:flex;align-items:center;gap:8px;margin-bottom:12px;';
    var statusDot = document.createElement('span');
    statusDot.id = 'gf-server-status-dot';
    statusDot.style.cssText = 'width:10px;height:10px;border-radius:50%;background:#9CA3AF;flex-shrink:0;';
    var statusText = document.createElement('span');
    statusText.id = 'gf-server-status-text';
    statusText.style.cssText = 'font-size:13px;color:#6B7280;font-family:system-ui,-apple-system,sans-serif;';
    statusText.textContent = 'Not connected — using local simulation';
    statusRow.appendChild(statusDot);
    statusRow.appendChild(statusText);
    sec.appendChild(statusRow);

    // Server IP input
    var row = document.createElement('div');
    row.style.cssText = 'display:flex;gap:8px;align-items:center;';
    var input = document.createElement('input');
    input.type = 'text';
    input.id = 'gf-server-ip';
    input.className = 'gf-input';
    input.placeholder = 'e.g. 192.168.1.50:5555';
    input.style.cssText += 'flex:1;';
    // Load saved server IP
    var savedIp = '';
    if (GF.config && GF.config.get) {
      savedIp = GF.config.get('server_ip') || '';
    } else {
      savedIp = localStorage.getItem('gf_server_ip') || '';
    }
    input.value = savedIp;

    var connectBtn = document.createElement('button');
    connectBtn.className = 'gf-btn gf-btn-primary';
    connectBtn.textContent = 'Connect';
    connectBtn.style.cssText += 'white-space:nowrap;padding:8px 16px;';
    connectBtn.addEventListener('click', function() {
      var ip = input.value.trim();
      if (!ip) {
        // Disconnect — go back to local
        localStorage.setItem('gf_server_ip', '');
        if (GF.config && GF.config.set) GF.config.set('server_ip', '');
        statusDot.style.background = '#9CA3AF';
        statusText.textContent = 'Disconnected — using local simulation';
        return;
      }
      // Save and test connection
      var url = ip.indexOf('://') >= 0 ? ip : 'http://' + ip;
      if (url.indexOf(':', 6) < 0) url += ':5555'; // default port
      localStorage.setItem('gf_server_ip', url);
      if (GF.config && GF.config.set) GF.config.set('server_ip', url);

      statusDot.style.background = '#F59E0B';
      statusText.textContent = 'Connecting to ' + url + '...';

      // Test connection
      fetch(url + '/api/system/health', { method: 'GET', signal: AbortSignal.timeout(3000) })
        .then(function(r) { return r.json(); })
        .then(function(data) {
          statusDot.style.background = '#22c55e';
          statusText.textContent = 'Connected to ' + url + ' — ' + (data.active_machine || 'online');
        })
        .catch(function(err) {
          statusDot.style.background = '#EF4444';
          statusText.textContent = 'Failed: ' + (err.message || 'unreachable');
        });
    });

    row.appendChild(input);
    row.appendChild(connectBtn);
    sec.appendChild(row);

    // Help text
    var help = document.createElement('div');
    help.style.cssText = 'font-size:11px;color:#9CA3AF;margin-top:6px;font-family:system-ui,-apple-system,sans-serif;';
    help.textContent = 'Enter the IP of your Raspberry Pi running the detection pipeline. Leave empty for simulation mode.';
    sec.appendChild(help);

    return sec;
  }

  // ─────────────────────────────────────────────────────────
  // SECTION: Machine Type
  // ─────────────────────────────────────────────────────────
  var MACHINE_DEFS = [
    { type: 'wheel_loader', label: 'Wheel Loader', icon: ICONS['wheel-loader'] },
    { type: 'excavator',    label: 'Excavator',    icon: ICONS['excavator'] },
    { type: 'dozer',        label: 'Dozer',        icon: ICONS['dozer'] },
    { type: 'dump_truck',   label: 'Dump Truck',   icon: ICONS['dump-truck'] },
  ];
  var _activeMachine = 'wheel_loader';

  function buildMachineSection() {
    var sec = document.createElement('div');
    sec.className = 'gf-section';

    var title = document.createElement('div');
    title.className = 'gf-section-title';
    title.textContent = 'Machine Type';
    sec.appendChild(title);

    var grid = document.createElement('div');
    grid.className = 'gf-machine-grid';
    grid.id = 'gf-machine-grid';

    MACHINE_DEFS.forEach(function(m) {
      var card = document.createElement('div');
      card.className = 'gf-machine-card' + (m.type === _activeMachine ? ' gf-active' : '');
      card.dataset.type = m.type;
      card.innerHTML =
        '<span class="gf-machine-icon">' + m.icon + '</span>' +
        '<span>' + m.label + '</span>';
      card.addEventListener('click', function() { activateMachine(m.type); });
      grid.appendChild(card);
    });

    sec.appendChild(grid);

    var status = document.createElement('div');
    status.className = 'gf-status-msg';
    status.id = 'gf-machine-status';
    sec.appendChild(status);

    return sec;
  }

  function activateMachine(type) {
    var grid = document.getElementById('gf-machine-grid');
    var statusEl = document.getElementById('gf-machine-status');
    if (!grid) return;

    // Optimistic UI update
    _activeMachine = type;
    var cards = grid.querySelectorAll('.gf-machine-card');
    for (var i = 0; i < cards.length; i++) {
      cards[i].classList.toggle('gf-active', cards[i].dataset.type === type);
    }

    if (statusEl) statusEl.textContent = '';

    GF.api.post('/api/machines/' + type + '/activate').then(function() {
      if (statusEl) statusEl.textContent = 'Switched.';
      setTimeout(function() { if (statusEl) statusEl.textContent = ''; }, 1500);
    }).catch(function(err) {
      if (statusEl) {
        statusEl.className = 'gf-error-msg';
        statusEl.textContent = 'Failed: ' + err.message;
      }
    });
  }

  function loadMachines() {
    GF.api.get('/api/machines').then(function(data) {
      var grid = document.getElementById('gf-machine-grid');
      if (!grid) return;
      // Mark the currently active machine if the API returns it
      if (data && data.active) {
        _activeMachine = data.active;
        var cards = grid.querySelectorAll('.gf-machine-card');
        for (var i = 0; i < cards.length; i++) {
          cards[i].classList.toggle('gf-active', cards[i].dataset.type === data.active);
        }
      }
    }).catch(function() { /* no API, defaults are fine */ });
  }

  // ─────────────────────────────────────────────────────────
  // SECTION: Zone Distances
  // ─────────────────────────────────────────────────────────
  var _zones = { danger_m: 3.0, warning_m: 7.0, max_range_m: 10.0 };

  var ZONE_SLIDERS = [
    { key: 'danger_m',    label: 'Danger Zone',   cls: 'gf-slider-danger', color: '#EF4444', min: 1,  max: 10,  step: 0.5 },
    { key: 'warning_m',   label: 'Warning Zone',  cls: 'gf-slider-warning',color: '#F59E0B', min: 3,  max: 20,  step: 0.5 },
    { key: 'max_range_m', label: 'Max Range',     cls: 'gf-slider-range',  color: '#44A5D6', min: 5,  max: 30,  step: 0.5 },
  ];

  function buildZoneSection() {
    var sec = document.createElement('div');
    sec.className = 'gf-section';

    var title = document.createElement('div');
    title.className = 'gf-section-title';
    title.textContent = 'Zone Distances';
    sec.appendChild(title);

    ZONE_SLIDERS.forEach(function(def) {
      var row = document.createElement('div');
      row.className = 'gf-zone-row';

      var head = document.createElement('div');
      head.className = 'gf-zone-row-head';

      var label = document.createElement('span');
      label.className = 'gf-zone-label';
      label.textContent = def.label;

      var valSpan = document.createElement('span');
      valSpan.className = 'gf-zone-value';
      valSpan.id = 'gf-zone-val-' + def.key;
      valSpan.style.color = def.color;
      valSpan.textContent = _zones[def.key].toFixed(1) + 'm';

      head.appendChild(label);
      head.appendChild(valSpan);
      row.appendChild(head);

      var slider = document.createElement('input');
      slider.type = 'range';
      slider.id = 'gf-zone-slider-' + def.key;
      slider.className = 'gf-slider ' + def.cls;
      slider.min = def.min;
      slider.max = def.max;
      slider.step = def.step;
      slider.value = _zones[def.key];
      updateSliderFill(slider, def.min, def.max);

      slider.addEventListener('input', function() {
        var v = parseFloat(slider.value);
        _zones[def.key] = v;
        if (valSpan) valSpan.textContent = v.toFixed(1) + 'm';
        updateSliderFill(slider, def.min, def.max);
        // Live preview
        if (GF.zones && typeof GF.zones.setConfig === 'function') {
          GF.zones.setConfig({ danger_m: _zones.danger_m, warning_m: _zones.warning_m, max_range_m: _zones.max_range_m });
        }
      });

      row.appendChild(slider);
      sec.appendChild(row);
    });

    var saveBtn = document.createElement('button');
    saveBtn.className = 'gf-save-btn';
    saveBtn.id = 'gf-zone-save-btn';
    saveBtn.textContent = 'Save Zone Settings';
    saveBtn.addEventListener('click', saveZones);
    sec.appendChild(saveBtn);

    var statusEl = document.createElement('div');
    statusEl.className = 'gf-status-msg';
    statusEl.id = 'gf-zone-status';
    sec.appendChild(statusEl);

    return sec;
  }

  function updateSliderFill(slider, min, max) {
    var pct = ((parseFloat(slider.value) - min) / (max - min) * 100).toFixed(1) + '%';
    slider.style.setProperty('--pct', pct);
  }

  function loadZones() {
    GF.api.get('/api/config').then(function(cfg) {
      if (cfg && cfg.zones) {
        if (cfg.zones.danger_m)    _zones.danger_m    = cfg.zones.danger_m;
        if (cfg.zones.warning_m)   _zones.warning_m   = cfg.zones.warning_m;
        if (cfg.zones.max_range_m) _zones.max_range_m = cfg.zones.max_range_m;
        renderZoneSliders();
      }
    }).catch(function() {});
  }

  function renderZoneSliders() {
    ZONE_SLIDERS.forEach(function(def) {
      var slider = document.getElementById('gf-zone-slider-' + def.key);
      var valSpan = document.getElementById('gf-zone-val-' + def.key);
      if (slider) {
        slider.value = _zones[def.key];
        updateSliderFill(slider, def.min, def.max);
      }
      if (valSpan) valSpan.textContent = _zones[def.key].toFixed(1) + 'm';
    });
  }

  function saveZones() {
    var btn = document.getElementById('gf-zone-save-btn');
    var statusEl = document.getElementById('gf-zone-status');
    if (btn) { btn.disabled = true; btn.textContent = 'Saving...'; }

    GF.api.post('/api/config', { zones: {
      danger_m:    _zones.danger_m,
      warning_m:   _zones.warning_m,
      max_range_m: _zones.max_range_m
    }}).then(function() {
      if (statusEl) { statusEl.className = 'gf-status-msg'; statusEl.textContent = 'Saved.'; }
      if (btn) { btn.disabled = false; btn.textContent = 'Save Zone Settings'; }
      setTimeout(function() { if (statusEl) statusEl.textContent = ''; }, 2000);
    }).catch(function(err) {
      if (statusEl) { statusEl.className = 'gf-error-msg'; statusEl.textContent = 'Failed: ' + err.message; }
      if (btn) { btn.disabled = false; btn.textContent = 'Save Zone Settings'; }
    });
  }

  // ─────────────────────────────────────────────────────────
  // SECTION: Detection Classes
  // ─────────────────────────────────────────────────────────
  var DEFAULT_CLASSES = [
    { id: 'person',     label: 'Person',     icon: ICONS['user'],      priority: 1, enabled: true  },
    { id: 'vehicle',    label: 'Vehicle',    icon: ICONS['car'],       priority: 2, enabled: true  },
    { id: 'excavator',  label: 'Excavator',  icon: ICONS['excavator'], priority: 2, enabled: true  },
    { id: 'dump_truck', label: 'Dump Truck', icon: ICONS['dump-truck'],priority: 3, enabled: true  },
    { id: 'dozer',      label: 'Dozer',      icon: ICONS['dozer'],     priority: 3, enabled: true  },
    { id: 'forklift',   label: 'Forklift',   icon: ICONS['wrench'],    priority: 2, enabled: false },
    { id: 'cyclist',    label: 'Cyclist',    icon: ICONS['bike'],      priority: 2, enabled: false },
    { id: 'cone',       label: 'Traffic Cone', icon: ICONS['triangle'],priority: 4, enabled: false },
  ];
  var _detectionClasses = null; // loaded from API or defaults

  function buildDetectionSection() {
    var sec = document.createElement('div');
    sec.className = 'gf-section';

    var title = document.createElement('div');
    title.className = 'gf-section-title';
    title.textContent = 'Detection Classes';
    sec.appendChild(title);

    var list = document.createElement('div');
    list.id = 'gf-detection-list';
    sec.appendChild(list);

    // Render defaults immediately; API data replaces on load
    renderDetectionClasses(DEFAULT_CLASSES, list);

    return sec;
  }

  function renderDetectionClasses(classes, container) {
    if (!container) container = document.getElementById('gf-detection-list');
    if (!container) return;
    container.innerHTML = '';

    classes.forEach(function(cls) {
      var row = document.createElement('div');
      row.className = 'gf-class-row';

      var icon = document.createElement('div');
      icon.className = 'gf-class-icon';
      icon.innerHTML = cls.icon || '&#8226;';

      var info = document.createElement('div');
      info.className = 'gf-class-info';
      info.innerHTML =
        '<div class="gf-class-name">' + cls.label + '</div>' +
        '<div class="gf-class-priority">Priority ' + cls.priority + '</div>';

      var toggle = buildToggle('gf-det-' + cls.id, cls.enabled, function(checked) {
        cls.enabled = checked;
        saveDetectionClass(cls.id, checked);
      });

      row.appendChild(icon);
      row.appendChild(info);
      row.appendChild(toggle);
      container.appendChild(row);
    });
  }

  function buildToggle(id, checked, onChange) {
    var label = document.createElement('label');
    label.className = 'gf-toggle';
    label.htmlFor = id;

    var input = document.createElement('input');
    input.type = 'checkbox';
    input.id = id;
    input.checked = checked;

    var track = document.createElement('div');
    track.className = 'gf-toggle-track';

    var thumb = document.createElement('div');
    thumb.className = 'gf-toggle-thumb';

    input.addEventListener('change', function() {
      onChange(input.checked);
    });

    label.appendChild(input);
    label.appendChild(track);
    label.appendChild(thumb);
    return label;
  }

  function loadDetectionConfig() {
    GF.api.get('/api/detection/config').then(function(data) {
      if (!data) return;
      // API may return array or object with classes property
      var classes = Array.isArray(data) ? data : (data.classes || null);
      if (!classes) return;
      _detectionClasses = classes;
      renderDetectionClasses(classes);
    }).catch(function() {
      // Use defaults
      _detectionClasses = DEFAULT_CLASSES.slice();
    });
  }

  function saveDetectionClass(classId, enabled) {
    var update = {};
    update[classId] = { enabled: enabled };
    GF.api.post('/api/detection/config', update).catch(function(err) {
      console.warn('GF.settings: failed to save detection config', err);
    });
  }

  // ─────────────────────────────────────────────────────────
  // SECTION: Camera Management
  // ─────────────────────────────────────────────────────────
  var _cameras = [];
  var _editingCameraId = null;

  var MOUNT_POSITIONS = [
    'front', 'rear', 'left', 'right',
    'front-left', 'front-right', 'rear-left', 'rear-right'
  ];

  function buildCameraSection() {
    var sec = document.createElement('div');
    sec.className = 'gf-section';

    var title = document.createElement('div');
    title.className = 'gf-section-title';
    title.textContent = 'Camera Management';
    sec.appendChild(title);

    var list = document.createElement('div');
    list.id = 'gf-camera-list';
    sec.appendChild(list);

    // Add Camera button
    var addBtn = document.createElement('button');
    addBtn.id = 'gf-add-camera-btn';
    addBtn.innerHTML = '<svg width="14" height="14" viewBox="0 0 14 14" fill="none"><path d="M7 1v12M1 7h12" stroke="currentColor" stroke-width="2" stroke-linecap="round"/></svg> Add Camera';
    addBtn.addEventListener('click', function() { showCameraForm(null); });
    sec.appendChild(addBtn);

    // Placement editor button
    var placementBtn = document.createElement('button');
    placementBtn.id = 'gf-open-placement-btn';
    placementBtn.innerHTML = '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="3" width="18" height="18" rx="2"/><circle cx="8.5" cy="8.5" r="1.5"/><circle cx="15.5" cy="8.5" r="1.5"/><circle cx="15.5" cy="15.5" r="1.5"/><circle cx="8.5" cy="15.5" r="1.5"/></svg> Camera Placement Editor';
    placementBtn.addEventListener('click', function() {
      if (GF.cameraPlacement && typeof GF.cameraPlacement.open === 'function') {
        GF.settings.close();
        setTimeout(function() { GF.cameraPlacement.open(); }, 350);
      }
    });
    sec.appendChild(placementBtn);

    // Camera form (hidden by default)
    var formWrap = document.createElement('div');
    formWrap.id = 'gf-camera-form-wrap';
    formWrap.style.display = 'none';
    formWrap.appendChild(buildCameraForm());
    sec.appendChild(formWrap);

    var statusEl = document.createElement('div');
    statusEl.className = 'gf-status-msg';
    statusEl.id = 'gf-camera-status';
    sec.appendChild(statusEl);

    return sec;
  }

  function buildCameraForm() {
    var box = document.createElement('div');
    box.className = 'gf-form-box';

    var titleEl = document.createElement('div');
    titleEl.style.cssText = 'font-size:13px;font-weight:700;color:#22384C;margin-bottom:12px;font-family:system-ui,-apple-system,sans-serif;';
    titleEl.id = 'gf-camera-form-title';
    titleEl.textContent = 'Add Camera';
    box.appendChild(titleEl);

    // Name
    box.appendChild(buildFormRow('Name', 'gf-cam-name', 'text', 'e.g. Front Camera'));
    // IP / RTSP URL
    box.appendChild(buildFormRow('IP Address / RTSP URL', 'gf-cam-url', 'text', 'e.g. 192.168.1.10 or rtsp://...'));
    // Mount position (select)
    box.appendChild(buildFormRowSelect('Mount Position', 'gf-cam-mount', MOUNT_POSITIONS));
    // Angle offset
    box.appendChild(buildFormRow('Angle Offset (degrees)', 'gf-cam-angle', 'number', '0'));

    var actions = document.createElement('div');
    actions.className = 'gf-form-actions';

    var cancelBtn = document.createElement('button');
    cancelBtn.className = 'gf-btn gf-btn-ghost';
    cancelBtn.textContent = 'Cancel';
    cancelBtn.addEventListener('click', hideCameraForm);

    var saveBtn = document.createElement('button');
    saveBtn.className = 'gf-btn gf-btn-primary';
    saveBtn.id = 'gf-camera-save-btn';
    saveBtn.textContent = 'Save';
    saveBtn.addEventListener('click', submitCameraForm);

    actions.appendChild(cancelBtn);
    actions.appendChild(saveBtn);
    box.appendChild(actions);

    return box;
  }

  function buildFormRow(labelText, inputId, type, placeholder) {
    var row = document.createElement('div');
    row.className = 'gf-form-row';

    var label = document.createElement('label');
    label.className = 'gf-form-label';
    label.htmlFor = inputId;
    label.textContent = labelText;

    var input = document.createElement('input');
    input.type = type;
    input.id = inputId;
    input.className = 'gf-input';
    input.placeholder = placeholder || '';

    row.appendChild(label);
    row.appendChild(input);
    return row;
  }

  function buildFormRowSelect(labelText, selectId, options) {
    var row = document.createElement('div');
    row.className = 'gf-form-row';

    var label = document.createElement('label');
    label.className = 'gf-form-label';
    label.htmlFor = selectId;
    label.textContent = labelText;

    var select = document.createElement('select');
    select.id = selectId;
    select.className = 'gf-input';

    options.forEach(function(opt) {
      var o = document.createElement('option');
      o.value = opt;
      o.textContent = opt.charAt(0).toUpperCase() + opt.slice(1).replace(/-/g, ' ');
      select.appendChild(o);
    });

    row.appendChild(label);
    row.appendChild(select);
    return row;
  }

  function showCameraForm(camera) {
    var formWrap = document.getElementById('gf-camera-form-wrap');
    var formTitle = document.getElementById('gf-camera-form-title');
    var saveBtn = document.getElementById('gf-camera-save-btn');
    if (!formWrap) return;

    if (camera) {
      _editingCameraId = camera.id;
      if (formTitle) formTitle.textContent = 'Edit Camera';
      if (saveBtn) saveBtn.textContent = 'Update';
      setFieldValue('gf-cam-name',  camera.name || '');
      setFieldValue('gf-cam-url',   camera.url || camera.ip || '');
      setFieldValue('gf-cam-mount', camera.mount || 'front');
      setFieldValue('gf-cam-angle', camera.angle_offset || 0);
    } else {
      _editingCameraId = null;
      if (formTitle) formTitle.textContent = 'Add Camera';
      if (saveBtn) saveBtn.textContent = 'Save';
      setFieldValue('gf-cam-name',  '');
      setFieldValue('gf-cam-url',   '');
      setFieldValue('gf-cam-mount', 'front');
      setFieldValue('gf-cam-angle', 0);
    }

    formWrap.style.display = 'block';
    document.getElementById('gf-add-camera-btn').style.display = 'none';

    // Scroll form into view
    setTimeout(function() {
      var input = document.getElementById('gf-cam-name');
      if (input) input.focus();
    }, 100);
  }

  function hideCameraForm() {
    var formWrap = document.getElementById('gf-camera-form-wrap');
    var addBtn = document.getElementById('gf-add-camera-btn');
    if (formWrap) formWrap.style.display = 'none';
    if (addBtn) addBtn.style.display = '';
    _editingCameraId = null;
  }

  function setFieldValue(id, value) {
    var el = document.getElementById(id);
    if (el) el.value = value;
  }

  function getFieldValue(id) {
    var el = document.getElementById(id);
    return el ? el.value : '';
  }

  function submitCameraForm() {
    var name  = getFieldValue('gf-cam-name').trim();
    var url   = getFieldValue('gf-cam-url').trim();
    var mount = getFieldValue('gf-cam-mount');
    var angle = parseFloat(getFieldValue('gf-cam-angle')) || 0;
    var statusEl = document.getElementById('gf-camera-status');
    var saveBtn = document.getElementById('gf-camera-save-btn');

    if (!name || !url) {
      if (statusEl) { statusEl.className = 'gf-error-msg'; statusEl.textContent = 'Name and URL are required.'; }
      return;
    }

    var data = { name: name, url: url, mount: mount, angle_offset: angle };
    if (saveBtn) { saveBtn.disabled = true; saveBtn.textContent = 'Saving...'; }

    var promise;
    if (_editingCameraId !== null) {
      promise = GF.api.patch('/api/cameras/' + _editingCameraId, data);
    } else {
      promise = GF.api.post('/api/cameras', data);
    }

    promise.then(function() {
      hideCameraForm();
      if (statusEl) { statusEl.className = 'gf-status-msg'; statusEl.textContent = 'Saved.'; }
      setTimeout(function() { if (statusEl) statusEl.textContent = ''; }, 2000);
      loadCameras();
    }).catch(function(err) {
      if (statusEl) { statusEl.className = 'gf-error-msg'; statusEl.textContent = 'Failed: ' + err.message; }
    }).then(function() {
      if (saveBtn) { saveBtn.disabled = false; saveBtn.textContent = (_editingCameraId ? 'Update' : 'Save'); }
    });
  }

  function loadCameras() {
    GF.api.get('/api/cameras').then(function(data) {
      _cameras = Array.isArray(data) ? data : (data.cameras || []);
      renderCameraList();
    }).catch(function() {
      _cameras = [];
      renderCameraList();
    });
  }

  function renderCameraList() {
    var list = document.getElementById('gf-camera-list');
    if (!list) return;
    list.innerHTML = '';

    if (_cameras.length === 0) {
      var empty = document.createElement('div');
      empty.className = 'gf-status-msg';
      empty.textContent = 'No cameras configured.';
      list.appendChild(empty);
      return;
    }

    _cameras.forEach(function(cam) {
      var item = document.createElement('div');
      item.className = 'gf-camera-item';

      var dot = document.createElement('div');
      dot.className = 'gf-camera-status ' + (cam.connected ? 'connected' : 'disconnected');

      var info = document.createElement('div');
      info.className = 'gf-camera-info';
      info.innerHTML =
        '<div class="gf-camera-name">' + escapeHtml(cam.name || 'Camera') + '</div>' +
        '<div class="gf-camera-sub">' + escapeHtml(cam.mount || '') + (cam.url || cam.ip ? ' — ' + escapeHtml(cam.url || cam.ip) : '') + '</div>';

      var editBtn = document.createElement('button');
      editBtn.className = 'gf-icon-btn';
      editBtn.title = 'Edit';
      editBtn.innerHTML = '<svg width="13" height="13" viewBox="0 0 13 13" fill="none"><path d="M9.5 1.5l2 2-7 7H2.5v-2l7-7z" stroke="#6B7280" stroke-width="1.4" stroke-linejoin="round"/></svg>';
      editBtn.addEventListener('click', (function(c) {
        return function() { showCameraForm(c); };
      })(cam));

      var delBtn = document.createElement('button');
      delBtn.className = 'gf-icon-btn danger';
      delBtn.title = 'Delete';
      delBtn.innerHTML = '<svg width="13" height="13" viewBox="0 0 13 13" fill="none"><path d="M2 3h9M5 3V2h3v1M4 3v7h5V3" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round"/></svg>';
      delBtn.addEventListener('click', (function(c) {
        return function() { deleteCamera(c); };
      })(cam));

      item.appendChild(dot);
      item.appendChild(info);
      item.appendChild(editBtn);
      item.appendChild(delBtn);
      list.appendChild(item);
    });
  }

  function deleteCamera(cam) {
    var statusEl = document.getElementById('gf-camera-status');
    GF.api.del('/api/cameras/' + cam.id).then(function() {
      if (statusEl) { statusEl.className = 'gf-status-msg'; statusEl.textContent = 'Deleted.'; }
      setTimeout(function() { if (statusEl) statusEl.textContent = ''; }, 1500);
      loadCameras();
    }).catch(function(err) {
      if (statusEl) { statusEl.className = 'gf-error-msg'; statusEl.textContent = 'Failed: ' + err.message; }
    });
  }

  // ── Utility ────────────────────────────────────────────────
  function escapeHtml(str) {
    return String(str)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

  // ─────────────────────────────────────────────────────────
  // PUBLIC API
  // ─────────────────────────────────────────────────────────
  GF.settings = {
    open: function() {
      var panel = document.getElementById('gf-settings-panel');
      var backdrop = document.getElementById('gf-settings-backdrop');
      if (!panel) return;
      panel.classList.add('gf-open');
      backdrop.classList.add('gf-open');

      // Load fresh data each time the panel opens
      loadMachines();
      loadZones();
      loadDetectionConfig();
      loadCameras();
    },

    close: function() {
      var panel = document.getElementById('gf-settings-panel');
      var backdrop = document.getElementById('gf-settings-backdrop');
      if (!panel) return;
      panel.classList.remove('gf-open');
      backdrop.classList.remove('gf-open');
      hideCameraForm();
    }
  };

  // ── Bootstrap ─────────────────────────────────────────────
  function init() {
    injectStyles();
    buildDOM();
  }

  // Run after DOM is ready
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }

})();
