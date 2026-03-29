/* ═══════════════════════════════════════════════════════════
   GridFront Detect — Excavator Model
   Depends on: materials.js (GF.mk, GF.mkr, GF.rbox, GF.bodyMat, GF.darkMat, GF.glassMat, GF.metalMat)
   ═══════════════════════════════════════════════════════════ */
window.GF = window.GF || {};
GF.models = GF.models || {};

GF.models.excavator = function() {
  var mk = GF.mk, mkr = GF.mkr, rbox = GF.rbox;
  var bodyMat = GF.bodyMat, darkMat = GF.darkMat, glassMat = GF.glassMat, metalMat = GF.metalMat;

  var g = new THREE.Group();
  // Tracks — rounded capsule shape with sprocket drums
  [-1.1, 1.1].forEach(function(x) {
    // Track body — capsule laid flat
    var track = mk(new THREE.CapsuleGeometry(0.22, 2.8, 5, 12), darkMat, x, 0.22, 0, g);
    track.rotation.x = Math.PI / 2;
    // Track top rail
    rbox(0.38, 0.06, 2.6, 0.03, darkMat, x, 0.46, 0, g);
    // Drive sprocket (rear)
    mkr(new THREE.CylinderGeometry(0.26, 0.26, 0.32, 14), darkMat, x, 0.24, -1.5, 0, 0, Math.PI / 2, g);
    // Idler (front)
    mkr(new THREE.CylinderGeometry(0.20, 0.20, 0.32, 14), darkMat, x, 0.24, 1.5, 0, 0, Math.PI / 2, g);
  });
  // Turntable
  mk(new THREE.CylinderGeometry(0.95, 1.05, 0.18, 24), bodyMat, 0, 0.58, 0, g);
  // Upper body — rounded
  rbox(2.0, 0.85, 2.3, 0.2, bodyMat, 0, 0.65, -0.15, g);
  // Counterweight (rear — half cylinder)
  var cw = mk(new THREE.CylinderGeometry(1.0, 1.0, 0.8, 20, 1, false, Math.PI * 0.65, Math.PI * 0.7), bodyMat, 0, 1.1, -0.2, g);
  // Engine deck (rounded)
  rbox(1.7, 0.3, 1.1, 0.12, bodyMat, 0, 1.5, -0.75, g);
  // Cab — rounded
  rbox(1.15, 0.95, 1.2, 0.12, bodyMat, -0.3, 1.5, 0.45, g);
  // Cab windows (planes — thin and clean)
  mk(new THREE.PlaneGeometry(0.95, 0.65), glassMat, -0.3, 2.05, 1.06, g);
  mk(new THREE.PlaneGeometry(1.0, 0.65), glassMat, -0.86, 2.05, 0.45, g).rotation.y = -Math.PI / 2;
  mk(new THREE.PlaneGeometry(1.0, 0.65), glassMat, 0.26, 2.05, 0.45, g).rotation.y = Math.PI / 2;
  // Boom — capsule
  var boom = mk(new THREE.CapsuleGeometry(0.14, 2.6, 4, 10), bodyMat, 0.35, 2.0, 2.1, g);
  boom.rotation.x = Math.PI / 2 + 0.3;
  // Stick — thinner capsule
  var stick = mk(new THREE.CapsuleGeometry(0.11, 1.8, 4, 8), bodyMat, 0.35, 1.3, 3.7, g);
  stick.rotation.x = Math.PI / 2 - 0.4;
  // Bucket — curved scoop
  var bkt = mk(new THREE.CylinderGeometry(0.4, 0.4, 0.85, 10, 1, true, -0.9, 1.8), metalMat, 0.35, 0.35, 4.6, g);
  // Bucket teeth
  for (var et = -0.3; et <= 0.3; et += 0.12) {
    mk(new THREE.ConeGeometry(0.03, 0.1, 5), darkMat, 0.35 + et, 0.15, 4.9, g).rotation.x = Math.PI / 2;
  }
  // Hydraulic cylinders (thin capsules)
  var hyd1 = mk(new THREE.CapsuleGeometry(0.03, 1.2, 3, 6), metalMat, 0.35, 2.4, 1.4, g);
  hyd1.rotation.x = Math.PI / 2 + 0.5;
  return g;
};
