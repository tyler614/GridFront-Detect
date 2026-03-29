/* ═══════════════════════════════════════════════════════════
   GridFront Detect — Camera Visualization
   Renders camera icons and FOV frustum cones in the 3D scene.
   ═══════════════════════════════════════════════════════════ */

window.GF = window.GF || {};

GF.cameraViz = (function () {
    'use strict';

    // ── Internal state ──────────────────────────────────────
    var scene = null;
    var cameraGroup = null;       // THREE.Group holding all camera objects
    var mountData = [];           // current machine's camera_mounts array
    var cameraSpec = null;        // current machine's camera_spec
    var cameraObjects = {};       // keyed by mount id: { icon, cone, wireframe, label }
    var clipDistance = 10;        // how far to draw cones (configurable, max_depth_m or less)

    // ── Colors ──────────────────────────────────────────────
    var COLOR_ACTIVE   = 0x44A5D6;
    var COLOR_INACTIVE = 0x6B7280;
    var OPACITY_FILL_ACTIVE   = 0.08;
    var OPACITY_FILL_INACTIVE = 0.04;
    var OPACITY_WIRE          = 0.15;

    // ── Default machine profiles (fallback if API not available) ─
    var defaultMachines = {
        wheel_loader: {
            camera_mounts: [
                { id: 'front', label: 'Front',  position: [0, 2.8, 4.2],   rotation: [0, 0, 0] },
                { id: 'rear',  label: 'Rear',   position: [0, 2.5, -4.2],  rotation: [0, 180, 0] },
                { id: 'left',  label: 'Left',   position: [-1.25, 2.8, 0], rotation: [0, -90, 0] },
                { id: 'right', label: 'Right',  position: [1.25, 2.8, 0],  rotation: [0, 90, 0] }
            ],
            camera_spec: {
                hfov_deg: 127,
                depth_hfov_deg: 73,
                vfov_deg: 58,
                max_depth_m: 15
            }
        }
    };

    // ── FOV cone geometry builder ───────────────────────────
    // Creates a pyramid from the camera origin to the far plane,
    // using the depth HFOV and VFOV angles.
    function createFovConeGeometry(hfov_deg, vfov_deg, range) {
        var hfov = hfov_deg * Math.PI / 180;
        var vfov = vfov_deg * Math.PI / 180;
        var hw = Math.tan(hfov / 2) * range;   // half-width at far plane
        var hh = Math.tan(vfov / 2) * range;   // half-height at far plane

        // 5 vertices: apex (camera) + 4 corners of the far plane
        // Cone points along local +Z axis (camera forward direction)
        var verts = new Float32Array([
            0,    0,    0,       // 0: apex
           -hw,  -hh,  range,   // 1: bottom-left
            hw,  -hh,  range,   // 2: bottom-right
            hw,   hh,  range,   // 3: top-right
           -hw,   hh,  range    // 4: top-left
        ]);

        // 4 side triangles + 2 triangles for the far plane cap
        var indices = [
            0, 1, 2,   // bottom face
            0, 2, 3,   // right face
            0, 3, 4,   // top face
            0, 4, 1,   // left face
            1, 3, 2,   // far plane tri 1
            1, 4, 3    // far plane tri 2
        ];

        var geo = new THREE.BufferGeometry();
        geo.setAttribute('position', new THREE.BufferAttribute(verts, 3));
        geo.setIndex(indices);
        geo.computeVertexNormals();
        return geo;
    }

    // ── Camera icon builder ─────────────────────────────────
    // Small camera-shaped mesh: rounded box body + cylinder lens
    function createCameraIcon(color) {
        var group = new THREE.Group();

        // Camera body — small rounded box
        var bodyGeo = new THREE.BoxGeometry(0.08, 0.06, 0.05);
        var bodyMat = new THREE.MeshStandardMaterial({
            color: color,
            roughness: 0.4,
            metalness: 0.3
        });
        var body = new THREE.Mesh(bodyGeo, bodyMat);
        group.add(body);

        // Lens — tiny cylinder protruding from front
        var lensGeo = new THREE.CylinderGeometry(0.015, 0.018, 0.03, 8);
        var lensMat = new THREE.MeshStandardMaterial({
            color: 0x222222,
            roughness: 0.2,
            metalness: 0.5
        });
        var lens = new THREE.Mesh(lensGeo, lensMat);
        // Rotate cylinder so it points along +Z (forward)
        lens.rotation.x = Math.PI / 2;
        lens.position.z = 0.04;
        group.add(lens);

        // Status indicator glow — small sphere
        var glowGeo = new THREE.SphereGeometry(0.012, 8, 8);
        var glowMat = new THREE.MeshBasicMaterial({
            color: color,
            transparent: true,
            opacity: 0.8
        });
        var glow = new THREE.Mesh(glowGeo, glowMat);
        glow.position.set(0.03, 0.025, 0);
        glow.name = 'statusGlow';
        group.add(glow);

        return group;
    }

    // ── Build all visuals for one camera mount ──────────────
    function buildCameraVisuals(mount) {
        var pos = mount.position;   // [x, y, z]
        var rot = mount.rotation;   // [rx, ry, rz] in degrees

        var range = Math.min(clipDistance, cameraSpec.max_depth_m || 15);
        var hfov = cameraSpec.depth_hfov_deg || 73;
        var vfov = cameraSpec.vfov_deg || 58;

        // -- FOV cone (transparent fill) --
        var coneGeo = createFovConeGeometry(hfov, vfov, range);
        var coneMat = new THREE.MeshBasicMaterial({
            color: COLOR_ACTIVE,
            transparent: true,
            opacity: OPACITY_FILL_ACTIVE,
            side: THREE.DoubleSide,
            depthWrite: false
        });
        var cone = new THREE.Mesh(coneGeo, coneMat);

        // -- FOV cone wireframe overlay --
        var wireMat = new THREE.MeshBasicMaterial({
            color: COLOR_ACTIVE,
            transparent: true,
            opacity: OPACITY_WIRE,
            wireframe: true,
            depthWrite: false
        });
        var wireframe = new THREE.Mesh(coneGeo.clone(), wireMat);

        // -- Camera icon --
        var icon = createCameraIcon(COLOR_ACTIVE);

        // -- Position and rotate everything --
        // Each visual is placed at the mount position
        var objects = [cone, wireframe, icon];
        for (var i = 0; i < objects.length; i++) {
            var obj = objects[i];
            obj.position.set(pos[0], pos[1], pos[2]);

            // Apply mount rotation (degrees to radians)
            // rotation[1] is yaw (Y-axis rotation)
            if (rot) {
                obj.rotation.set(
                    (rot[0] || 0) * Math.PI / 180,
                    (rot[1] || 0) * Math.PI / 180,
                    (rot[2] || 0) * Math.PI / 180
                );
            }
        }

        // Add to scene group
        cameraGroup.add(cone);
        cameraGroup.add(wireframe);
        cameraGroup.add(icon);

        return {
            icon: icon,
            cone: cone,
            wireframe: wireframe,
            active: true
        };
    }

    // ── Remove all camera visuals ───────────────────────────
    function clearCameras() {
        if (cameraGroup) {
            while (cameraGroup.children.length > 0) {
                var child = cameraGroup.children[0];
                cameraGroup.remove(child);
                if (child.geometry) child.geometry.dispose();
                if (child.material) child.material.dispose();
            }
        }
        cameraObjects = {};
    }

    // ── Build cameras for current mount data ────────────────
    function buildAllCameras() {
        clearCameras();
        if (!mountData || !cameraSpec) return;

        for (var i = 0; i < mountData.length; i++) {
            var mount = mountData[i];
            cameraObjects[mount.id] = buildCameraVisuals(mount);
        }
    }

    // ── Public API ──────────────────────────────────────────

    /**
     * Initialize camera visualization.
     * @param {THREE.Scene} threeScene — the Three.js scene to add cameras to
     * @param {object} [options] — optional config
     * @param {number} [options.clipDistance] — max cone draw distance (default 10)
     */
    function init(threeScene, options) {
        scene = threeScene;
        options = options || {};
        clipDistance = options.clipDistance || 10;

        cameraGroup = new THREE.Group();
        cameraGroup.name = 'cameraVizGroup';
        scene.add(cameraGroup);

        // Try to load machine data from GF.api, fall back to defaults
        var machineType = 'wheel_loader';
        var machineData = null;

        if (GF.api && typeof GF.api.getMachines === 'function') {
            var machines = GF.api.getMachines();
            if (machines && machines[machineType]) {
                machineData = machines[machineType];
            }
        }

        if (!machineData) {
            machineData = defaultMachines[machineType];
        }

        if (machineData) {
            mountData = machineData.camera_mounts || [];
            cameraSpec = machineData.camera_spec || {};
            buildAllCameras();
        }
    }

    /**
     * Update camera health/status colors.
     * @param {object} cameraHealth — keyed by camera id, e.g. { front: { connected: true }, rear: { connected: false } }
     */
    function update(cameraHealth) {
        if (!cameraHealth) return;

        for (var id in cameraObjects) {
            if (!cameraObjects.hasOwnProperty(id)) continue;

            var cam = cameraObjects[id];
            var health = cameraHealth[id];
            var connected = health ? health.connected : false;

            var color = connected ? COLOR_ACTIVE : COLOR_INACTIVE;
            var fillOpacity = connected ? OPACITY_FILL_ACTIVE : OPACITY_FILL_INACTIVE;

            // Update cone fill
            if (cam.cone && cam.cone.material) {
                cam.cone.material.color.setHex(color);
                cam.cone.material.opacity = fillOpacity;
            }

            // Update wireframe
            if (cam.wireframe && cam.wireframe.material) {
                cam.wireframe.material.color.setHex(color);
            }

            // Update icon body color
            if (cam.icon && cam.icon.children.length > 0) {
                // Body mesh is first child
                cam.icon.children[0].material.color.setHex(color);

                // Status glow
                var glow = cam.icon.getObjectByName('statusGlow');
                if (glow) {
                    glow.material.color.setHex(color);
                    glow.material.opacity = connected ? 0.8 : 0.2;
                }
            }

            cam.active = connected;
        }
    }

    /**
     * Switch to a different machine type and rebuild camera visuals.
     * @param {string} type — machine type key, e.g. 'wheel_loader'
     */
    function setMachineType(type) {
        var machineData = null;

        if (GF.api && typeof GF.api.getMachines === 'function') {
            var machines = GF.api.getMachines();
            if (machines && machines[type]) {
                machineData = machines[type];
            }
        }

        if (!machineData && defaultMachines[type]) {
            machineData = defaultMachines[type];
        }

        if (machineData) {
            mountData = machineData.camera_mounts || [];
            cameraSpec = machineData.camera_spec || {};
            buildAllCameras();
        }
    }

    /**
     * Set the max draw distance for FOV cones.
     * @param {number} distance — distance in meters
     */
    function setClipDistance(distance) {
        clipDistance = distance;
        buildAllCameras();
    }

    /**
     * Show or hide all camera visuals.
     * @param {boolean} visible
     */
    function setVisible(visible) {
        if (cameraGroup) {
            cameraGroup.visible = visible;
        }
    }

    /**
     * Get the THREE.Group containing all camera visuals (for external manipulation).
     * @returns {THREE.Group|null}
     */
    function getGroup() {
        return cameraGroup;
    }

    /**
     * Dispose of all resources.
     */
    function dispose() {
        clearCameras();
        if (cameraGroup && scene) {
            scene.remove(cameraGroup);
        }
        cameraGroup = null;
        scene = null;
    }

    // ── Expose public interface ─────────────────────────────
    return {
        init: init,
        update: update,
        setMachineType: setMachineType,
        setClipDistance: setClipDistance,
        setVisible: setVisible,
        getGroup: getGroup,
        dispose: dispose
    };

})();
