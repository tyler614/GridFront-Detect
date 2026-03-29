/* ═══════════════════════════════════════════════════════════
   GridFront Detect — Dozer Model (CAT D6 style)
   Depends on: materials.js (GF.mk, GF.mkr, GF.rbox, GF.bodyMat, GF.darkMat, GF.glassMat, GF.metalMat, GF.frameMat)
   Dimensions: L 4.7m  W 2.7m  H 3.1m — under 1500 triangles
   ═══════════════════════════════════════════════════════════ */
window.GF = window.GF || {};
GF.models = GF.models || {};

GF.models.dozer = function() {
  var mk = GF.mk, mkr = GF.mkr, rbox = GF.rbox;
  var bodyMat = GF.bodyMat, darkMat = GF.darkMat, glassMat = GF.glassMat,
      metalMat = GF.metalMat, frameMat = GF.frameMat;

  var g = new THREE.Group();

  /* ── Tracked undercarriage ─────────────────────────────── */
  [-1.15, 1.15].forEach(function(x) {
    // Track body — capsule profile, laid on side
    var track = mk(new THREE.CapsuleGeometry(0.28, 3.2, 5, 12), darkMat, x, 0.28, 0, g);
    track.rotation.x = Math.PI / 2;

    // Top rail — flat bar running along track top
    rbox(0.48, 0.06, 3.0, 0.03, darkMat, x, 0.58, 0, g);

    // Drive sprocket — rear, larger toothed wheel
    mkr(new THREE.CylinderGeometry(0.32, 0.32, 0.40, 12), darkMat, x, 0.30, -1.70, 0, 0, Math.PI / 2, g);
    // Sprocket hub
    mkr(new THREE.CylinderGeometry(0.14, 0.14, 0.44, 8), metalMat, x, 0.30, -1.70, 0, 0, Math.PI / 2, g);

    // Idler wheel — front, slightly smaller
    mkr(new THREE.CylinderGeometry(0.24, 0.24, 0.40, 12), darkMat, x, 0.28, 1.70, 0, 0, Math.PI / 2, g);
    // Idler hub
    mkr(new THREE.CylinderGeometry(0.10, 0.10, 0.44, 8), metalMat, x, 0.28, 1.70, 0, 0, Math.PI / 2, g);

    // Road wheels — 3 evenly spaced along bottom
    [-0.85, 0, 0.85].forEach(function(zp) {
      mkr(new THREE.CylinderGeometry(0.18, 0.18, 0.36, 10), darkMat, x, 0.18, zp, 0, 0, Math.PI / 2, g);
      // Wheel hub cap
      mkr(new THREE.CylinderGeometry(0.08, 0.08, 0.40, 6), metalMat, x, 0.18, zp, 0, 0, Math.PI / 2, g);
    });

    // Track frame — structural side plate
    rbox(0.10, 0.40, 3.0, 0.04, frameMat, x, 0.40, 0, g);
  });

  /* ── Main hull body ────────────────────────────────────── */
  // Lower hull — wide rounded box sitting on tracks
  rbox(2.1, 0.50, 2.8, 0.18, bodyMat, 0, 0.58, -0.05, g);
  // Upper hull taper — slightly narrower
  rbox(1.95, 0.35, 2.5, 0.14, bodyMat, 0, 1.08, -0.15, g);

  /* ── Engine compartment (rear) ─────────────────────────── */
  rbox(1.80, 0.55, 1.30, 0.12, bodyMat, 0, 1.30, -0.85, g);
  // Engine deck louvers — dark grille strip
  rbox(1.50, 0.06, 0.80, 0.03, darkMat, 0, 1.86, -0.85, g);
  // Exhaust stack — vertical pipe
  mkr(new THREE.CylinderGeometry(0.06, 0.07, 0.65, 8), metalMat, -0.55, 1.90, -0.95, 0, 0, 0, g);
  // Exhaust cap
  mkr(new THREE.CylinderGeometry(0.09, 0.09, 0.04, 8), metalMat, -0.55, 2.25, -0.95, 0, 0, 0, g);
  // Pre-cleaner / air intake
  mkr(new THREE.CylinderGeometry(0.07, 0.07, 0.35, 8), metalMat, 0.55, 1.90, -0.95, 0, 0, 0, g);
  mkr(new THREE.SphereGeometry(0.09, 6, 6), metalMat, 0.55, 2.10, -0.95, 0, 0, 0, g);

  /* ── Cab with ROPS ─────────────────────────────────────── */
  // Cab body — rounded box
  rbox(1.30, 1.00, 1.25, 0.12, bodyMat, 0, 1.43, 0.35, g);

  // ROPS posts — 4 thin structural cylinders at cab corners
  var cabL = -0.58, cabR = 0.58, cabF = 0.92, cabB = -0.22;
  var ropsH = 1.10, ropsY = 1.43, ropsR = 0.03;
  [[cabL, cabF], [cabR, cabF], [cabL, cabB], [cabR, cabB]].forEach(function(p) {
    mkr(new THREE.CylinderGeometry(ropsR, ropsR, ropsH, 6), frameMat, p[0], ropsY + ropsH / 2, p[1], 0, 0, 0, g);
  });
  // ROPS top frame — front crossbar
  mkr(new THREE.CylinderGeometry(ropsR, ropsR, 1.16, 6), frameMat, 0, ropsY + ropsH, cabF, 0, 0, Math.PI / 2, g);
  // ROPS top frame — rear crossbar
  mkr(new THREE.CylinderGeometry(ropsR, ropsR, 1.16, 6), frameMat, 0, ropsY + ropsH, cabB, 0, 0, Math.PI / 2, g);
  // ROPS top frame — side rails
  mkr(new THREE.CylinderGeometry(ropsR, ropsR, 1.14, 6), frameMat, cabL, ropsY + ropsH, 0.35, Math.PI / 2, 0, 0, g);
  mkr(new THREE.CylinderGeometry(ropsR, ropsR, 1.14, 6), frameMat, cabR, ropsY + ropsH, 0.35, Math.PI / 2, 0, 0, g);

  // Glass panels — front, left, right
  mk(new THREE.PlaneGeometry(1.05, 0.70), glassMat, 0, 2.00, 0.98, g);
  var gl = mk(new THREE.PlaneGeometry(1.05, 0.70), glassMat, -0.65, 2.00, 0.35, g);
  gl.rotation.y = -Math.PI / 2;
  var gr = mk(new THREE.PlaneGeometry(1.05, 0.70), glassMat, 0.65, 2.00, 0.35, g);
  gr.rotation.y = Math.PI / 2;
  // Rear window — smaller
  var gbk = mk(new THREE.PlaneGeometry(0.90, 0.55), glassMat, 0, 2.00, -0.28, g);
  gbk.rotation.y = Math.PI;

  /* ── Blade ─────────────────────────────────────────────── */
  // Curved blade — cylinder segment, ~2.9m wide
  mk(new THREE.CylinderGeometry(1.8, 1.8, 2.9, 16, 1, true, -0.38, 0.76), metalMat, 0, 0.60, 2.20, g);

  // Blade top edge reinforcement bar
  mkr(new THREE.CylinderGeometry(0.04, 0.04, 2.9, 8), metalMat, 0, 1.15, 1.82, 0, 0, Math.PI / 2, g);

  // Blade cutting edge — dark strip at bottom
  rbox(2.80, 0.08, 0.15, 0.02, darkMat, 0, 0.10, 2.18, g);

  // Push arms — connect blade to track frame, slight angle
  [-0.90, 0.90].forEach(function(x) {
    var arm = mk(new THREE.CapsuleGeometry(0.07, 1.30, 3, 6), frameMat, x, 0.50, 1.50, g);
    arm.rotation.x = Math.PI / 2 - 0.08;
  });

  // Hydraulic tilt cylinders — on push arms
  [-0.75, 0.75].forEach(function(x) {
    var cyl = mk(new THREE.CapsuleGeometry(0.04, 0.70, 3, 6), metalMat, x, 0.85, 1.65, g);
    cyl.rotation.x = 0.45;
  });

  /* ── Ripper (rear) ─────────────────────────────────────── */
  // Ripper frame — horizontal bar across rear
  mkr(new THREE.CylinderGeometry(0.05, 0.05, 1.20, 8), frameMat, 0, 0.55, -2.00, 0, 0, Math.PI / 2, g);

  // Ripper mounting arms — pair angling down from body
  [-0.40, 0.40].forEach(function(x) {
    var mnt = mk(new THREE.CapsuleGeometry(0.04, 0.60, 3, 6), frameMat, x, 0.45, -1.90, g);
    mnt.rotation.x = -0.35;
  });

  // Ripper shank — single angled tooth
  var shank = mk(new THREE.CapsuleGeometry(0.05, 0.55, 3, 6), metalMat, 0, 0.15, -2.15, g);
  shank.rotation.x = -0.30;

  // Ripper tooth tip — cone
  var tip = mk(new THREE.ConeGeometry(0.06, 0.20, 6), metalMat, 0, -0.10, -2.35, g);
  tip.rotation.x = -0.30;

  return g;
};
