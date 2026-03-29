/* ═══════════════════════════════════════════════════════════
   GridFront Detect — App Entry Point
   Animation loop glue. Depends on all other GF modules.
   ═══════════════════════════════════════════════════════════ */
(function() {
  var scene = GF.scene.scene;
  var renderer = GF.scene.renderer;
  var camera = GF.scene.camera;

  // Initialize zone rings (config-reactive, animated on breach)
  GF.zones.init(scene);

  // Host machine — the equipment this tablet is mounted on
  var host = new THREE.Group();
  scene.add(host);
  GF.createObject('wheel_loader', null, function(model) {
    host.add(model);
  });

  // Load config from API and apply zone distances
  if (GF.api && typeof GF.api.getConfig === 'function') {
    GF.api.getConfig().then(function(cfg) {
      if (cfg && cfg.zones) {
        GF.zones.setConfig(cfg.zones);
      }
    }).catch(function() { /* API not available */ });
  }

  // Animation loop
  var startTime = performance.now();
  var lastTime = startTime;

  function animate() {
    requestAnimationFrame(animate);
    var now = performance.now();
    var dt = Math.min((now - lastTime) / 1000, 0.1);
    var t = (now - startTime) / 1000;
    lastTime = now;

    GF.orbit.update();
    GF.detection.update(t, dt);
    GF.zones.update(GF.detection.stats, dt);
    GF.hud.update(GF.detection.stats);

    renderer.render(scene, camera);
  }
  animate();

  // Resize handler
  window.addEventListener('resize', function() {
    camera.aspect = window.innerWidth / window.innerHeight;
    camera.updateProjectionMatrix();
    renderer.setSize(window.innerWidth, window.innerHeight);
  });

  // Hide loading indicator
  document.getElementById('loading').style.display = 'none';
})();
