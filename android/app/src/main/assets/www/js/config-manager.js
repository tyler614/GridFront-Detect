/* ═══════════════════════════════════════════════════════════
   GridFront Detect — Config Manager
   Local config layer using localStorage. Intercepts GF.api
   calls so the app works fully offline without Flask.

   Intercepts all /api/* calls that match local patterns and
   handles them synchronously from localStorage. Falls through
   to the real fetch for any URL that doesn't match (e.g. when
   Flask IS reachable on the tablet).

   Registers as GF.config and wraps GF.api.{get,post,patch,del}.
   ═══════════════════════════════════════════════════════════ */

(function() {
  'use strict';

  window.GF = window.GF || {};

  // ── Storage keys ──────────────────────────────────────────
  var KEY_CONFIG    = 'gf_config';
  var KEY_CAMERAS   = 'gf_cameras';
  var KEY_DETECTION = 'gf_detection_config';

  // ── Embedded machine profiles (from machine_profiles.py) ──
  var MACHINE_PROFILES = {
    wheel_loader: {
      type:    'wheel_loader',
      name:    'Wheel Loader',
      example: 'CAT 950 GC',
      dimensions: { length_m: 8.4, width_m: 2.5, height_m: 3.4 },
      default_zones: { danger_m: 3.5, warning_m: 6.0, max_range_m: 12.0 },
      camera_mounts: [
        { id: 'front', label: 'Front', position: [0, 2.8,  4.2], rotation: [0,   0, 0] },
        { id: 'rear',  label: 'Rear',  position: [0, 2.5, -4.2], rotation: [0, 180, 0] },
        { id: 'left',  label: 'Left',  position: [-1.25, 2.8, 0], rotation: [0, -90, 0] },
        { id: 'right', label: 'Right', position: [ 1.25, 2.8, 0], rotation: [0,  90, 0] }
      ],
      camera_spec: { hfov_deg: 127, depth_hfov_deg: 73, vfov_deg: 58, max_depth_m: 15 }
    },
    excavator: {
      type:    'excavator',
      name:    'Excavator',
      example: 'CAT 320',
      dimensions: { length_m: 9.5, width_m: 2.9, height_m: 3.0 },
      default_zones: { danger_m: 4.0, warning_m: 7.0, max_range_m: 12.0 },
      camera_mounts: [
        { id: 'front', label: 'Front', position: [0, 2.8,  1.5], rotation: [0,   0, 0] },
        { id: 'rear',  label: 'Rear',  position: [0, 2.5, -1.5], rotation: [0, 180, 0] },
        { id: 'left',  label: 'Left',  position: [-1.45, 2.8, 0], rotation: [0, -90, 0] },
        { id: 'right', label: 'Right', position: [ 1.45, 2.8, 0], rotation: [0,  90, 0] }
      ],
      camera_spec: { hfov_deg: 127, depth_hfov_deg: 73, vfov_deg: 58, max_depth_m: 15 }
    },
    dozer: {
      type:    'dozer',
      name:    'Dozer',
      example: 'CAT D6',
      dimensions: { length_m: 4.7, width_m: 2.7, height_m: 3.1 },
      default_zones: { danger_m: 3.0, warning_m: 5.5, max_range_m: 10.0 },
      camera_mounts: [
        { id: 'front', label: 'Front', position: [0, 2.8,  2.35], rotation: [0,   0, 0] },
        { id: 'rear',  label: 'Rear',  position: [0, 2.5, -2.35], rotation: [0, 180, 0] },
        { id: 'left',  label: 'Left',  position: [-1.35, 2.8, 0], rotation: [0, -90, 0] },
        { id: 'right', label: 'Right', position: [ 1.35, 2.8, 0], rotation: [0,  90, 0] }
      ],
      camera_spec: { hfov_deg: 127, depth_hfov_deg: 73, vfov_deg: 58, max_depth_m: 15 }
    },
    dump_truck: {
      type:    'dump_truck',
      name:    'Dump Truck',
      example: 'CAT 740',
      dimensions: { length_m: 10.6, width_m: 3.5, height_m: 3.7 },
      default_zones: { danger_m: 4.5, warning_m: 8.0, max_range_m: 15.0 },
      camera_mounts: [
        { id: 'front', label: 'Front', position: [0, 3.2,  5.3], rotation: [0,   0, 0] },
        { id: 'rear',  label: 'Rear',  position: [0, 2.8, -5.3], rotation: [0, 180, 0] },
        { id: 'left',  label: 'Left',  position: [-1.75, 3.0, 0], rotation: [0, -90, 0] },
        { id: 'right', label: 'Right', position: [ 1.75, 3.0, 0], rotation: [0,  90, 0] }
      ],
      camera_spec: { hfov_deg: 127, depth_hfov_deg: 73, vfov_deg: 58, max_depth_m: 15 }
    }
  };

  // ── Default detection classes ──────────────────────────────
  var DEFAULT_DETECTION_CONFIG = {
    classes: [
      { id: 'person',     label: 'Person',       icon: '\uD83D\uDEB6', priority: 1, enabled: true  },
      { id: 'vehicle',    label: 'Vehicle',      icon: '\uD83D\uDE97', priority: 2, enabled: true  },
      { id: 'excavator',  label: 'Excavator',    icon: '\uD83C\uDFD7\uFE0F', priority: 3, enabled: true  },
      { id: 'dump_truck', label: 'Dump Truck',   icon: '\uD83D\uDE9B', priority: 3, enabled: true  },
      { id: 'dozer',      label: 'Dozer',        icon: '\uD83D\uDE9C', priority: 3, enabled: true  },
      { id: 'forklift',   label: 'Forklift',     icon: '\uD83C\uDFED', priority: 4, enabled: true  },
      { id: 'cyclist',    label: 'Cyclist',      icon: '\uD83D\uDEB4', priority: 4, enabled: true  },
      { id: 'cone',       label: 'Traffic Cone', icon: '\uD83D\uDD36', priority: 5, enabled: true  }
    ]
  };

  // ── Default config ─────────────────────────────────────────
  var DEFAULT_CONFIG = {
    machine_name: 'Wheel Loader #1',
    machine_type: 'wheel_loader',
    zones: {
      danger_m:    3.5,
      warning_m:   6.0,
      max_range_m: 12.0
    },
    alerts: {
      sound_enabled: true,
      vibration_enabled: true
    },
    display: {
      show_labels:   true,
      show_zones:    true,
      show_grid:     false,
      dark_mode:     false
    }
  };

  // ── Helpers ────────────────────────────────────────────────
  function readJson(key, fallback) {
    try {
      var raw = localStorage.getItem(key);
      if (raw === null) return fallback;
      return JSON.parse(raw);
    } catch (e) {
      console.warn('GF.config: failed to parse', key, e);
      return fallback;
    }
  }

  function writeJson(key, value) {
    try {
      localStorage.setItem(key, JSON.stringify(value));
      return true;
    } catch (e) {
      console.warn('GF.config: failed to write', key, e);
      return false;
    }
  }

  function deepMerge(base, overlay) {
    var result = {};
    var k;
    for (k in base) {
      if (Object.prototype.hasOwnProperty.call(base, k)) {
        result[k] = base[k];
      }
    }
    for (k in overlay) {
      if (Object.prototype.hasOwnProperty.call(overlay, k)) {
        var v = overlay[k];
        if (v !== null && typeof v === 'object' && !Array.isArray(v) &&
            typeof result[k] === 'object' && result[k] !== null && !Array.isArray(result[k])) {
          result[k] = deepMerge(result[k], v);
        } else {
          result[k] = v;
        }
      }
    }
    return result;
  }

  function resolved(value) {
    return new Promise(function(resolve) { resolve(value); });
  }

  function genId() {
    return 'cam_' + Date.now() + '_' + Math.floor(Math.random() * 10000);
  }

  function fireConfigChanged(detail) {
    try {
      var evt = new CustomEvent('gf-config-changed', { detail: detail || {} });
      window.dispatchEvent(evt);
    } catch (e) {
      // IE fallback
      var ie = document.createEvent('CustomEvent');
      ie.initCustomEvent('gf-config-changed', true, false, detail || {});
      window.dispatchEvent(ie);
    }
  }

  // ── Local store read/write helpers ─────────────────────────
  function getConfig() {
    return readJson(KEY_CONFIG, DEFAULT_CONFIG);
  }

  function saveConfig(cfg) {
    writeJson(KEY_CONFIG, cfg);
  }

  function getCameras() {
    return readJson(KEY_CAMERAS, []);
  }

  function saveCameras(cameras) {
    writeJson(KEY_CAMERAS, cameras);
  }

  function getDetectionConfig() {
    return readJson(KEY_DETECTION, DEFAULT_DETECTION_CONFIG);
  }

  function saveDetectionConfig(cfg) {
    writeJson(KEY_DETECTION, cfg);
  }

  // ── Route matching ─────────────────────────────────────────
  // Returns a match object { handler, params } or null.
  function matchRoute(method, path) {
    // Strip query string for matching
    var cleanPath = path.split('?')[0];

    var routes = [
      // Config
      { method: 'GET',    pattern: /^\/api\/config$/,            handler: handleGetConfig },
      { method: 'POST',   pattern: /^\/api\/config$/,            handler: handlePostConfig },
      // Cameras
      { method: 'GET',    pattern: /^\/api\/cameras$/,           handler: handleGetCameras },
      { method: 'POST',   pattern: /^\/api\/cameras$/,           handler: handlePostCamera },
      { method: 'GET',    pattern: /^\/api\/cameras\/([^/]+)\/status$/, handler: handleGetCameraStatus },
      { method: 'PATCH',  pattern: /^\/api\/cameras\/([^/]+)$/, handler: handlePatchCamera },
      { method: 'DELETE', pattern: /^\/api\/cameras\/([^/]+)$/, handler: handleDeleteCamera },
      // Machines
      { method: 'GET',    pattern: /^\/api\/machines$/,          handler: handleGetMachines },
      { method: 'POST',   pattern: /^\/api\/machines\/([^/]+)\/activate$/, handler: handleActivateMachine },
      // Detection
      { method: 'GET',    pattern: /^\/api\/detection\/config$/, handler: handleGetDetectionConfig },
      { method: 'POST',   pattern: /^\/api\/detection\/config$/, handler: handlePostDetectionConfig },
      // System
      { method: 'GET',    pattern: /^\/api\/system\/health$/,    handler: handleGetHealth }
      // NOTE: /api/spatial is NOT intercepted — let detection-renderer's
      // mock fallback handle it when Flask is unavailable
    ];

    var upperMethod = method.toUpperCase();
    for (var i = 0; i < routes.length; i++) {
      var route = routes[i];
      if (route.method !== upperMethod) continue;
      var m = cleanPath.match(route.pattern);
      if (m) {
        return { handler: route.handler, params: m.slice(1) };
      }
    }
    return null;
  }

  // ── Route handlers ─────────────────────────────────────────
  function handleGetConfig() {
    return resolved(getConfig());
  }

  function handlePostConfig(data) {
    var current = getConfig();
    var updated = deepMerge(current, data || {});
    saveConfig(updated);
    fireConfigChanged({ type: 'config', config: updated });
    return resolved(updated);
  }

  function handleGetCameras() {
    return resolved(getCameras());
  }

  function handlePostCamera(data) {
    var cameras = getCameras();
    var cam = deepMerge(data || {}, {});
    cam.id = cam.id || genId();
    cam.connected = false;
    cameras.push(cam);
    saveCameras(cameras);
    fireConfigChanged({ type: 'cameras', cameras: cameras });
    return resolved(cam);
  }

  function handleGetCameraStatus(data, params) {
    var id = params[0];
    var cameras = getCameras();
    for (var i = 0; i < cameras.length; i++) {
      if (cameras[i].id === id) {
        return resolved({ id: id, connected: cameras[i].connected || false, status: 'offline' });
      }
    }
    return resolved({ id: id, connected: false, status: 'not_found' });
  }

  function handlePatchCamera(data, params) {
    var id = params[0];
    var cameras = getCameras();
    var found = null;
    for (var i = 0; i < cameras.length; i++) {
      if (cameras[i].id === id) {
        cameras[i] = deepMerge(cameras[i], data || {});
        found = cameras[i];
        break;
      }
    }
    if (!found) {
      // Camera not found — create it
      var cam = deepMerge(data || {}, {});
      cam.id = id;
      cam.connected = false;
      cameras.push(cam);
      found = cam;
    }
    saveCameras(cameras);
    fireConfigChanged({ type: 'cameras', cameras: cameras });
    return resolved(found);
  }

  function handleDeleteCamera(data, params) {
    var id = params[0];
    var cameras = getCameras();
    var filtered = [];
    for (var i = 0; i < cameras.length; i++) {
      if (cameras[i].id !== id) filtered.push(cameras[i]);
    }
    saveCameras(filtered);
    fireConfigChanged({ type: 'cameras', cameras: filtered });
    return resolved({ deleted: id });
  }

  function handleGetMachines() {
    var cfg = getConfig();
    var active = cfg.machine_type || 'wheel_loader';
    var profiles = [];
    var keys = Object.keys(MACHINE_PROFILES);
    for (var i = 0; i < keys.length; i++) {
      profiles.push(MACHINE_PROFILES[keys[i]]);
    }
    return resolved({ active: active, profiles: profiles });
  }

  function handleActivateMachine(data, params) {
    var type = params[0];
    var profile = MACHINE_PROFILES[type];
    if (!profile) {
      return new Promise(function(resolve, reject) {
        reject(new Error('Unknown machine type: ' + type));
      });
    }

    var cfg = getConfig();
    cfg.machine_type = type;
    // Apply default zones for this machine type
    cfg.zones = {
      danger_m:    profile.default_zones.danger_m,
      warning_m:   profile.default_zones.warning_m,
      max_range_m: profile.default_zones.max_range_m
    };
    saveConfig(cfg);
    fireConfigChanged({ type: 'machine', machine_type: type, zones: cfg.zones, config: cfg });
    return resolved({ active: type, zones: cfg.zones, profile: profile });
  }

  function handleGetDetectionConfig() {
    return resolved(getDetectionConfig());
  }

  function handlePostDetectionConfig(data) {
    var current = getDetectionConfig();
    // data may be an object of { classId: { enabled: bool } } patches,
    // or a full replacement with a .classes array
    if (data && Array.isArray(data.classes)) {
      // Full replacement
      saveDetectionConfig(data);
      return resolved(data);
    }
    // Partial update: { classId: { enabled: bool } }
    if (data && current.classes) {
      for (var i = 0; i < current.classes.length; i++) {
        var cls = current.classes[i];
        if (data[cls.id]) {
          var patch = data[cls.id];
          if (typeof patch.enabled !== 'undefined') cls.enabled = patch.enabled;
          if (typeof patch.priority !== 'undefined') cls.priority = patch.priority;
        }
      }
    }
    saveDetectionConfig(current);
    return resolved(current);
  }

  function handleGetHealth() {
    return resolved({
      status:     'ok',
      source:     'local',
      flask:      false,
      timestamp:  new Date().toISOString(),
      version:    '1.0.0-local'
    });
  }

  function handleGetSpatial() {
    // Return empty live state — detection-renderer uses mock internally
    return resolved({
      detections: [],
      summary:    { people: 0, equipment: 0, markers: 0 },
      fps:        0,
      source:     'local'
    });
  }

  // ── API interceptor ────────────────────────────────────────
  // Wrap each GF.api method. If the path matches a local route,
  // handle it locally (no network). Otherwise fall through to
  // the original fetch-based implementation.

  if (GF.api) {
    var _origGet  = GF.api.get.bind(GF.api);
    var _origPost = GF.api.post.bind(GF.api);
    var _origPatch = GF.api.patch.bind(GF.api);
    var _origDel  = GF.api.del.bind(GF.api);

    GF.api.get = function(path) {
      var route = matchRoute('GET', path);
      if (route) {
        return route.handler(null, route.params);
      }
      return _origGet(path);
    };

    GF.api.post = function(path, data) {
      var route = matchRoute('POST', path);
      if (route) {
        return route.handler(data, route.params);
      }
      return _origPost(path, data);
    };

    GF.api.patch = function(path, data) {
      var route = matchRoute('PATCH', path);
      if (route) {
        return route.handler(data, route.params);
      }
      return _origPatch(path, data);
    };

    GF.api.del = function(path) {
      var route = matchRoute('DELETE', path);
      if (route) {
        return route.handler(null, route.params);
      }
      return _origDel(path);
    };

    // Override checkConnection to use local health check
    GF.api.checkConnection = function() {
      GF.api._connected = true;
      return resolved(true);
    };

    console.log('GF.config: API interceptor installed');
  } else {
    console.warn('GF.config: GF.api not found — interceptor not installed');
  }

  // ── Zone config change listener ────────────────────────────
  // When machine changes, push updated zones to zone-renderer
  window.addEventListener('gf-config-changed', function(evt) {
    var detail = evt.detail || {};
    if ((detail.type === 'config' || detail.type === 'machine') && detail.zones) {
      if (GF.zones && typeof GF.zones.setConfig === 'function') {
        GF.zones.setConfig(detail.zones);
      }
    }
  });

  // ── Public GF.config API ───────────────────────────────────
  GF.config = {

    get: function(key) {
      var cfg = getConfig();
      if (key === undefined) return cfg;
      // Support dot notation: 'zones.danger_m'
      var parts = key.split('.');
      var val = cfg;
      for (var i = 0; i < parts.length; i++) {
        if (val === null || typeof val !== 'object') return undefined;
        val = val[parts[i]];
      }
      return val;
    },

    set: function(key, value) {
      var cfg = getConfig();
      // Support dot notation
      var parts = key.split('.');
      if (parts.length === 1) {
        cfg[key] = value;
      } else {
        var obj = cfg;
        for (var i = 0; i < parts.length - 1; i++) {
          if (typeof obj[parts[i]] !== 'object' || obj[parts[i]] === null) {
            obj[parts[i]] = {};
          }
          obj = obj[parts[i]];
        }
        obj[parts[parts.length - 1]] = value;
      }
      saveConfig(cfg);
      fireConfigChanged({ type: 'set', key: key, value: value, config: cfg });
      return cfg;
    },

    getAll: function() {
      return getConfig();
    },

    getMachineProfiles: function() {
      return MACHINE_PROFILES;
    },

    getCameras: function() {
      return getCameras();
    },

    getDetectionConfig: function() {
      return getDetectionConfig();
    },

    // Reset everything back to factory defaults (useful for testing)
    reset: function() {
      localStorage.removeItem(KEY_CONFIG);
      localStorage.removeItem(KEY_CAMERAS);
      localStorage.removeItem(KEY_DETECTION);
      fireConfigChanged({ type: 'reset' });
      console.log('GF.config: reset to defaults');
    }
  };

  console.log('GF.config: ready (machine=' + getConfig().machine_type + ')');

})();
