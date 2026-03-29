/* ═══════════════════════════════════════════════════════════
   GridFront Detect — Dozer Model
   Depends on: materials.js (GF.mk, GF.mkr, GF.rbox, GF.bodyMat, GF.darkMat, GF.glassMat, GF.metalMat)
   ═══════════════════════════════════════════════════════════ */
window.GF = window.GF || {};
GF.models = GF.models || {};

GF.models.dozer = function() {
  var mk = GF.mk, mkr = GF.mkr, rbox = GF.rbox;
  var bodyMat = GF.bodyMat, darkMat = GF.darkMat, glassMat = GF.glassMat, metalMat = GF.metalMat;

  var g = new THREE.Group();
  // Tracks — capsule profile
  [-1.15, 1.15].forEach(function(x) {
    var track = mk(new THREE.CapsuleGeometry(0.24, 2.8, 5, 12), darkMat, x, 0.24, 0, g);
    track.rotation.x = Math.PI / 2;
    rbox(0.42, 0.06, 2.6, 0.03, darkMat, x, 0.5, 0, g);
    mkr(new THREE.CylinderGeometry(0.28, 0.28, 0.38, 14), darkMat, x, 0.26, 1.55, 0, 0, Math.PI / 2, g);
    mkr(new THREE.CylinderGeometry(0.22, 0.22, 0.38, 14), darkMat, x, 0.24, -1.55, 0, 0, Math.PI / 2, g);
  });
  // Main body — rounded
  rbox(1.9, 0.85, 2.3, 0.2, bodyMat, 0, 0.55, -0.1, g);
  // Engine deck — rounded
  rbox(1.7, 0.4, 1.1, 0.12, bodyMat, 0, 1.4, -0.65, g);
  // Cab — rounded
  rbox(1.3, 0.95, 1.2, 0.12, bodyMat, 0, 1.4, 0.3, g);
  // Windows
  mk(new THREE.PlaneGeometry(1.05, 0.65), glassMat, 0, 1.95, 0.9, g);
  mk(new THREE.PlaneGeometry(1.0, 0.65), glassMat, -0.63, 1.95, 0.3, g).rotation.y = -Math.PI / 2;
  mk(new THREE.PlaneGeometry(1.0, 0.65), glassMat, 0.63, 1.95, 0.3, g).rotation.y = Math.PI / 2;
  // Blade — curved via cylinder segment
  var blade = mk(new THREE.CylinderGeometry(1.6, 1.6, 2.9, 14, 1, true, -0.35, 0.7), metalMat, 0, 0.5, 2.0, g);
  // Blade top edge — rounded
  mk(new THREE.CylinderGeometry(0.04, 0.04, 2.9, 8), metalMat, 0, 1.0, 1.65, g).rotation.z = Math.PI / 2;
  // Push arms — capsules
  [-0.85, 0.85].forEach(function(x) {
    var arm = mk(new THREE.CapsuleGeometry(0.06, 1.0, 3, 6), darkMat, x, 0.5, 1.3, g);
    arm.rotation.x = Math.PI / 2;
  });
  // Ripper (rear)
  mk(new THREE.CapsuleGeometry(0.04, 0.5, 3, 6), darkMat, 0, 0.25, -1.8, g);
  return g;
};
