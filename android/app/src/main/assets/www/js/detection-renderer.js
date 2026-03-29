/* ═══════════════════════════════════════════════════════════
   GridFront Detect — Detection Renderer
   Mock detection objects, mesh management, smoothing
   Depends on: scene-manager.js, model-registry.js
   ═══════════════════════════════════════════════════════════ */
window.GF = window.GF || {};

GF.detection = (function() {
  var scene = GF.scene.scene;

  var mockObjects = [
    { id: 'p1', cls: 'person', path: function(t) { return [Math.sin(t * .4) * 3 + 2, 0, Math.cos(t * .4) * 3 + 2]; }, ppe: { hardHat: true, vest: true } },
    { id: 'p2', cls: 'person', path: function(t) { return [-3 + Math.sin(t * .3 + 1) * 1.5, 0, 4 + Math.cos(t * .5) * 2]; }, ppe: { hardHat: true, vest: false } },
    { id: 'p3', cls: 'person', path: function(t) { return [Math.sin(t * .15) * 4 - 1, 0, -4 + Math.sin(t * .2) * 1]; }, ppe: { hardHat: false, vest: true } },
    { id: 'ex1', cls: 'excavator', path: function() { return [7, 0, 8]; }, heading: -Math.PI / 4 },
    { id: 'dt1', cls: 'dump_truck', path: function(t) { return [-8 + Math.sin(t * .15) * 3, 0, 9]; }, heading: Math.PI / 2 },
    { id: 'c1', cls: 'cone', path: function() { return [4, 0, 5]; } },
    { id: 'c2', cls: 'cone', path: function() { return [6, 0, 5]; } },
    { id: 'c3', cls: 'cone', path: function() { return [8, 0, 5]; } },
    { id: 'c4', cls: 'cone', path: function() { return [4, 0, 7]; } },
    { id: 'c5', cls: 'cone', path: function() { return [8, 0, 7]; } },
    { id: 'b1', cls: 'barrier', path: function() { return [-5, 0, 6]; } },
    { id: 'b2', cls: 'barrier', path: function() { return [-5, 0, 8]; } },
    { id: 'dz1', cls: 'dozer', path: function() { return [-7, 0, -6]; }, heading: Math.PI / 6 }
  ];

  var detMeshes = {};
  var smoothing = {};

  // Initialize all detection objects
  mockObjects.forEach(function(obj) {
    var pos = obj.path(0);
    GF.createObject(obj.cls, obj.ppe || null, function(mesh) {
      mesh.position.set(pos[0], pos[1], pos[2]);
      if (obj.heading !== undefined) mesh.rotation.y = obj.heading;
      scene.add(mesh);
      detMeshes[obj.id] = mesh;
    });
    smoothing[obj.id] = { pos: [pos[0], pos[1], pos[2]], rotY: obj.heading || 0 };
  });

  var stats = { people: 0, equip: 0, markers: 0, closestDist: Infinity };

  function update(t, dt) {
    var closestDist = Infinity;
    var people = 0, equip = 0, markers = 0;

    mockObjects.forEach(function(obj) {
      var target = obj.path(t);
      var s = smoothing[obj.id];
      var mesh = detMeshes[obj.id];
      if (!s || !mesh) return;

      var alpha = 1 - Math.exp(-dt * 6);
      var px = s.pos[0], pz = s.pos[2];
      s.pos[0] += (target[0] - s.pos[0]) * alpha;
      s.pos[1] += (target[1] - s.pos[1]) * alpha;
      s.pos[2] += (target[2] - s.pos[2]) * alpha;
      mesh.position.set(s.pos[0], s.pos[1], s.pos[2]);

      if (obj.heading === undefined) {
        var vx = dt > 0 ? (s.pos[0] - px) / dt : 0;
        var vz = dt > 0 ? (s.pos[2] - pz) / dt : 0;
        if (Math.sqrt(vx * vx + vz * vz) > 0.3) {
          var tr = Math.atan2(vx, vz);
          var diff = tr - s.rotY;
          while (diff > Math.PI) diff -= 2 * Math.PI;
          while (diff < -Math.PI) diff += 2 * Math.PI;
          s.rotY += diff * (1 - Math.exp(-dt * 4));
          mesh.rotation.y = s.rotY;
        }
      }

      var d = Math.sqrt(s.pos[0] * s.pos[0] + s.pos[2] * s.pos[2]);
      if (d < closestDist) closestDist = d;
      if (obj.cls === 'person') people++;
      else if (obj.cls === 'excavator' || obj.cls === 'dump_truck' || obj.cls === 'dozer') equip++;
      else markers++;
    });

    stats.people = people;
    stats.equip = equip;
    stats.markers = markers;
    stats.closestDist = closestDist;
  }

  return {
    update: update,
    stats: stats
  };
})();
