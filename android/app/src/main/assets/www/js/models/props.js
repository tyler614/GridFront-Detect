/* ═══════════════════════════════════════════════════════════
   GridFront Detect — Props (Cone + Barrier)
   Depends on: materials.js (GF.mk, GF.rbox, GF.darkMat)
   ═══════════════════════════════════════════════════════════ */
window.GF = window.GF || {};
GF.models = GF.models || {};

GF.models.cone = function() {
  var mk = GF.mk, rbox = GF.rbox, darkMat = GF.darkMat;

  var g = new THREE.Group();
  var coneMat = new THREE.MeshStandardMaterial({ color: '#9CA3AF', metalness: 0.1, roughness: 0.7 });
  var stripeMat = new THREE.MeshStandardMaterial({ color: '#D1D5DB', roughness: 0.5 });
  // Rubber base — rounded
  rbox(0.36, 0.03, 0.36, 0.04, darkMat, 0, 0, 0, g);
  // Cone body — smooth tapered cylinder
  mk(new THREE.CylinderGeometry(0.025, 0.14, 0.55, 16), coneMat, 0, 0.30, 0, g);
  // Reflective stripes
  mk(new THREE.CylinderGeometry(0.083, 0.098, 0.06, 16), stripeMat, 0, 0.18, 0, g);
  mk(new THREE.CylinderGeometry(0.052, 0.068, 0.06, 16), stripeMat, 0, 0.35, 0, g);
  // Rounded tip
  mk(new THREE.SphereGeometry(0.025, 8, 6), coneMat, 0, 0.57, 0, g);
  return g;
};

GF.models.barrier = function() {
  var g = new THREE.Group();
  var concreteMat = new THREE.MeshStandardMaterial({ color: '#9CA3AF', metalness: 0.05, roughness: 0.85 });
  // Use a lathe to create the tapered jersey barrier profile
  var pts = [];
  pts.push(new THREE.Vector2(0.3, 0));
  pts.push(new THREE.Vector2(0.3, 0.15));
  pts.push(new THREE.Vector2(0.22, 0.35));
  pts.push(new THREE.Vector2(0.12, 0.65));
  pts.push(new THREE.Vector2(0.1, 0.8));
  pts.push(new THREE.Vector2(0.12, 0.82));
  pts.push(new THREE.Vector2(0, 0.82));
  var latheGeo = new THREE.LatheGeometry(pts, 4);
  var barrier = new THREE.Mesh(latheGeo, concreteMat);
  barrier.scale.set(1, 1, 2.2);
  g.add(barrier);
  return g;
};
