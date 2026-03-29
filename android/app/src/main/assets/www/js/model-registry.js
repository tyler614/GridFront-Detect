/* ═══════════════════════════════════════════════════════════
   GridFront Detect — Model Registry
   GLTF loader, model cache, createObject()
   Depends on: scene-manager.js, materials.js, all model files
   ═══════════════════════════════════════════════════════════ */
window.GF = window.GF || {};

GF.registry = (function() {
  var gltfLoader = new THREE.GLTFLoader();

  // Model registry — maps detection class to GLB file + scale + y-offset
  // Add entries here as you download and convert models from GrabCAD
  var MODEL_REGISTRY = {
    // GLB models disabled — they contain embedded ground planes that render as
    // giant white slabs. Using procedural fallbacks until clean models are available.
    // 'wheel_loader': { file: 'models/cat-950gc.glb', scale: 1.0, yOffset: 0 },
    // 'dozer':        { file: 'models/cat-d2.glb',    scale: 1.0, yOffset: 0 },
    // 'excavator':    { file: 'models/excavator.glb',  scale: 1.0, yOffset: 0 },
    // 'dump_truck':   { file: 'models/cat-740.glb',   scale: 1.0, yOffset: 0 },
    // 'person':       { file: 'models/person.glb',     scale: 0.65, yOffset: 0 },
    // 'cone':         { file: 'models/cone.glb',       scale: 1.0, yOffset: 0 },
  };

  // Cache loaded models so we clone instead of re-loading
  var modelCache = {};

  function loadModel(type, callback) {
    var entry = MODEL_REGISTRY[type];
    if (!entry) { callback(null); return; }
    if (modelCache[type]) { callback(modelCache[type].clone()); return; }

    console.log('Loading model: ' + entry.file);
    gltfLoader.load(entry.file, function(gltf) {
      console.log('Model loaded: ' + type);
      var model = gltf.scene;
      model.scale.setScalar(entry.scale);
      model.position.y = entry.yOffset || 0;
      // Apply color override and ensure proper encoding
      model.traverse(function(child) {
        if (child.isMesh && child.material) {
          if (child.material.map) child.material.map.encoding = THREE.sRGBEncoding;
          if (entry.color) {
            child.material = child.material.clone();
            child.material.color.set(entry.color);
            child.material.map = null;
          }
        }
      });
      modelCache[type] = model;
      callback(model.clone());
    }, undefined, function(err) {
      console.warn('Model load failed for ' + type + ':', err);
      callback(null);
    });
  }

  var FALLBACKS = {
    wheel_loader: GF.models.wheel_loader,
    person: GF.models.person,
    excavator: GF.models.excavator,
    dump_truck: GF.models.dump_truck,
    dozer: GF.models.dozer,
    cone: GF.models.cone,
    barrier: GF.models.barrier
  };

  function createObject(type, opts, callback) {
    loadModel(type, function(gltfModel) {
      if (gltfModel) {
        callback(gltfModel);
      } else {
        var fn = FALLBACKS[type];
        callback(fn ? fn(opts) : new THREE.Group());
      }
    });
  }

  return {
    createObject: createObject,
    loadModel: loadModel,
    MODEL_REGISTRY: MODEL_REGISTRY,
    modelCache: modelCache
  };
})();

// Convenience alias
GF.createObject = GF.registry.createObject;
