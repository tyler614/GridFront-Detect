/* ═══════════════════════════════════════════════════════════
   GridFront Detect — Camera Placement Editor
   2D top-down drag-and-drop camera placement with FOV cones,
   perimeter snapping, coverage analysis, and calibration.
   Registers as GF.cameraPlacement with open() / close().
   ═══════════════════════════════════════════════════════════ */

window.GF = window.GF || {};

GF.cameraPlacement = (function () {
  'use strict';

  // ── Constants ────────────────────────────────────────────
  var MAX_CAMERAS = 8;
  var DEFAULT_FOV = 127;
  var DEFAULT_RANGE = 12;
  var MIN_RANGE = 1;
  var MAX_RANGE = 20;
  var SNAP_THRESHOLD_M = 2.0;
  var CAM_RADIUS_M = 0.5;
  var HANDLE_DIST_M = 1.6;
  var HANDLE_RADIUS_M = 0.35;
  var TOUCH_SLOP_PX = 8;
  var MIN_SCALE = 6;
  var MAX_SCALE = 100;
  var COVERAGE_SAMPLE_STEP = 0.5;
  var COVERAGE_MAX_RADIUS = 20;

  var COLORS = [
    '#4A84BF', '#22c55e', '#F59E0B', '#EF4444',
    '#8B5CF6', '#EC4899', '#06B6D4', '#F97316'
  ];
  var BG        = '#0F0F0F';
  var CANVAS_BG = '#141414';
  var GRID_MIN  = '#1C1C1C';
  var GRID_MAJ  = '#282828';
  var GRID_TXT  = '#555555';
  var MACHINE_FILL   = '#1E2228';
  var MACHINE_STROKE = '#3A4450';
  var SIDE_BG   = '#161616';
  var SIDE_BDR  = '#262626';
  var TXT_PRI   = '#F2F2F2';
  var TXT_SEC   = '#A6A6A6';
  var TXT_DIM   = '#666666';
  var ACCENT    = '#4A84BF';
  var DANGER    = '#EF4444';
  var SUCCESS   = '#22c55e';
  var WARNING   = '#F59E0B';

  // ── Machine silhouettes — top-down [x, z] in meters ─────
  var SILHOUETTES = {
    wheel_loader: [
      [-0.8, 4.2], [-1.15, 3.6], [-1.25, 2.8], [-1.25, -2.8],
      [-1.15, -3.6], [-0.8, -4.2], [0.8, -4.2], [1.15, -3.6],
      [1.25, -2.8], [1.25, 2.8], [1.15, 3.6], [0.8, 4.2]
    ],
    excavator: [
      [-1.2, 4.75], [-1.45, 3.8], [-1.45, -3.8], [-1.2, -4.75],
      [1.2, -4.75], [1.45, -3.8], [1.45, 3.8], [1.2, 4.75]
    ],
    dozer: [
      [-1.35, 2.35], [-1.35, -1.5], [-1.2, -2.35],
      [1.2, -2.35], [1.35, -1.5], [1.35, 2.35]
    ],
    dump_truck: [
      [-1.5, 5.3], [-1.75, 4.2], [-1.75, -4.2], [-1.5, -5.3],
      [1.5, -5.3], [1.75, -4.2], [1.75, 4.2], [1.5, 5.3]
    ]
  };

  // ── Lucide-style SVG icon paths ──────────────────────────
  var ICONS = {
    camera: '<path d="M23 19a2 2 0 0 1-2 2H3a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h4l2-3h6l2 3h4a2 2 0 0 1 2 2z"/><circle cx="12" cy="13" r="4"/>',
    close: '<line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/>',
    plus: '<line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/>',
    trash: '<polyline points="3 6 5 6 21 6"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/><line x1="10" y1="11" x2="10" y2="17"/><line x1="14" y1="11" x2="14" y2="17"/>',
    ruler: '<path d="M21.3 15.3a2.4 2.4 0 0 1 0 3.4l-2.6 2.6a2.4 2.4 0 0 1-3.4 0L2.7 8.7a2.41 2.41 0 0 1 0-3.4l2.6-2.6a2.41 2.41 0 0 1 3.4 0Z"/><path d="m14.5 12.5 2-2"/><path d="m11.5 9.5 2-2"/><path d="m8.5 6.5 2-2"/><path d="m17.5 15.5 2-2"/>',
    zoomIn: '<circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/><line x1="11" y1="8" x2="11" y2="14"/><line x1="8" y1="11" x2="14" y2="11"/>',
    zoomOut: '<circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/><line x1="8" y1="11" x2="14" y2="11"/>',
    shuffle: '<polyline points="16 3 21 3 21 8"/><line x1="4" y1="20" x2="21" y2="3"/><polyline points="21 16 21 21 16 21"/><line x1="15" y1="15" x2="21" y2="21"/><line x1="4" y1="4" x2="9" y2="9"/>',
    download: '<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/>',
    clipboard: '<rect width="8" height="4" x="8" y="2" rx="1" ry="1"/><path d="M16 4h2a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2h2"/>',
    check: '<polyline points="20 6 9 17 4 12"/>',
    alertTriangle: '<path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3Z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/>',
    arrowLeft: '<line x1="19" y1="12" x2="5" y2="12"/><polyline points="12 19 5 12 12 5"/>',
    sidebar: '<rect width="18" height="18" x="3" y="3" rx="2" ry="2"/><line x1="15" y1="3" x2="15" y2="21"/>',
    crosshair: '<circle cx="12" cy="12" r="10"/><line x1="22" y1="12" x2="18" y2="12"/><line x1="6" y1="12" x2="2" y2="12"/><line x1="12" y1="6" x2="12" y2="2"/><line x1="12" y1="22" x2="12" y2="18"/>',
    eye: '<path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/><circle cx="12" cy="12" r="3"/>',
    eyeOff: '<path d="M17.94 17.94A10.07 10.07 0 0 1 12 20c-7 0-11-8-11-8a18.45 18.45 0 0 1 5.06-5.94"/><path d="M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 11 8 11 8a18.5 18.5 0 0 1-2.16 3.19"/><line x1="1" y1="1" x2="23" y2="23"/>',
    rotateCcw: '<polyline points="1 4 1 10 7 10"/><path d="M3.51 15a9 9 0 1 0 2.13-9.36L1 10"/>'
  };

  function icon(name, size) {
    size = size || 20;
    return '<svg width="' + size + '" height="' + size + '" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">' + (ICONS[name] || '') + '</svg>';
  }

  // ── State ────────────────────────────────────────────────
  var isOpen = false;
  var overlay = null;
  var canvas = null;
  var ctx = null;
  var sidebarEl = null;
  var sidebarVisible = true;
  var cameras = [];
  var selectedIdx = -1;
  var machineType = 'wheel_loader';
  var outline = null;

  // View transform
  var vx = 0, vz = 0;   // view center in world
  var vs = 30;            // pixels per meter

  // Interaction
  var interacting = false;
  var dragMode = null;    // 'cam', 'rot', 'new', 'pan', 'measure'
  var dragIdx = -1;
  var pointerDown = false;
  var pointerStart = { x: 0, y: 0 };
  var pointerMoved = false;
  var pinchDist0 = 0;
  var pinchScale0 = 0;
  var pinchCenter = null;

  // Measure
  var measureActive = false;
  var mStart = null;
  var mEnd = null;

  // Calibration
  var calActive = false;
  var calStep = 0;
  var calResults = [];

  // Coverage
  var coverage = 0;

  // Rendering
  var rafId = null;
  var needsRender = true;

  // ── Geometry helpers ─────────────────────────────────────

  function dist(ax, az, bx, bz) {
    var dx = bx - ax, dz = bz - az;
    return Math.sqrt(dx * dx + dz * dz);
  }

  function closestPointOnSeg(px, pz, ax, az, bx, bz) {
    var dx = bx - ax, dz = bz - az;
    var len2 = dx * dx + dz * dz;
    if (len2 < 1e-8) return { x: ax, z: az, t: 0 };
    var t = ((px - ax) * dx + (pz - az) * dz) / len2;
    t = Math.max(0, Math.min(1, t));
    return { x: ax + t * dx, z: az + t * dz, t: t };
  }

  function closestPointOnOutline(px, pz, poly) {
    var best = null;
    var bestD = Infinity;
    for (var i = 0; i < poly.length; i++) {
      var a = poly[i];
      var b = poly[(i + 1) % poly.length];
      var cp = closestPointOnSeg(px, pz, a[0], a[1], b[0], b[1]);
      var d = dist(px, pz, cp.x, cp.z);
      if (d < bestD) {
        bestD = d;
        // compute outward normal
        var ex = b[0] - a[0], ez = b[1] - a[1];
        var nl = Math.sqrt(ex * ex + ez * ez);
        var nx = ez / nl, nz = -ex / nl;
        // ensure outward (away from origin)
        var mx = (a[0] + b[0]) / 2, mz = (a[1] + b[1]) / 2;
        if (mx * nx + mz * nz < 0) { nx = -nx; nz = -nz; }
        best = { x: cp.x, z: cp.z, dist: d, nx: nx, nz: nz, edgeIdx: i };
      }
    }
    return best;
  }

  function outlinePerimeter(poly) {
    var len = 0;
    for (var i = 0; i < poly.length; i++) {
      var a = poly[i], b = poly[(i + 1) % poly.length];
      len += dist(a[0], a[1], b[0], b[1]);
    }
    return len;
  }

  function pointAlongOutline(poly, d) {
    var total = outlinePerimeter(poly);
    d = ((d % total) + total) % total;
    var acc = 0;
    for (var i = 0; i < poly.length; i++) {
      var a = poly[i], b = poly[(i + 1) % poly.length];
      var segLen = dist(a[0], a[1], b[0], b[1]);
      if (acc + segLen >= d) {
        var t = (d - acc) / segLen;
        var px = a[0] + t * (b[0] - a[0]);
        var pz = a[1] + t * (b[1] - a[1]);
        var ex = b[0] - a[0], ez = b[1] - a[1];
        var nl = Math.sqrt(ex * ex + ez * ez);
        var nx = ez / nl, nz = -ex / nl;
        var mx = (a[0] + b[0]) / 2, mz = (a[1] + b[1]) / 2;
        if (mx * nx + mz * nz < 0) { nx = -nx; nz = -nz; }
        return { x: px, z: pz, nx: nx, nz: nz };
      }
      acc += segLen;
    }
    return { x: poly[0][0], z: poly[0][1], nx: 0, nz: 1 };
  }

  function pointInPolygon(px, pz, poly) {
    var inside = false;
    for (var i = 0, j = poly.length - 1; i < poly.length; j = i++) {
      var xi = poly[i][0], zi = poly[i][1];
      var xj = poly[j][0], zj = poly[j][1];
      if ((zi > pz) !== (zj > pz) &&
          px < (xj - xi) * (pz - zi) / (zj - zi) + xi) {
        inside = !inside;
      }
    }
    return inside;
  }

  function pointInFov(px, pz, cam) {
    if (!cam.enabled) return false;
    var dx = px - cam.x, dz = pz - cam.z;
    var d = Math.sqrt(dx * dx + dz * dz);
    if (d > cam.range || d < 0.01) return false;
    var ptAngle = Math.atan2(dx, dz) * 180 / Math.PI;
    var diff = ((ptAngle - cam.angle + 540) % 360) - 180;
    return Math.abs(diff) <= cam.fov / 2;
  }

  // ── Coordinate transforms ────────────────────────────────

  function canvasW() { return canvas ? canvas.width : 800; }
  function canvasH() { return canvas ? canvas.height : 600; }

  function w2cx(wx) { return (wx - vx) * vs + canvasW() / 2; }
  function w2cy(wz) { return -(wz - vz) * vs + canvasH() / 2; }
  function c2wx(cx) { return (cx - canvasW() / 2) / vs + vx; }
  function c2wz(cy) { return -(cy - canvasH() / 2) / vs + vz; }

  // ── Camera data helpers ──────────────────────────────────

  function genId() {
    return 'cam_' + Date.now() + '_' + Math.floor(Math.random() * 10000);
  }

  function createCamera(x, z, angle) {
    var idx = cameras.length;
    return {
      id: genId(),
      name: 'Camera ' + (idx + 1),
      x: x,
      z: z,
      angle: angle || 0,
      fov: DEFAULT_FOV,
      range: DEFAULT_RANGE,
      enabled: true,
      mountHeight: 2.8,
      color: COLORS[idx % COLORS.length]
    };
  }

  function snapToPerimeter(cam) {
    if (!outline) return;
    var cp = closestPointOnOutline(cam.x, cam.z, outline);
    if (cp && cp.dist < SNAP_THRESHOLD_M) {
      cam.x = cp.x;
      cam.z = cp.z;
      cam.angle = Math.atan2(cp.nx, cp.nz) * 180 / Math.PI;
    }
  }

  // ── Coverage display ──────────────────────────────────────

  function updateCoverageDisplay() {
    var el = document.getElementById('gf-cp-coverage-pct');
    if (el) {
      el.textContent = coverage + '%';
      el.style.color = coverageColor();
    }
  }

  function coverageColor() {
    if (coverage >= 80) return SUCCESS;
    if (coverage >= 50) return WARNING;
    return DANGER;
  }

  // ── Coverage calculation ─────────────────────────────────

  var calcCoverage = function () {
    if (!outline || cameras.length === 0) { coverage = 0; updateCoverageDisplay(); return; }
    var total = 0, covered = 0;
    var step = COVERAGE_SAMPLE_STEP;
    for (var wx = -COVERAGE_MAX_RADIUS; wx <= COVERAGE_MAX_RADIUS; wx += step) {
      for (var wz = -COVERAGE_MAX_RADIUS; wz <= COVERAGE_MAX_RADIUS; wz += step) {
        if (pointInPolygon(wx, wz, outline)) continue;
        if (dist(wx, wz, 0, 0) > COVERAGE_MAX_RADIUS) continue;
        total++;
        for (var c = 0; c < cameras.length; c++) {
          if (pointInFov(wx, wz, cameras[c])) { covered++; break; }
        }
      }
    }
    coverage = total > 0 ? Math.round(covered / total * 100) : 0;
    updateCoverageDisplay();
  };

  // ── Persist cameras ──────────────────────────────────────

  function saveToStorage() {
    var data = cameras.map(function (cam) {
      var radY = cam.angle * Math.PI / 180;
      return {
        id: cam.id,
        name: cam.name,
        position: [cam.x, cam.mountHeight, cam.z],
        rotation: [0, cam.angle, 0],
        hfov_deg: cam.fov,
        range_m: cam.range,
        enabled: cam.enabled,
        connected: false,
        color: cam.color,
        _placement: { x: cam.x, z: cam.z, angle: cam.angle, fov: cam.fov, range: cam.range, mountHeight: cam.mountHeight }
      };
    });
    try {
      localStorage.setItem('gf_cameras', JSON.stringify(data));
      var evt = new CustomEvent('gf-config-changed', { detail: { type: 'cameras', cameras: data } });
      window.dispatchEvent(evt);
    } catch (e) { /* storage full or unavailable */ }
  }

  function loadFromStorage() {
    cameras = [];
    try {
      var raw = localStorage.getItem('gf_cameras');
      if (!raw) return;
      var arr = JSON.parse(raw);
      if (!Array.isArray(arr)) return;
      for (var i = 0; i < arr.length; i++) {
        var d = arr[i];
        var cam;
        if (d._placement) {
          cam = createCamera(d._placement.x, d._placement.z, d._placement.angle);
          cam.fov = d._placement.fov || DEFAULT_FOV;
          cam.range = d._placement.range || DEFAULT_RANGE;
          cam.mountHeight = d._placement.mountHeight || 2.8;
        } else if (d.position) {
          cam = createCamera(d.position[0], d.position[2], d.rotation ? d.rotation[1] : 0);
          cam.fov = d.hfov_deg || DEFAULT_FOV;
          cam.range = d.range_m || DEFAULT_RANGE;
          cam.mountHeight = d.position[1] || 2.8;
        } else {
          continue;
        }
        cam.id = d.id || cam.id;
        cam.name = d.name || cam.name;
        cam.enabled = d.enabled !== false;
        cam.color = d.color || COLORS[i % COLORS.length];
        cameras.push(cam);
      }
    } catch (e) { cameras = []; }
  }

  function exportConfig() {
    var json = JSON.stringify(cameras.map(function (cam) {
      return {
        id: cam.id,
        name: cam.name,
        position: { x: cam.x, z: cam.z, height: cam.mountHeight },
        angle_deg: cam.angle,
        hfov_deg: cam.fov,
        range_m: cam.range,
        enabled: cam.enabled
      };
    }), null, 2);
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(json).then(function () {
        showToast('Config copied to clipboard');
      });
    } else {
      showToast('Clipboard unavailable');
    }
  }

  // ── Toast notification ───────────────────────────────────

  function showToast(msg) {
    var el = document.getElementById('gf-cp-toast');
    if (!el) return;
    el.textContent = msg;
    el.classList.add('visible');
    setTimeout(function () { el.classList.remove('visible'); }, 2200);
  }

  // ── DOM construction ─────────────────────────────────────

  function buildDOM() {
    if (overlay) return;

    // Stylesheet
    var style = document.createElement('style');
    style.textContent = buildCSS();
    document.head.appendChild(style);

    // Overlay
    overlay = document.createElement('div');
    overlay.id = 'gf-cp-overlay';
    overlay.innerHTML = buildHTML();
    document.body.appendChild(overlay);

    // Acquire canvas and sidebar refs
    canvas = document.getElementById('gf-cp-canvas');
    if (canvas) ctx = canvas.getContext('2d');
    sidebarEl = document.getElementById('gf-cp-sidebar');

    bindEvents();
  }

  function acquireCanvas() {
    canvas = document.getElementById('gf-cp-canvas');
    if (canvas) ctx = canvas.getContext('2d');
    sidebarEl = document.getElementById('gf-cp-sidebar');
  }

  function buildCSS() {
    return [
      '#gf-cp-overlay {',
      '  position:fixed;top:0;left:0;right:0;bottom:0;',
      '  background:' + BG + ';z-index:2000;',
      '  display:none;flex-direction:column;',
      '  font-family:system-ui,-apple-system,sans-serif;',
      '  color:' + TXT_PRI + ';',
      '}',
      '#gf-cp-overlay.open { display:flex; }',

      /* Header */
      '#gf-cp-header {',
      '  display:flex;align-items:center;gap:10px;',
      '  padding:10px 16px;background:#121212;',
      '  border-bottom:1px solid ' + SIDE_BDR + ';flex-shrink:0;',
      '  padding-top:max(10px,env(safe-area-inset-top));',
      '}',
      '#gf-cp-header .title { font-size:16px;font-weight:700;flex:1; }',
      '.gf-cp-hbtn {',
      '  width:36px;height:36px;border-radius:8px;border:none;',
      '  background:transparent;color:' + TXT_SEC + ';cursor:pointer;',
      '  display:flex;align-items:center;justify-content:center;',
      '  -webkit-tap-highlight-color:transparent;',
      '}',
      '.gf-cp-hbtn:active { background:#262626; }',
      '.gf-cp-hbtn.active { color:' + ACCENT + ';background:#1a2535; }',

      /* Main area */
      '#gf-cp-main {',
      '  display:flex;flex:1;overflow:hidden;position:relative;',
      '}',

      /* Canvas area */
      '#gf-cp-canvas-wrap {',
      '  flex:1;position:relative;overflow:hidden;',
      '  background:' + CANVAS_BG + ';',
      '}',
      '#gf-cp-canvas {',
      '  display:block;width:100%;height:100%;touch-action:none;',
      '}',

      /* Toolbar */
      '#gf-cp-toolbar {',
      '  position:absolute;bottom:12px;left:50%;transform:translateX(-50%);',
      '  display:flex;gap:6px;padding:6px 10px;',
      '  background:rgba(18,18,18,0.92);border:1px solid ' + SIDE_BDR + ';',
      '  border-radius:12px;backdrop-filter:blur(8px);',
      '  -webkit-backdrop-filter:blur(8px);align-items:center;',
      '}',
      '.gf-cp-tool {',
      '  width:42px;height:42px;border-radius:8px;border:none;',
      '  background:transparent;color:' + TXT_SEC + ';cursor:pointer;',
      '  display:flex;align-items:center;justify-content:center;',
      '  -webkit-tap-highlight-color:transparent;flex-shrink:0;',
      '  position:relative;',
      '}',
      '.gf-cp-tool:active { background:#262626; }',
      '.gf-cp-tool.active { color:' + ACCENT + ';background:#1a2535; }',
      '.gf-cp-tool-sep {',
      '  width:1px;height:24px;background:#333;flex-shrink:0;',
      '}',
      '#gf-cp-drag-cam {',
      '  width:42px;height:42px;border-radius:8px;',
      '  border:2px dashed ' + ACCENT + ';color:' + ACCENT + ';',
      '  background:rgba(74,132,191,0.08);cursor:grab;',
      '  display:flex;align-items:center;justify-content:center;',
      '  -webkit-tap-highlight-color:transparent;',
      '}',
      '#gf-cp-drag-cam:active { cursor:grabbing;background:rgba(74,132,191,0.15); }',

      /* Coverage pill */
      '#gf-cp-coverage {',
      '  position:absolute;top:12px;left:12px;',
      '  padding:6px 14px;border-radius:20px;',
      '  background:rgba(18,18,18,0.92);border:1px solid ' + SIDE_BDR + ';',
      '  backdrop-filter:blur(8px);-webkit-backdrop-filter:blur(8px);',
      '  font-size:13px;font-weight:600;',
      '  display:flex;align-items:center;gap:8px;',
      '}',
      '#gf-cp-coverage-pct { font-size:18px;font-weight:700; }',

      /* Measure readout */
      '#gf-cp-measure-readout {',
      '  position:absolute;top:12px;left:50%;transform:translateX(-50%);',
      '  padding:6px 14px;border-radius:20px;',
      '  background:rgba(74,132,191,0.9);',
      '  font-size:14px;font-weight:700;color:#fff;',
      '  display:none;pointer-events:none;',
      '}',

      /* Sidebar */
      '#gf-cp-sidebar {',
      '  width:320px;max-width:40vw;background:' + SIDE_BG + ';',
      '  border-left:1px solid ' + SIDE_BDR + ';',
      '  display:flex;flex-direction:column;overflow:hidden;',
      '  transition:margin-right 0.25s ease;flex-shrink:0;',
      '}',
      '#gf-cp-sidebar.hidden {',
      '  margin-right:-320px;',
      '}',
      '#gf-cp-side-head {',
      '  padding:12px 14px;border-bottom:1px solid ' + SIDE_BDR + ';',
      '  font-size:13px;font-weight:700;color:' + TXT_SEC + ';',
      '  text-transform:uppercase;letter-spacing:0.6px;',
      '  display:flex;align-items:center;justify-content:space-between;',
      '}',
      '#gf-cp-side-body {',
      '  flex:1;overflow-y:auto;padding:8px 14px 80px;',
      '  -webkit-overflow-scrolling:touch;',
      '}',

      /* Camera card in sidebar */
      '.gf-cp-cam-card {',
      '  background:#1A1A1A;border:1px solid ' + SIDE_BDR + ';',
      '  border-radius:10px;padding:10px 12px;margin-bottom:8px;',
      '  cursor:pointer;-webkit-tap-highlight-color:transparent;',
      '  transition:border-color 0.15s;',
      '}',
      '.gf-cp-cam-card.selected { border-color:' + ACCENT + '; }',
      '.gf-cp-cam-card-head {',
      '  display:flex;align-items:center;gap:8px;margin-bottom:6px;',
      '}',
      '.gf-cp-cam-dot {',
      '  width:10px;height:10px;border-radius:50%;flex-shrink:0;',
      '}',
      '.gf-cp-cam-name {',
      '  flex:1;font-size:14px;font-weight:600;',
      '  background:none;border:none;color:' + TXT_PRI + ';',
      '  font-family:inherit;padding:0;min-width:0;',
      '}',
      '.gf-cp-cam-name:focus {',
      '  outline:none;border-bottom:1px solid ' + ACCENT + ';',
      '}',
      '.gf-cp-cam-del {',
      '  width:28px;height:28px;border-radius:6px;border:none;',
      '  background:transparent;color:' + TXT_DIM + ';cursor:pointer;',
      '  display:flex;align-items:center;justify-content:center;',
      '}',
      '.gf-cp-cam-del:active { color:' + DANGER + ';background:rgba(239,68,68,0.1); }',
      '.gf-cp-cam-detail {',
      '  font-size:12px;color:' + TXT_DIM + ';',
      '  display:flex;gap:12px;flex-wrap:wrap;margin-bottom:6px;',
      '}',

      /* Sliders in sidebar */
      '.gf-cp-slider-row {',
      '  display:flex;align-items:center;gap:8px;margin:4px 0;',
      '}',
      '.gf-cp-slider-label {',
      '  font-size:11px;font-weight:600;color:' + TXT_DIM + ';',
      '  width:42px;flex-shrink:0;',
      '}',
      '.gf-cp-slider {',
      '  -webkit-appearance:none;appearance:none;flex:1;height:4px;',
      '  border-radius:2px;outline:none;cursor:pointer;',
      '  background:linear-gradient(to right,' + ACCENT + ' 0%,' + ACCENT + ' var(--pct,50%),#333 var(--pct,50%));',
      '}',
      '.gf-cp-slider::-webkit-slider-thumb {',
      '  -webkit-appearance:none;appearance:none;',
      '  width:18px;height:18px;border-radius:50%;',
      '  background:#fff;border:2px solid ' + ACCENT + ';',
      '  box-shadow:0 1px 4px rgba(0,0,0,0.4);cursor:pointer;',
      '}',
      '.gf-cp-slider-val {',
      '  font-size:12px;font-weight:700;color:' + TXT_PRI + ';',
      '  width:40px;text-align:right;flex-shrink:0;',
      '}',

      /* Toggle */
      '.gf-cp-toggle {',
      '  position:relative;width:38px;height:22px;flex-shrink:0;cursor:pointer;',
      '}',
      '.gf-cp-toggle input { opacity:0;width:0;height:0;position:absolute; }',
      '.gf-cp-toggle-track {',
      '  position:absolute;top:0;left:0;right:0;bottom:0;',
      '  background:#333;border-radius:11px;transition:background 0.2s;',
      '}',
      '.gf-cp-toggle input:checked + .gf-cp-toggle-track { background:' + SUCCESS + '; }',
      '.gf-cp-toggle-thumb {',
      '  position:absolute;top:2px;left:2px;width:18px;height:18px;',
      '  border-radius:50%;background:#fff;box-shadow:0 1px 3px rgba(0,0,0,0.3);',
      '  transition:transform 0.2s;',
      '}',
      '.gf-cp-toggle input:checked ~ .gf-cp-toggle-thumb { transform:translateX(16px); }',

      /* Action buttons */
      '.gf-cp-action {',
      '  width:100%;height:38px;border-radius:8px;border:1px solid ' + SIDE_BDR + ';',
      '  background:transparent;color:' + TXT_SEC + ';',
      '  font-size:13px;font-weight:600;font-family:inherit;',
      '  cursor:pointer;display:flex;align-items:center;',
      '  justify-content:center;gap:6px;margin-bottom:8px;',
      '  -webkit-tap-highlight-color:transparent;',
      '}',
      '.gf-cp-action:active { background:#1a2535;color:' + ACCENT + ';border-color:' + ACCENT + '; }',
      '.gf-cp-action.primary {',
      '  background:' + ACCENT + ';color:#fff;border-color:' + ACCENT + ';',
      '}',
      '.gf-cp-action.primary:active { background:#3a6fa8; }',

      /* Calibration overlay */
      '#gf-cp-cal-overlay {',
      '  position:absolute;top:0;left:0;right:0;bottom:0;',
      '  background:rgba(0,0,0,0.85);z-index:10;',
      '  display:none;flex-direction:column;align-items:center;',
      '  justify-content:center;padding:24px;',
      '}',
      '#gf-cp-cal-overlay.open { display:flex; }',
      '#gf-cp-cal-box {',
      '  background:#1A1A1A;border:1px solid ' + SIDE_BDR + ';',
      '  border-radius:16px;max-width:520px;width:100%;',
      '  padding:24px;',
      '}',
      '#gf-cp-cal-title {',
      '  font-size:18px;font-weight:700;margin-bottom:4px;',
      '}',
      '#gf-cp-cal-sub {',
      '  font-size:13px;color:' + TXT_SEC + ';margin-bottom:16px;',
      '}',
      '#gf-cp-cal-canvas {',
      '  width:100%;height:200px;border-radius:10px;',
      '  background:#0F0F0F;margin-bottom:16px;',
      '}',
      '#gf-cp-cal-instruction {',
      '  font-size:15px;font-weight:600;text-align:center;',
      '  margin-bottom:16px;line-height:1.5;',
      '}',
      '#gf-cp-cal-buttons {',
      '  display:flex;gap:10px;',
      '}',
      '#gf-cp-cal-buttons button {',
      '  flex:1;height:44px;border-radius:10px;border:none;',
      '  font-size:14px;font-weight:600;font-family:inherit;',
      '  cursor:pointer;-webkit-tap-highlight-color:transparent;',
      '}',
      '.gf-cp-cal-pass { background:' + SUCCESS + ';color:#fff; }',
      '.gf-cp-cal-pass:active { background:#1aab4a; }',
      '.gf-cp-cal-fail { background:#333;color:' + TXT_SEC + '; }',
      '.gf-cp-cal-fail:active { background:#444; }',
      '.gf-cp-cal-skip { background:transparent;color:' + TXT_DIM + ';border:1px solid #333 !important; }',

      /* Cal results */
      '.gf-cp-cal-result {',
      '  display:flex;align-items:center;gap:10px;padding:8px 0;',
      '  border-bottom:1px solid #222;',
      '}',
      '.gf-cp-cal-result:last-child { border-bottom:none; }',
      '.gf-cp-cal-result-icon { width:24px;text-align:center; }',
      '.gf-cp-cal-result .pass { color:' + SUCCESS + '; }',
      '.gf-cp-cal-result .fail { color:' + DANGER + '; }',
      '.gf-cp-cal-result .skip { color:' + TXT_DIM + '; }',

      /* Toast */
      '#gf-cp-toast {',
      '  position:absolute;bottom:80px;left:50%;transform:translateX(-50%);',
      '  padding:8px 20px;border-radius:20px;',
      '  background:rgba(255,255,255,0.12);color:#fff;',
      '  font-size:13px;font-weight:600;',
      '  opacity:0;transition:opacity 0.3s;pointer-events:none;',
      '}',
      '#gf-cp-toast.visible { opacity:1; }',

      /* Scale bar */
      '#gf-cp-scale {',
      '  position:absolute;bottom:70px;left:12px;',
      '  display:flex;align-items:flex-end;gap:4px;',
      '  font-size:10px;font-weight:600;color:' + TXT_DIM + ';',
      '  pointer-events:none;',
      '}',
      '#gf-cp-scale-bar {',
      '  height:3px;background:' + TXT_DIM + ';border-radius:1px;',
      '  min-width:30px;',
      '}',
    ].join('\n');
  }

  function buildHTML() {
    return [
      /* Header */
      '<div id="gf-cp-header">',
      '  <button class="gf-cp-hbtn" id="gf-cp-back">' + icon('arrowLeft', 22) + '</button>',
      '  <span class="title">Camera Placement</span>',
      '  <button class="gf-cp-hbtn" id="gf-cp-btn-cal" title="Calibration">' + icon('crosshair', 20) + '</button>',
      '  <button class="gf-cp-hbtn" id="gf-cp-btn-export" title="Export">' + icon('clipboard', 20) + '</button>',
      '  <button class="gf-cp-hbtn" id="gf-cp-btn-sidebar" title="Toggle sidebar">' + icon('sidebar', 20) + '</button>',
      '</div>',

      /* Main area */
      '<div id="gf-cp-main">',

      /* Canvas wrap */
      '  <div id="gf-cp-canvas-wrap">',
      '    <canvas id="gf-cp-canvas"></canvas>',

      /* Coverage pill */
      '    <div id="gf-cp-coverage">',
      '      Coverage <span id="gf-cp-coverage-pct">0%</span>',
      '    </div>',

      /* Measure readout */
      '    <div id="gf-cp-measure-readout"></div>',

      /* Scale bar */
      '    <div id="gf-cp-scale">',
      '      <div id="gf-cp-scale-bar"></div>',
      '      <span id="gf-cp-scale-label">5m</span>',
      '    </div>',

      /* Toolbar */
      '    <div id="gf-cp-toolbar">',
      '      <div id="gf-cp-drag-cam" title="Drag to place camera">' + icon('camera', 20) + '</div>',
      '      <div class="gf-cp-tool-sep"></div>',
      '      <button class="gf-cp-tool" id="gf-cp-btn-measure" title="Measure">' + icon('ruler', 20) + '</button>',
      '      <div class="gf-cp-tool-sep"></div>',
      '      <button class="gf-cp-tool" id="gf-cp-btn-zoomin" title="Zoom in">' + icon('zoomIn', 20) + '</button>',
      '      <button class="gf-cp-tool" id="gf-cp-btn-zoomout" title="Zoom out">' + icon('zoomOut', 20) + '</button>',
      '    </div>',

      /* Toast */
      '    <div id="gf-cp-toast"></div>',

      /* Calibration overlay */
      '    <div id="gf-cp-cal-overlay">',
      '      <div id="gf-cp-cal-box">',
      '        <div id="gf-cp-cal-title">Calibration Verification</div>',
      '        <div id="gf-cp-cal-sub">Verify each camera detects at the expected range.</div>',
      '        <canvas id="gf-cp-cal-canvas"></canvas>',
      '        <div id="gf-cp-cal-instruction"></div>',
      '        <div id="gf-cp-cal-buttons"></div>',
      '      </div>',
      '    </div>',
      '  </div>',

      /* Sidebar */
      '  <div id="gf-cp-sidebar">',
      '    <div id="gf-cp-side-head">',
      '      <span>Cameras</span>',
      '      <span id="gf-cp-cam-count">0 / ' + MAX_CAMERAS + '</span>',
      '    </div>',
      '    <div id="gf-cp-side-body"></div>',
      '  </div>',

      '</div>'
    ].join('\n');
  }

  // ── Canvas rendering ─────────────────────────────────────

  function render() {
    if (!ctx || !canvas) return;
    var w = canvasW(), h = canvasH();
    ctx.clearRect(0, 0, w, h);

    // Background
    ctx.fillStyle = CANVAS_BG;
    ctx.fillRect(0, 0, w, h);

    drawGrid(w, h);
    drawMachine();
    drawFovCones();
    drawMachineLabel();
    drawCameras();
    drawMeasure();
    updateScaleBar();
  }

  function drawGrid(w, h) {
    // Determine visible world bounds
    var wl = c2wx(0), wr = c2wx(w);
    var wt = c2wz(0), wb = c2wz(h);
    var minX = Math.min(wl, wr), maxX = Math.max(wl, wr);
    var minZ = Math.min(wt, wb), maxZ = Math.max(wt, wb);

    // Minor grid (1m)
    ctx.strokeStyle = GRID_MIN;
    ctx.lineWidth = 1;
    ctx.beginPath();
    var startX = Math.floor(minX);
    var startZ = Math.floor(minZ);
    for (var gx = startX; gx <= maxX; gx++) {
      if (gx % 5 === 0) continue;
      var cx = w2cx(gx);
      ctx.moveTo(cx, 0);
      ctx.lineTo(cx, h);
    }
    for (var gz = startZ; gz <= maxZ; gz++) {
      if (gz % 5 === 0) continue;
      var cy = w2cy(gz);
      ctx.moveTo(0, cy);
      ctx.lineTo(w, cy);
    }
    ctx.stroke();

    // Major grid (5m)
    ctx.strokeStyle = GRID_MAJ;
    ctx.lineWidth = 1;
    ctx.beginPath();
    var start5X = Math.floor(minX / 5) * 5;
    var start5Z = Math.floor(minZ / 5) * 5;
    for (var mx = start5X; mx <= maxX; mx += 5) {
      var mcx = w2cx(mx);
      ctx.moveTo(mcx, 0);
      ctx.lineTo(mcx, h);
    }
    for (var mz = start5Z; mz <= maxZ; mz += 5) {
      var mcy = w2cy(mz);
      ctx.moveTo(0, mcy);
      ctx.lineTo(w, mcy);
    }
    ctx.stroke();

    // Grid labels on major lines
    if (vs > 10) {
      ctx.fillStyle = GRID_TXT;
      ctx.font = '600 10px system-ui,-apple-system,sans-serif';
      ctx.textAlign = 'left';
      ctx.textBaseline = 'top';
      for (var lx = start5X; lx <= maxX; lx += 5) {
        if (lx === 0) continue;
        ctx.fillText(lx + 'm', w2cx(lx) + 3, w2cy(0) + 3);
      }
      ctx.textAlign = 'right';
      ctx.textBaseline = 'bottom';
      for (var lz = start5Z; lz <= maxZ; lz += 5) {
        if (lz === 0) continue;
        ctx.fillText(lz + 'm', w2cx(0) - 3, w2cy(lz) - 3);
      }
    }

    // Origin crosshair
    ctx.strokeStyle = '#333';
    ctx.lineWidth = 1;
    ctx.setLineDash([4, 4]);
    ctx.beginPath();
    ctx.moveTo(w2cx(0), 0);
    ctx.lineTo(w2cx(0), h);
    ctx.moveTo(0, w2cy(0));
    ctx.lineTo(w, w2cy(0));
    ctx.stroke();
    ctx.setLineDash([]);
  }

  function drawMachine() {
    if (!outline || outline.length < 3) return;
    ctx.beginPath();
    ctx.moveTo(w2cx(outline[0][0]), w2cy(outline[0][1]));
    for (var i = 1; i < outline.length; i++) {
      ctx.lineTo(w2cx(outline[i][0]), w2cy(outline[i][1]));
    }
    ctx.closePath();
    ctx.fillStyle = MACHINE_FILL;
    ctx.fill();
    ctx.strokeStyle = MACHINE_STROKE;
    ctx.lineWidth = 2;
    ctx.stroke();

    // Draw "FRONT" indicator
    ctx.fillStyle = TXT_DIM;
    ctx.font = '600 10px system-ui,-apple-system,sans-serif';
    ctx.textAlign = 'center';
    ctx.textBaseline = 'bottom';
    var frontZ = -Infinity;
    for (var f = 0; f < outline.length; f++) {
      if (outline[f][1] > frontZ) frontZ = outline[f][1];
    }
    ctx.fillText('FRONT', w2cx(0), w2cy(frontZ) - 6);
  }

  function drawMachineLabel() {
    if (!outline) return;
    ctx.fillStyle = TXT_DIM;
    ctx.font = '500 11px system-ui,-apple-system,sans-serif';
    ctx.textAlign = 'center';
    ctx.textBaseline = 'middle';
    ctx.fillText(getMachineLabel(), w2cx(0), w2cy(0));
  }

  function getMachineLabel() {
    var profiles = null;
    if (GF.config && typeof GF.config.getMachineProfiles === 'function') {
      profiles = GF.config.getMachineProfiles();
    }
    if (profiles && profiles[machineType]) return profiles[machineType].name;
    return machineType.replace(/_/g, ' ').replace(/\b\w/g, function (c) { return c.toUpperCase(); });
  }

  function drawFovCones() {
    for (var i = 0; i < cameras.length; i++) {
      var cam = cameras[i];
      if (!cam.enabled) continue;
      var cx = w2cx(cam.x), cy = w2cy(cam.z);
      var rPx = cam.range * vs;
      // Convert angle: world angle 0 = +Z = up on canvas
      var rad = -cam.angle * Math.PI / 180;
      var halfFov = cam.fov / 2 * Math.PI / 180;
      var startAngle = rad - Math.PI / 2 - halfFov;
      var endAngle = rad - Math.PI / 2 + halfFov;

      // Fill
      ctx.beginPath();
      ctx.moveTo(cx, cy);
      ctx.arc(cx, cy, rPx, startAngle, endAngle);
      ctx.closePath();
      ctx.fillStyle = hexToRgba(cam.color, 0.1);
      ctx.fill();

      // Edge line
      ctx.strokeStyle = hexToRgba(cam.color, 0.3);
      ctx.lineWidth = 1.5;
      ctx.beginPath();
      ctx.moveTo(cx, cy);
      ctx.arc(cx, cy, rPx, startAngle, endAngle);
      ctx.closePath();
      ctx.stroke();

      // Range arc (dashed)
      ctx.setLineDash([4, 4]);
      ctx.strokeStyle = hexToRgba(cam.color, 0.15);
      ctx.lineWidth = 1;
      ctx.beginPath();
      ctx.arc(cx, cy, rPx, startAngle, endAngle);
      ctx.stroke();
      ctx.setLineDash([]);
    }
  }

  function drawCameras() {
    for (var i = 0; i < cameras.length; i++) {
      var cam = cameras[i];
      var cx = w2cx(cam.x), cy = w2cy(cam.z);
      var r = CAM_RADIUS_M * vs;
      var sel = (i === selectedIdx);

      // Direction line
      var dirRad = cam.angle * Math.PI / 180;
      var dirX = Math.sin(dirRad), dirZ = Math.cos(dirRad);
      var lineLen = HANDLE_DIST_M * vs;
      ctx.strokeStyle = hexToRgba(cam.color, sel ? 0.7 : 0.4);
      ctx.lineWidth = 2;
      ctx.beginPath();
      ctx.moveTo(cx, cy);
      ctx.lineTo(cx + dirX * lineLen, cy - dirZ * lineLen);
      ctx.stroke();

      // Rotation handle
      var hx = cx + dirX * lineLen;
      var hy = cy - dirZ * lineLen;
      var hr = HANDLE_RADIUS_M * vs;
      ctx.beginPath();
      ctx.arc(hx, hy, hr, 0, Math.PI * 2);
      ctx.fillStyle = sel ? cam.color : hexToRgba(cam.color, 0.5);
      ctx.fill();
      ctx.strokeStyle = '#fff';
      ctx.lineWidth = 1.5;
      ctx.stroke();

      // Arrow inside handle
      ctx.fillStyle = '#fff';
      ctx.font = 'bold ' + Math.max(8, hr * 1.2) + 'px system-ui';
      ctx.textAlign = 'center';
      ctx.textBaseline = 'middle';
      ctx.save();
      ctx.translate(hx, hy);
      ctx.rotate(-dirRad);
      ctx.fillText('\u21BB', 0, 0);
      ctx.restore();

      // Camera circle
      ctx.beginPath();
      ctx.arc(cx, cy, r, 0, Math.PI * 2);
      ctx.fillStyle = cam.enabled ? cam.color : '#555';
      ctx.fill();
      if (sel) {
        ctx.strokeStyle = '#fff';
        ctx.lineWidth = 2.5;
        ctx.stroke();
      }

      // Camera label
      ctx.fillStyle = '#fff';
      ctx.font = '700 ' + Math.max(9, r * 0.9) + 'px system-ui,-apple-system,sans-serif';
      ctx.textAlign = 'center';
      ctx.textBaseline = 'middle';
      ctx.fillText((i + 1).toString(), cx, cy);

      // Name label below
      ctx.fillStyle = sel ? TXT_PRI : TXT_SEC;
      ctx.font = '600 10px system-ui,-apple-system,sans-serif';
      ctx.textBaseline = 'top';
      ctx.fillText(cam.name, cx, cy + r + 4);
    }
  }

  function drawMeasure() {
    if (!measureActive || !mStart) return;
    var end = mEnd || mStart;
    var sx = w2cx(mStart.x), sy = w2cy(mStart.z);
    var ex = w2cx(end.x), ey = w2cy(end.z);

    ctx.strokeStyle = ACCENT;
    ctx.lineWidth = 2;
    ctx.setLineDash([6, 4]);
    ctx.beginPath();
    ctx.moveTo(sx, sy);
    ctx.lineTo(ex, ey);
    ctx.stroke();
    ctx.setLineDash([]);

    // Endpoints
    ctx.fillStyle = ACCENT;
    ctx.beginPath();
    ctx.arc(sx, sy, 4, 0, Math.PI * 2);
    ctx.fill();
    ctx.beginPath();
    ctx.arc(ex, ey, 4, 0, Math.PI * 2);
    ctx.fill();

    // Distance
    var d = dist(mStart.x, mStart.z, end.x, end.z);
    var readout = document.getElementById('gf-cp-measure-readout');
    if (readout) {
      readout.textContent = d.toFixed(2) + ' m';
      readout.style.display = 'block';
    }
  }

  function updateScaleBar() {
    var bar = document.getElementById('gf-cp-scale-bar');
    var label = document.getElementById('gf-cp-scale-label');
    if (!bar || !label) return;
    // Pick a nice scale length
    var targets = [1, 2, 5, 10, 20, 50];
    var best = 5;
    for (var i = 0; i < targets.length; i++) {
      var px = targets[i] * vs;
      if (px >= 40 && px <= 200) { best = targets[i]; break; }
    }
    bar.style.width = (best * vs) + 'px';
    label.textContent = best + 'm';
  }

  function hexToRgba(hex, a) {
    var r = parseInt(hex.slice(1, 3), 16);
    var g = parseInt(hex.slice(3, 5), 16);
    var b = parseInt(hex.slice(5, 7), 16);
    return 'rgba(' + r + ',' + g + ',' + b + ',' + a + ')';
  }

  // ── Render scheduling ─────────────────────────────────────
  // Renders on-demand only — no continuous loop needed for a tool UI.

  function startLoop() {
    // No-op: rendering is triggered by requestRender()
  }

  function requestRender() {
    if (!isOpen || !ctx || !canvas) return;
    // Debounce via setTimeout to batch rapid updates
    if (rafId) return;
    rafId = setTimeout(function () {
      rafId = null;
      if (isOpen && ctx && canvas) render();
    }, 0);
  }

  // ── Sidebar rendering ────────────────────────────────────

  function renderSidebar() {
    var body = document.getElementById('gf-cp-side-body');
    if (!body) return;
    var html = [];

    // Camera cards
    for (var i = 0; i < cameras.length; i++) {
      html.push(buildCameraCard(i));
    }

    // Add camera button
    if (cameras.length < MAX_CAMERAS) {
      html.push('<button class="gf-cp-action" id="gf-cp-add-cam">' + icon('plus', 16) + ' Add Camera</button>');
    }

    // Auto-arrange
    if (cameras.length > 0) {
      html.push('<button class="gf-cp-action" id="gf-cp-auto-arrange">' + icon('shuffle', 16) + ' Auto-Arrange</button>');
    }

    // Coverage summary
    html.push('<div style="margin-top:12px;padding-top:12px;border-top:1px solid ' + SIDE_BDR + '">');
    html.push('<div style="font-size:11px;font-weight:600;color:' + TXT_DIM + ';text-transform:uppercase;letter-spacing:0.5px;margin-bottom:6px">Coverage Summary</div>');
    html.push('<div style="font-size:28px;font-weight:700;color:' + coverageColor() + '">' + coverage + '%</div>');
    html.push('<div style="font-size:12px;color:' + TXT_DIM + ';margin-top:2px">' + cameras.length + ' camera' + (cameras.length !== 1 ? 's' : '') + ' placed</div>');
    html.push('</div>');

    body.innerHTML = html.join('');

    // Update count
    var countEl = document.getElementById('gf-cp-cam-count');
    if (countEl) countEl.textContent = cameras.length + ' / ' + MAX_CAMERAS;

    // Bind sidebar events
    bindSidebarEvents();
  }

  function buildCameraCard(idx) {
    var cam = cameras[idx];
    var sel = idx === selectedIdx;
    var h = [];
    h.push('<div class="gf-cp-cam-card' + (sel ? ' selected' : '') + '" data-idx="' + idx + '">');

    // Head row
    h.push('<div class="gf-cp-cam-card-head">');
    h.push('<div class="gf-cp-cam-dot" style="background:' + cam.color + '"></div>');
    h.push('<input class="gf-cp-cam-name" data-idx="' + idx + '" value="' + escHtml(cam.name) + '"/>');

    // Enable toggle
    h.push('<label class="gf-cp-toggle">');
    h.push('<input type="checkbox" data-toggle-idx="' + idx + '"' + (cam.enabled ? ' checked' : '') + '/>');
    h.push('<div class="gf-cp-toggle-track"></div>');
    h.push('<div class="gf-cp-toggle-thumb"></div>');
    h.push('</label>');

    h.push('<button class="gf-cp-cam-del" data-del-idx="' + idx + '">' + icon('trash', 14) + '</button>');
    h.push('</div>');

    // Details
    h.push('<div class="gf-cp-cam-detail">');
    h.push('<span>X: ' + cam.x.toFixed(1) + 'm</span>');
    h.push('<span>Z: ' + cam.z.toFixed(1) + 'm</span>');
    h.push('<span>' + Math.round(cam.angle) + '\u00B0</span>');
    h.push('</div>');

    // FOV slider
    var fovPct = ((cam.fov - 30) / (170 - 30) * 100);
    h.push('<div class="gf-cp-slider-row">');
    h.push('<span class="gf-cp-slider-label">FOV</span>');
    h.push('<input type="range" class="gf-cp-slider" data-fov-idx="' + idx + '" min="30" max="170" value="' + cam.fov + '" style="--pct:' + fovPct + '%"/>');
    h.push('<span class="gf-cp-slider-val">' + Math.round(cam.fov) + '\u00B0</span>');
    h.push('</div>');

    // Range slider
    var rangePct = ((cam.range - MIN_RANGE) / (MAX_RANGE - MIN_RANGE) * 100);
    h.push('<div class="gf-cp-slider-row">');
    h.push('<span class="gf-cp-slider-label">Range</span>');
    h.push('<input type="range" class="gf-cp-slider" data-range-idx="' + idx + '" min="' + MIN_RANGE + '" max="' + MAX_RANGE + '" step="0.5" value="' + cam.range + '" style="--pct:' + rangePct + '%"/>');
    h.push('<span class="gf-cp-slider-val">' + cam.range.toFixed(1) + 'm</span>');
    h.push('</div>');

    h.push('</div>');
    return h.join('');
  }

  function escHtml(s) {
    var d = document.createElement('div');
    d.textContent = s;
    return d.innerHTML;
  }

  function bindSidebarEvents() {
    var body = document.getElementById('gf-cp-side-body');
    if (!body) return;

    // Card selection
    var cards = body.querySelectorAll('.gf-cp-cam-card');
    for (var i = 0; i < cards.length; i++) {
      (function (card) {
        card.addEventListener('click', function (e) {
          // Don't select when interacting with controls
          if (e.target.tagName === 'INPUT' || e.target.tagName === 'BUTTON' ||
              e.target.closest('button') || e.target.closest('label')) return;
          var idx = parseInt(card.getAttribute('data-idx'));
          selectCamera(idx);
        });
      })(cards[i]);
    }

    // Name inputs
    var names = body.querySelectorAll('.gf-cp-cam-name');
    for (var n = 0; n < names.length; n++) {
      (function (input) {
        input.addEventListener('change', function () {
          var idx = parseInt(input.getAttribute('data-idx'));
          if (cameras[idx]) {
            cameras[idx].name = input.value || ('Camera ' + (idx + 1));
            saveToStorage();
            requestRender();
          }
        });
        input.addEventListener('focus', function () {
          input.select();
        });
      })(names[n]);
    }

    // Toggles
    var toggles = body.querySelectorAll('[data-toggle-idx]');
    for (var t = 0; t < toggles.length; t++) {
      (function (chk) {
        chk.addEventListener('change', function () {
          var idx = parseInt(chk.getAttribute('data-toggle-idx'));
          if (cameras[idx]) {
            cameras[idx].enabled = chk.checked;
            calcCoverage();
            saveToStorage();
            requestRender();
            renderSidebar();
          }
        });
      })(toggles[t]);
    }

    // Delete buttons
    var dels = body.querySelectorAll('[data-del-idx]');
    for (var d = 0; d < dels.length; d++) {
      (function (btn) {
        btn.addEventListener('click', function (e) {
          e.stopPropagation();
          var idx = parseInt(btn.getAttribute('data-del-idx'));
          removeCamera(idx);
        });
      })(dels[d]);
    }

    // FOV sliders
    var fovs = body.querySelectorAll('[data-fov-idx]');
    for (var fi = 0; fi < fovs.length; fi++) {
      (function (slider) {
        slider.addEventListener('input', function () {
          var idx = parseInt(slider.getAttribute('data-fov-idx'));
          if (cameras[idx]) {
            cameras[idx].fov = parseFloat(slider.value);
            slider.style.setProperty('--pct', ((cameras[idx].fov - 30) / 140 * 100) + '%');
            var valEl = slider.parentNode.querySelector('.gf-cp-slider-val');
            if (valEl) valEl.textContent = Math.round(cameras[idx].fov) + '\u00B0';
            calcCoverage();
            requestRender();
          }
        });
        slider.addEventListener('change', function () {
          saveToStorage();
          renderSidebar();
        });
      })(fovs[fi]);
    }

    // Range sliders
    var ranges = body.querySelectorAll('[data-range-idx]');
    for (var ri = 0; ri < ranges.length; ri++) {
      (function (slider) {
        slider.addEventListener('input', function () {
          var idx = parseInt(slider.getAttribute('data-range-idx'));
          if (cameras[idx]) {
            cameras[idx].range = parseFloat(slider.value);
            slider.style.setProperty('--pct', ((cameras[idx].range - MIN_RANGE) / (MAX_RANGE - MIN_RANGE) * 100) + '%');
            var valEl = slider.parentNode.querySelector('.gf-cp-slider-val');
            if (valEl) valEl.textContent = cameras[idx].range.toFixed(1) + 'm';
            calcCoverage();
            requestRender();
          }
        });
        slider.addEventListener('change', function () {
          saveToStorage();
          renderSidebar();
        });
      })(ranges[ri]);
    }

    // Add camera button
    var addBtn = document.getElementById('gf-cp-add-cam');
    if (addBtn) {
      addBtn.addEventListener('click', function () {
        addCameraAtCenter();
      });
    }

    // Auto-arrange button
    var autoBtn = document.getElementById('gf-cp-auto-arrange');
    if (autoBtn) {
      autoBtn.addEventListener('click', function () {
        autoArrange();
      });
    }
  }

  // ── Camera actions ───────────────────────────────────────

  function addCamera(x, z, angle) {
    if (cameras.length >= MAX_CAMERAS) {
      showToast('Maximum ' + MAX_CAMERAS + ' cameras');
      return;
    }
    var cam = createCamera(x, z, angle);
    cam.color = COLORS[cameras.length % COLORS.length];
    snapToPerimeter(cam);
    cameras.push(cam);
    selectedIdx = cameras.length - 1;
    calcCoverage();
    saveToStorage();
    renderSidebar();
    requestRender();
  }

  function addCameraAtCenter() {
    // Place at front of machine perimeter
    if (outline) {
      var frontZ = -Infinity;
      for (var i = 0; i < outline.length; i++) {
        if (outline[i][1] > frontZ) frontZ = outline[i][1];
      }
      addCamera(0, frontZ, 0);
    } else {
      addCamera(0, 4, 0);
    }
  }

  function removeCamera(idx) {
    if (idx < 0 || idx >= cameras.length) return;
    cameras.splice(idx, 1);
    // Recolor
    for (var i = 0; i < cameras.length; i++) {
      cameras[i].color = COLORS[i % COLORS.length];
    }
    if (selectedIdx >= cameras.length) selectedIdx = cameras.length - 1;
    if (selectedIdx < 0) selectedIdx = -1;
    calcCoverage();
    saveToStorage();
    renderSidebar();
    requestRender();
  }

  function selectCamera(idx) {
    selectedIdx = idx;
    renderSidebar();
    requestRender();
  }

  function autoArrangeInternal() {
    if (!outline) return;
    var n = cameras.length;
    if (n === 0) return;
    var perim = outlinePerimeter(outline);
    for (var i = 0; i < n; i++) {
      var d = (perim / n) * i;
      var pt = pointAlongOutline(outline, d);
      cameras[i].x = pt.x;
      cameras[i].z = pt.z;
      cameras[i].angle = Math.atan2(pt.nx, pt.nz) * 180 / Math.PI;
    }
  }

  function autoArrange() {
    autoArrangeInternal();
    calcCoverage();
    saveToStorage();
    renderSidebar();
    requestRender();
    showToast('Cameras auto-arranged');
  }

  // ── Hit testing ──────────────────────────────────────────

  function hitTestCamera(cx, cy) {
    var wx = c2wx(cx), wz = c2wz(cy);
    var threshold = CAM_RADIUS_M * 1.3;
    // Check in reverse order (last drawn = on top)
    for (var i = cameras.length - 1; i >= 0; i--) {
      if (dist(wx, wz, cameras[i].x, cameras[i].z) < threshold) {
        return { type: 'cam', idx: i };
      }
    }
    return null;
  }

  function hitTestHandle(cx, cy) {
    var wx = c2wx(cx), wz = c2wz(cy);
    var threshold = HANDLE_RADIUS_M * 1.5;
    for (var i = cameras.length - 1; i >= 0; i--) {
      var cam = cameras[i];
      var dirRad = cam.angle * Math.PI / 180;
      var hx = cam.x + Math.sin(dirRad) * HANDLE_DIST_M;
      var hz = cam.z + Math.cos(dirRad) * HANDLE_DIST_M;
      if (dist(wx, wz, hx, hz) < threshold) {
        return { type: 'rot', idx: i };
      }
    }
    return null;
  }

  // ── Pointer / touch event handling ───────────────────────

  function getPointerPos(e) {
    var rect = canvas.getBoundingClientRect();
    var ratio = canvas.width / rect.width;
    if (e.touches && e.touches.length > 0) {
      return { x: (e.touches[0].clientX - rect.left) * ratio, y: (e.touches[0].clientY - rect.top) * ratio };
    }
    return { x: (e.clientX - rect.left) * ratio, y: (e.clientY - rect.top) * ratio };
  }

  function getTouchDist(e) {
    if (!e.touches || e.touches.length < 2) return 0;
    var dx = e.touches[1].clientX - e.touches[0].clientX;
    var dy = e.touches[1].clientY - e.touches[0].clientY;
    return Math.sqrt(dx * dx + dy * dy);
  }

  function getTouchCenter(e) {
    if (!e.touches || e.touches.length < 2) return null;
    var rect = canvas.getBoundingClientRect();
    var ratio = canvas.width / rect.width;
    return {
      x: ((e.touches[0].clientX + e.touches[1].clientX) / 2 - rect.left) * ratio,
      y: ((e.touches[0].clientY + e.touches[1].clientY) / 2 - rect.top) * ratio
    };
  }

  function onPointerDown(e) {
    if (calActive) return;
    e.preventDefault();

    // Pinch-to-zoom start
    if (e.touches && e.touches.length >= 2) {
      pinchDist0 = getTouchDist(e);
      pinchScale0 = vs;
      pinchCenter = getTouchCenter(e);
      dragMode = 'pinch';
      return;
    }

    var pos = getPointerPos(e);
    pointerDown = true;
    pointerStart = { x: pos.x, y: pos.y };
    pointerMoved = false;

    if (measureActive) {
      mStart = { x: c2wx(pos.x), z: c2wz(pos.y) };
      mEnd = null;
      dragMode = 'measure';
      requestRender();
      return;
    }

    // Test hits
    var handleHit = hitTestHandle(pos.x, pos.y);
    if (handleHit) {
      dragMode = 'rot';
      dragIdx = handleHit.idx;
      selectCamera(dragIdx);
      return;
    }

    var camHit = hitTestCamera(pos.x, pos.y);
    if (camHit) {
      dragMode = 'cam';
      dragIdx = camHit.idx;
      selectCamera(dragIdx);
      return;
    }

    // Empty area — pan or deselect
    dragMode = 'pan';
    dragIdx = -1;
  }

  function onPointerMove(e) {
    if (!pointerDown && dragMode !== 'pinch' && dragMode !== 'new') return;
    e.preventDefault();

    // Pinch
    if (dragMode === 'pinch' && e.touches && e.touches.length >= 2) {
      var newDist = getTouchDist(e);
      var newCenter = getTouchCenter(e);
      if (pinchDist0 > 0 && newDist > 0) {
        var ratio = newDist / pinchDist0;
        var newScale = Math.max(MIN_SCALE, Math.min(MAX_SCALE, pinchScale0 * ratio));
        // Zoom towards pinch center
        if (pinchCenter && newCenter) {
          var wcx = c2wx(pinchCenter.x), wcz = c2wz(pinchCenter.y);
          vs = newScale;
          var newWcx = c2wx(pinchCenter.x), newWcz = c2wz(pinchCenter.y);
          vx += wcx - newWcx;
          vz += wcz - newWcz;
        } else {
          vs = newScale;
        }
        requestRender();
      }
      return;
    }

    var pos = getPointerPos(e);
    var dx = pos.x - pointerStart.x;
    var dy = pos.y - pointerStart.y;

    if (!pointerMoved && Math.sqrt(dx * dx + dy * dy) < TOUCH_SLOP_PX) return;
    pointerMoved = true;

    if (dragMode === 'new') {
      // Dragging new camera from toolbar
      if (cameras.length > 0) {
        var newCam = cameras[cameras.length - 1];
        newCam.x = c2wx(pos.x);
        newCam.z = c2wz(pos.y);
        snapToPerimeter(newCam);
        calcCoverage();
        requestRender();
        renderSidebar();
      }
      return;
    }

    if (dragMode === 'cam' && dragIdx >= 0 && dragIdx < cameras.length) {
      cameras[dragIdx].x = c2wx(pos.x);
      cameras[dragIdx].z = c2wz(pos.y);
      snapToPerimeter(cameras[dragIdx]);
      calcCoverage();
      requestRender();
      return;
    }

    if (dragMode === 'rot' && dragIdx >= 0 && dragIdx < cameras.length) {
      var cam = cameras[dragIdx];
      var worldX = c2wx(pos.x), worldZ = c2wz(pos.y);
      cam.angle = Math.atan2(worldX - cam.x, worldZ - cam.z) * 180 / Math.PI;
      calcCoverage();
      requestRender();
      return;
    }

    if (dragMode === 'measure') {
      mEnd = { x: c2wx(pos.x), z: c2wz(pos.y) };
      requestRender();
      return;
    }

    if (dragMode === 'pan') {
      vx -= dx / vs;
      vz += dy / vs;
      pointerStart = { x: pos.x, y: pos.y };
      requestRender();
      return;
    }
  }

  function onPointerUp(e) {
    if (dragMode === 'new') {
      // Finalize new camera placement
      if (cameras.length > 0) {
        snapToPerimeter(cameras[cameras.length - 1]);
        calcCoverage();
        saveToStorage();
        renderSidebar();
        requestRender();
      }
      dragMode = null;
      pointerDown = false;
      return;
    }

    if (dragMode === 'cam' || dragMode === 'rot') {
      saveToStorage();
      renderSidebar();
    }

    if (dragMode === 'pan' && !pointerMoved) {
      // Tap on empty space — deselect
      selectCamera(-1);
    }

    if (dragMode === 'measure' && mStart && mEnd) {
      // Keep the measure visible
    }

    dragMode = null;
    pointerDown = false;
    pointerMoved = false;
    pinchDist0 = 0;
    requestRender();
  }

  function onWheel(e) {
    e.preventDefault();
    var pos = getPointerPos(e);
    var wcx = c2wx(pos.x), wcz = c2wz(pos.y);
    var factor = e.deltaY > 0 ? 0.9 : 1.1;
    var newScale = Math.max(MIN_SCALE, Math.min(MAX_SCALE, vs * factor));
    vs = newScale;
    var newWcx = c2wx(pos.x), newWcz = c2wz(pos.y);
    vx += wcx - newWcx;
    vz += wcz - newWcz;
    requestRender();
  }

  // ── Drag from toolbar ────────────────────────────────────

  function onDragCamStart(e) {
    if (cameras.length >= MAX_CAMERAS) {
      showToast('Maximum ' + MAX_CAMERAS + ' cameras');
      return;
    }
    e.preventDefault();
    var pos = getPointerPos(e);
    var wx = c2wx(pos.x || canvasW() / 2);
    var wz = c2wz(pos.y || canvasH() / 2);
    addCamera(wx, wz, 0);
    dragMode = 'new';
    dragIdx = cameras.length - 1;
    pointerDown = true;
    pointerMoved = true;
  }

  function onDragCamStartFromToolbar(e) {
    if (cameras.length >= MAX_CAMERAS) {
      showToast('Maximum ' + MAX_CAMERAS + ' cameras');
      return;
    }
    e.preventDefault();

    // Create camera at canvas center
    var wx = c2wx(canvasW() / 2);
    var wz = c2wz(canvasH() / 2);

    // If touch event, use touch position
    if (e.touches && e.touches.length > 0) {
      var rect = canvas.getBoundingClientRect();
      var ratio = canvas.width / rect.width;
      var tx = (e.touches[0].clientX - rect.left) * ratio;
      var ty = (e.touches[0].clientY - rect.top) * ratio;
      wx = c2wx(tx);
      wz = c2wz(ty);
    }

    addCamera(wx, wz, 0);
    dragMode = 'new';
    dragIdx = cameras.length - 1;
    pointerDown = true;
    pointerMoved = true;
  }

  // ── Event binding ────────────────────────────────────────

  function bindEvents() {
    if (!canvas || !overlay) return;

    // Canvas pointer events
    canvas.addEventListener('mousedown', onPointerDown, { passive: false });
    canvas.addEventListener('mousemove', onPointerMove, { passive: false });
    canvas.addEventListener('mouseup', onPointerUp);
    canvas.addEventListener('mouseleave', onPointerUp);
    canvas.addEventListener('touchstart', onPointerDown, { passive: false });
    canvas.addEventListener('touchmove', onPointerMove, { passive: false });
    canvas.addEventListener('touchend', onPointerUp);
    canvas.addEventListener('touchcancel', onPointerUp);
    canvas.addEventListener('wheel', onWheel, { passive: false });

    // Drag from toolbar
    var dragSrc = document.getElementById('gf-cp-drag-cam');
    if (dragSrc) {
      dragSrc.addEventListener('mousedown', function (e) {
        onDragCamStartFromToolbar(e);
      });
      dragSrc.addEventListener('touchstart', function (e) {
        onDragCamStartFromToolbar(e);
      }, { passive: false });
    }

    // After drag starts on toolbar, canvas handles the move/up
    document.addEventListener('mousemove', function (e) {
      if (dragMode === 'new') onPointerMove(e);
    }, { passive: false });
    document.addEventListener('mouseup', function (e) {
      if (dragMode === 'new') onPointerUp(e);
    });
    document.addEventListener('touchmove', function (e) {
      if (dragMode === 'new') onPointerMove(e);
    }, { passive: false });
    document.addEventListener('touchend', function (e) {
      if (dragMode === 'new') onPointerUp(e);
    });

    // Header buttons
    document.getElementById('gf-cp-back').addEventListener('click', close);

    document.getElementById('gf-cp-btn-sidebar').addEventListener('click', function () {
      sidebarVisible = !sidebarVisible;
      sidebarEl.classList.toggle('hidden', !sidebarVisible);
      this.classList.toggle('active', sidebarVisible);
      setTimeout(resizeCanvas, 300);
    });

    document.getElementById('gf-cp-btn-measure').addEventListener('click', function () {
      measureActive = !measureActive;
      this.classList.toggle('active', measureActive);
      if (!measureActive) {
        mStart = null;
        mEnd = null;
        var readout = document.getElementById('gf-cp-measure-readout');
        if (readout) readout.style.display = 'none';
      }
      requestRender();
    });

    document.getElementById('gf-cp-btn-zoomin').addEventListener('click', function () {
      zoomBy(1.3);
    });

    document.getElementById('gf-cp-btn-zoomout').addEventListener('click', function () {
      zoomBy(0.7);
    });

    document.getElementById('gf-cp-btn-export').addEventListener('click', exportConfig);

    document.getElementById('gf-cp-btn-cal').addEventListener('click', function () {
      startCalibration();
    });

    // Resize
    window.addEventListener('resize', function () {
      if (isOpen) resizeCanvas();
    });
  }

  function zoomBy(factor) {
    vs = Math.max(MIN_SCALE, Math.min(MAX_SCALE, vs * factor));
    requestRender();
  }

  function resizeCanvas() {
    if (!canvas) return;
    var wrap = document.getElementById('gf-cp-canvas-wrap');
    if (!wrap) return;
    var dpr = 1; // Keep at 1 for performance on tablets
    canvas.width = wrap.clientWidth * dpr;
    canvas.height = wrap.clientHeight * dpr;
    requestRender();
  }

  // ── Calibration wizard ───────────────────────────────────

  function startCalibration() {
    if (cameras.length === 0) {
      showToast('Place cameras first');
      return;
    }
    calActive = true;
    calStep = 0;
    calResults = [];
    for (var i = 0; i < cameras.length; i++) {
      calResults.push({ idx: i, status: 'pending' });
    }
    showCalStep();
  }

  function showCalStep() {
    var calOverlay = document.getElementById('gf-cp-cal-overlay');
    if (!calOverlay) return;

    if (calStep >= cameras.length) {
      showCalSummary();
      return;
    }

    calOverlay.classList.add('open');
    var cam = cameras[calStep];

    // Title
    var title = document.getElementById('gf-cp-cal-title');
    title.textContent = 'Calibrating: ' + cam.name;
    title.style.color = cam.color;

    // Subtitle
    var sub = document.getElementById('gf-cp-cal-sub');
    sub.textContent = 'Step ' + (calStep + 1) + ' of ' + cameras.length;

    // Draw mini-map
    drawCalMiniMap(cam);

    // Instruction
    var instr = document.getElementById('gf-cp-cal-instruction');
    instr.innerHTML = 'Place a person <strong style="color:' + ACCENT + '">3 meters</strong> in front of ' + escHtml(cam.name) + '.<br/>Verify the system detects them.';

    // Buttons
    var btns = document.getElementById('gf-cp-cal-buttons');
    btns.innerHTML = [
      '<button class="gf-cp-cal-fail" id="gf-cp-cal-notdet">Not Detected</button>',
      '<button class="gf-cp-cal-pass" id="gf-cp-cal-det">Detection Confirmed</button>'
    ].join('');

    document.getElementById('gf-cp-cal-det').addEventListener('click', function () {
      calResults[calStep].status = 'pass';
      calStep++;
      showCalStep();
    });
    document.getElementById('gf-cp-cal-notdet').addEventListener('click', function () {
      calResults[calStep].status = 'fail';
      calStep++;
      showCalStep();
    });
  }

  function drawCalMiniMap(cam) {
    var calCanvas = document.getElementById('gf-cp-cal-canvas');
    if (!calCanvas) return;
    var cctx = calCanvas.getContext('2d');
    var cw = calCanvas.width = calCanvas.clientWidth;
    var ch = calCanvas.height = calCanvas.clientHeight || 200;
    cctx.clearRect(0, 0, cw, ch);
    cctx.fillStyle = '#0F0F0F';
    cctx.fillRect(0, 0, cw, ch);

    // Scale to fit machine + 5m padding
    var scale = Math.min(cw, ch) / 18;
    var cx = cw / 2, cy = ch / 2;

    // Draw machine
    if (outline && outline.length > 2) {
      cctx.beginPath();
      cctx.moveTo(cx + outline[0][0] * scale, cy - outline[0][1] * scale);
      for (var i = 1; i < outline.length; i++) {
        cctx.lineTo(cx + outline[i][0] * scale, cy - outline[i][1] * scale);
      }
      cctx.closePath();
      cctx.fillStyle = MACHINE_FILL;
      cctx.fill();
      cctx.strokeStyle = MACHINE_STROKE;
      cctx.lineWidth = 1;
      cctx.stroke();
    }

    // Highlight this camera
    var camCx = cx + cam.x * scale;
    var camCy = cy - cam.z * scale;
    cctx.beginPath();
    cctx.arc(camCx, camCy, 6, 0, Math.PI * 2);
    cctx.fillStyle = cam.color;
    cctx.fill();
    cctx.strokeStyle = '#fff';
    cctx.lineWidth = 2;
    cctx.stroke();

    // Draw other cameras dimmed
    for (var j = 0; j < cameras.length; j++) {
      if (j === calStep) continue;
      var oc = cameras[j];
      cctx.beginPath();
      cctx.arc(cx + oc.x * scale, cy - oc.z * scale, 4, 0, Math.PI * 2);
      cctx.fillStyle = '#444';
      cctx.fill();
    }

    // Draw 3m test point
    var dirRad = cam.angle * Math.PI / 180;
    var testX = cam.x + Math.sin(dirRad) * 3;
    var testZ = cam.z + Math.cos(dirRad) * 3;
    var testCx = cx + testX * scale;
    var testCy = cy - testZ * scale;

    // Line from camera to test point
    cctx.strokeStyle = hexToRgba(cam.color, 0.5);
    cctx.lineWidth = 1;
    cctx.setLineDash([4, 3]);
    cctx.beginPath();
    cctx.moveTo(camCx, camCy);
    cctx.lineTo(testCx, testCy);
    cctx.stroke();
    cctx.setLineDash([]);

    // Test point
    cctx.beginPath();
    cctx.arc(testCx, testCy, 8, 0, Math.PI * 2);
    cctx.fillStyle = hexToRgba(ACCENT, 0.3);
    cctx.fill();
    cctx.strokeStyle = ACCENT;
    cctx.lineWidth = 2;
    cctx.stroke();

    // Label
    cctx.fillStyle = ACCENT;
    cctx.font = '600 11px system-ui,-apple-system,sans-serif';
    cctx.textAlign = 'center';
    cctx.textBaseline = 'bottom';
    cctx.fillText('3m', testCx, testCy - 12);

    // Person icon at test point
    cctx.fillStyle = '#fff';
    cctx.font = '600 10px system-ui';
    cctx.textBaseline = 'middle';
    cctx.fillText('P', testCx, testCy);
  }

  function showCalSummary() {
    var calOverlay = document.getElementById('gf-cp-cal-overlay');
    if (!calOverlay) return;

    var passed = 0, failed = 0;
    for (var i = 0; i < calResults.length; i++) {
      if (calResults[i].status === 'pass') passed++;
      if (calResults[i].status === 'fail') failed++;
    }

    var title = document.getElementById('gf-cp-cal-title');
    title.textContent = 'Calibration Complete';
    title.style.color = TXT_PRI;

    var sub = document.getElementById('gf-cp-cal-sub');
    sub.textContent = passed + ' passed, ' + failed + ' failed';

    // Hide mini-map
    var calCanvas = document.getElementById('gf-cp-cal-canvas');
    if (calCanvas) calCanvas.style.display = 'none';

    // Results list
    var instr = document.getElementById('gf-cp-cal-instruction');
    var html = [];
    for (var r = 0; r < calResults.length; r++) {
      var cam = cameras[r];
      var res = calResults[r];
      var statusIcon = res.status === 'pass' ? '<span class="pass">' + icon('check', 16) + '</span>'
                     : res.status === 'fail' ? '<span class="fail">' + icon('alertTriangle', 16) + '</span>'
                     : '<span class="skip">--</span>';
      html.push('<div class="gf-cp-cal-result">');
      html.push('<div class="gf-cp-cal-result-icon">' + statusIcon + '</div>');
      html.push('<div style="flex:1;font-size:14px;font-weight:600">' + escHtml(cam.name) + '</div>');
      html.push('<div style="font-size:12px;color:' + (res.status === 'pass' ? SUCCESS : res.status === 'fail' ? DANGER : TXT_DIM) + '">' + res.status.toUpperCase() + '</div>');
      html.push('</div>');
    }
    instr.innerHTML = html.join('');

    // Buttons
    var btns = document.getElementById('gf-cp-cal-buttons');
    var retryHtml = '';
    if (failed > 0) {
      retryHtml = '<button class="gf-cp-cal-skip" id="gf-cp-cal-retry">Retry Failed</button>';
    }
    btns.innerHTML = retryHtml + '<button class="gf-cp-cal-pass" id="gf-cp-cal-done">Done</button>';

    document.getElementById('gf-cp-cal-done').addEventListener('click', function () {
      endCalibration();
    });

    if (failed > 0) {
      document.getElementById('gf-cp-cal-retry').addEventListener('click', function () {
        // Reset failed cameras and restart
        calStep = 0;
        for (var i = 0; i < calResults.length; i++) {
          if (calResults[i].status === 'fail') calResults[i].status = 'pending';
        }
        // Find first pending
        while (calStep < calResults.length && calResults[calStep].status !== 'pending') calStep++;
        var calCanv = document.getElementById('gf-cp-cal-canvas');
        if (calCanv) calCanv.style.display = '';
        showCalStep();
      });
    }
  }

  function endCalibration() {
    calActive = false;
    var calOverlay = document.getElementById('gf-cp-cal-overlay');
    if (calOverlay) calOverlay.classList.remove('open');
    var calCanvas = document.getElementById('gf-cp-cal-canvas');
    if (calCanvas) calCanvas.style.display = '';
    requestRender();
  }

  // ── Public API ───────────────────────────────────────────

  function open() {
    buildDOM();

    // Load current config
    if (GF.config) {
      machineType = GF.config.get('machine_type') || 'wheel_loader';
    }
    outline = SILHOUETTES[machineType] || SILHOUETTES.wheel_loader;

    loadFromStorage();

    // If no cameras, create default 4 from machine profile or auto-arrange
    if (cameras.length === 0) {
      var mounted = false;
      // Try machine profiles from config
      var profiles = null;
      if (GF.config && typeof GF.config.getMachineProfiles === 'function') {
        profiles = GF.config.getMachineProfiles();
      }
      var profile = profiles ? profiles[machineType] : null;
      if (profile && profile.camera_mounts) {
        for (var i = 0; i < profile.camera_mounts.length; i++) {
          var m = profile.camera_mounts[i];
          var cam = createCamera(m.position[0], m.position[2], m.rotation[1]);
          cam.name = m.label;
          cam.color = COLORS[i % COLORS.length];
          cam.mountHeight = m.position[1];
          cameras.push(cam);
        }
        mounted = true;
      }
      // Fallback: create 4 cameras auto-arranged around perimeter
      if (!mounted && outline) {
        var defaultNames = ['Front', 'Rear', 'Left', 'Right'];
        for (var d = 0; d < 4; d++) {
          var c = createCamera(0, 0, 0);
          c.name = defaultNames[d];
          c.color = COLORS[d];
          cameras.push(c);
        }
        autoArrangeInternal();
      }
      if (cameras.length > 0) saveToStorage();
    }

    // Reset view
    vx = 0; vz = 0;
    vs = 30;
    selectedIdx = -1;
    measureActive = false;
    mStart = null;
    mEnd = null;

    isOpen = true;
    overlay.classList.add('open');

    // Re-acquire canvas after overlay is visible
    acquireCanvas();
    resizeCanvas();

    // Fit view to show machine + cameras
    fitView();

    calcCoverage();
    renderSidebar();
    startLoop();
    requestRender();
  }

  function close() {
    isOpen = false;
    if (overlay) overlay.classList.remove('open');
    if (rafId) { clearTimeout(rafId); rafId = null; }
    endCalibration();
  }

  function fitView() {
    // Find bounding box of machine + all cameras
    var minX = Infinity, maxX = -Infinity;
    var minZ = Infinity, maxZ = -Infinity;
    if (outline) {
      for (var i = 0; i < outline.length; i++) {
        if (outline[i][0] < minX) minX = outline[i][0];
        if (outline[i][0] > maxX) maxX = outline[i][0];
        if (outline[i][1] < minZ) minZ = outline[i][1];
        if (outline[i][1] > maxZ) maxZ = outline[i][1];
      }
    }
    for (var c = 0; c < cameras.length; c++) {
      var cam = cameras[c];
      var r = cam.range;
      if (cam.x - r < minX) minX = cam.x - r;
      if (cam.x + r > maxX) maxX = cam.x + r;
      if (cam.z - r < minZ) minZ = cam.z - r;
      if (cam.z + r > maxZ) maxZ = cam.z + r;
    }
    if (!isFinite(minX)) { minX = -10; maxX = 10; minZ = -10; maxZ = 10; }

    var pad = 3;
    var rangeX = (maxX - minX) + pad * 2;
    var rangeZ = (maxZ - minZ) + pad * 2;
    vx = (minX + maxX) / 2;
    vz = (minZ + maxZ) / 2;

    var cw = canvasW() || 800;
    var ch = canvasH() || 600;
    vs = Math.min(cw / rangeX, ch / rangeZ);
    vs = Math.max(MIN_SCALE, Math.min(MAX_SCALE, vs));
  }

  // ── Return public interface ──────────────────────────────
  return {
    open: open,
    close: close
  };
})();
