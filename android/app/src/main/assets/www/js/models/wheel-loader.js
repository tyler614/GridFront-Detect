/* ═══════════════════════════════════════════════════════════
   GridFront Detect — Wheel Loader Model
   Depends on: materials.js (GF.mk, GF.mkr, GF.rbox, GF.mkWheel)
   ═══════════════════════════════════════════════════════════ */
window.GF = window.GF || {};
GF.models = GF.models || {};

GF.models.wheel_loader = function() {
  var mk = GF.mk, mkr = GF.mkr, rbox = GF.rbox, mkWheel = GF.mkWheel;

  var g = new THREE.Group();
  var hb = new THREE.MeshStandardMaterial({ color: '#4B5563', metalness: 0.3, roughness: 0.5 });
  var hd = new THREE.MeshStandardMaterial({ color: '#1F2937', roughness: 0.8 });
  var hg = new THREE.MeshStandardMaterial({ color: '#64748B', metalness: 0.5, roughness: 0.2, transparent: true, opacity: 0.5 });
  var hHub = new THREE.MeshStandardMaterial({ color: '#374151', metalness: 0.4, roughness: 0.5 });

  // Rear body (rounded)
  rbox(2.1, 1.0, 1.8, 0.2, hb, 0, 0.5, -0.9, g);
  // Engine hood (rounded top)
  rbox(1.8, 0.5, 1.4, 0.15, hb, 0, 1.5, -1.0, g);
  mk(new THREE.CylinderGeometry(0.06, 0.05, 0.6, 8), hd, -0.7, 2.3, -1.0, g);
  // Articulation joint
  mk(new THREE.CylinderGeometry(0.3, 0.3, 0.6, 16), hd, 0, 1.1, 0, g);
  // Front body
  rbox(2.0, 0.8, 1.6, 0.18, hb, 0, 0.55, 1.0, g);
  // Cab — rounded box
  rbox(1.5, 1.2, 1.4, 0.15, hb, 0, 1.6, -0.1, g);
  // Cab roof — rounded
  rbox(1.6, 0.08, 1.5, 0.12, hb, 0, 2.8, -0.1, g);
  // Windshield (curved via cylinder segment)
  var windshield = mk(new THREE.CylinderGeometry(1.2, 1.2, 1.35, 16, 1, true, -0.35, 0.7), hg, 0, 2.25, 0.3, g);
  // Side windows
  mk(new THREE.PlaneGeometry(1.2, 0.85), hg, -0.74, 2.25, -0.1, g).rotation.y = -Math.PI / 2;
  mk(new THREE.PlaneGeometry(1.2, 0.85), hg, 0.74, 2.25, -0.1, g).rotation.y = Math.PI / 2;
  // Boom arms (capsules for roundness)
  [-0.5, 0.5].forEach(function(x) {
    var arm = mk(new THREE.CapsuleGeometry(0.07, 2.2, 4, 8), hb, x, 1.55, 2.0, g);
    arm.rotation.x = Math.PI / 2 + 0.15;
  });
  // Bucket — curved scoop via cylinder segment
  var scoop = mk(new THREE.CylinderGeometry(0.7, 0.7, 1.9, 12, 1, true, -0.8, 1.6), hb, 0, 0.75, 3.2, g);
  // Bucket lip
  mk(new THREE.CylinderGeometry(0.04, 0.04, 1.9, 8), hd, 0, 0.55, 3.7, g).rotation.z = Math.PI / 2;
  // Bucket teeth
  for (var bt = -0.7; bt <= 0.7; bt += 0.28) {
    mk(new THREE.ConeGeometry(0.04, 0.14, 6), hd, bt, 0.5, 3.8, g).rotation.x = Math.PI / 2;
  }
  // Wheels
  mkWheel(0.55, 0.4, -1.15, 0.55, -1.1, g, hd, hHub);
  mkWheel(0.55, 0.4, 1.15, 0.55, -1.1, g, hd, hHub);
  mkWheel(0.55, 0.4, -1.10, 0.55, 1.1, g, hd, hHub);
  mkWheel(0.55, 0.4, 1.10, 0.55, 1.1, g, hd, hHub);
  // Rounded fenders (half-cylinder)
  [-1.1, 1.1].forEach(function(x) {
    [-1.1, 1.1].forEach(function(z) {
      var f = mk(new THREE.CylinderGeometry(0.35, 0.35, 0.45, 12, 1, true, 0, Math.PI), hb, x, 0.85, z, g);
      f.rotation.y = (x > 0) ? Math.PI / 2 : -Math.PI / 2;
    });
  });
  return g;
};
