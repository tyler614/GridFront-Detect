/* ═══════════════════════════════════════════════════════════
   GridFront Detect — Person Model
   Depends on: materials.js (GF.mk)
   ═══════════════════════════════════════════════════════════ */
window.GF = window.GF || {};
GF.models = GF.models || {};

GF.models.person = function(ppe) {
  var mk = GF.mk;

  var g = new THREE.Group();
  var pm = new THREE.MeshStandardMaterial({ color: '#7B8794', metalness: 0.1, roughness: 0.8 });
  var pd = new THREE.MeshStandardMaterial({ color: '#6B7280', roughness: 0.85 });
  var bootMat = new THREE.MeshStandardMaterial({ color: '#4B5563', roughness: 0.9 });
  // Boots (rounded)
  mk(new THREE.CapsuleGeometry(0.06, 0.06, 4, 8), bootMat, -0.09, 0.08, 0.02, g);
  mk(new THREE.CapsuleGeometry(0.06, 0.06, 4, 8), bootMat, 0.09, 0.08, 0.02, g);
  // Legs — capsules
  mk(new THREE.CapsuleGeometry(0.055, 0.35, 4, 8), pd, -0.09, 0.40, 0, g);
  mk(new THREE.CapsuleGeometry(0.055, 0.35, 4, 8), pd, 0.09, 0.40, 0, g);
  // Hips — sphere
  mk(new THREE.SphereGeometry(0.16, 10, 8), pd, 0, 0.64, 0, g);
  // Torso — capsule (tapered via scale)
  var torso = mk(new THREE.CapsuleGeometry(0.15, 0.28, 5, 10), pm, 0, 0.92, 0, g);
  // Shoulders — sphere
  mk(new THREE.SphereGeometry(0.17, 10, 8), pm, 0, 1.1, 0, g);
  // Arms — capsules
  var a1 = mk(new THREE.CapsuleGeometry(0.04, 0.32, 4, 8), pm, -0.24, 0.88, 0, g); a1.rotation.z = 0.1;
  var a2 = mk(new THREE.CapsuleGeometry(0.04, 0.32, 4, 8), pm, 0.24, 0.88, 0, g); a2.rotation.z = -0.1;
  // Hands — small spheres
  mk(new THREE.SphereGeometry(0.04, 8, 6), pm, -0.27, 0.68, 0, g);
  mk(new THREE.SphereGeometry(0.04, 8, 6), pm, 0.27, 0.68, 0, g);
  // Neck
  mk(new THREE.CylinderGeometry(0.045, 0.055, 0.08, 8), pm, 0, 1.22, 0, g);
  // Head — sphere
  mk(new THREE.SphereGeometry(0.11, 12, 10), pm, 0, 1.38, 0, g);
  // Hard hat
  if (ppe && ppe.hardHat) {
    mk(new THREE.SphereGeometry(0.14, 14, 8, 0, Math.PI * 2, 0, Math.PI * 0.5), pm, 0, 1.42, 0, g);
    mk(new THREE.CylinderGeometry(0.17, 0.17, 0.025, 16), pm, 0, 1.44, 0, g);
  }
  return g;
};
