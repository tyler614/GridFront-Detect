/* ═══════════════════════════════════════════════════════════
   GridFront Detect — Excavator Model (CAT 320 style)
   Depends on: materials.js (GF.mk, GF.mkr, GF.rbox, GF.bodyMat, GF.darkMat, GF.glassMat, GF.metalMat, GF.frameMat)
   ═══════════════════════════════════════════════════════════ */
window.GF = window.GF || {};
GF.models = GF.models || {};

GF.models.excavator = function() {
  var mk = GF.mk, mkr = GF.mkr, rbox = GF.rbox;
  var bodyMat = GF.bodyMat, darkMat = GF.darkMat, glassMat = GF.glassMat;
  var metalMat = GF.metalMat, frameMat = GF.frameMat;

  var g = new THREE.Group();

  // ── Tracked undercarriage ───────────────────────────────
  // Track frame crossmembers
  rbox(1.8, 0.1, 0.35, 0.04, frameMat, 0, 0.42, 0.6, g);
  rbox(1.8, 0.1, 0.35, 0.04, frameMat, 0, 0.42, -0.6, g);

  [-1.1, 1.1].forEach(function(x) {
    // Track body — elongated capsule profile
    var track = mk(new THREE.CapsuleGeometry(0.24, 2.9, 5, 12), darkMat, x, 0.24, 0, g);
    track.rotation.x = Math.PI / 2;

    // Track top rail
    rbox(0.4, 0.07, 2.7, 0.03, darkMat, x, 0.5, 0, g);

    // Drive sprocket drum (rear, larger)
    mkr(new THREE.CylinderGeometry(0.3, 0.3, 0.36, 14), darkMat, x, 0.26, -1.55, 0, 0, Math.PI / 2, g);
    // Sprocket hub cap
    mkr(new THREE.CylinderGeometry(0.15, 0.15, 0.38, 10), metalMat, x, 0.26, -1.55, 0, 0, Math.PI / 2, g);

    // Idler drum (front, smaller)
    mkr(new THREE.CylinderGeometry(0.22, 0.22, 0.34, 14), darkMat, x, 0.24, 1.55, 0, 0, Math.PI / 2, g);
    // Idler hub cap
    mkr(new THREE.CylinderGeometry(0.11, 0.11, 0.36, 10), metalMat, x, 0.24, 1.55, 0, 0, Math.PI / 2, g);

    // Road wheels (4 visible underneath)
    for (var rw = -0.9; rw <= 0.9; rw += 0.6) {
      mkr(new THREE.CylinderGeometry(0.14, 0.14, 0.3, 10), frameMat, x, 0.12, rw, 0, 0, Math.PI / 2, g);
    }

    // Track guide (inner strip)
    var side = x > 0 ? -1 : 1;
    rbox(0.08, 0.05, 2.5, 0.02, frameMat, x + side * 0.12, 0.5, 0, g);
  });

  // ── Turntable / slew ring ──────────────────────────────
  mk(new THREE.CylinderGeometry(1.0, 1.1, 0.12, 24), frameMat, 0, 0.56, 0, g);
  mk(new THREE.CylinderGeometry(0.85, 0.85, 0.06, 20), metalMat, 0, 0.62, 0, g);

  // ── Upper body platform ────────────────────────────────
  rbox(2.05, 0.35, 2.4, 0.18, bodyMat, 0, 0.65, -0.1, g);

  // ── Counterweight (rear — half-cylinder, rounded) ──────
  var cwGeo = new THREE.CylinderGeometry(1.02, 1.02, 0.7, 16, 1, false, Math.PI * 0.7, Math.PI * 0.6);
  var cw = mk(cwGeo, bodyMat, 0, 1.15, -0.15, g);
  // Counterweight rear cap (solid rounded feel)
  rbox(1.85, 0.5, 0.6, 0.15, bodyMat, 0, 1.0, -1.25, g);

  // ── Engine deck ────────────────────────────────────────
  rbox(1.6, 0.38, 1.2, 0.12, bodyMat, 0.1, 1.0, -0.6, g);
  // Engine grille lines (3 subtle horizontal strips)
  for (var gl = 0; gl < 3; gl++) {
    rbox(0.7, 0.025, 0.06, 0.01, darkMat, 0.7, 1.18 + gl * 0.1, -1.15, g);
  }
  // Exhaust stack
  mk(new THREE.CylinderGeometry(0.06, 0.05, 0.35, 8), darkMat, 0.55, 1.6, -0.7, g);
  mk(new THREE.CylinderGeometry(0.08, 0.06, 0.06, 8), darkMat, 0.55, 1.8, -0.7, g);

  // ── Operator cab (offset left) ─────────────────────────
  rbox(1.1, 1.0, 1.15, 0.13, bodyMat, -0.35, 1.0, 0.5, g);
  // Cab roof overhang
  rbox(1.2, 0.06, 1.25, 0.1, bodyMat, -0.35, 2.02, 0.52, g);

  // Cab glass — front windshield (slight forward lean)
  var windshield = mk(new THREE.PlaneGeometry(0.9, 0.7), glassMat, -0.35, 1.6, 1.08, g);
  windshield.rotation.x = -0.12;
  // Left side glass
  mk(new THREE.PlaneGeometry(0.95, 0.7), glassMat, -0.91, 1.6, 0.5, g).rotation.y = -Math.PI / 2;
  // Right side glass
  mk(new THREE.PlaneGeometry(0.95, 0.7), glassMat, 0.21, 1.6, 0.5, g).rotation.y = Math.PI / 2;
  // Rear cab glass (smaller)
  mk(new THREE.PlaneGeometry(0.8, 0.45), glassMat, -0.35, 1.65, -0.07, g).rotation.y = Math.PI;

  // ── Boom (heavy capsule arm) ───────────────────────────
  // Main boom — from cab area upward then forward
  var boomLen = 2.8;
  var boom = mk(new THREE.CapsuleGeometry(0.16, boomLen, 5, 10), bodyMat, 0.35, 2.05, 1.9, g);
  boom.rotation.x = Math.PI / 2 + 0.35;
  // Boom side plates (flanges for realism)
  [-0.18, 0.18].forEach(function(dx) {
    var flange = mk(new THREE.CapsuleGeometry(0.04, 2.0, 3, 6), bodyMat, 0.35 + dx, 2.05, 1.6, g);
    flange.rotation.x = Math.PI / 2 + 0.35;
  });

  // Boom hydraulic ram (body-to-boom, thin cylinder parallel)
  var boomRam = mk(new THREE.CapsuleGeometry(0.035, 1.4, 3, 6), metalMat, 0.35, 2.5, 1.2, g);
  boomRam.rotation.x = Math.PI / 2 + 0.55;
  // Ram piston (thinner, extends forward)
  var boomPiston = mk(new THREE.CapsuleGeometry(0.025, 0.8, 3, 6), metalMat, 0.35, 2.15, 2.1, g);
  boomPiston.rotation.x = Math.PI / 2 + 0.35;

  // ── Stick / arm (thinner capsule) ──────────────────────
  var stick = mk(new THREE.CapsuleGeometry(0.12, 2.0, 4, 8), bodyMat, 0.35, 1.25, 3.75, g);
  stick.rotation.x = Math.PI / 2 - 0.45;

  // Stick hydraulic cylinder (boom-to-stick)
  var stickRam = mk(new THREE.CapsuleGeometry(0.03, 1.0, 3, 6), metalMat, 0.35, 2.0, 3.0, g);
  stickRam.rotation.x = Math.PI / 2 - 0.1;
  var stickPiston = mk(new THREE.CapsuleGeometry(0.02, 0.6, 3, 6), metalMat, 0.35, 1.55, 3.6, g);
  stickPiston.rotation.x = Math.PI / 2 - 0.35;

  // ── Bucket ─────────────────────────────────────────────
  // Curved scoop (cylinder segment — wider for realism)
  mk(new THREE.CylinderGeometry(0.42, 0.42, 0.9, 10, 1, true, -0.95, 1.9), metalMat, 0.35, 0.32, 4.6, g);
  // Bucket back plate (solid fill)
  var backPlate = mk(new THREE.CapsuleGeometry(0.38, 0.15, 4, 8), metalMat, 0.35, 0.42, 4.3, g);
  backPlate.rotation.x = Math.PI / 2 - 0.5;

  // Bucket connecting link (visible linkage)
  mk(new THREE.CapsuleGeometry(0.025, 0.4, 3, 6), frameMat, 0.35, 0.7, 4.35, g);
  mk(new THREE.CapsuleGeometry(0.025, 0.3, 3, 6), frameMat, 0.2, 0.65, 4.25, g).rotation.z = 0.3;

  // Bucket teeth (6 cones along lip)
  for (var t = -0.35; t <= 0.35; t += 0.14) {
    var tooth = mk(new THREE.ConeGeometry(0.03, 0.12, 5), darkMat, 0.35 + t, 0.12, 4.95, g);
    tooth.rotation.x = Math.PI / 2;
  }

  // ── Bucket hydraulic cylinder ──────────────────────────
  var bucketRam = mk(new THREE.CapsuleGeometry(0.025, 0.7, 3, 6), metalMat, 0.5, 1.0, 4.0, g);
  bucketRam.rotation.x = Math.PI / 2 - 0.6;

  return g;
};
