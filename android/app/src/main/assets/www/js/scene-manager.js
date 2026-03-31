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
  renderer.toneMapping = THREE.ACESFilmicToneMapping;
  renderer.toneMappingExposure = 1.2;
  renderer.shadowMap.enabled = true;
  renderer.shadowMap.type = THREE.PCFSoftShadowMap;
  container.appendChild(renderer.domElement);

  var scene = new THREE.Scene();
  scene.background = new THREE.Color('#141414');
  scene.fog = new THREE.FogExp2('#141414', 0.015);

  var camera = new THREE.PerspectiveCamera(50, window.innerWidth / window.innerHeight, 0.1, 200);

  // Lighting — dark scene with premium directional lighting
  scene.add(new THREE.AmbientLight(0xffffff, 0.3));
  var sun = new THREE.DirectionalLight(0xffd9b3, 0.8);
  sun.position.set(10, 20, 5);
  sun.castShadow = true;
  sun.shadow.mapSize.width = 1024;
  sun.shadow.mapSize.height = 1024;
  sun.shadow.camera.near = 0.5;
  sun.shadow.camera.far = 100;
  scene.add(sun);
  var fill = new THREE.DirectionalLight(0x8899cc, 0.3);
  fill.position.set(-10, 15, -10);
  scene.add(fill);
  scene.add(new THREE.HemisphereLight(0x1a1a2e, 0x0a0a0a, 0.4));

  // Ground
  var ground = new THREE.Mesh(
    new THREE.PlaneGeometry(200, 200),
    new THREE.MeshStandardMaterial({ color: '#1A1A1A', metalness: 0.05, roughness: 0.9 })
  );
  ground.rotation.x = -Math.PI / 2;
  ground.position.y = -0.01;
  ground.receiveShadow = true;
  scene.add(ground);
  scene.add(new THREE.GridHelper(30, 30, 0x222222, 0x1E1E1E));

  // Zone rings are now managed by zone-renderer.js (GF.zones)

  return {
    scene: scene,
    renderer: renderer,
    camera: camera,
    container: container
  };
})();
