/* ═══════════════════════════════════════════════════════════
   GridFront Detect — Zone Renderer
   Config-reactive zone rings with breach animation.
   Depends on: scene-manager.js
   ═══════════════════════════════════════════════════════════ */
window.GF = window.GF || {};

GF.zones = (function() {
  var scene = null;

  // Default zone config
  var zoneConfig = { danger_m: 3.5, warning_m: 6, max_range_m: 12 };

  // Zone definitions: key, color, base opacity, width (meters)
  var ZONE_DEFS = {
    danger:   { color: '#EF4444', baseOpacity: 0.8, width: 0.12 },
    warning:  { color: '#F59E0B', baseOpacity: 0.6, width: 0.10 },
    maxRange: { color: '#44A5D6', baseOpacity: 0.3, width: 0.08 }
  };

  // Active meshes
  var rings = {};      // { danger: { ring, glow }, warning: {...}, maxRange: {...} }
  var labels = {};     // { danger: sprite, ... }
  var fadeAnim = null;  // { elapsed, duration, oldMeshes, newMeshes }

  // Breach state
  var dangerBreached = false;
  var warningBreached = false;
  var animTime = 0;

  // ── Init ──────────────────────────────────────────────────
  function init(sceneRef) {
    scene = sceneRef;

    // Try loading config from API if available
    if (GF.api && typeof GF.api.getConfig === 'function') {
      GF.api.getConfig().then(function(cfg) {
        if (cfg && cfg.zones) {
          setConfig(cfg.zones);
        }
      }).catch(function() {
        // API not available, use defaults
      });
    }

    buildRings();
  }

  // ── Build ring meshes ─────────────────────────────────────
  function createRingMesh(radius, width, color, opacity) {
    var inner = radius - width / 2;
    var outer = radius + width / 2;
    if (inner < 0) inner = 0;

    var mesh = new THREE.Mesh(
      new THREE.RingGeometry(inner, outer, 128),
      new THREE.MeshBasicMaterial({
        color: color,
        transparent: true,
        opacity: opacity,
        side: THREE.DoubleSide,
        depthWrite: false
      })
    );
    mesh.rotation.x = -Math.PI / 2;
    mesh.position.y = 0.02;
    return mesh;
  }

  function createGlowMesh(radius, width, color) {
    // Wider, very transparent ring underneath for soft glow effect
    var glowWidth = width * 3;
    var inner = radius - glowWidth / 2;
    var outer = radius + glowWidth / 2;
    if (inner < 0) inner = 0;

    var mesh = new THREE.Mesh(
      new THREE.RingGeometry(inner, outer, 128),
      new THREE.MeshBasicMaterial({
        color: color,
        transparent: true,
        opacity: 0,
        side: THREE.DoubleSide,
        depthWrite: false
      })
    );
    mesh.rotation.x = -Math.PI / 2;
    mesh.position.y = 0.015;
    return mesh;
  }

  function createLabel(text, radius, color) {
    // Create a small canvas for the distance label
    var canvas = document.createElement('canvas');
    var size = 128;
    canvas.width = size;
    canvas.height = 48;
    var ctx = canvas.getContext('2d');

    ctx.clearRect(0, 0, size, 48);
    ctx.font = '600 24px system-ui, -apple-system, sans-serif';
    ctx.textAlign = 'center';
    ctx.textBaseline = 'middle';

    // Background pill
    var metrics = ctx.measureText(text);
    var pw = metrics.width + 16;
    var ph = 28;
    var px = (size - pw) / 2;
    var py = (48 - ph) / 2;
    ctx.fillStyle = 'rgba(0,0,0,0.6)';
    ctx.beginPath();
    ctx.roundRect(px, py, pw, ph, 4);
    ctx.fill();

    // Text
    ctx.fillStyle = '#F2F2F2';
    ctx.fillText(text, size / 2, 24);

    var texture = new THREE.CanvasTexture(canvas);
    texture.needsUpdate = true;

    var mat = new THREE.SpriteMaterial({
      map: texture,
      transparent: true,
      depthTest: false,
      depthWrite: false
    });
    var sprite = new THREE.Sprite(mat);
    sprite.scale.set(1.6, 0.6, 1);
    // Place label at front of ring (positive Z = "front" in the scene)
    sprite.position.set(0, 0.5, radius);

    return sprite;
  }

  function buildRings() {
    var danger_m = zoneConfig.danger_m;
    var warning_m = zoneConfig.warning_m;
    var max_range_m = zoneConfig.max_range_m;

    // Danger ring
    var dr = createRingMesh(danger_m, ZONE_DEFS.danger.width, ZONE_DEFS.danger.color, ZONE_DEFS.danger.baseOpacity);
    var dg = createGlowMesh(danger_m, ZONE_DEFS.danger.width, ZONE_DEFS.danger.color);
    scene.add(dr);
    scene.add(dg);
    rings.danger = { ring: dr, glow: dg };

    // Warning ring
    var wr = createRingMesh(warning_m, ZONE_DEFS.warning.width, ZONE_DEFS.warning.color, ZONE_DEFS.warning.baseOpacity);
    var wg = createGlowMesh(warning_m, ZONE_DEFS.warning.width, ZONE_DEFS.warning.color);
    scene.add(wr);
    scene.add(wg);
    rings.warning = { ring: wr, glow: wg };

    // Max range ring
    var mr = createRingMesh(max_range_m, ZONE_DEFS.maxRange.width, ZONE_DEFS.maxRange.color, ZONE_DEFS.maxRange.baseOpacity);
    scene.add(mr);
    rings.maxRange = { ring: mr, glow: null };

    // Labels
    labels.danger = createLabel(danger_m.toFixed(1) + 'm', danger_m, ZONE_DEFS.danger.color);
    labels.warning = createLabel(warning_m.toFixed(1) + 'm', warning_m, ZONE_DEFS.warning.color);
    labels.maxRange = createLabel(max_range_m.toFixed(1) + 'm', max_range_m, ZONE_DEFS.maxRange.color);
    scene.add(labels.danger);
    scene.add(labels.warning);
    scene.add(labels.maxRange);
  }

  function removeAllMeshes() {
    var meshes = [];
    ['danger', 'warning', 'maxRange'].forEach(function(key) {
      if (rings[key]) {
        if (rings[key].ring) meshes.push(rings[key].ring);
        if (rings[key].glow) meshes.push(rings[key].glow);
      }
      if (labels[key]) meshes.push(labels[key]);
    });
    return meshes;
  }

  function disposeMeshes(meshes) {
    meshes.forEach(function(m) {
      scene.remove(m);
      if (m.geometry) m.geometry.dispose();
      if (m.material) {
        if (m.material.map) m.material.map.dispose();
        m.material.dispose();
      }
    });
  }

  // ── Config update with animated transition ────────────────
  function setConfig(cfg) {
    if (!cfg) return;
    var newDanger = cfg.danger_m || zoneConfig.danger_m;
    var newWarning = cfg.warning_m || zoneConfig.warning_m;
    var newRange = cfg.max_range_m || zoneConfig.max_range_m;

    // Skip if no change
    if (newDanger === zoneConfig.danger_m &&
        newWarning === zoneConfig.warning_m &&
        newRange === zoneConfig.max_range_m) {
      return;
    }

    // Collect old meshes for fade-out
    var oldMeshes = removeAllMeshes();

    // Update config
    zoneConfig.danger_m = newDanger;
    zoneConfig.warning_m = newWarning;
    zoneConfig.max_range_m = newRange;

    // Reset ring/label references
    rings = {};
    labels = {};

    // Build new rings
    buildRings();

    // Collect new meshes for fade-in
    var newMeshes = removeAllMeshes();
    // They are still in the scene (removeAllMeshes just collects refs)

    // Start transition animation
    // Set new meshes to 0 opacity initially
    newMeshes.forEach(function(m) {
      if (m.material) m.material.opacity = 0;
    });

    fadeAnim = {
      elapsed: 0,
      duration: 0.3,
      oldMeshes: oldMeshes,
      newMeshes: newMeshes,
      oldStartOpacities: oldMeshes.map(function(m) {
        return m.material ? m.material.opacity : 0;
      }),
      newTargetOpacities: newMeshes.map(function(m) {
        // Store the intended opacity before we zeroed them
        // We need to recalculate from zone defs
        return getTargetOpacity(m);
      })
    };
  }

  function getTargetOpacity(mesh) {
    // Determine which zone this mesh belongs to based on its geometry
    // Check ring associations
    var keys = ['danger', 'warning', 'maxRange'];
    for (var i = 0; i < keys.length; i++) {
      var key = keys[i];
      if (rings[key]) {
        if (rings[key].ring === mesh) return ZONE_DEFS[key].baseOpacity;
        if (rings[key].glow === mesh) return 0; // glow starts at 0
      }
      if (labels[key] === mesh) return 1;
    }
    return 0;
  }

  // ── Update (called each frame) ────────────────────────────
  function update(detectionStats, dt) {
    if (!scene) return;

    animTime += dt;

    // Handle fade transition
    if (fadeAnim) {
      fadeAnim.elapsed += dt;
      var progress = Math.min(fadeAnim.elapsed / fadeAnim.duration, 1);
      // Smooth ease
      var t = progress * progress * (3 - 2 * progress);

      // Fade out old
      fadeAnim.oldMeshes.forEach(function(m, i) {
        if (m.material) {
          m.material.opacity = fadeAnim.oldStartOpacities[i] * (1 - t);
        }
      });

      // Fade in new
      fadeAnim.newMeshes.forEach(function(m, i) {
        if (m.material) {
          m.material.opacity = fadeAnim.newTargetOpacities[i] * t;
        }
      });

      if (progress >= 1) {
        // Dispose old meshes
        disposeMeshes(fadeAnim.oldMeshes);
        fadeAnim = null;
      }

      return; // Skip breach animation during transition
    }

    // Determine breach state from detection stats
    var closestDist = detectionStats ? detectionStats.closestDist : Infinity;
    dangerBreached = closestDist < zoneConfig.danger_m;
    warningBreached = !dangerBreached && closestDist < zoneConfig.warning_m;

    // ── Danger ring animation ───────────────────────────────
    if (rings.danger && rings.danger.ring) {
      var dRing = rings.danger.ring;
      var dGlow = rings.danger.glow;
      var def = ZONE_DEFS.danger;

      if (dangerBreached) {
        // Pulse opacity: 0.5 -> 1.0 at 2Hz using sine wave
        var pulse = Math.sin(animTime * 2 * Math.PI * 2); // 2Hz
        var opacity = 0.5 + 0.5 * (0.5 + 0.5 * pulse);  // maps sin to 0.5..1.0
        dRing.material.opacity = opacity;

        // Grow ring thickness: rebuild geometry with 1.3x width
        var growWidth = def.width * 1.3;
        var inner = zoneConfig.danger_m - growWidth / 2;
        var outer = zoneConfig.danger_m + growWidth / 2;
        if (inner < 0) inner = 0;
        dRing.geometry.dispose();
        dRing.geometry = new THREE.RingGeometry(inner, outer, 128);

        // Glow: expand outward with low opacity
        if (dGlow) {
          var glowScale = 1.0 + 0.3 * (0.5 + 0.5 * pulse);
          var glowWidth = def.width * 3 * glowScale;
          var gi = zoneConfig.danger_m - glowWidth / 2;
          var go = zoneConfig.danger_m + glowWidth / 2;
          if (gi < 0) gi = 0;
          dGlow.geometry.dispose();
          dGlow.geometry = new THREE.RingGeometry(gi, go, 128);
          dGlow.material.opacity = 0.1 * (0.5 + 0.5 * pulse);
        }
      } else {
        // Reset to base state
        dRing.material.opacity = def.baseOpacity;
        var baseInner = zoneConfig.danger_m - def.width / 2;
        var baseOuter = zoneConfig.danger_m + def.width / 2;
        if (baseInner < 0) baseInner = 0;
        dRing.geometry.dispose();
        dRing.geometry = new THREE.RingGeometry(baseInner, baseOuter, 128);

        if (dGlow) {
          dGlow.material.opacity = 0;
        }
      }
    }

    // ── Warning ring animation ──────────────────────────────
    if (rings.warning && rings.warning.ring) {
      var wRing = rings.warning.ring;
      var wGlow = rings.warning.glow;
      var wDef = ZONE_DEFS.warning;

      if (warningBreached) {
        // Gentle pulse: 0.4 -> 0.7 at 1Hz
        var wPulse = Math.sin(animTime * 2 * Math.PI * 1); // 1Hz
        var wOpacity = 0.4 + 0.3 * (0.5 + 0.5 * wPulse);  // maps to 0.4..0.7
        wRing.material.opacity = wOpacity;

        // Subtle glow
        if (wGlow) {
          wGlow.material.opacity = 0.06 * (0.5 + 0.5 * wPulse);
        }
      } else {
        wRing.material.opacity = wDef.baseOpacity;
        if (wGlow) {
          wGlow.material.opacity = 0;
        }
      }
    }
  }

  // ── Public API ────────────────────────────────────────────
  return {
    init: init,
    setConfig: setConfig,
    update: update
  };
})();
