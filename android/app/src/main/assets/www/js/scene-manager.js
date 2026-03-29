/* ═══════════════════════════════════════════════════════════
   GridFront Detect — Scene Manager
   Three.js scene setup: renderer, camera, lighting, ground, grid, zone rings
   ═══════════════════════════════════════════════════════════ */
window.GF = window.GF || {};

GF.scene = (function() {
  var loading = document.getElementById('loading');
  if (typeof THREE === 'undefined') { loading.textContent = 'ERROR: THREE not loaded'; loading.style.color = 'red'; return; }

  var container = document.getElementById('canvas-container');

  // Renderer
  var renderer = new THREE.WebGLRenderer({ antialias: false, powerPreference: 'default', alpha: false });
  renderer.setSize(window.innerWidth, window.innerHeight);
  renderer.setPixelRatio(1);
  renderer.outputEncoding = THREE.sRGBEncoding;
  container.appendChild(renderer.domElement);

  var scene = new THREE.Scene();
  scene.background = new THREE.Color('#F8F8F8');

  var camera = new THREE.PerspectiveCamera(50, window.innerWidth / window.innerHeight, 0.1, 200);

  // Lighting — bright and even for good model visibility
  scene.add(new THREE.AmbientLight(0xffffff, 0.6));
  var sun = new THREE.DirectionalLight(0xffffff, 0.9);
  sun.position.set(10, 20, 5);
  scene.add(sun);
  var fill = new THREE.DirectionalLight(0xe8f4fd, 0.3);
  fill.position.set(-5, 15, -10);
  scene.add(fill);
  scene.add(new THREE.HemisphereLight(0xddeeff, 0x998866, 0.3));

  // Ground
  var ground = new THREE.Mesh(
    new THREE.PlaneGeometry(200, 200),
    new THREE.MeshStandardMaterial({ color: '#F0F0F3' })
  );
  ground.rotation.x = -Math.PI / 2;
  ground.position.y = -0.01;
  scene.add(ground);
  scene.add(new THREE.GridHelper(30, 30, 0xD0D2D5, 0xE0E2E5));

  // Zone rings
  function addRing(inner, outer, color, opacity) {
    var ring = new THREE.Mesh(
      new THREE.RingGeometry(inner, outer, 128),
      new THREE.MeshBasicMaterial({ color: color, transparent: true, opacity: opacity, side: THREE.DoubleSide })
    );
    ring.rotation.x = -Math.PI / 2;
    ring.position.y = 0.02;
    scene.add(ring);
  }
  addRing(3.44, 3.56, '#EF4444', 0.8);
  addRing(5.95, 6.05, '#F59E0B', 0.6);
  addRing(11.9, 12.1, '#44A5D6', 0.3);

  return {
    scene: scene,
    renderer: renderer,
    camera: camera,
    container: container,
    addRing: addRing
  };
})();
