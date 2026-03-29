/**
 * props.js — Traffic props models for GridFront Detect
 * Traffic cone, jersey barrier, delineator post, exclusion fence
 * Uses shared GF material palette and helper functions.
 */
window.GF = window.GF || {};
GF.models = GF.models || {};

/* ── Traffic Cone ─────────────────────────────────────────────────
   Rubber base + tapered cone body + 2 reflective stripes + rounded tip
   Target: < 300 triangles                                          */
GF.models.cone = function () {
  var mk = GF.mk, rbox = GF.rbox;
  var g = new THREE.Group();

  // Reflective stripe material (#D1D5DB light gray)
  var stripeMat = new THREE.MeshStandardMaterial({
    color: 0xD1D5DB, roughness: 0.3, metalness: 0.1
  });

  // --- Base: square-ish rubber pad with rounded corners ---
  // 36cm wide, 36cm deep, 3cm tall
  rbox(0.36, 0.03, 0.36, 0.02, GF.darkMat, 0, 0.015, 0, g);

  // --- Cone body: tapered cylinder ---
  // bottom radius 0.14, top radius 0.025, height 0.55
  var coneGeo = new THREE.CylinderGeometry(0.025, 0.14, 0.55, 12, 1, false);
  mk(coneGeo, GF.bodyMat, 0, 0.03 + 0.275, 0, g);

  // --- Reflective stripe 1 at ~1/3 height ---
  var stripe1Geo = new THREE.CylinderGeometry(0.072, 0.095, 0.06, 12, 1, false);
  mk(stripe1Geo, stripeMat, 0, 0.03 + 0.183, 0, g);

  // --- Reflective stripe 2 at ~2/3 height ---
  var stripe2Geo = new THREE.CylinderGeometry(0.042, 0.065, 0.06, 12, 1, false);
  mk(stripe2Geo, stripeMat, 0, 0.03 + 0.367, 0, g);

  // --- Rounded tip ---
  var tipGeo = new THREE.SphereGeometry(0.025, 8, 6);
  mk(tipGeo, GF.bodyMat, 0, 0.03 + 0.55, 0, g);

  return g;
};

/* ── Jersey Barrier ───────────────────────────────────────────────
   New Jersey barrier profile via LatheGeometry, stretched along Z.
   ~80cm tall, ~60cm wide at base, ~20cm wide at top, ~3.2m long.
   Target: < 300 triangles                                          */
GF.models.barrier = function () {
  var mk = GF.mk;
  var g = new THREE.Group();

  // NJ barrier cross-section profile (half-profile for lathe, in meters)
  // Points from bottom-center to top-center (x = radius, y = height)
  var pts = [
    new THREE.Vector2(0.00, 0.00),  // bottom center
    new THREE.Vector2(0.30, 0.00),  // base outer edge (60cm wide / 2)
    new THREE.Vector2(0.30, 0.05),  // base lip
    new THREE.Vector2(0.22, 0.15),  // lower slope start
    new THREE.Vector2(0.12, 0.55),  // upper slope
    new THREE.Vector2(0.10, 0.70),  // near top
    new THREE.Vector2(0.10, 0.80),  // top outer edge (20cm wide / 2)
    new THREE.Vector2(0.00, 0.80)   // top center
  ];

  // Lathe with few segments — we only need the shape, will scale Z
  var latheGeo = new THREE.LatheGeometry(pts, 8);

  // Scale: lathe creates a round shape (~0.6m diameter).
  // Stretch along Z to make it 3.2m long, compress X to flatten sides.
  // The lathe radius gives us the width; we scale Z for length.
  latheGeo.scale(1.0, 1.0, 5.33); // 0.6m * 5.33 ~ 3.2m along Z

  mk(latheGeo, GF.frameMat, 0, 0, 0, g);

  return g;
};

/* ── Delineator Post ──────────────────────────────────────────────
   Thin vertical post with T-shaped top cap and reflective band.
   ~1.2m tall, ~5cm diameter.
   Target: < 200 triangles                                          */
GF.models.delineator = function () {
  var mk = GF.mk, mkr = GF.mkr;
  var g = new THREE.Group();

  // Reflective band material
  var stripeMat = new THREE.MeshStandardMaterial({
    color: 0xD1D5DB, roughness: 0.3, metalness: 0.1
  });

  // --- Vertical post ---
  // radius 0.025 (5cm diameter), height 1.2m
  var postGeo = new THREE.CylinderGeometry(0.025, 0.025, 1.2, 8, 1, false);
  mk(postGeo, GF.bodyMat, 0, 0.6, 0, g);

  // --- T-shaped top cap: horizontal cylinder ---
  // radius 0.02, length 0.15 (wider than post), rotated 90 deg on Z
  var capGeo = new THREE.CylinderGeometry(0.02, 0.02, 0.15, 8, 1, false);
  mkr(capGeo, GF.darkMat, 0, 1.2, 0, 0, 0, Math.PI / 2, g);

  // --- Reflective band near top ---
  // Slightly wider ring at ~1.05m height
  var bandGeo = new THREE.CylinderGeometry(0.03, 0.03, 0.08, 8, 1, false);
  mk(bandGeo, stripeMat, 0, 1.05, 0, g);

  return g;
};

/* ── Exclusion Fence Section ──────────────────────────────────────
   Two vertical posts (~1.2m tall) spaced 2m apart, horizontal top
   rail, semi-transparent mesh panel between them.
   Target: < 300 triangles                                          */
GF.models.fence = function () {
  var mk = GF.mk, mkr = GF.mkr;
  var g = new THREE.Group();

  // Semi-transparent mesh material for the fence panel
  var meshMat = new THREE.MeshStandardMaterial({
    color: 0xD1D5DB, roughness: 0.6, metalness: 0.2,
    transparent: true, opacity: 0.35, side: THREE.DoubleSide
  });

  var postSpacing = 2.0; // 2m apart
  var postHeight = 1.2;
  var postRadius = 0.02; // 4cm diameter

  // --- Left post ---
  var postGeo = new THREE.CylinderGeometry(postRadius, postRadius, postHeight, 8, 1, false);
  mk(postGeo, GF.metalMat, -postSpacing / 2, postHeight / 2, 0, g);

  // --- Right post ---
  mk(postGeo, GF.metalMat, postSpacing / 2, postHeight / 2, 0, g);

  // --- Horizontal top rail connecting posts ---
  var railGeo = new THREE.CylinderGeometry(0.015, 0.015, postSpacing, 8, 1, false);
  mkr(railGeo, GF.metalMat, 0, postHeight, 0, 0, 0, Math.PI / 2, g);

  // --- Mesh panel: simple plane between posts ---
  var panelGeo = new THREE.PlaneGeometry(postSpacing, postHeight * 0.85);
  mk(panelGeo, meshMat, 0, postHeight * 0.45, 0, g);

  return g;
};
