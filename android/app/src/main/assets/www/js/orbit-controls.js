/* ═══════════════════════════════════════════════════════════
   GridFront Detect — Orbit Controls
   Camera orbit via touch/mouse/wheel
   Depends on: scene-manager.js (GF.scene.renderer, GF.scene.camera)
   ═══════════════════════════════════════════════════════════ */
window.GF = window.GF || {};

GF.orbit = (function() {
  var camera = GF.scene.camera;
  var canvas = GF.scene.renderer.domElement;

  var angle = Math.PI * 0.85;
  var pitch = 0.75;
  var dist = 22;
  var lookAt = new THREE.Vector3(0, 1.0, 2);
  var isDragging = false;
  var prevX = 0, prevY = 0;
  var pinchDist = 0;

  canvas.addEventListener('pointerdown', function(e) {
    isDragging = true; prevX = e.clientX; prevY = e.clientY;
    canvas.setPointerCapture(e.pointerId);
  });
  canvas.addEventListener('pointermove', function(e) {
    if (!isDragging) return;
    angle -= (e.clientX - prevX) * 0.005;
    pitch = Math.max(0.2, Math.min(1.5, pitch + (e.clientY - prevY) * 0.005));
    prevX = e.clientX; prevY = e.clientY;
  });
  canvas.addEventListener('pointerup', function(e) {
    isDragging = false;
    canvas.releasePointerCapture(e.pointerId);
  });
  canvas.addEventListener('wheel', function(e) {
    dist = Math.max(6, Math.min(35, dist + e.deltaY * 0.02));
    e.preventDefault();
  }, { passive: false });

  canvas.addEventListener('touchstart', function(e) {
    if (e.touches.length === 2) {
      var dx = e.touches[0].clientX - e.touches[1].clientX;
      var dy = e.touches[0].clientY - e.touches[1].clientY;
      pinchDist = Math.sqrt(dx * dx + dy * dy);
    }
  }, { passive: true });
  canvas.addEventListener('touchmove', function(e) {
    if (e.touches.length === 2) {
      var dx = e.touches[0].clientX - e.touches[1].clientX;
      var dy = e.touches[0].clientY - e.touches[1].clientY;
      var newDist = Math.sqrt(dx * dx + dy * dy);
      dist = Math.max(6, Math.min(35, dist + (pinchDist - newDist) * 0.05));
      pinchDist = newDist;
    }
  }, { passive: true });

  function updateCamera() {
    camera.position.set(
      lookAt.x + Math.sin(angle) * Math.cos(pitch) * dist,
      lookAt.y + Math.sin(pitch) * dist,
      lookAt.z + Math.cos(angle) * Math.cos(pitch) * dist
    );
    camera.lookAt(lookAt);
  }

  return {
    update: updateCamera
  };
})();
