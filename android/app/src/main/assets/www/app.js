/* ═══════════════════════════════════════════════════════════
   GridFront Detect — Client App
   Single-page application for the kiosk tablet.
   ═══════════════════════════════════════════════════════════ */

// ── State ────────────────────────────────────────────────
let currentPage = 'radar';
let config = loadConfig();
let detections = [];
let alertHistory = JSON.parse(localStorage.getItem('gf_alerts') || '[]');
let lastZone = 'CLEAR';
let demoAngle = 0;

// ── Config persistence ───────────────────────────────────
function loadConfig() {
    const saved = localStorage.getItem('gf_config');
    const defaults = {
        machine_name: 'Machine 1',
        cameras: [],
        zones: { danger_m: 3, warning_m: 7, max_range_m: 10 },
        connectivity: { mode: 'wifi', wifi_ssid: '', wifi_password: '', apn: '' },
        alerts: { sound_enabled: true, danger_sound: 'alarm', warning_sound: 'chime' },
        display: { brightness: 80 },
        platform: { url: 'https://platform.gridfront.io', api_key: '', tenant_id: '' },
    };
    return saved ? { ...defaults, ...JSON.parse(saved) } : defaults;
}

function saveConfig() {
    localStorage.setItem('gf_config', JSON.stringify(config));
}

// ── Navigation ───────────────────────────────────────────
function navigate(page) {
    currentPage = page;
    document.querySelectorAll('.nav-item').forEach(el => {
        el.classList.toggle('active', el.dataset.page === page);
    });
    renderPage();
}

function renderPage() {
    const content = document.getElementById('page-content');
    switch (currentPage) {
        case 'radar': content.innerHTML = radarPage(); initRadar(); break;
        case 'cameras': content.innerHTML = camerasPage(); break;
        case 'alerts': content.innerHTML = alertsPage(); break;
        case 'settings': content.innerHTML = settingsPage(); initSettings(); break;
    }
    lucide.createIcons();
}

// ── RADAR PAGE ───────────────────────────────────────────
function radarPage() {
    return `
        <div style="display:flex;align-items:center;justify-content:center;height:100%;padding:8px;">
            <div style="position:relative;width:100%;max-width:480px;aspect-ratio:1;">
                <canvas id="radar-canvas" style="width:100%;height:100%;border-radius:50%;"></canvas>
            </div>
        </div>
        <div class="radar-stats">
            <div class="stat-item">
                <div class="stat-value" style="color:var(--info)" id="s-closest">--</div>
                <div class="stat-label">Closest</div>
            </div>
            <div class="stat-item">
                <div class="stat-value" style="color:var(--danger)" id="s-danger">0</div>
                <div class="stat-label">Danger</div>
            </div>
            <div class="stat-item">
                <div class="stat-value" style="color:var(--warning)" id="s-warning">0</div>
                <div class="stat-label">Warning</div>
            </div>
            <div class="stat-item">
                <div class="stat-value" style="color:var(--ok)" id="s-total">0</div>
                <div class="stat-label">Total</div>
            </div>
        </div>`;
}

let radarCanvas, radarCtx;
function initRadar() {
    radarCanvas = document.getElementById('radar-canvas');
    if (!radarCanvas) return;
    radarCtx = radarCanvas.getContext('2d');
    resizeRadar();
    window.addEventListener('resize', resizeRadar);
}

function resizeRadar() {
    if (!radarCanvas) return;
    const p = radarCanvas.parentElement;
    const s = Math.min(p.clientWidth, p.clientHeight);
    const dpr = window.devicePixelRatio || 1;
    radarCanvas.width = s * dpr;
    radarCanvas.height = s * dpr;
    radarCanvas.style.width = s + 'px';
    radarCanvas.style.height = s + 'px';
}

function drawRadar(dets) {
    if (!radarCtx || !radarCanvas) return;
    const dpr = window.devicePixelRatio || 1;
    const w = radarCanvas.width / dpr;
    const h = radarCanvas.height / dpr;
    radarCtx.setTransform(dpr, 0, 0, dpr, 0, 0);

    const cx = w / 2, cy = h / 2;
    const radius = Math.min(cx, cy) - 6;
    const ZD = config.zones.danger_m, ZW = config.zones.warning_m, MR = config.zones.max_range_m;
    const scale = radius / MR;

    radarCtx.clearRect(0, 0, w, h);

    // Background — light theme
    radarCtx.fillStyle = '#FFFFFF';
    radarCtx.beginPath(); radarCtx.arc(cx, cy, radius + 1, 0, Math.PI * 2); radarCtx.fill();

    // Outer border
    radarCtx.strokeStyle = '#E5E5E5';
    radarCtx.lineWidth = 1;
    radarCtx.beginPath(); radarCtx.arc(cx, cy, radius, 0, Math.PI * 2); radarCtx.stroke();

    // Zone fills — subtle on white
    radarCtx.fillStyle = 'rgba(34,197,94,0.04)';
    radarCtx.beginPath(); radarCtx.arc(cx, cy, MR * scale, 0, Math.PI * 2); radarCtx.fill();
    radarCtx.fillStyle = 'rgba(245,158,11,0.06)';
    radarCtx.beginPath(); radarCtx.arc(cx, cy, ZW * scale, 0, Math.PI * 2); radarCtx.fill();
    radarCtx.fillStyle = 'rgba(239,68,68,0.08)';
    radarCtx.beginPath(); radarCtx.arc(cx, cy, ZD * scale, 0, Math.PI * 2); radarCtx.fill();

    // Zone rings
    [{r:ZD,c:'rgba(239,68,68,.3)'},{r:ZW,c:'rgba(245,158,11,.25)'},{r:MR,c:'rgba(34,197,94,.2)'}].forEach(z => {
        const r = z.r * scale;
        radarCtx.beginPath(); radarCtx.arc(cx, cy, r, 0, Math.PI * 2);
        radarCtx.strokeStyle = z.c; radarCtx.lineWidth = 1;
        radarCtx.setLineDash([3,3]); radarCtx.stroke(); radarCtx.setLineDash([]);
        radarCtx.fillStyle = 'rgba(115,115,115,.5)';
        radarCtx.font = '500 9px Roboto'; radarCtx.textAlign = 'left';
        radarCtx.fillText(z.r + 'm', cx + 3, cy - r + 10);
    });

    // Crosshairs
    radarCtx.strokeStyle = 'rgba(229,229,229,.8)'; radarCtx.lineWidth = .5;
    radarCtx.beginPath();
    radarCtx.moveTo(cx, cy - radius); radarCtx.lineTo(cx, cy + radius);
    radarCtx.moveTo(cx - radius, cy); radarCtx.lineTo(cx + radius, cy);
    radarCtx.stroke();

    // 45deg lines
    radarCtx.strokeStyle = 'rgba(229,229,229,.4)';
    for (let a = Math.PI / 4; a < Math.PI * 2; a += Math.PI / 2) {
        radarCtx.beginPath(); radarCtx.moveTo(cx, cy);
        radarCtx.lineTo(cx + Math.cos(a) * radius, cy - Math.sin(a) * radius);
        radarCtx.stroke();
    }

    // Direction labels
    radarCtx.fillStyle = 'rgba(115,115,115,.6)';
    radarCtx.font = '500 10px Roboto'; radarCtx.textAlign = 'center'; radarCtx.textBaseline = 'middle';
    radarCtx.fillText('FRONT', cx, cy - radius + 12);
    radarCtx.fillText('REAR', cx, cy + radius - 12);
    radarCtx.fillText('L', cx - radius + 10, cy);
    radarCtx.fillText('R', cx + radius - 10, cy);

    // Machine body — GridFront blue
    const mw = 16, mh = 24;
    radarCtx.fillStyle = '#3CABD6';
    radarCtx.beginPath(); radarCtx.roundRect(cx-mw/2, cy-mh/2, mw, mh, 3); radarCtx.fill();
    radarCtx.fillStyle = '#FFFFFF';
    radarCtx.beginPath(); radarCtx.roundRect(cx-mw/2+3, cy-mh/2+3, mw-6, mh-6, 2); radarCtx.fill();
    radarCtx.fillStyle = '#3CABD6';
    radarCtx.beginPath(); radarCtx.moveTo(cx, cy-5); radarCtx.lineTo(cx-3.5, cy); radarCtx.lineTo(cx+3.5, cy);
    radarCtx.closePath(); radarCtx.fill();

    // Detections
    for (const d of dets) {
        const rx = cx + d.x_m * scale, ry = cy - d.z_m * scale;
        const col = d.zone === 'DANGER' ? '#EF4444' : d.zone === 'WARNING' ? '#F59E0B' : '#22C55E';

        // Glow
        const g = radarCtx.createRadialGradient(rx, ry, 0, rx, ry, 18);
        g.addColorStop(0, col + '33'); g.addColorStop(1, 'transparent');
        radarCtx.fillStyle = g;
        radarCtx.beginPath(); radarCtx.arc(rx, ry, 18, 0, Math.PI * 2); radarCtx.fill();

        // Ring + dot
        radarCtx.beginPath(); radarCtx.arc(rx, ry, 7, 0, Math.PI * 2);
        radarCtx.strokeStyle = col; radarCtx.lineWidth = 1.5; radarCtx.stroke();
        radarCtx.fillStyle = col;
        radarCtx.beginPath(); radarCtx.arc(rx, ry, 3.5, 0, Math.PI * 2); radarCtx.fill();

        // Label
        radarCtx.fillStyle = '#171717'; radarCtx.font = '700 10px Roboto';
        radarCtx.textAlign = 'center'; radarCtx.textBaseline = 'bottom';
        radarCtx.fillText(d.distance_m.toFixed(1) + 'm', rx, ry - 10);
        radarCtx.fillStyle = col; radarCtx.font = '500 8px Roboto'; radarCtx.textBaseline = 'top';
        radarCtx.fillText('PERSON', rx, ry + 10);
    }

    // Stats
    const danger = dets.filter(d => d.zone === 'DANGER').length;
    const warning = dets.filter(d => d.zone === 'WARNING').length;
    const distances = dets.map(d => d.distance_m);
    const closest = distances.length ? Math.min(...distances) : null;

    const el = id => document.getElementById(id);
    if (el('s-closest')) el('s-closest').textContent = closest ? closest.toFixed(1) + 'm' : '--';
    if (el('s-danger')) el('s-danger').textContent = danger;
    if (el('s-warning')) el('s-warning').textContent = warning;
    if (el('s-total')) el('s-total').textContent = dets.length;

    // Zone banner
    const banner = document.getElementById('zone-banner');
    if (danger > 0) {
        banner.className = 'zone-banner danger';
        banner.textContent = `DANGER \u2014 ${danger} PERSON${danger>1?'S':''} \u2022 ${closest?.toFixed(1)||'--'}m`;
    } else if (warning > 0) {
        banner.className = 'zone-banner warning';
        banner.textContent = `WARNING \u2014 ${warning} NEARBY`;
    } else {
        banner.className = 'zone-banner clear';
        banner.textContent = 'ALL CLEAR';
    }

    // Alert logging
    const curZone = danger > 0 ? 'DANGER' : warning > 0 ? 'WARNING' : 'CLEAR';
    if (curZone !== lastZone && curZone !== 'CLEAR') {
        alertHistory.unshift({ zone: curZone, count: danger + warning, closest, timestamp: Date.now() });
        if (alertHistory.length > 200) alertHistory = alertHistory.slice(0, 200);
        localStorage.setItem('gf_alerts', JSON.stringify(alertHistory));
    }
    lastZone = curZone;
}

// ── CAMERAS PAGE ─────────────────────────────────────────
function camerasPage() {
    const cams = config.cameras;
    const list = cams.length ? cams.map((c, i) => `
        <div class="card">
            <div class="card-content flex justify-between items-center" style="padding:12px 16px;">
                <div class="flex items-center gap-2">
                    <div style="width:36px;height:36px;border-radius:var(--radius);background:var(--secondary);display:flex;align-items:center;justify-content:center;">
                        <i data-lucide="camera" style="width:18px;height:18px;color:var(--muted-foreground)"></i>
                    </div>
                    <div>
                        <div style="font-weight:600;font-size:13px;">${c.name || c.id || 'Camera ' + i}</div>
                        <div class="text-xs text-muted" style="margin-top:2px;">
                            <span class="badge ${c.status==='active'?'badge-ok':'badge-muted'}">${c.status||'offline'}</span>
                            ${c.position||''} ${c.mount_transform?.yaw||0}&deg;
                        </div>
                    </div>
                </div>
                <div class="flex gap-2">
                    <button class="btn btn-ghost btn-icon btn-sm" onclick="editCamera(${i})"><i data-lucide="pencil" style="width:14px;height:14px"></i></button>
                    <button class="btn btn-ghost btn-icon btn-sm" onclick="deleteCamera(${i})" style="color:var(--destructive)"><i data-lucide="trash-2" style="width:14px;height:14px"></i></button>
                </div>
            </div>
        </div>`).join('') : `
        <div class="card">
            <div class="card-content" style="text-align:center;padding:32px 16px;">
                <i data-lucide="camera-off" style="width:40px;height:40px;color:var(--muted-foreground);margin:0 auto 10px;display:block"></i>
                <p style="font-weight:600;font-size:14px;">No cameras configured</p>
                <p class="text-xs text-muted mt-2">Add a camera to begin proximity detection.</p>
            </div>
        </div>`;

    return `
        <div class="p-4 flex flex-col gap-3">
            <div class="flex justify-between items-center mb-2">
                <div>
                    <div style="font-size:18px;font-weight:700;">Cameras</div>
                    <div class="text-xs text-muted">Configure cameras and mount positions</div>
                </div>
                <button class="btn btn-primary btn-sm" onclick="showCameraModal()">
                    <i data-lucide="plus" style="width:14px;height:14px"></i> Add
                </button>
            </div>
            ${list}
        </div>
        <div class="modal-overlay" id="cam-modal">
            <div class="modal-content card">
                <div class="card-header flex justify-between items-center">
                    <div class="card-title" id="cam-modal-title">Add Camera</div>
                    <button class="btn btn-ghost btn-icon btn-sm" onclick="closeCameraModal()"><i data-lucide="x" style="width:16px;height:16px"></i></button>
                </div>
                <div class="card-content">
                    <div class="form-group"><label class="label">Name</label><input class="input" id="cm-name" placeholder="e.g. Front Camera"></div>
                    <div class="form-group"><label class="label">Position</label>
                        <select class="select" id="cm-pos"><option value="front">Front</option><option value="rear">Rear</option><option value="left">Left</option><option value="right">Right</option></select></div>
                    <div class="form-group"><label class="label">Mount Offset (m from center)</label>
                        <div class="grid-2 mt-2">
                            <div><label class="label text-xs">Forward/Back</label><input class="input" id="cm-ox" type="number" step="0.1" value="0"></div>
                            <div><label class="label text-xs">Left/Right</label><input class="input" id="cm-oy" type="number" step="0.1" value="0"></div>
                        </div></div>
                    <div class="form-group"><label class="label">Facing (degrees)</label>
                        <div class="label-desc">0=forward, 90=right, 180=rear, 270=left</div>
                        <input class="input" id="cm-yaw" type="number" step="1" value="0"></div>
                    <div class="flex gap-2 mt-3">
                        <button class="btn btn-secondary w-full" onclick="closeCameraModal()">Cancel</button>
                        <button class="btn btn-primary w-full" onclick="saveCameraModal()">Save</button>
                    </div>
                </div>
            </div>
        </div>`;
}

let editingCamIdx = -1;
function showCameraModal(idx) {
    editingCamIdx = idx !== undefined ? idx : -1;
    const c = editingCamIdx >= 0 ? config.cameras[editingCamIdx] : {};
    document.getElementById('cam-modal-title').textContent = editingCamIdx >= 0 ? 'Edit Camera' : 'Add Camera';
    document.getElementById('cm-name').value = c.name || '';
    document.getElementById('cm-pos').value = c.position || 'front';
    document.getElementById('cm-ox').value = c.mount_transform?.x || 0;
    document.getElementById('cm-oy').value = c.mount_transform?.y || 0;
    document.getElementById('cm-yaw').value = c.mount_transform?.yaw || 0;
    document.getElementById('cam-modal').classList.add('show');
    lucide.createIcons();
}
function closeCameraModal() { document.getElementById('cam-modal').classList.remove('show'); }
function editCamera(i) { showCameraModal(i); }
function saveCameraModal() {
    const cam = {
        id: editingCamIdx >= 0 ? config.cameras[editingCamIdx].id : 'cam-' + Date.now(),
        name: document.getElementById('cm-name').value || 'Camera',
        position: document.getElementById('cm-pos').value,
        status: 'disconnected',
        mount_transform: {
            x: parseFloat(document.getElementById('cm-ox').value) || 0,
            y: parseFloat(document.getElementById('cm-oy').value) || 0,
            z: 0, yaw: parseFloat(document.getElementById('cm-yaw').value) || 0, pitch: 0, roll: 0,
        },
    };
    if (editingCamIdx >= 0) config.cameras[editingCamIdx] = cam;
    else config.cameras.push(cam);
    saveConfig(); closeCameraModal(); renderPage();
}
function deleteCamera(i) {
    if (!confirm('Remove this camera?')) return;
    config.cameras.splice(i, 1); saveConfig(); renderPage();
}

// ── ALERTS PAGE ──────────────────────────────────────────
function alertsPage() {
    const list = alertHistory.length ? alertHistory.slice(0, 50).map(a => {
        const t = new Date(a.timestamp);
        return `
        <div class="card">
            <div class="card-content flex justify-between items-center" style="padding:10px 14px;">
                <div class="flex items-center gap-2">
                    <div style="width:32px;height:32px;border-radius:50%;background:${a.zone==='DANGER'?'var(--danger-bg)':'var(--warning-bg)'};display:flex;align-items:center;justify-content:center;">
                        <i data-lucide="${a.zone==='DANGER'?'alert-triangle':'alert-circle'}" style="width:16px;height:16px;color:${a.zone==='DANGER'?'var(--danger)':'var(--warning)'}"></i>
                    </div>
                    <div>
                        <div style="font-weight:600;font-size:13px;">
                            <span class="badge ${a.zone==='DANGER'?'badge-danger':'badge-warning'}" style="margin-right:4px">${a.zone}</span>
                            ${a.count} person${a.count>1?'s':''}
                        </div>
                        <div class="text-xs text-muted">Closest: ${a.closest?.toFixed(1)||'--'}m</div>
                    </div>
                </div>
                <div style="text-align:right"><div class="text-xs text-muted">${t.toLocaleTimeString()}</div><div class="text-xs text-muted">${t.toLocaleDateString()}</div></div>
            </div>
        </div>`;
    }).join('') : `
        <div class="card"><div class="card-content" style="text-align:center;padding:32px 16px;">
            <i data-lucide="bell-off" style="width:40px;height:40px;color:var(--muted-foreground);margin:0 auto 10px;display:block"></i>
            <p style="font-weight:600">No alerts yet</p>
            <p class="text-xs text-muted mt-2">Proximity alerts appear here when persons enter danger or warning zones.</p>
        </div></div>`;

    return `
        <div class="p-4 flex flex-col gap-2">
            <div class="flex justify-between items-center mb-2">
                <div><div style="font-size:18px;font-weight:700;">Alerts</div><div class="text-xs text-muted">Proximity event history</div></div>
                <button class="btn btn-outline btn-sm" onclick="clearAlerts()">Clear</button>
            </div>
            ${list}
        </div>`;
}
function clearAlerts() { alertHistory = []; localStorage.setItem('gf_alerts', '[]'); renderPage(); }

// ── SETTINGS PAGE ────────────────────────────────────────
function settingsPage() {
    return `
        <div class="p-4 flex flex-col gap-3" style="padding-bottom:20px;">
            <div style="font-size:18px;font-weight:700;">Settings</div>

            <div class="card"><div class="card-header"><div class="card-title">Connectivity</div><div class="card-description">Network connection for uploading to GridFront</div></div>
                <div class="card-content">
                    <div class="form-group"><label class="label">Mode</label>
                        <select class="select" id="st-conn" onchange="toggleConn()">${['wifi','sim'].map(m=>`<option value="${m}" ${config.connectivity.mode===m?'selected':''}>${m==='wifi'?'WiFi':'SIM Card (LTE)'}</option>`).join('')}</select></div>
                    <div id="st-wifi"><div class="form-group"><label class="label">WiFi Network</label><input class="input" id="st-ssid" placeholder="SSID" value="${config.connectivity.wifi_ssid||''}"></div>
                        <div class="form-group"><label class="label">Password</label><input class="input" id="st-wpass" type="password" value="${config.connectivity.wifi_password||''}"></div></div>
                    <div id="st-sim" style="display:none"><div class="form-group"><label class="label">APN</label><input class="input" id="st-apn" placeholder="internet" value="${config.connectivity.apn||''}"></div></div>
                </div></div>

            <div class="card"><div class="card-header"><div class="card-title">GridFront Platform</div></div>
                <div class="card-content">
                    <div class="form-group"><label class="label">Platform URL</label><input class="input" id="st-url" value="${config.platform.url||''}"></div>
                    <div class="form-group"><label class="label">API Key</label><input class="input" id="st-key" type="password" value="${config.platform.api_key||''}"></div>
                    <div class="form-group"><label class="label">Tenant ID</label><input class="input" id="st-tenant" value="${config.platform.tenant_id||''}"></div>
                </div></div>

            <div class="card"><div class="card-header"><div class="card-title">Detection Zones</div></div>
                <div class="card-content">
                    <div class="form-group"><label class="label" style="color:var(--danger)">Danger Zone (m)</label><input class="input" id="st-zd" type="number" step="0.5" value="${config.zones.danger_m}"></div>
                    <div class="form-group"><label class="label" style="color:var(--warning)">Warning Zone (m)</label><input class="input" id="st-zw" type="number" step="0.5" value="${config.zones.warning_m}"></div>
                    <div class="form-group"><label class="label">Max Range (m)</label><input class="input" id="st-zm" type="number" step="1" value="${config.zones.max_range_m}"></div>
                </div></div>

            <div class="card"><div class="card-header"><div class="card-title">Alerts</div></div>
                <div class="card-content">
                    <div class="form-row"><div class="form-row-label"><div class="label" style="margin:0">Sound Alerts</div></div>
                        <button class="toggle ${config.alerts.sound_enabled?'active':''}" id="st-snd" onclick="this.classList.toggle('active')"></button></div>
                </div></div>

            <div class="card"><div class="card-header"><div class="card-title">Display</div></div>
                <div class="card-content">
                    <div class="form-group"><label class="label">Machine Name</label><input class="input" id="st-mname" value="${config.machine_name||''}"></div>
                </div></div>

            <button class="btn btn-primary w-full" onclick="saveSettings()">Save Settings</button>

            <div class="card mt-2"><div class="card-content flex justify-between items-center">
                <div><div class="text-sm" style="font-weight:600">Device Info</div>
                    <div class="text-xs text-muted mt-2">Oukitel RT3 Pro</div>
                    <div class="text-xs text-muted">GridFront Detect v0.1.0</div></div>
                <button class="btn btn-outline btn-sm" onclick="if(confirm('Reset all settings?')){localStorage.clear();location.reload();}">Reset</button>
            </div></div>
        </div>`;
}

function initSettings() { toggleConn(); }
function toggleConn() {
    const m = document.getElementById('st-conn')?.value;
    const w = document.getElementById('st-wifi');
    const s = document.getElementById('st-sim');
    if (w) w.style.display = m === 'wifi' ? 'block' : 'none';
    if (s) s.style.display = m === 'sim' ? 'block' : 'none';
}
function saveSettings() {
    config.connectivity = {
        mode: document.getElementById('st-conn').value,
        wifi_ssid: document.getElementById('st-ssid').value,
        wifi_password: document.getElementById('st-wpass').value,
        apn: document.getElementById('st-apn')?.value || '',
    };
    config.platform = {
        url: document.getElementById('st-url').value,
        api_key: document.getElementById('st-key').value,
        tenant_id: document.getElementById('st-tenant').value,
    };
    config.zones = {
        danger_m: parseFloat(document.getElementById('st-zd').value) || 3,
        warning_m: parseFloat(document.getElementById('st-zw').value) || 7,
        max_range_m: parseFloat(document.getElementById('st-zm').value) || 10,
    };
    config.alerts = { sound_enabled: document.getElementById('st-snd').classList.contains('active') };
    config.machine_name = document.getElementById('st-mname').value;
    saveConfig();
    const btn = event.target; btn.textContent = 'Saved!';
    setTimeout(() => { btn.textContent = 'Save Settings'; }, 1200);
}

// ── Demo data loop ───────────────────────────────────────
function demoTick() {
    demoAngle += 0.04;
    const d1 = 3.5 + 2.5 * Math.sin(demoAngle * 0.3);
    const x1 = d1 * Math.sin(demoAngle), z1 = d1 * Math.cos(demoAngle);
    const ZD = config.zones.danger_m, ZW = config.zones.warning_m;
    const zone1 = d1 < ZD ? 'DANGER' : d1 < ZW ? 'WARNING' : 'CLEAR';

    detections = [{ track_id: 1, label: 'person', confidence: .92, x_m: +x1.toFixed(2), y_m: 0, z_m: +z1.toFixed(2), distance_m: +d1.toFixed(2), zone: zone1, camera_id: 'cam-0' }];

    if (Math.random() > .65) {
        const d2 = 2 + Math.random() * 6, a2 = Math.random() * Math.PI * 2;
        const zone2 = d2 < ZD ? 'DANGER' : d2 < ZW ? 'WARNING' : 'CLEAR';
        detections.push({ track_id: 2, label: 'person', confidence: .8, x_m: +(d2*Math.sin(a2)).toFixed(2), y_m: 0, z_m: +(d2*Math.cos(a2)).toFixed(2), distance_m: +d2.toFixed(2), zone: zone2, camera_id: 'cam-1' });
    }

    if (currentPage === 'radar') drawRadar(detections);
}

// ── Init ─────────────────────────────────────────────────
navigate('radar');
setInterval(demoTick, 100);
