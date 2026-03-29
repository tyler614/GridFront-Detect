/* ═══════════════════════════════════════════════════════════
   GridFront Detect — Detection Renderer
   Live data integration: SSE → polling → mock fallback
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
  var MODE_MOCK = 'Mock';

  var mode = MODE_MOCK;
  var sseSource = null;
  var pollTimer = null;
  var lastDataTime = 0;          // timestamp of last real API data
  var mockFallbackDelay = 3000;  // ms before falling back to mock
  var connectionAttempted = false;

  // Tracked detection meshes: { track_id: { mesh, smoothPos, smoothRotY, zone, fadeState, fadeStart, label } }
  var tracks = {};
  // Latest detections from API
  var liveDetections = null;
  var liveSummary = null;
  var liveFps = 0;

  // ── Label overlay ──────────────────────────────────────
  var labelsOverlay = document.createElement('div');
  labelsOverlay.id = 'labels-overlay';
  labelsOverlay.style.cssText = 'position:absolute;top:0;left:0;width:100%;height:100%;pointer-events:none;overflow:hidden;z-index:5;';
  container.style.position = 'relative';
  container.appendChild(labelsOverlay);

  // ── Mock data (fallback) ───────────────────────────────
  var mockObjects = [
    { id: 'p1', cls: 'person', path: function(t) { return [Math.sin(t * .4) * 3 + 2, 0, Math.cos(t * .4) * 3 + 2]; }, ppe: { hardHat: true, vest: true } },
    { id: 'p2', cls: 'person', path: function(t) { return [-3 + Math.sin(t * .3 + 1) * 1.5, 0, 4 + Math.cos(t * .5) * 2]; }, ppe: { hardHat: true, vest: false } },
    { id: 'p3', cls: 'person', path: function(t) { return [Math.sin(t * .15) * 4 - 1, 0, -4 + Math.sin(t * .2) * 1]; }, ppe: { hardHat: false, vest: true } },
    { id: 'ex1', cls: 'excavator', path: function() { return [7, 0, 8]; }, heading: -Math.PI / 4 },
    { id: 'dt1', cls: 'dump_truck', path: function(t) { return [-8 + Math.sin(t * .15) * 3, 0, 9]; }, heading: Math.PI / 2 },
    { id: 'c1', cls: 'cone', path: function() { return [4, 0, 5]; } },
    { id: 'c2', cls: 'cone', path: function() { return [6, 0, 5]; } },
    { id: 'c3', cls: 'cone', path: function() { return [8, 0, 5]; } },
    { id: 'c4', cls: 'cone', path: function() { return [4, 0, 7]; } },
    { id: 'c5', cls: 'cone', path: function() { return [8, 0, 7]; } },
    { id: 'b1', cls: 'barrier', path: function() { return [-5, 0, 6]; } },
    { id: 'b2', cls: 'barrier', path: function() { return [-5, 0, 8]; } },
    { id: 'dz1', cls: 'dozer', path: function() { return [-7, 0, -6]; }, heading: Math.PI / 6 }
  ];

  var mockMeshes = {};
  var mockSmoothing = {};
  var mockInitialized = false;

  function initMock() {
    if (mockInitialized) return;
    mockInitialized = true;
    mockObjects.forEach(function(obj) {
      var pos = obj.path(0);
      GF.createObject(obj.cls, obj.ppe || null, function(mesh) {
        mesh.position.set(pos[0], pos[1], pos[2]);
        if (obj.heading !== undefined) mesh.rotation.y = obj.heading;
        scene.add(mesh);
        mockMeshes[obj.id] = mesh;
      });
      mockSmoothing[obj.id] = { pos: [pos[0], pos[1], pos[2]], rotY: obj.heading || 0 };
    });
  }

  function removeMockObjects() {
    Object.keys(mockMeshes).forEach(function(id) {
      var mesh = mockMeshes[id];
      if (mesh) {
        scene.remove(mesh);
        disposeMesh(mesh);
      }
    });
    mockMeshes = {};
    mockSmoothing = {};
    mockInitialized = false;
  }

  function updateMock(t, dt) {
    if (!mockInitialized) initMock();
    var closestDist = Infinity;
    var people = 0, equip = 0, markers = 0;

    mockObjects.forEach(function(obj) {
      var target = obj.path(t);
      var s = mockSmoothing[obj.id];
      var mesh = mockMeshes[obj.id];
      if (!s || !mesh) return;

      var alpha = 1 - Math.exp(-dt * 6);
      var px = s.pos[0], pz = s.pos[2];
      s.pos[0] += (target[0] - s.pos[0]) * alpha;
      s.pos[1] += (target[1] - s.pos[1]) * alpha;
      s.pos[2] += (target[2] - s.pos[2]) * alpha;
      mesh.position.set(s.pos[0], s.pos[1], s.pos[2]);

      if (obj.heading === undefined) {
        var vx = dt > 0 ? (s.pos[0] - px) / dt : 0;
        var vz = dt > 0 ? (s.pos[2] - pz) / dt : 0;
        if (Math.sqrt(vx * vx + vz * vz) > 0.3) {
          var tr = Math.atan2(vx, vz);
          var diff = tr - s.rotY;
          while (diff > Math.PI) diff -= 2 * Math.PI;
          while (diff < -Math.PI) diff += 2 * Math.PI;
          s.rotY += diff * (1 - Math.exp(-dt * 4));
          mesh.rotation.y = s.rotY;
        }
      }

      var d = Math.sqrt(s.pos[0] * s.pos[0] + s.pos[2] * s.pos[2]);
      if (d < closestDist) closestDist = d;
      if (obj.cls === 'person') people++;
      else if (obj.cls === 'excavator' || obj.cls === 'dump_truck' || obj.cls === 'dozer') equip++;
      else markers++;
    });

    stats.people = people;
    stats.equip = equip;
    stats.markers = markers;
    stats.closestDist = closestDist;
    stats.zone = closestDist < 3.5 ? 'DANGER' : closestDist < 6 ? 'WARNING' : 'CLEAR';
    stats.fps = 0;
    stats.mode = MODE_MOCK;
    stats.summary = null;
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
          child.material.color.copy(child.userData.origColor).lerp(new THREE.Color('#EF4444'), 0.3);
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
      el.style.cssText = 'position:absolute;font-size:11px;font-weight:700;color:#22384C;background:rgba(255,255,255,0.85);padding:2px 6px;border-radius:4px;white-space:nowrap;transform:translate(-50%,-100%);pointer-events:none;';
      labelsOverlay.appendChild(el);
    }
    el.textContent = text;
    var w = labelsOverlay.clientWidth || window.innerWidth;
    var h = labelsOverlay.clientHeight || window.innerHeight;
    var above = worldPos.clone();
    above.y += 2.2; // offset above head
    var screen = worldToScreen(above, camera, w, h);
    // Hide if behind camera
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

    // Switch from mock to live on first real data
    if (mode === MODE_MOCK && mockInitialized) {
      removeMockObjects();
      clearAllLabels();
    }
  }

  function tryConnect() {
    if (connectionAttempted) return;
    connectionAttempted = true;

    // Check if api-client is loaded
    if (!GF.api || !GF.api.connectStream) {
      console.log('DetectionRenderer: api-client not loaded, starting mock');
      mode = MODE_MOCK;
      return;
    }

    // Try SSE first
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

      // If SSE doesn't deliver data within 2s, also start polling as backup
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

    // Process each detection
    liveDetections.forEach(function(det) {
      var tid = det.track_id;
      activeIds[tid] = true;
      var track = tracks[tid];

      if (!track) {
        // New track — create mesh
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
        // Existing track — update target for smooth interpolation
        track.zone = det.zone || 'CLEAR';
        track.distance = det.distance_m || 0;
        track.label = det.label || 'person';

        // Cancel any fade-out if track reappeared
        if (track.fadeState === 'fading') {
          track.fadeState = null;
          if (track.mesh) setMeshOpacityAndScale(track.mesh, 1);
        }
      }

      // Smooth interpolation
      var alpha = 1 - Math.exp(-dt * 6);
      var prevX = track.smoothPos[0];
      var prevZ = track.smoothPos[2];
      track.smoothPos[0] += (det.x_m - track.smoothPos[0]) * alpha;
      track.smoothPos[1] += ((det.y_m || 0) - track.smoothPos[1]) * alpha;
      track.smoothPos[2] += (det.z_m - track.smoothPos[2]) * alpha;

      if (track.mesh && !track.creating) {
        track.mesh.position.set(track.smoothPos[0], track.smoothPos[1], track.smoothPos[2]);

        // Face direction of movement
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

        // Zone tint
        applyZoneTint(track.mesh, track.zone);

        // Distance label
        updateLabel(tid, track.distance.toFixed(1) + 'm', track.mesh.position);
      }

      // Stats
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
      if (track.creating) return; // still being created

      if (!track.fadeState) {
        track.fadeState = 'fading';
        track.fadeStart = now;
      }

      var elapsed = (now - track.fadeStart) / 1000;
      var fadeDuration = 0.5;
      if (elapsed >= fadeDuration) {
        // Remove fully
        if (track.mesh) {
          scene.remove(track.mesh);
          disposeMesh(track.mesh);
        }
        removeLabel(tid);
        delete tracks[tid];
      } else {
        // Fade
        var factor = 1 - (elapsed / fadeDuration);
        if (track.mesh) setMeshOpacityAndScale(track.mesh, factor);
        // Update label to show fading
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
    // Attempt connection on first update
    if (!connectionAttempted) tryConnect();

    var now = performance.now();
    var hasRecentData = lastDataTime > 0 && (now - lastDataTime) < mockFallbackDelay;

    if (hasRecentData) {
      // Live mode — remove mock objects if still present
      if (mockInitialized) {
        removeMockObjects();
        clearAllLabels();
      }
      updateLive(t, dt);
    } else {
      // Mock fallback — remove live tracks if any
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
