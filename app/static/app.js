import * as THREE from "https://esm.sh/three@0.170.0";
import { OrbitControls } from "https://esm.sh/three@0.170.0/examples/jsm/controls/OrbitControls.js";
import { GLTFLoader } from "https://esm.sh/three@0.170.0/examples/jsm/loaders/GLTFLoader.js";
const $=id=>document.getElementById(id);
const container=$("canvas"),scene=new THREE.Scene();
const camera=new THREE.PerspectiveCamera(45,1,.1,1000);
camera.position.set(4,3,5);
const renderer=new THREE.WebGLRenderer({antialias:true,alpha:true});
renderer.setPixelRatio(Math.min(window.devicePixelRatio||1,2));
container.appendChild(renderer.domElement);
scene.add(new THREE.HemisphereLight(0xffffff,0x4d6588,2));
const key=new THREE.DirectionalLight(0xffffff,2);key.position.set(4,8,6);scene.add(key);
const grid=new THREE.GridHelper(12,12,0x3d596b,0x263746);scene.add(grid);
const controls=new OrbitControls(camera,renderer.domElement);controls.enableDamping=true;
let model=null;
function resize(){const w=container.clientWidth,h=container.clientHeight;camera.aspect=w/h;camera.updateProjectionMatrix();renderer.setSize(w,h)}
new ResizeObserver(resize).observe(container);resize();
function animate(){requestAnimationFrame(animate);controls.update();renderer.render(scene,camera)}animate();
function display(url){new GLTFLoader().load(url,gltf=>{if(model)scene.remove(model);model=gltf.scene;scene.add(model);const box=new THREE.Box3().setFromObject(model);const center=box.getCenter(new THREE.Vector3()),radius=Math.max(box.getSize(new THREE.Vector3()).length(),1);controls.target.copy(center);camera.position.copy(center).add(new THREE.Vector3(radius,radius*.7,radius));camera.lookAt(center);controls.update();$("hint").textContent="Drag to orbit · Pinch to zoom";},undefined,()=>{$("feedback").textContent="Scene generated, but GLB preview could not load."})}
$("size").addEventListener("input",()=>{$("size-value").textContent=$("size").value});
fetch("/health").then(r=>{if(!r.ok)throw Error();$("status").textContent="API online"}).catch(()=>$("status").textContent="API offline");
$("scene-form").addEventListener("submit",async e=>{e.preventDefault();const button=$("generate");button.disabled=true;button.textContent="Generating…";$("feedback").textContent="Blender is building your scene. Please wait.";try{const r=await fetch("/v1/scenes",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({shape:$("shape").value,size:Number($("size").value),name:$("name").value})});const data=await r.json();if(!r.ok)throw Error(data.detail||"Generation failed");for(const [id,key] of [["blend-link","scene.blend"],["glb-link","scene.glb"],["png-link","preview.png"]])$(id).href=data.files[key];$("downloads").hidden=false;display(data.files["scene.glb"]);$("feedback").textContent="Scene created. Download your files below."}catch(err){$("feedback").textContent=String(err.message||err)}finally{button.disabled=false;button.textContent="Generate scene"}});
