import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';

function disposeTree(root) {
  root?.traverse((node) => {
    node.geometry?.dispose();
    const materials = node.material ? (Array.isArray(node.material) ? node.material : [node.material]) : [];
    for (const material of materials) {
      for (const value of Object.values(material)) if (value?.isTexture) value.dispose();
      material.dispose();
    }
  });
}

export function createViewer(container, onLost, onSelect = () => {}) {
  const scene = new THREE.Scene();
  const camera = new THREE.PerspectiveCamera(42, 1, 0.01, 2000);
  camera.position.set(5, 4, 6);
  const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true, powerPreference: 'low-power' });
  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 1.75));
  renderer.outputColorSpace = THREE.SRGBColorSpace;
  container.replaceChildren(renderer.domElement);
  renderer.domElement.addEventListener('webglcontextlost', (event) => {
    event.preventDefault();
    onLost();
  });
  scene.add(new THREE.HemisphereLight(0xffffff, 0x485a71, 2.5));
  const light = new THREE.DirectionalLight(0xffffff, 2.5);
  light.position.set(4, 9, 6);
  scene.add(light);
  const grid = new THREE.GridHelper(12, 12, 0x56776f, 0x304655);
  scene.add(grid);
  const controls = new OrbitControls(camera, renderer.domElement);
  controls.enableDamping = !window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  controls.dampingFactor = 0.1;
  controls.maxPolarAngle = Math.PI * 0.98;
  controls.minDistance = 0.2;
  controls.maxDistance = 800;
  let model = null;
  let generation = 0;
  let frame = 0;
  let disposed = false;
  let selectedId = null;
  let selection = null;
  const pointers = new Set();
  let tap = null;
  function select(id) {
    selectedId = id;
    if (selection) { scene.remove(selection); disposeTree(selection); selection = null; }
    let target = null;
    model?.traverse((node) => { if (node.userData.bca_object_id === id) target = node; });
    if (target) { selection = new THREE.BoxHelper(target, 0xf1d382); scene.add(selection); }
    renderer.domElement.dataset.selectedObject = target ? id : '';
    invalidate();
  }
  function pointerDown(event) {
    pointers.add(event.pointerId);
    tap = pointers.size === 1 && event.button === 0
      ? { id: event.pointerId, x: event.clientX, y: event.clientY, at: performance.now() } : null;
  }
  function pointerMove(event) {
    if (tap && Math.hypot(event.clientX - tap.x, event.clientY - tap.y) > 8) tap = null;
  }
  function pointerUp(event) {
    if (tap?.id === event.pointerId && pointers.size === 1 && performance.now() - tap.at < 700 && model
        && Math.hypot(event.clientX - tap.x, event.clientY - tap.y) <= 8) {
      const bounds = renderer.domElement.getBoundingClientRect();
      const point = new THREE.Vector2((event.clientX - bounds.left) / bounds.width * 2 - 1,
                                     -(event.clientY - bounds.top) / bounds.height * 2 + 1);
      const ray = new THREE.Raycaster();
      ray.setFromCamera(point, camera);
      let target = ray.intersectObject(model, true)[0]?.object;
      while (target && !target.userData.bca_object_id) target = target.parent;
      onSelect(target?.userData.bca_object_id || null);
    }
    pointers.delete(event.pointerId); tap = null;
  }
  function pointerCancel(event) { pointers.delete(event.pointerId); tap = null; }
  renderer.domElement.addEventListener('pointerdown', pointerDown);
  renderer.domElement.addEventListener('pointermove', pointerMove);
  renderer.domElement.addEventListener('pointerup', pointerUp);
  renderer.domElement.addEventListener('pointercancel', pointerCancel);
  function invalidate() {
    if (!frame && !disposed && !document.hidden) frame = requestAnimationFrame(draw);
  }
  function draw() {
    frame = 0;
    if (disposed || document.hidden) return;
    const moving = controls.update();
    renderer.render(scene, camera);
    if (moving) invalidate();
  }
  function resize() {
    const width = container.clientWidth;
    const height = container.clientHeight;
    if (!width || !height) return;
    camera.aspect = width / height;
    camera.updateProjectionMatrix();
    renderer.setSize(width, height);
    invalidate();
  }
  function reset() {
    const box = model ? new THREE.Box3().setFromObject(model) : new THREE.Box3();
    const center = box.isEmpty() ? new THREE.Vector3() : box.getCenter(new THREE.Vector3());
    const radius = box.isEmpty() ? 3 : Math.max(box.getSize(new THREE.Vector3()).length(), 0.4);
    controls.target.copy(center);
    camera.position.copy(center).add(new THREE.Vector3(radius, radius * 0.7, radius * 1.25));
    camera.near = Math.max(radius / 1000, 0.001);
    camera.far = Math.max(radius * 100, 1000);
    camera.updateProjectionMatrix();
    grid.position.set(center.x, box.isEmpty() ? 0 : box.min.y - 0.01, center.z);
    grid.scale.setScalar(Math.max(radius / 6, 0.2));
    controls.update();
    invalidate();
  }
  function replace(next) {
    if (model) {
      scene.remove(model);
      disposeTree(model);
    }
    model = next;
    scene.add(model);
    container.dataset.modelLoaded = 'true';
    reset();
    select(selectedId);
  }
  controls.addEventListener('change', invalidate);
  const observer = new ResizeObserver(resize);
  observer.observe(container);
  document.addEventListener('visibilitychange', invalidate);
  resize();
  reset();
  return {
    async load(url) {
      const serial = ++generation;
      const gltf = await new GLTFLoader().loadAsync(url);
      if (serial !== generation || disposed) { disposeTree(gltf.scene); return false; }
      replace(gltf.scene);
      return true;
    },
    showSpec(spec) {
      generation++;
      const group = new THREE.Group();
      for (const object of spec.objects) {
        const half = object.size / 2;
        const geometry = object.shape === 'cube' ? new THREE.BoxGeometry(object.size, object.size, object.size)
          : object.shape === 'sphere' ? new THREE.SphereGeometry(half, 32, 16)
            : new THREE.CylinderGeometry(half, half, object.size, 48);
        const mesh = new THREE.Mesh(geometry, new THREE.MeshStandardMaterial({ color: object.color, roughness: 0.38 }));
        mesh.userData.bca_object_id = object.id;
        const [x, y, z] = object.position;
        mesh.position.set(x, z, -y);
        group.add(mesh);
      }
      replace(group);
    },
    reset,
    select,
    dispose() {
      disposed = true;
      generation++;
      cancelAnimationFrame(frame);
      observer.disconnect();
      document.removeEventListener('visibilitychange', invalidate);
      controls.dispose();
      renderer.domElement.removeEventListener('pointerdown', pointerDown);
      renderer.domElement.removeEventListener('pointermove', pointerMove);
      renderer.domElement.removeEventListener('pointerup', pointerUp);
      renderer.domElement.removeEventListener('pointercancel', pointerCancel);
      disposeTree(selection);
      disposeTree(model);
      disposeTree(grid);
      renderer.dispose();
      container.replaceChildren();
    },
  };
}
