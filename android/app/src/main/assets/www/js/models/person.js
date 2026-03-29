/* ═══════════════════════════════════════════════════════════
   GridFront Detect — Person Model
   Procedural Three.js construction-worker figure with PPE.
   ~1.8 m tall, 7.5-head proportions, <800 triangles.
   ═══════════════════════════════════════════════════════════ */
window.GF = window.GF || {};
GF.models = GF.models || {};

GF.models.person = function (ppe) {
  ppe = ppe || {};
  var mk  = GF.mk;
  var mkr = GF.mkr;
  var g   = new THREE.Group();

  // ── Materials ───────────────────────────────────────────
  var personMat = new THREE.MeshStandardMaterial({ color: '#7B8794', metalness: 0.1, roughness: 0.8 });
  var darkMat   = new THREE.MeshStandardMaterial({ color: '#6B7280', metalness: 0.1, roughness: 0.8 });
  var bootMat   = new THREE.MeshStandardMaterial({ color: '#4B5563', metalness: 0.1, roughness: 0.85 });
  var vestMat   = new THREE.MeshStandardMaterial({ color: '#B0B8C4', metalness: 0.1, roughness: 0.7 });
  var stripeMat = new THREE.MeshStandardMaterial({ color: '#D4D8DE', metalness: 0.3, roughness: 0.4 });
  var hatMat    = new THREE.MeshStandardMaterial({ color: '#E2C542', metalness: 0.1, roughness: 0.6 });

  // ── Proportions (metres) ────────────────────────────────
  // 7.5 heads = 1.80 m  →  1 head = 0.24 m
  var H   = 0.24;                // head unit
  var seg = 5;                   // radial segments (low-poly)

  // Heights from ground (approximate anatomical landmarks)
  // Soles        0.00
  // Ankles       0.10
  // Knees        0.48
  // Hips         0.90
  // Navel        1.04
  // Shoulders    1.44
  // Chin         1.56
  // Top of head  1.80

  // ── Head ────────────────────────────────────────────────
  var headR = H * 0.48;   // ~0.115
  mk(new THREE.SphereGeometry(headR, seg + 1, seg), personMat, 0, 1.68, 0, g);

  // ── Neck ────────────────────────────────────────────────
  mk(new THREE.CapsuleGeometry(0.045, 0.06, seg, seg), personMat, 0, 1.53, 0, g);

  // ── Torso (chest + abdomen as one capsule) ──────────────
  // From hip centre (0.93) to shoulder centre (1.44) = 0.51
  var torsoLen = 0.40;
  var torsoR   = 0.14;
  mk(new THREE.CapsuleGeometry(torsoR, torsoLen, seg, seg), personMat, 0, 1.17, 0, g);

  // ── Vest overlay ────────────────────────────────────────
  if (ppe.vest) {
    mk(new THREE.CapsuleGeometry(torsoR + 0.015, torsoLen - 0.04, seg, seg), vestMat, 0, 1.17, 0, g);
    // Reflective stripes — two thin torus rings
    var stripeR = torsoR + 0.025;
    mk(new THREE.TorusGeometry(stripeR, 0.008, 4, seg + 2), stripeMat, 0, 1.28, 0, g);
    mk(new THREE.TorusGeometry(stripeR, 0.008, 4, seg + 2), stripeMat, 0, 1.10, 0, g);
  }

  // ── Shoulders (joint spheres) ───────────────────────────
  var shoulderW = 0.20;   // half-width from centre
  var shoulderY = 1.42;
  var jointR    = 0.055;
  mk(new THREE.SphereGeometry(jointR, seg, seg), personMat, -shoulderW, shoulderY, 0, g);
  mk(new THREE.SphereGeometry(jointR, seg, seg), personMat,  shoulderW, shoulderY, 0, g);

  // ── Upper arms ──────────────────────────────────────────
  // Arms angled slightly outward (~8°) and slightly forward
  var uaLen = 0.26;
  var uaR   = 0.045;
  // Left upper arm
  mkr(new THREE.CapsuleGeometry(uaR, uaLen, seg, seg), personMat,
      -shoulderW - 0.04, shoulderY - 0.16, 0.02,
      0, 0, 0.14, g);
  // Right upper arm
  mkr(new THREE.CapsuleGeometry(uaR, uaLen, seg, seg), personMat,
       shoulderW + 0.04, shoulderY - 0.16, 0.02,
       0, 0, -0.14, g);

  // ── Elbows ──────────────────────────────────────────────
  var elbowY = shoulderY - 0.33;
  var elbowX = 0.26;
  mk(new THREE.SphereGeometry(0.04, seg, seg), personMat, -elbowX, elbowY, 0.02, g);
  mk(new THREE.SphereGeometry(0.04, seg, seg), personMat,  elbowX, elbowY, 0.02, g);

  // ── Forearms ────────────────────────────────────────────
  var faLen = 0.22;
  var faR   = 0.038;
  mkr(new THREE.CapsuleGeometry(faR, faLen, seg, seg), personMat,
      -elbowX - 0.01, elbowY - 0.14, 0.03,
      0.1, 0, 0.06, g);
  mkr(new THREE.CapsuleGeometry(faR, faLen, seg, seg), personMat,
       elbowX + 0.01, elbowY - 0.14, 0.03,
      -0.1, 0, -0.06, g);

  // ── Hands (small spheres) ───────────────────────────────
  mk(new THREE.SphereGeometry(0.035, seg, seg), darkMat, -0.29, 0.82, 0.05, g);
  mk(new THREE.SphereGeometry(0.035, seg, seg), darkMat,  0.29, 0.82, 0.05, g);

  // ── Hips (joint spheres) ────────────────────────────────
  var hipW = 0.10;
  var hipY = 0.92;
  mk(new THREE.SphereGeometry(0.06, seg, seg), personMat, -hipW, hipY, 0, g);
  mk(new THREE.SphereGeometry(0.06, seg, seg), personMat,  hipW, hipY, 0, g);

  // ── Thighs ──────────────────────────────────────────────
  var thLen = 0.34;
  var thR   = 0.065;
  mk(new THREE.CapsuleGeometry(thR, thLen, seg, seg), darkMat, -hipW, 0.70, 0, g);
  mk(new THREE.CapsuleGeometry(thR, thLen, seg, seg), darkMat,  hipW, 0.70, 0, g);

  // ── Knees ───────────────────────────────────────────────
  var kneeY = 0.48;
  mk(new THREE.SphereGeometry(0.05, seg, seg), darkMat, -hipW, kneeY, 0, g);
  mk(new THREE.SphereGeometry(0.05, seg, seg), darkMat,  hipW, kneeY, 0, g);

  // ── Calves ──────────────────────────────────────────────
  var calfLen = 0.26;
  var calfR   = 0.048;
  mk(new THREE.CapsuleGeometry(calfR, calfLen, seg, seg), darkMat, -hipW, 0.30, 0, g);
  mk(new THREE.CapsuleGeometry(calfR, calfLen, seg, seg), darkMat,  hipW, 0.30, 0, g);

  // ── Boots (feet) ────────────────────────────────────────
  // Capsule oriented horizontally, slightly forward
  var bootLen = 0.14;
  var bootR   = 0.048;
  mkr(new THREE.CapsuleGeometry(bootR, bootLen, seg, seg), bootMat,
      -hipW, 0.06, 0.04,
      Math.PI / 2, 0, 0, g);
  mkr(new THREE.CapsuleGeometry(bootR, bootLen, seg, seg), bootMat,
       hipW, 0.06, 0.04,
       Math.PI / 2, 0, 0, g);

  // ── Hard hat ────────────────────────────────────────────
  if (ppe.hardHat) {
    var hatR = headR + 0.03;   // slightly larger than head
    // Dome — upper hemisphere
    var domeGeo = new THREE.SphereGeometry(hatR, seg + 1, seg, 0, Math.PI * 2, 0, Math.PI / 2);
    mk(domeGeo, hatMat, 0, 1.78, 0, g);
    // Brim — flat ring around the dome
    var brimGeo = new THREE.CylinderGeometry(hatR + 0.05, hatR + 0.05, 0.015, seg + 2);
    mk(brimGeo, hatMat, 0, 1.78, 0, g);
  }

  return g;
};
