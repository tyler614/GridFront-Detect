/* ═══════════════════════════════════════════════════════════
   GridFront Detect — Dump Truck Model
   Depends on: materials.js (GF.mk, GF.rbox, GF.mkWheel, GF.bodyMat, GF.darkMat, GF.glassMat, GF.metalMat)
   ═══════════════════════════════════════════════════════════ */
window.GF = window.GF || {};
GF.models = GF.models || {};

GF.models.dump_truck = function() {
  var mk = GF.mk, rbox = GF.rbox, mkWheel = GF.mkWheel;
  var bodyMat = GF.bodyMat, darkMat = GF.darkMat, glassMat = GF.glassMat, metalMat = GF.metalMat;

  var g = new THREE.Group();
  var hubMat = new THREE.MeshStandardMaterial({ color: '#6B7280', metalness: 0.3, roughness: 0.5 });
  // Chassis — rounded rail
  rbox(0.7, 0.22, 5.6, 0.08, darkMat, 0, 0.45, 0, g);
  // Hood/engine — smooth rounded shape
  rbox(1.9, 0.85, 0.9, 0.2, bodyMat, 0, 0.85, 3.4, g);
  // Cab — rounded
  rbox(2.0, 1.25, 1.3, 0.2, bodyMat, 0, 1.0, 2.2, g);
  // Cab roof — rounded
  rbox(2.05, 0.08, 1.4, 0.15, bodyMat, 0, 2.28, 2.25, g);
  // Windshield — slight curve
  mk(new THREE.CylinderGeometry(1.8, 1.8, 1.75, 12, 1, true, -0.28, 0.56), glassMat, 0, 1.8, 2.55, g);
  // Side windows
  mk(new THREE.PlaneGeometry(0.95, 0.7), glassMat, -0.98, 1.75, 2.2, g).rotation.y = -Math.PI / 2;
  mk(new THREE.PlaneGeometry(0.95, 0.7), glassMat, 0.98, 1.75, 2.2, g).rotation.y = Math.PI / 2;
  // Dump bed floor — slight curve
  rbox(2.15, 0.1, 3.6, 0.06, metalMat, 0, 0.88, -0.65, g);
  // Dump bed sides — slight inward taper at top
  mk(new THREE.PlaneGeometry(3.6, 1.0), metalMat, -1.05, 1.38, -0.65, g).rotation.y = -Math.PI / 2;
  mk(new THREE.PlaneGeometry(3.6, 1.0), metalMat, 1.05, 1.38, -0.65, g).rotation.y = Math.PI / 2;
  // Bed front wall
  rbox(2.1, 1.15, 0.06, 0.04, metalMat, 0, 0.93, 1.15, g);
  // Tailgate
  rbox(2.1, 0.65, 0.06, 0.04, metalMat, 0, 1.1, -2.5, g);
  // Front wheels
  mkWheel(0.45, 0.35, -1.15, 0.45, 2.8, g, darkMat, hubMat);
  mkWheel(0.45, 0.35, 1.15, 0.45, 2.8, g, darkMat, hubMat);
  // Rear dual wheels
  mkWheel(0.5, 0.28, -1.2, 0.5, -1.2, g, darkMat, hubMat);
  mkWheel(0.5, 0.28, -0.85, 0.5, -1.2, g, darkMat, hubMat);
  mkWheel(0.5, 0.28, 0.85, 0.5, -1.2, g, darkMat, hubMat);
  mkWheel(0.5, 0.28, 1.2, 0.5, -1.2, g, darkMat, hubMat);
  // Rounded fenders (front)
  [-1.15, 1.15].forEach(function(x) {
    var f = mk(new THREE.SphereGeometry(0.32, 10, 6, 0, Math.PI * 2, 0, Math.PI * 0.5), bodyMat, x, 0.7, 2.8, g);
    f.scale.set(1, 0.5, 1);
  });
  return g;
};
