/* ═══════════════════════════════════════════════════════════
   GridFront Detect — Detection Renderer
   Live data integration: SSE → polling → mock fallback
   Mock mode simulates realistic OAK-D spatial pipeline output.
   Depends on: scene-manager.js, model-registry.js, api-client.js
   ═══════════════════════════════════════════════════════════ */
window.GF = window.GF || {};

GF.detection = (function() {
  var scene = GF.scene.scene;
  var camera = GF.scene.camera;
  var container = GF.scene.container;

  // ── State ──────────────────────────────────────────────
  var MODE_SSE = 'SSE';
  var MODE_POLL = 'Polling';
  var MODE_MOCK = 'Sim';

  var mode = MODE_MOCK;
  var sseSource = null;
  var pollTimer = null;
  var lastDataTime = 0;
  var mockFallbackDelay = 3000;
  var connectionAttempted = false;

  var tracks = {};
  var liveDetections = null;
  var liveSummary = null;
  var liveFps = 0;

  // ── Label overlay ──────────────────────────────────────
  var labelsOverlay = document.createElement('div');
  labelsOverlay.id = 'labels-overlay';
  labelsOverlay.style.cssText = 'position:absolute;top:0;left:0;width:100%;height:100%;pointer-events:none;overflow:hidden;z-index:5;';
  container.style.position = 'relative';
  container.appendChild(labelsOverlay);

  // ═════════════════════════════════════════════════════════
  // REALISTIC CONSTRUCTION SITE SIMULATION
  // Mimics OAK-D Pro W PoE spatial detection pipeline:
  // - 4 cameras (front/rear/left/right) with 73° depth HFOV
  // - Track IDs, confidence, bearing, camera attribution
  // - Depth estimation noise (±0.05–0.15m)
  // - Workers with realistic behaviors (approach, work, walk away)
  // - Vehicles on site roads
  // - PPE detection (hardhat, vest)
  // - Objects appear/disappear as they enter/leave FOVs
  // ═════════════════════════════════════════════════════════

  // Zone thresholds (updated from config)
  var simZones = { danger_m: 3.5, warning_m: 6.0, max_range_m: 12.0 };
  if (GF.config && GF.config.getAll) {
    var cfg = GF.config.getAll();
    if (cfg && cfg.zones) {
      simZones.danger_m = cfg.zones.danger_m || 3.5;
      simZones.warning_m = cfg.zones.warning_m || 6.0;
      simZones.max_range_m = cfg.zones.max_range_m || 12.0;
    }
  }
  // Listen for config changes
  window.addEventListener('gf-config-changed', function() {
    if (GF.config && GF.config.getAll) {
      var c = GF.config.getAll();
      if (c && c.zones) {
        simZones.danger_m = c.zones.danger_m || 3.5;
        simZones.warning_m = c.zones.warning_m || 6.0;
        simZones.max_range_m = c.zones.max_range_m || 12.0;
      }
    }
  });

  // ── Pseudo-random with seed ────────────────────────────
  var _seed = 42;
  function srand(s) { _seed = s; }
  function rand() { _seed = (_seed * 16807 + 0) % 2147483647; return (_seed - 1) / 2147483646; }
  function randRange(a, b) { return a + rand() * (b - a); }
  function gaussNoise() {
    var u = 1 - rand(), v = rand();
    return Math.sqrt(-2 * Math.log(u)) * Math.cos(2 * Math.PI * v);
  }

  // ── Camera model (4 OAK-D Pro W) ──────────────────────
  var CAMERAS = [
    { id: 'cam-front', angle: 0,           hfov: 73 },
    { id: 'cam-rear',  angle: Math.PI,     hfov: 73 },
    { id: 'cam-left',  angle: -Math.PI/2,  hfov: 73 },
    { id: 'cam-right', angle: Math.PI/2,   hfov: 73 }
  ];

  function getCameraForPoint(x, z) {
    var bearing = Math.atan2(x, z);
    var best = null, bestDiff = Infinity;
    for (var i = 0; i < CAMERAS.length; i++) {
      var diff = Math.abs(bearing - CAMERAS[i].angle);
      if (diff > Math.PI) diff = 2 * Math.PI - diff;
      var halfFov = (CAMERAS[i].hfov / 2) * Math.PI / 180;
      if (diff < halfFov && diff < bestDiff) {
        bestDiff = diff;
        best = CAMERAS[i];
      }
    }
    return best;
  }

  // ── Simulated actors ───────────────────────────────────
  var nextTrackId = 100;
  var simActors = [];
  var simMeshes = {};
  var simSmoothing = {};
  var simInitialized = false;
  var simFps = 0;
  var simFrameCount = 0;
  var simFpsTimer = 0;
  var simLastUpdate = 0;

  // Waypoint-based movement: actors walk between waypoints
  function makeWaypoints(points, speed, loop) {
    return { points: points, speed: speed || 1.2, loop: loop !== false, idx: 0, frac: 0, waiting: 0, waitTime: 0 };
  }

  function initSimActors() {
    simActors = [];
    srand(Date.now() % 10000);
    var tid = nextTrackId;

    // ── WORKERS (5 people with different behaviors) ──────

    // Worker 1: Walking a perimeter check route around the machine
    simActors.push({
      trackId: tid++, cls: 'person', label: 'person',
      ppe: { hardHat: true, vest: true },
      confidence: 0.94,
      wp: makeWaypoints([
        [5, 0, 2], [6, 0, -2], [4, 0, -5], [0, 0, -6],
        [-4, 0, -5], [-6, 0, -2], [-5, 0, 2], [-3, 0, 5],
        [0, 0, 6], [3, 0, 5]
      ], 1.1, true),
      noiseScale: 0.08
    });

    // Worker 2: Spotter standing near the bucket, occasionally moving
    simActors.push({
      trackId: tid++, cls: 'person', label: 'person',
      ppe: { hardHat: true, vest: true },
      confidence: 0.91,
      wp: makeWaypoints([
        [3.5, 0, 1.5], [4.0, 0, 2.0], [3.2, 0, 1.8], [3.8, 0, 1.2],
        [3.5, 0, 1.5]
      ], 0.3, true),
      noiseScale: 0.06,
      waitRange: [2, 6]
    });

    // Worker 3: Walks from parking area toward the machine, gets close (DANGER), backs off
    simActors.push({
      trackId: tid++, cls: 'person', label: 'person',
      ppe: { hardHat: true, vest: false },
      confidence: 0.88,
      wp: makeWaypoints([
        [10, 0, 8], [7, 0, 5], [4, 0, 3], [2.5, 0, 1.5],
        [1.8, 0, 0.5],  // DANGER zone approach
        [2.5, 0, 1.5], [4, 0, 3], [7, 0, 5], [10, 0, 8]
      ], 1.0, true),
      noiseScale: 0.10,
      waitRange: [0.5, 2]
    });

    // Worker 4: Working at a fixed station, small movements
    simActors.push({
      trackId: tid++, cls: 'person', label: 'person',
      ppe: { hardHat: true, vest: true },
      confidence: 0.96,
      wp: makeWaypoints([
        [-4, 0, 7], [-4.3, 0, 7.2], [-3.8, 0, 6.8], [-4.1, 0, 7.4],
        [-4, 0, 7]
      ], 0.2, true),
      noiseScale: 0.05,
      waitRange: [3, 8]
    });

    // Worker 5: Crosses the site periodically (appears and disappears from FOV)
    simActors.push({
      trackId: tid++, cls: 'person', label: 'person',
      ppe: { hardHat: false, vest: true },
      confidence: 0.82,
      wp: makeWaypoints([
        [-12, 0, -3], [-8, 0, -2], [-4, 0, -1], [0, 0, 0.5],
        [4, 0, 1], [8, 0, 2], [12, 0, 3],
        [12, 0, 3], [8, 0, 2], [4, 0, 1], [0, 0, 0.5],
        [-4, 0, -1], [-8, 0, -2], [-12, 0, -3]
      ], 1.3, true),
      noiseScale: 0.12
    });

    // ── VEHICLES ─────────────────────────────────────────

    // Excavator: Working nearby, turret rotates (slight position drift)
    simActors.push({
      trackId: tid++, cls: 'excavator', label: 'excavator',
      confidence: 0.97,
      wp: makeWaypoints([
        [8, 0, 7], [8.2, 0, 7.1], [7.8, 0, 6.9], [8.1, 0, 7.2],
        [8, 0, 7]
      ], 0.1, true),
      heading: -Math.PI / 4,
      headingDrift: 0.3,
      noiseScale: 0.04,
      waitRange: [4, 10]
    });

    // Dump truck: Driving a haul route
    simActors.push({
      trackId: tid++, cls: 'dump_truck', label: 'dump_truck',
      confidence: 0.95,
      wp: makeWaypoints([
        [-10, 0, 10], [-6, 0, 9], [-3, 0, 8.5], [0, 0, 8],
        [5, 0, 8.5], [9, 0, 9], [12, 0, 10],
        [12, 0, 10], [9, 0, 9], [5, 0, 8.5], [0, 0, 8],
        [-3, 0, 8.5], [-6, 0, 9], [-10, 0, 10]
      ], 2.5, true),
      noiseScale: 0.06,
      waitRange: [5, 12]
    });

    // Dozer: Slow passes in a work area
    simActors.push({
      trackId: tid++, cls: 'dozer', label: 'dozer',
      confidence: 0.93,
      wp: makeWaypoints([
        [-8, 0, -5], [-6, 0, -5.5], [-4, 0, -6], [-6, 0, -6.5],
        [-8, 0, -7], [-10, 0, -6.5], [-8, 0, -6], [-8, 0, -5]
      ], 0.8, true),
      noiseScale: 0.05,
      waitRange: [2, 5]
    });

    // ── STATIC MARKERS ──────────────────────────────────

    // Cone line (exclusion zone boundary)
    var conePositions = [
      [4, 0, 5], [5.5, 0, 5], [7, 0, 5], [8.5, 0, 5],
      [4, 0, 7], [8.5, 0, 7]
    ];
    for (var ci = 0; ci < conePositions.length; ci++) {
      simActors.push({
        trackId: tid++, cls: 'cone', label: 'cone',
        confidence: 0.85 + rand() * 0.1,
        wp: makeWaypoints([conePositions[ci]], 0, false),
        noiseScale: 0.03,
        isStatic: true
      });
    }

    // Barriers
    simActors.push({
      trackId: tid++, cls: 'barrier', label: 'barrier',
      confidence: 0.88,
      wp: makeWaypoints([[-5, 0, 6]], 0, false),
      heading: 0,
      noiseScale: 0.02,
      isStatic: true
    });
    simActors.push({
      trackId: tid++, cls: 'barrier', label: 'barrier',
      confidence: 0.86,
      wp: makeWaypoints([[-5, 0, 8]], 0, false),
      heading: 0,
      noiseScale: 0.02,
      isStatic: true
    });

    // Delineator posts
    simActors.push({
      trackId: tid++, cls: 'delineator', label: 'delineator',
      confidence: 0.78,
      wp: makeWaypoints([[6, 0, -3]], 0, false),
      noiseScale: 0.03,
      isStatic: true
    });
    simActors.push({
      trackId: tid++, cls: 'delineator', label: 'delineator',
      confidence: 0.76,
      wp: makeWaypoints([[6, 0, -5]], 0, false),
      noiseScale: 0.03,
      isStatic: true
    });

    nextTrackId = tid;
  }

  // ── Waypoint movement engine ───────────────────────────
  function updateWaypoint(actor, dt) {
    var wp = actor.wp;
    if (!wp || wp.points.length < 2) return wp.points[0] || [0, 0, 0];

    // Waiting at waypoint
    if (wp.waiting > 0) {
      wp.waiting -= dt;
      return wp.points[wp.idx];
    }

    var from = wp.points[wp.idx];
    var toIdx = (wp.idx + 1) % wp.points.length;
    var to = wp.points[toIdx];
    var dx = to[0] - from[0], dz = to[2] - from[2];
    var segLen = Math.sqrt(dx * dx + dz * dz);
    if (segLen < 0.01) segLen = 0.01;
    var step = (wp.speed * dt) / segLen;
    wp.frac += step;

    if (wp.frac >= 1) {
      wp.frac = 0;
      wp.idx = toIdx;
      // Wait at waypoint
      if (actor.waitRange) {
        wp.waiting = actor.waitRange[0] + rand() * (actor.waitRange[1] - actor.waitRange[0]);
      }
      if (!wp.loop && wp.idx === 0) {
        wp.idx = wp.points.length - 1;
        wp.frac = 1;
      }
      return wp.points[wp.idx];
    }

    // Lerp position
    return [
      from[0] + dx * wp.frac,
      from[1] + (to[1] - from[1]) * wp.frac,
      from[2] + dz * wp.frac
    ];
  }

  // ── Depth estimation noise (simulates OAK-D stereo error) ─
  function addDepthNoise(pos, scale) {
    var dist = Math.sqrt(pos[0] * pos[0] + pos[2] * pos[2]);
    // Noise increases with distance (stereo depth property)
    var noiseMag = scale * (1 + dist * 0.03);
    return [
      pos[0] + gaussNoise() * noiseMag,
      pos[1],
      pos[2] + gaussNoise() * noiseMag
    ];
  }

  // ── Confidence fluctuation ─────────────────────────────
  function fluctuateConfidence(base, t, id) {
    srand(id * 1000 + Math.floor(t * 3));
    var wobble = gaussNoise() * 0.03;
    return Math.max(0.5, Math.min(1.0, base + wobble));
  }

  // ── Init mock meshes ───────────────────────────────────
  function initMock() {
    if (simInitialized) return;
    simInitialized = true;
    initSimActors();
    simLastUpdate = performance.now() / 1000;

    simActors.forEach(function(actor) {
      var pos = actor.wp.points[0] || [0, 0, 0];
      GF.createObject(actor.cls, actor.ppe || null, function(mesh) {
        mesh.position.set(pos[0], pos[1], pos[2]);
        if (actor.heading !== undefined) mesh.rotation.y = actor.heading;
        scene.add(mesh);
        simMeshes[actor.trackId] = mesh;
      });
      simSmoothing[actor.trackId] = {
        pos: [pos[0], pos[1], pos[2]],
        rotY: actor.heading || 0,
        visible: true
      };
    });
  }

  function removeMockObjects() {
    Object.keys(simMeshes).forEach(function(id) {
      var mesh = simMeshes[id];
      if (mesh) {
        scene.remove(mesh);
        disposeMesh(mesh);
      }
    });
    simMeshes = {};
    simSmoothing = {};
    simInitialized = false;
    simActors = [];
  }

  // ── Main mock update (10Hz sim, 60fps render) ──────────
  function updateMock(t, dt) {
    if (!simInitialized) initMock();

    // Simulate 10Hz detection rate (update actor positions at 10Hz, render smooth at 60fps)
    simFrameCount++;
    simFpsTimer += dt;
    if (simFpsTimer >= 1.0) {
      simFps = Math.round(simFrameCount / simFpsTimer);
      simFrameCount = 0;
      simFpsTimer = 0;
    }

    var closestDist = Infinity;
    var people = 0, equip = 0, markers = 0;
    var highestZone = 'CLEAR';
    var dangerCount = 0;

    simActors.forEach(function(actor) {
      var s = simSmoothing[actor.trackId];
      var mesh = simMeshes[actor.trackId];
      if (!s) return;

      // Move along waypoints
      var rawPos = updateWaypoint(actor, dt);

      // Add depth estimation noise
      var noisyPos = addDepthNoise(rawPos, actor.noiseScale || 0.08);

      // Check camera visibility
      var dist = Math.sqrt(noisyPos[0] * noisyPos[0] + noisyPos[2] * noisyPos[2]);
      var cam = getCameraForPoint(noisyPos[0], noisyPos[2]);
      var inRange = dist <= simZones.max_range_m + 2;
      var visible = cam !== null && inRange;

      // Static objects always visible if in range
      if (actor.isStatic && inRange) visible = true;

      // Fluctuate confidence
      actor._conf = fluctuateConfidence(actor.confidence, t, actor.trackId);

      // Low confidence = sometimes invisible (detection dropout)
      if (actor._conf < 0.65 && !actor.isStatic) {
        visible = rand() > 0.3; // 30% chance of dropout at low confidence
      }

      s.visible = visible;

      if (!mesh) return;

      if (!visible) {
        mesh.visible = false;
        removeLabel(actor.trackId);
        return;
      }
      mesh.visible = true;

      // Smooth interpolation (60fps from ~10Hz sim data)
      var alpha = 1 - Math.exp(-dt * 8);
      var prevX = s.pos[0], prevZ = s.pos[2];
      s.pos[0] += (noisyPos[0] - s.pos[0]) * alpha;
      s.pos[1] += (noisyPos[1] - s.pos[1]) * alpha;
      s.pos[2] += (noisyPos[2] - s.pos[2]) * alpha;
      mesh.position.set(s.pos[0], s.pos[1], s.pos[2]);

      // Face direction of travel (not for static or explicitly headed)
      if (actor.heading === undefined && !actor.isStatic) {
        var vx = dt > 0 ? (s.pos[0] - prevX) / dt : 0;
        var vz = dt > 0 ? (s.pos[2] - prevZ) / dt : 0;
        if (Math.sqrt(vx * vx + vz * vz) > 0.2) {
          var tr = Math.atan2(vx, vz);
          var diff = tr - s.rotY;
          while (diff > Math.PI) diff -= 2 * Math.PI;
          while (diff < -Math.PI) diff += 2 * Math.PI;
          s.rotY += diff * (1 - Math.exp(-dt * 4));
          mesh.rotation.y = s.rotY;
        }
      } else if (actor.headingDrift) {
        // Slight heading drift for working equipment
        s.rotY = (actor.heading || 0) + Math.sin(t * 0.2) * actor.headingDrift;
        mesh.rotation.y = s.rotY;
      }

      // Zone classification
      var zone = 'CLEAR';
      if (dist < simZones.danger_m) zone = 'DANGER';
      else if (dist < simZones.warning_m) zone = 'WARNING';

      // Zone tint
      applyZoneTint(mesh, zone);

      // Distance label with camera ID and confidence
      var camLabel = cam ? cam.id.replace('cam-', '').charAt(0).toUpperCase() : '?';
      var labelText = dist.toFixed(1) + 'm';
      if (actor.cls === 'person') {
        labelText = dist.toFixed(1) + 'm · ' + Math.round(actor._conf * 100) + '%';
      }
      updateLabel(actor.trackId, labelText, mesh.position);

      // Stats
      if (dist < closestDist && actor.cls !== 'cone' && actor.cls !== 'barrier' && actor.cls !== 'delineator') {
        closestDist = dist;
      }
      if (actor.cls === 'person') { people++; }
      else if (actor.cls === 'excavator' || actor.cls === 'dump_truck' || actor.cls === 'dozer') { equip++; }
      else { markers++; }

      if (zone === 'DANGER') { highestZone = 'DANGER'; dangerCount++; }
      else if (zone === 'WARNING' && highestZone !== 'DANGER') { highestZone = 'WARNING'; }
    });

    stats.people = people;
    stats.equip = equip;
    stats.markers = markers;
    stats.closestDist = closestDist === Infinity ? Infinity : closestDist;
    stats.zone = highestZone;
    stats.fps = simFps;
    stats.mode = MODE_MOCK;
    stats.summary = {
      danger_count: dangerCount,
      cameras_active: 4,
      detection_hz: 10
    };
  }

  // ── Mesh lifecycle helpers ─────────────────────────────
  function disposeMesh(mesh) {
    mesh.traverse(function(child) {
      if (child.isMesh) {
        if (child.geometry) child.geometry.dispose();
        if (child.material) {
          if (Array.isArray(child.material)) {
            child.material.forEach(function(m) { m.dispose(); });
          } else {
            child.material.dispose();
          }
        }
      }
    });
  }

  function applyZoneTint(mesh, zone) {
    mesh.traverse(function(child) {
      if (child.isMesh && child.material) {
        if (!child.userData.origColor) {
          child.userData.origColor = child.material.color.clone();
        }
        if (zone === 'DANGER') {
          child.material.color.copy(child.userData.origColor).lerp(new THREE.Color('#EF4444'), 0.35);
        } else if (zone === 'WARNING') {
          child.material.color.copy(child.userData.origColor).lerp(new THREE.Color('#F59E0B'), 0.2);
        } else {
          child.material.color.copy(child.userData.origColor);
        }
      }
    });
  }

  function setMeshOpacityAndScale(mesh, factor) {
    var s = Math.max(0, factor);
    mesh.scale.setScalar(s);
    mesh.traverse(function(child) {
      if (child.isMesh && child.material) {
        child.material.transparent = true;
        child.material.opacity = Math.max(0, factor);
      }
    });
  }

  // ── Screen-space projection ────────────────────────────
  function worldToScreen(position, cam, width, height) {
    var v = position.clone();
    v.project(cam);
    return {
      x: (v.x * 0.5 + 0.5) * width,
      y: (-v.y * 0.5 + 0.5) * height
    };
  }

  function updateLabel(trackId, text, worldPos) {
    var labelId = 'lbl-' + trackId;
    var el = document.getElementById(labelId);
    if (!el) {
      el = document.createElement('div');
      el.id = labelId;
      el.style.cssText = 'position:absolute;font-size:13px;font-weight:600;color:#F2F2F2;background:rgba(0,0,0,0.75);padding:4px 8px;border-radius:6px;white-space:nowrap;transform:translate(-50%,-100%);pointer-events:none;border:1px solid rgba(255,255,255,0.1);-webkit-backdrop-filter:blur(4px);backdrop-filter:blur(4px);';
      labelsOverlay.appendChild(el);
    }
    el.textContent = text;
    var w = labelsOverlay.clientWidth || window.innerWidth;
    var h = labelsOverlay.clientHeight || window.innerHeight;
    var above = worldPos.clone();
    above.y += 2.2;
    var screen = worldToScreen(above, camera, w, h);
    var v = above.clone().project(camera);
    if (v.z > 1) {
      el.style.display = 'none';
    } else {
      el.style.display = '';
      el.style.left = screen.x + 'px';
      el.style.top = screen.y + 'px';
    }
  }

  function removeLabel(trackId) {
    var el = document.getElementById('lbl-' + trackId);
    if (el) el.parentNode.removeChild(el);
  }

  function clearAllLabels() {
    while (labelsOverlay.firstChild) {
      labelsOverlay.removeChild(labelsOverlay.firstChild);
    }
  }

  // ── Data connection ────────────────────────────────────
  function onApiData(data) {
    lastDataTime = performance.now();
    liveDetections = data.detections || [];
    liveSummary = data.summary || null;
    liveFps = data.fps || 0;

    if (mode === MODE_MOCK && simInitialized) {
      removeMockObjects();
      clearAllLabels();
    }
  }

  function tryConnect() {
    if (connectionAttempted) return;
    connectionAttempted = true;

    if (!GF.api || !GF.api.connectStream) {
      console.log('DetectionRenderer: api-client not loaded, starting sim');
      mode = MODE_MOCK;
      return;
    }

    console.log('DetectionRenderer: attempting SSE connection');
    try {
      sseSource = GF.api.connectStream(
        function(data) {
          mode = MODE_SSE;
          onApiData(data);
        },
        function(err) {
          console.warn('DetectionRenderer: SSE error, falling back to polling');
          if (sseSource) { sseSource.close(); sseSource = null; }
          startPolling();
        }
      );

      setTimeout(function() {
        if (lastDataTime === 0) {
          console.log('DetectionRenderer: SSE no data after 2s, starting polling');
          if (sseSource) { sseSource.close(); sseSource = null; }
          startPolling();
        }
      }, 2000);
    } catch (e) {
      console.warn('DetectionRenderer: SSE failed to start:', e);
      startPolling();
    }
  }

  function startPolling() {
    if (pollTimer) return;
    console.log('DetectionRenderer: starting polling at 100ms');
    pollTimer = setInterval(function() {
      GF.api.getSpatial().then(function(data) {
        mode = MODE_POLL;
        onApiData(data);
      }).catch(function(err) {
        // Polling failed — will fall back to mock after timeout
      });
    }, 100);
  }

  // ── Live detection update ──────────────────────────────
  function updateLive(t, dt) {
    if (!liveDetections) return;

    var now = performance.now();
    var activeIds = {};
    var closestDist = Infinity;
    var people = 0, equip = 0, markers = 0;
    var highestZone = 'CLEAR';

    liveDetections.forEach(function(det) {
      var tid = det.track_id;
      activeIds[tid] = true;
      var track = tracks[tid];

      if (!track) {
        track = {
          mesh: null,
          smoothPos: [det.x_m, det.y_m || 0, det.z_m],
          smoothRotY: 0,
          zone: det.zone || 'CLEAR',
          fadeState: null,
          fadeStart: 0,
          distance: det.distance_m || 0,
          label: det.label || 'person',
          creating: true
        };
        tracks[tid] = track;

        GF.createObject(det.label || 'person', null, function(mesh) {
          mesh.position.set(det.x_m, det.y_m || 0, det.z_m);
          scene.add(mesh);
          track.mesh = mesh;
          track.creating = false;
          applyZoneTint(mesh, det.zone || 'CLEAR');
        });
      } else {
        track.zone = det.zone || 'CLEAR';
        track.distance = det.distance_m || 0;
        track.label = det.label || 'person';

        if (track.fadeState === 'fading') {
          track.fadeState = null;
          if (track.mesh) setMeshOpacityAndScale(track.mesh, 1);
        }
      }

      var alpha = 1 - Math.exp(-dt * 6);
      var prevX = track.smoothPos[0];
      var prevZ = track.smoothPos[2];
      track.smoothPos[0] += (det.x_m - track.smoothPos[0]) * alpha;
      track.smoothPos[1] += ((det.y_m || 0) - track.smoothPos[1]) * alpha;
      track.smoothPos[2] += (det.z_m - track.smoothPos[2]) * alpha;

      if (track.mesh && !track.creating) {
        track.mesh.position.set(track.smoothPos[0], track.smoothPos[1], track.smoothPos[2]);

        var vx = dt > 0 ? (track.smoothPos[0] - prevX) / dt : 0;
        var vz = dt > 0 ? (track.smoothPos[2] - prevZ) / dt : 0;
        if (Math.sqrt(vx * vx + vz * vz) > 0.3) {
          var targetRot = Math.atan2(vx, vz);
          var diff = targetRot - track.smoothRotY;
          while (diff > Math.PI) diff -= 2 * Math.PI;
          while (diff < -Math.PI) diff += 2 * Math.PI;
          track.smoothRotY += diff * (1 - Math.exp(-dt * 4));
          track.mesh.rotation.y = track.smoothRotY;
        }

        applyZoneTint(track.mesh, track.zone);
        updateLabel(tid, track.distance.toFixed(1) + 'm', track.mesh.position);
      }

      var d = track.distance;
      if (d < closestDist) closestDist = d;
      if (track.label === 'person') people++;
      else if (track.label === 'excavator' || track.label === 'dump_truck' || track.label === 'dozer' || track.label === 'wheel_loader') equip++;
      else markers++;

      if (track.zone === 'DANGER') highestZone = 'DANGER';
      else if (track.zone === 'WARNING' && highestZone !== 'DANGER') highestZone = 'WARNING';
    });

    // Fade out disappeared tracks
    Object.keys(tracks).forEach(function(tid) {
      if (activeIds[tid]) return;
      var track = tracks[tid];
      if (track.creating) return;

      if (!track.fadeState) {
        track.fadeState = 'fading';
        track.fadeStart = now;
      }

      var elapsed = (now - track.fadeStart) / 1000;
      var fadeDuration = 0.5;
      if (elapsed >= fadeDuration) {
        if (track.mesh) {
          scene.remove(track.mesh);
          disposeMesh(track.mesh);
        }
        removeLabel(tid);
        delete tracks[tid];
      } else {
        var factor = 1 - (elapsed / fadeDuration);
        if (track.mesh) setMeshOpacityAndScale(track.mesh, factor);
        if (track.mesh) updateLabel(tid, track.distance.toFixed(1) + 'm', track.mesh.position);
      }
    });

    stats.people = people;
    stats.equip = equip;
    stats.markers = markers;
    stats.closestDist = closestDist === Infinity ? Infinity : closestDist;
    stats.zone = highestZone;
    stats.fps = liveFps;
    stats.mode = mode;
    stats.summary = liveSummary;
  }

  // ── Stats object ───────────────────────────────────────
  var stats = { people: 0, equip: 0, markers: 0, closestDist: Infinity, zone: 'CLEAR', fps: 0, mode: MODE_MOCK, summary: null };

  // ── Main update ────────────────────────────────────────
  function update(t, dt) {
    if (!connectionAttempted) tryConnect();

    var now = performance.now();
    var hasRecentData = lastDataTime > 0 && (now - lastDataTime) < mockFallbackDelay;

    if (hasRecentData) {
      if (simInitialized) {
        removeMockObjects();
        clearAllLabels();
      }
      updateLive(t, dt);
    } else {
      if (Object.keys(tracks).length > 0) {
        Object.keys(tracks).forEach(function(tid) {
          if (tracks[tid].mesh) {
            scene.remove(tracks[tid].mesh);
            disposeMesh(tracks[tid].mesh);
          }
          removeLabel(tid);
        });
        tracks = {};
        clearAllLabels();
      }
      updateMock(t, dt);
    }
  }

  return {
    update: update,
    stats: stats
  };
})();
