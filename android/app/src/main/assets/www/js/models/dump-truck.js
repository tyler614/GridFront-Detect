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

  // Front chassis rail
  rbox(1.2, 0.25, 3.0, 0.08, frameMat, 0, 0.55, 2.8, front);

  // Engine hood — long rounded block forward of cab
  rbox(2.2, 0.9, 1.6, 0.2, bodyMat, 0, 1.0, 3.6, front);

  // Engine hood top grill detail
  rbox(1.6, 0.06, 1.0, 0.04, darkMat, 0, 1.52, 3.7, front);

  // Radiator grille (front face)
  rbox(1.8, 0.7, 0.08, 0.06, darkMat, 0, 1.1, 4.42, front);

  // Cab body — rounded box
  rbox(2.2, 1.3, 1.5, 0.22, bodyMat, 0, 1.1, 2.2, front);

  // Cab roof — slight overhang
  rbox(2.3, 0.08, 1.6, 0.16, bodyMat, 0, 2.48, 2.15, front);

  // Windshield — curved cylinder segment for convex glass
  mk(new THREE.CylinderGeometry(2.0, 2.0, 1.9, 14, 1, true, -0.27, 0.54),
     glassMat, 0, 1.95, 2.7, front);

  // Rear cab window
  mk(new THREE.PlaneGeometry(1.5, 0.6), glassMat, 0, 2.0, 1.44, front);

  // Side windows (left + right)
  mk(new THREE.PlaneGeometry(1.1, 0.7), glassMat, -1.1, 1.95, 2.2, front).rotation.y = -Math.PI / 2;
  mk(new THREE.PlaneGeometry(1.1, 0.7), glassMat, 1.1, 1.95, 2.2, front).rotation.y = Math.PI / 2;

  // Front fenders — half-sphere arches over front wheels
  [-1.3, 1.3].forEach(function(x) {
    var f = mk(new THREE.SphereGeometry(0.42, 10, 6, 0, Math.PI * 2, 0, Math.PI * 0.5),
               bodyMat, x, 0.75, 3.6, front);
    f.scale.set(1.1, 0.5, 1.3);
  });

  // Exhaust stack — thin cylinder on left side of cab
  mkr(new THREE.CylinderGeometry(0.06, 0.07, 1.2, 8),
      darkMat, -1.25, 2.0, 2.9, 0, 0, 0, front);

  // Exhaust cap — small disc at top
  mk(new THREE.CylinderGeometry(0.09, 0.09, 0.04, 8),
     darkMat, -1.25, 2.62, 2.9, front);

  // Front headlights
  [-0.75, 0.75].forEach(function(x) {
    mk(new THREE.SphereGeometry(0.08, 6, 6), glassMat, x, 1.2, 4.44, front);
  });

  // Front axle crossbeam
  mkr(new THREE.CapsuleGeometry(0.08, 2.0, 4, 8),
      frameMat, 0, 0.5, 3.6, 0, 0, Math.PI / 2, front);

  // Front wheels (single per side — 1 axle, 2 wheels)
  mkWheel(0.5, 0.38, -1.4, 0.5, 3.6, front, darkMat, metalMat);
  mkWheel(0.5, 0.38, 1.4, 0.5, 3.6, front, darkMat, metalMat);

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

  // Rear chassis rail — extends under bed
  rbox(1.4, 0.25, 4.5, 0.08, frameMat, 0, 0.55, -1.2, rear);

  // ── Dump bed ────────────────────────────────────────────
  // V-shaped bed: wider at top, narrower at bottom
  // Bed floor — narrow bottom
  rbox(1.4, 0.1, 4.0, 0.06, metalMat, 0, 0.88, -1.2, rear);

  // Left bed wall — angled outward (tapered)
  var leftWall = mk(new THREE.PlaneGeometry(4.0, 1.2), metalMat,
                    -1.05, 1.48, -1.2, rear);
  leftWall.rotation.y = -Math.PI / 2;
  leftWall.rotation.x = 0.15; // slight outward lean

  var rightWall = mk(new THREE.PlaneGeometry(4.0, 1.2), metalMat,
                     1.05, 1.48, -1.2, rear);
  rightWall.rotation.y = Math.PI / 2;
  rightWall.rotation.x = 0.15;

  // Bed wall top rails — rounded caps along top edge
  mkr(new THREE.CapsuleGeometry(0.05, 3.8, 3, 8),
      metalMat, -1.1, 2.08, -1.2, Math.PI / 2, 0, 0, rear);
  mkr(new THREE.CapsuleGeometry(0.05, 3.8, 3, 8),
      metalMat, 1.1, 2.08, -1.2, Math.PI / 2, 0, 0, rear);

  // Bed front wall (bulkhead)
  rbox(2.1, 1.2, 0.08, 0.05, metalMat, 0, 0.95, 0.82, rear);

  // Bed front wall upper reinforcement
  rbox(2.2, 0.12, 0.12, 0.04, metalMat, 0, 2.12, 0.82, rear);

  // Tailgate — rear panel
  rbox(2.1, 0.9, 0.08, 0.05, metalMat, 0, 1.15, -3.22, rear);

  // Tailgate hinge bar
  mkr(new THREE.CapsuleGeometry(0.04, 1.8, 3, 8),
      frameMat, 0, 2.08, -3.22, 0, 0, Math.PI / 2, rear);

  // Bed V-shape reinforcement ribs (3 cross-braces underneath)
  [-0.3, -1.2, -2.1].forEach(function(z) {
    mkr(new THREE.CapsuleGeometry(0.04, 1.2, 3, 6),
        frameMat, 0, 0.78, z, 0, 0, Math.PI / 2, rear);
  });

  // ── Rear axle 1 (dual wheels) ───────────────────────────
  var rearAxle1Z = -1.0;

  // Axle crossbeam
  mkr(new THREE.CapsuleGeometry(0.08, 2.4, 4, 8),
      frameMat, 0, 0.5, rearAxle1Z, 0, 0, Math.PI / 2, rear);

  // Left dual wheels
  mkWheel(0.5, 0.28, -1.45, 0.5, rearAxle1Z, rear, darkMat, metalMat);
  mkWheel(0.5, 0.28, -1.05, 0.5, rearAxle1Z, rear, darkMat, metalMat);
  // Right dual wheels
  mkWheel(0.5, 0.28, 1.05, 0.5, rearAxle1Z, rear, darkMat, metalMat);
  mkWheel(0.5, 0.28, 1.45, 0.5, rearAxle1Z, rear, darkMat, metalMat);

  // ── Rear axle 2 (dual wheels) ───────────────────────────
  var rearAxle2Z = -2.2;

  // Axle crossbeam
  mkr(new THREE.CapsuleGeometry(0.08, 2.4, 4, 8),
      frameMat, 0, 0.5, rearAxle2Z, 0, 0, Math.PI / 2, rear);

  // Left dual wheels
  mkWheel(0.5, 0.28, -1.45, 0.5, rearAxle2Z, rear, darkMat, metalMat);
  mkWheel(0.5, 0.28, -1.05, 0.5, rearAxle2Z, rear, darkMat, metalMat);
  // Right dual wheels
  mkWheel(0.5, 0.28, 1.05, 0.5, rearAxle2Z, rear, darkMat, metalMat);
  mkWheel(0.5, 0.28, 1.45, 0.5, rearAxle2Z, rear, darkMat, metalMat);

  // ── Rear fender mudguards over dual wheels ──────────────
  [-1, 1].forEach(function(side) {
    var sx = side * 1.25;
    // Fender over axle 1
    rbox(0.9, 0.06, 0.9, 0.06, bodyMat, sx, 1.05, rearAxle1Z, rear);
    // Fender over axle 2
    rbox(0.9, 0.06, 0.9, 0.06, bodyMat, sx, 1.05, rearAxle2Z, rear);
  });

  // ── Rear tail lights ────────────────────────────────────
  [-0.7, 0.7].forEach(function(x) {
    mk(new THREE.SphereGeometry(0.06, 6, 6), darkMat, x, 1.4, -3.28, rear);
  });

  return g;
};
