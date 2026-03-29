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

  // Zone rings are now managed by zone-renderer.js (GF.zones)

  return {
    scene: scene,
    renderer: renderer,
    camera: camera,
    container: container
  };
})();
