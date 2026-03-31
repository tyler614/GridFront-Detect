/* ═══════════════════════════════════════════════════════════
   GridFront Detect — Dump Truck Model (CAT 740 style)
   Articulated dump truck: L~10.6m, W~3.5m, H~3.7m
   Depends on: materials.js (GF.mk, GF.mkr, GF.rbox, GF.mkWheel, GF.bodyMat, GF.darkMat, GF.glassMat, GF.metalMat, GF.frameMat)
   ═══════════════════════════════════════════════════════════ */
window.GF = window.GF || {};
GF.models = GF.models || {};

GF.models.dump_truck = function() {
  var mk = GF.mk, mkr = GF.mkr, rbox = GF.rbox, mkWheel = GF.mkWheel;
  var bodyMat = GF.bodyMat, darkMat = GF.darkMat, glassMat = GF.glassMat;
  var metalMat = GF.metalMat, frameMat = GF.frameMat;

  var g = new THREE.Group();

  // ── Front section group (cab + engine + front axle) ─────
  var front = new THREE.Group();
  g.add(front);

  // Front chassis rail — bottom raised to y=0.65 (above 0.60m wheel radius)
  rbox(1.2, 0.25, 3.0, 0.08, frameMat, 0, 0.65, 2.8, front);

  // Engine hood — raised 0.10m to sit above new wheel height
  rbox(2.2, 0.9, 1.6, 0.2, bodyMat, 0, 1.10, 3.6, front);

  // Engine hood top grill detail
  rbox(1.6, 0.06, 1.0, 0.04, darkMat, 0, 1.62, 3.7, front);

  // Radiator grille (front face)
  rbox(1.8, 0.7, 0.08, 0.06, darkMat, 0, 1.20, 4.42, front);

  // Cab body — raised 0.10m
  rbox(2.2, 1.3, 1.5, 0.22, bodyMat, 0, 1.20, 2.2, front);

  // Cab roof — raised 0.10m
  rbox(2.3, 0.08, 1.6, 0.16, bodyMat, 0, 2.58, 2.15, front);

  // Windshield — curved cylinder segment for convex glass; raised 0.10m
  mk(new THREE.CylinderGeometry(2.0, 2.0, 1.9, 14, 1, true, -0.27, 0.54),
     glassMat, 0, 2.05, 2.7, front);

  // Rear cab window — raised 0.10m
  mk(new THREE.PlaneGeometry(1.5, 0.6), glassMat, 0, 2.10, 1.44, front);

  // Side windows (left + right) — raised 0.10m
  mk(new THREE.PlaneGeometry(1.1, 0.7), glassMat, -1.1, 2.05, 2.2, front).rotation.y = -Math.PI / 2;
  mk(new THREE.PlaneGeometry(1.1, 0.7), glassMat, 1.1, 2.05, 2.2, front).rotation.y = Math.PI / 2;

  // Front fenders — half-sphere arches over front wheels; raised to clear 0.60m wheels
  [-1.3, 1.3].forEach(function(x) {
    var f = mk(new THREE.SphereGeometry(0.48, 10, 6, 0, Math.PI * 2, 0, Math.PI * 0.5),
               bodyMat, x, 0.85, 3.6, front);
    f.scale.set(1.1, 0.5, 1.3);
  });

  // Exhaust stack — thin cylinder on left side of cab; raised 0.10m
  mkr(new THREE.CylinderGeometry(0.06, 0.07, 1.2, 8),
      darkMat, -1.25, 2.10, 2.9, 0, 0, 0, front);

  // Exhaust cap — small disc at top; raised 0.10m
  mk(new THREE.CylinderGeometry(0.09, 0.09, 0.04, 8),
     darkMat, -1.25, 2.72, 2.9, front);

  // Front headlights — raised 0.10m
  [-0.75, 0.75].forEach(function(x) {
    mk(new THREE.SphereGeometry(0.08, 6, 6), glassMat, x, 1.30, 4.44, front);
  });

  // Front axle crossbeam — raised to wheel center height (0.60m)
  mkr(new THREE.CapsuleGeometry(0.08, 2.0, 4, 8),
      frameMat, 0, 0.6, 3.6, 0, 0, Math.PI / 2, front);

  // Front wheels — 0.60m radius (CAT 740 ~23.5R25 tires); y_center = radius
  mkWheel(0.6, 0.38, -1.4, 0.6, 3.6, front, darkMat, metalMat);
  mkWheel(0.6, 0.38, 1.4, 0.6, 3.6, front, darkMat, metalMat);

  // ── Articulation joint ──────────────────────────────────
  // Central pivot cylinder
  mkr(new THREE.CylinderGeometry(0.2, 0.2, 0.6, 12),
      frameMat, 0, 0.65, 1.25, 0, 0, 0, g);

  // Pivot housing — rounded ring
  mk(new THREE.TorusGeometry(0.25, 0.08, 8, 16),
     frameMat, 0, 0.65, 1.25, g).rotation.x = Math.PI / 2;

  // ── Rear section group (dump bed + rear axles) ──────────
  var rear = new THREE.Group();
  g.add(rear);

  // Rear chassis rail — bottom at y=0.65 (above 0.60m wheel radius)
  rbox(1.4, 0.25, 4.5, 0.08, frameMat, 0, 0.65, -1.2, rear);

  // ── Dump bed ────────────────────────────────────────────
  // V-shaped bed: wider at top, narrower at bottom; raised 0.10m with wheel height
  // Bed floor — narrow bottom
  rbox(1.4, 0.1, 4.0, 0.06, metalMat, 0, 0.98, -1.2, rear);

  // Left bed wall — angled outward (tapered)
  var leftWall = mk(new THREE.PlaneGeometry(4.0, 1.2), metalMat,
                    -1.05, 1.58, -1.2, rear);
  leftWall.rotation.y = -Math.PI / 2;
  leftWall.rotation.x = 0.15; // slight outward lean

  var rightWall = mk(new THREE.PlaneGeometry(4.0, 1.2), metalMat,
                     1.05, 1.58, -1.2, rear);
  rightWall.rotation.y = Math.PI / 2;
  rightWall.rotation.x = 0.15;

  // Bed wall top rails — rounded caps along top edge; raised 0.10m
  mkr(new THREE.CapsuleGeometry(0.05, 3.8, 3, 8),
      metalMat, -1.1, 2.18, -1.2, Math.PI / 2, 0, 0, rear);
  mkr(new THREE.CapsuleGeometry(0.05, 3.8, 3, 8),
      metalMat, 1.1, 2.18, -1.2, Math.PI / 2, 0, 0, rear);

  // Bed front wall (bulkhead) — raised 0.10m
  rbox(2.1, 1.2, 0.08, 0.05, metalMat, 0, 1.05, 0.82, rear);

  // Bed front wall upper reinforcement — raised 0.10m
  rbox(2.2, 0.12, 0.12, 0.04, metalMat, 0, 2.22, 0.82, rear);

  // Tailgate — rear panel; raised 0.10m
  rbox(2.1, 0.9, 0.08, 0.05, metalMat, 0, 1.25, -3.22, rear);

  // Tailgate hinge bar — raised 0.10m
  mkr(new THREE.CapsuleGeometry(0.04, 1.8, 3, 8),
      frameMat, 0, 2.18, -3.22, 0, 0, Math.PI / 2, rear);

  // Bed V-shape reinforcement ribs (3 cross-braces underneath); raised 0.10m
  [-0.3, -1.2, -2.1].forEach(function(z) {
    mkr(new THREE.CapsuleGeometry(0.04, 1.2, 3, 6),
        frameMat, 0, 0.88, z, 0, 0, Math.PI / 2, rear);
  });

  // ── Rear axle 1 (dual wheels) ───────────────────────────
  var rearAxle1Z = -1.0;

  // Axle crossbeam — at wheel center height 0.60m
  mkr(new THREE.CapsuleGeometry(0.08, 2.4, 4, 8),
      frameMat, 0, 0.6, rearAxle1Z, 0, 0, Math.PI / 2, rear);

  // Left dual wheels — 0.60m radius; y_center = radius = 0.60
  mkWheel(0.6, 0.28, -1.45, 0.6, rearAxle1Z, rear, darkMat, metalMat);
  mkWheel(0.6, 0.28, -1.05, 0.6, rearAxle1Z, rear, darkMat, metalMat);
  // Right dual wheels
  mkWheel(0.6, 0.28, 1.05, 0.6, rearAxle1Z, rear, darkMat, metalMat);
  mkWheel(0.6, 0.28, 1.45, 0.6, rearAxle1Z, rear, darkMat, metalMat);

  // ── Rear axle 2 (dual wheels) ───────────────────────────
  var rearAxle2Z = -2.2;

  // Axle crossbeam — at wheel center height 0.60m
  mkr(new THREE.CapsuleGeometry(0.08, 2.4, 4, 8),
      frameMat, 0, 0.6, rearAxle2Z, 0, 0, Math.PI / 2, rear);

  // Left dual wheels — 0.60m radius; y_center = radius = 0.60
  mkWheel(0.6, 0.28, -1.45, 0.6, rearAxle2Z, rear, darkMat, metalMat);
  mkWheel(0.6, 0.28, -1.05, 0.6, rearAxle2Z, rear, darkMat, metalMat);
  // Right dual wheels
  mkWheel(0.6, 0.28, 1.05, 0.6, rearAxle2Z, rear, darkMat, metalMat);
  mkWheel(0.6, 0.28, 1.45, 0.6, rearAxle2Z, rear, darkMat, metalMat);

  // ── Rear fender mudguards over dual wheels ──────────────
  [-1, 1].forEach(function(side) {
    var sx = side * 1.25;
    // Fender over axle 1 — raised 0.10m
    rbox(0.9, 0.06, 0.9, 0.06, bodyMat, sx, 1.25, rearAxle1Z, rear);
    // Fender over axle 2
    rbox(0.9, 0.06, 0.9, 0.06, bodyMat, sx, 1.25, rearAxle2Z, rear);
  });

  // ── Rear tail lights — raised 0.10m ─────────────────────
  [-0.7, 0.7].forEach(function(x) {
    mk(new THREE.SphereGeometry(0.06, 6, 6), darkMat, x, 1.50, -3.28, rear);
  });

  return g;
};
