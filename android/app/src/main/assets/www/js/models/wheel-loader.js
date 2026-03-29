/* ═══════════════════════════════════════════════════════════
   GridFront Detect — Wheel Loader Model (CAT 950 GC)
   HOST MACHINE — darker material palette
   Proportions: L:8.4m W:2.5m H:3.4m at cab (1:1 scale meters)
   Depends on: materials.js (GF.mk, GF.mkr, GF.rbox, GF.mkWheel)
   ═══════════════════════════════════════════════════════════ */
window.GF = window.GF || {};
GF.models = GF.models || {};

GF.models.wheel_loader = function() {
  var mk = GF.mk, mkr = GF.mkr, rbox = GF.rbox, mkWheel = GF.mkWheel;

  var g = new THREE.Group();

  // --- Host machine dark materials ---
  var hb = new THREE.MeshStandardMaterial({ color: '#4B5563', metalness: 0.3, roughness: 0.5 });
  var hd = new THREE.MeshStandardMaterial({ color: '#1F2937', roughness: 0.8 });
  var hg = new THREE.MeshStandardMaterial({ color: '#64748B', metalness: 0.5, roughness: 0.2, transparent: true, opacity: 0.5 });
  var hHub = new THREE.MeshStandardMaterial({ color: '#374151', metalness: 0.4, roughness: 0.5 });
  var hCyl = new THREE.MeshStandardMaterial({ color: '#6B7280', metalness: 0.6, roughness: 0.3 });
  var hVent = new THREE.MeshStandardMaterial({ color: '#111827', roughness: 0.9 });

  // === REAR SECTION (engine compartment + counterweight) ===
  // Rear main body — slightly tapered at back
  rbox(2.4, 1.4, 2.2, 0.22, hb, 0, 0.7, -1.6, g);

  // Counterweight — rounded mass at very back
  mk(new THREE.CylinderGeometry(1.2, 1.25, 1.3, 16, 1, false, -Math.PI * 0.5, Math.PI), hd, 0, 0.95, -2.8, g);

  // Engine hood — raised top section with slope
  rbox(2.0, 0.45, 1.8, 0.15, hb, 0, 2.1, -1.5, g);

  // Hood slope toward cab — capsule bridge
  mkr(new THREE.CapsuleGeometry(0.12, 1.6, 4, 8), hb, 0, 2.0, -0.6, Math.PI * 0.48, 0, 0, g);

  // Exhaust stack — vertical pipe with cap
  mk(new THREE.CylinderGeometry(0.08, 0.07, 0.8, 8), hd, -0.7, 2.7, -1.8, g);
  mk(new THREE.CylinderGeometry(0.11, 0.08, 0.06, 8), hd, -0.7, 3.12, -1.8, g);

  // Air intake stack (right side)
  mk(new THREE.CylinderGeometry(0.1, 0.09, 0.5, 8), hd, 0.7, 2.55, -1.6, g);
  mk(new THREE.SphereGeometry(0.11, 8, 6), hd, 0.7, 2.82, -1.6, g);

  // Cooling vents — left side grille (horizontal slats)
  for (var v = 0; v < 4; v++) {
    rbox(0.06, 0.08, 1.2, 0.02, hVent, -1.22, 1.2 + v * 0.22, -1.6, g);
  }
  // Cooling vents — right side grille
  for (var v2 = 0; v2 < 4; v2++) {
    rbox(0.06, 0.08, 1.2, 0.02, hVent, 1.22, 1.2 + v2 * 0.22, -1.6, g);
  }

  // Rear grille
  for (var rv = 0; rv < 3; rv++) {
    rbox(1.6, 0.06, 0.06, 0.02, hVent, 0, 1.2 + rv * 0.25, -2.72, g);
  }

  // === ARTICULATION JOINT ===
  // Main pivot cylinder — visible joint between front and rear
  mk(new THREE.CylinderGeometry(0.28, 0.28, 0.8, 16), hd, 0, 0.9, -0.2, g);
  // Pivot pin top cap
  mk(new THREE.CylinderGeometry(0.32, 0.32, 0.1, 16), hCyl, 0, 1.32, -0.2, g);
  // Pivot pin bottom cap
  mk(new THREE.CylinderGeometry(0.32, 0.32, 0.1, 16), hCyl, 0, 0.48, -0.2, g);
  // Steering cylinders flanking the joint
  mkr(new THREE.CapsuleGeometry(0.05, 0.8, 4, 6), hCyl, -0.6, 0.7, -0.2, 0, 0.2, 0, g);
  mkr(new THREE.CapsuleGeometry(0.05, 0.8, 4, 6), hCyl, 0.6, 0.7, -0.2, 0, -0.2, 0, g);

  // === FRONT SECTION (cab + boom mount) ===
  // Front chassis — lower frame
  rbox(2.3, 0.9, 2.0, 0.18, hb, 0, 0.45, 0.8, g);

  // Front fender platform / deck
  rbox(2.4, 0.12, 1.6, 0.1, hb, 0, 1.35, 0.8, g);

  // === CAB ===
  // Cab main body — ROPS structure
  rbox(1.5, 1.5, 1.5, 0.18, hb, 0, 1.4, -0.2, g);

  // Cab roof — slightly overhanging
  rbox(1.65, 0.1, 1.65, 0.14, hb, 0, 3.0, -0.2, g);

  // Windshield — curved cylinder segment (front glass)
  mkr(new THREE.CylinderGeometry(1.3, 1.3, 1.35, 16, 1, true, -0.35, 0.7), hg,
    0, 2.35, 0.3, 0, 0, 0, g);

  // Side windows — left
  mkr(new THREE.PlaneGeometry(1.25, 1.0), hg, -0.77, 2.3, -0.2, 0, -Math.PI / 2, 0, g);
  // Side windows — right
  mkr(new THREE.PlaneGeometry(1.25, 1.0), hg, 0.77, 2.3, -0.2, 0, Math.PI / 2, 0, g);
  // Rear window
  mkr(new THREE.PlaneGeometry(1.1, 0.8), hg, 0, 2.35, -0.97, 0, 0, 0, g);

  // ROPS corner pillars (4 capsules at cab corners)
  var px = [-0.65, 0.65], pz = [-0.85, 0.35];
  for (var pi = 0; pi < px.length; pi++) {
    for (var pj = 0; pj < pz.length; pj++) {
      mk(new THREE.CapsuleGeometry(0.04, 1.3, 3, 6), hd, px[pi], 2.25, pz[pj], g);
    }
  }

  // Door handle (right side)
  mkr(new THREE.CapsuleGeometry(0.015, 0.15, 3, 4), hCyl, 0.78, 2.0, -0.1, 0, 0, Math.PI / 2, g);

  // === BOOM ARMS ===
  // Left boom arm — capsule, angled from cab shoulders to bucket
  var boomLen = 3.2;
  [-0.55, 0.55].forEach(function(x) {
    // Main boom arm
    var arm = mkr(new THREE.CapsuleGeometry(0.09, boomLen, 4, 8), hb,
      x, 1.9, 1.8, -Math.PI * 0.38, 0, 0, g);

    // Hydraulic lift cylinder (thinner, alongside boom)
    mkr(new THREE.CapsuleGeometry(0.05, 1.8, 4, 6), hCyl,
      x * 0.85, 1.95, 0.7, -Math.PI * 0.28, 0, 0, g);

    // Cylinder rod (even thinner, chrome-like)
    mkr(new THREE.CapsuleGeometry(0.025, 1.0, 3, 6), hCyl,
      x * 0.85, 2.35, 1.7, -Math.PI * 0.35, 0, 0, g);
  });

  // Boom cross-brace near bucket end
  mkr(new THREE.CapsuleGeometry(0.04, 0.9, 3, 6), hd, 0, 1.25, 3.0, 0, 0, Math.PI / 2, g);

  // Tilt cylinder (single, center, connects to bucket)
  mkr(new THREE.CapsuleGeometry(0.06, 1.2, 4, 6), hCyl, 0, 1.65, 2.5, -Math.PI * 0.25, 0, 0, g);
  mkr(new THREE.CapsuleGeometry(0.03, 0.7, 3, 6), hCyl, 0, 1.45, 3.2, -Math.PI * 0.4, 0, 0, g);

  // Z-bar linkage
  mkr(new THREE.CapsuleGeometry(0.035, 0.6, 3, 6), hd, 0.25, 1.3, 2.8, -Math.PI * 0.6, 0, 0.15, g);
  mkr(new THREE.CapsuleGeometry(0.035, 0.6, 3, 6), hd, -0.25, 1.3, 2.8, -Math.PI * 0.6, 0, -0.15, g);

  // === BUCKET ===
  // Main scoop — curved cylinder segment (wider than body)
  mk(new THREE.CylinderGeometry(0.85, 0.85, 2.3, 14, 1, true, -0.9, 1.8), hb, 0, 0.7, 3.6, g);

  // Bucket back plate — closes the scoop
  mkr(new THREE.CylinderGeometry(0.85, 0.85, 2.3, 14, 1, true, 0.9, 0.15), hd, 0, 0.7, 3.6, 0, 0, 0, g);

  // Bucket side plates
  [-1.15, 1.15].forEach(function(x) {
    mkr(new THREE.CapsuleGeometry(0.04, 0.7, 3, 4), hd, x, 0.6, 3.8, -Math.PI * 0.2, 0, 0, g);
    mkr(new THREE.CapsuleGeometry(0.04, 0.5, 3, 4), hd, x, 0.9, 3.4, 0, 0, 0, g);
  });

  // Bucket cutting edge / lip — thick bar across front
  mkr(new THREE.CapsuleGeometry(0.04, 2.1, 4, 6), hd, 0, 0.35, 4.15, 0, 0, Math.PI / 2, g);

  // Bucket teeth — individual cones along the lip
  for (var bt = -0.9; bt <= 0.9; bt += 0.257) {
    mkr(new THREE.ConeGeometry(0.05, 0.18, 6), hd, bt, 0.3, 4.3, Math.PI * 0.55, 0, 0, g);
  }

  // === WHEELS ===
  // Front wheels — slightly larger (0.65m radius) — real loaders have bigger fronts
  mkWheel(0.65, 0.45, -1.2, 0.65, 1.0, g, hd, hHub);
  mkWheel(0.65, 0.45, 1.2, 0.65, 1.0, g, hd, hHub);

  // Rear wheels (0.60m radius)
  mkWheel(0.60, 0.42, -1.2, 0.60, -1.6, g, hd, hHub);
  mkWheel(0.60, 0.42, 1.2, 0.60, -1.6, g, hd, hHub);

  // === FENDERS ===
  // Front fenders — half-cylinder arches
  [-1.2, 1.2].forEach(function(x) {
    var ff = mk(new THREE.CylinderGeometry(0.75, 0.75, 0.5, 12, 1, true, 0, Math.PI), hb, x, 1.0, 1.0, g);
    ff.rotation.y = (x > 0) ? Math.PI / 2 : -Math.PI / 2;
    // Fender lip — capsule trim along top edge
    mkr(new THREE.CapsuleGeometry(0.025, 0.45, 3, 4), hd,
      x + (x > 0 ? 0.04 : -0.04), 1.32, 1.0, 0, 0, Math.PI / 2, g);
  });

  // Rear fenders — slightly smaller
  [-1.2, 1.2].forEach(function(x) {
    var rf = mk(new THREE.CylinderGeometry(0.68, 0.68, 0.46, 12, 1, true, 0, Math.PI), hb, x, 0.95, -1.6, g);
    rf.rotation.y = (x > 0) ? Math.PI / 2 : -Math.PI / 2;
    mkr(new THREE.CapsuleGeometry(0.025, 0.42, 3, 4), hd,
      x + (x > 0 ? 0.04 : -0.04), 1.25, -1.6, 0, 0, Math.PI / 2, g);
  });

  // === STEPS / LADDER (left side of cab) ===
  mkr(new THREE.CapsuleGeometry(0.025, 0.35, 3, 4), hd, -0.85, 0.6, 0.1, 0, 0, Math.PI / 2, g);
  mkr(new THREE.CapsuleGeometry(0.025, 0.35, 3, 4), hd, -0.85, 0.95, 0.0, 0, 0, Math.PI / 2, g);

  // Grab rail
  mk(new THREE.CapsuleGeometry(0.02, 0.7, 3, 4), hCyl, -0.82, 1.5, 0.35, g);

  // === LIGHTS ===
  // Front work lights on cab roof
  var lightMat = new THREE.MeshStandardMaterial({ color: '#E5E7EB', metalness: 0.2, roughness: 0.4 });
  mk(new THREE.SphereGeometry(0.06, 6, 4), lightMat, -0.55, 3.1, 0.3, g);
  mk(new THREE.SphereGeometry(0.06, 6, 4), lightMat, 0.55, 3.1, 0.3, g);

  // Rear work lights
  mk(new THREE.SphereGeometry(0.05, 6, 4), lightMat, -0.6, 2.4, -2.7, g);
  mk(new THREE.SphereGeometry(0.05, 6, 4), lightMat, 0.6, 2.4, -2.7, g);

  // Headlights (front, on boom mount area)
  mk(new THREE.SphereGeometry(0.07, 6, 4), lightMat, -0.85, 1.3, 1.5, g);
  mk(new THREE.SphereGeometry(0.07, 6, 4), lightMat, 0.85, 1.3, 1.5, g);

  return g;
};
