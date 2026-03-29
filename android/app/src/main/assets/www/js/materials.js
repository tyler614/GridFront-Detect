/* ═══════════════════════════════════════════════════════════
   GridFront Detect — Shared Materials & Helpers
   ═══════════════════════════════════════════════════════════ */
window.GF = window.GF || {};

// Tesla-style muted gray palette — uniform, clean, no bright colors
GF.bodyMat = new THREE.MeshStandardMaterial({ color: '#9CA3AF', metalness: 0.15, roughness: 0.7 });
GF.darkMat = new THREE.MeshStandardMaterial({ color: '#4B5563', roughness: 0.85 });
GF.glassMat = new THREE.MeshStandardMaterial({ color: '#CBD5E1', metalness: 0.3, roughness: 0.3, transparent: true, opacity: 0.6 });
GF.metalMat = new THREE.MeshStandardMaterial({ color: '#6B7280', metalness: 0.3, roughness: 0.5 });
GF.frameMat = new THREE.MeshStandardMaterial({ color: '#4B5563', metalness: 0.4, roughness: 0.4 });

GF.mk = function(geo, mat, x, y, z, p) {
  var m = new THREE.Mesh(geo, mat);
  m.position.set(x, y, z);
  p.add(m);
  return m;
};

GF.mkr = function(geo, mat, x, y, z, rx, ry, rz, p) {
  var m = GF.mk(geo, mat, x, y, z, p);
  if (rx) m.rotation.x = rx;
  if (ry) m.rotation.y = ry;
  if (rz) m.rotation.z = rz;
  return m;
};

// Rounded box via ExtrudeGeometry
GF.rbox = function(w, h, d, r, mat, x, y, z, parent) {
  var hw = w / 2, hd = d / 2;
  r = Math.min(r, hw, hd);
  var s = new THREE.Shape();
  s.moveTo(-hw + r, -hd);
  s.lineTo(hw - r, -hd);
  s.quadraticCurveTo(hw, -hd, hw, -hd + r);
  s.lineTo(hw, hd - r);
  s.quadraticCurveTo(hw, hd, hw - r, hd);
  s.lineTo(-hw + r, hd);
  s.quadraticCurveTo(-hw, hd, -hw, hd - r);
  s.lineTo(-hw, -hd + r);
  s.quadraticCurveTo(-hw, -hd, -hw + r, -hd);
  var geo = new THREE.ExtrudeGeometry(s, { depth: h, bevelEnabled: true, bevelThickness: Math.min(r * 0.6, h * 0.15), bevelSize: Math.min(r * 0.6, h * 0.15), bevelSegments: 3 });
  geo.translate(0, 0, 0);
  geo.rotateX(-Math.PI / 2);
  geo.translate(0, h, 0);
  var m = new THREE.Mesh(geo, mat);
  m.position.set(x, y, z);
  parent.add(m);
  return m;
};

// Wheel: tire (torus) + sidewall discs + hub
GF.mkWheel = function(radius, width, x, y, z, parent, tireMat, hubMat) {
  var wg = new THREE.Group();
  // Tire tread — torus gives the round rubber look
  var torus = new THREE.Mesh(new THREE.TorusGeometry(radius - width * 0.35, width * 0.35, 12, 24), tireMat);
  torus.rotation.y = Math.PI / 2;
  wg.add(torus);
  // Sidewalls — fill in the flat faces
  var side = new THREE.Mesh(new THREE.CylinderGeometry(radius - width * 0.1, radius - width * 0.1, width * 0.5, 20), tireMat);
  side.rotation.z = Math.PI / 2;
  wg.add(side);
  // Hub/rim
  var hub = new THREE.Mesh(new THREE.CylinderGeometry(radius * 0.4, radius * 0.4, width * 0.55, 14), hubMat);
  hub.rotation.z = Math.PI / 2;
  wg.add(hub);
  wg.position.set(x, y, z);
  parent.add(wg);
  return wg;
};
