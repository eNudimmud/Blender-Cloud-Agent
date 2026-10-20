const $ = (id) => document.getElementById(id);
const labels = { queued: 'En attente', running: 'Blender travaille…', succeeded: 'Terminé', failed: 'Échec', cancelled: 'Annulé' };
const errors = { timeout: 'Temps de rendu dépassé', worker_lost: 'Worker interrompu. Tu peux relancer le rendu.', blender_failed: 'Blender a échoué', worker_error: 'Worker indisponible', disk_full: 'Stockage plein', invalid_artifact: 'Fichiers incomplets', log_limit: 'Rendu interrompu' };
const state = { project: null, jobs: [], proposals: [], versions: [], selectedId: null, review: null, editable: true, viewer: null, viewerFailed: false, busy: false, authenticated: false, agentMode: 'rules', epoch: 0, shown: null, artifact: null };
function cacheGet(key) { try { return sessionStorage.getItem(key); } catch { return null; } }
function cacheSet(key, value) { try { value == null ? sessionStorage.removeItem(key) : sessionStorage.setItem(key, value); } catch { /* Private browser: server persistence still works. */ } }
function message(text = '') { $('feedback').textContent = text; }
function element(tag, text, className) { const node = document.createElement(tag); if (text) node.textContent = text; if (className) node.className = className; return node; }
function pendingAction() {
  try {
    const pending = JSON.parse(cacheGet('bca.pending'));
    if (!pending) return null;
    if (typeof pending.body !== 'string' || !/^[A-Za-z0-9_-]{8,100}$/.test(pending.key) ||
        !/^\/v1\/projects(?:\/import|\/[a-f0-9]{32}\/(?:chat|jobs|restore|proposals\/[a-f0-9]{32}\/confirm))?$/.test(pending.path)) throw Error();
    JSON.parse(pending.body);
    return pending;
  } catch { cacheSet('bca.pending', null); return null; }
}
function updatePendingButton() { $('resume-pending').hidden = !state.authenticated || !pendingAction(); }
function loginScreen() {
  state.authenticated = false;
  state.epoch++;
  state.viewer?.dispose(); state.viewer = null; state.shown = null;
  $('workspace').hidden = true; $('login-panel').hidden = false;
  $('connection').textContent = 'Atelier verrouillé';
  updatePendingButton();
}
async function request(path, options = {}) {
  const response = await fetch(path, { credentials: 'same-origin', ...options,
    headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': '1', ...options.headers } });
  if (response.status === 204) return null;
  const data = await response.json();
  if (!response.ok) {
    if (response.status === 401 && path !== '/v1/auth/session') loginScreen();
    const error = new Error(typeof data.detail === 'string' ? data.detail : 'Demande invalide. Vérifie les valeurs.');
    error.status = response.status; throw error;
  }
  return data;
}
async function action(path, body = {}) {
  const serialized = JSON.stringify(body);
  let pending = pendingAction();
  if (pending && (pending.path !== path || pending.body !== serialized)) throw new Error('Une demande attend la connexion. Recharge la page pour la reprendre.');
  pending ||= { path, body: serialized, key: crypto.randomUUID() };
  cacheSet('bca.pending', JSON.stringify(pending));
  updatePendingButton();
  try {
    const result = await request(path, { method: 'POST', body: serialized, headers: { 'Idempotency-Key': pending.key } });
    cacheSet('bca.pending', null); updatePendingButton(); return result;
  } catch (error) {
    if (error.status && error.status < 500) cacheSet('bca.pending', null);
    updatePendingButton();
    throw error;
  }
}
async function resumePending(automatic = false) {
  const pending = pendingAction();
  if (!pending) return null;
  if (automatic && state.agentMode === 'llm' && pending.path.endsWith('/chat')) {
    message('Une demande IA attend ta décision. Reprendre l’envoi peut appeler de nouveau le fournisseur.');
    updatePendingButton(); return null;
  }
  const result = await action(pending.path, JSON.parse(pending.body));
  const projectId = /^\/v1\/projects(?:\/import)?$/.test(pending.path)
    ? result.id : pending.path.match(/^\/v1\/projects\/([a-f0-9]{32})\//)?.[1];
  if (projectId) cacheSet('bca.project', projectId);
  message('Dernière demande reprise.');
  return projectId;
}
async function locked(task) {
  if (state.busy) return;
  state.busy = true;
  const inputs = [...document.querySelectorAll('button,select,input,textarea')];
  inputs.forEach((node) => node.disabled = true);
  message();
  try { await task(); } catch (error) {
    message(error.status ? error.message : 'Connexion interrompue. Tes projets restent enregistrés ; recharge pour reprendre la demande.');
    if (error.status === 409 && state.project) await openProject(state.project.id).catch(() => {});
  } finally {
    state.busy = false;
    for (const node of document.querySelectorAll('button,select,input,textarea')) node.disabled = false;
    syncViewControls();
  }
}
function syncViewControls() {
  for (const node of document.querySelectorAll('#selected-object,#message,#send,#render,#project-name,#name-form button,[data-prompt]')) node.disabled = state.busy || !state.editable;
  $('return-current').hidden = state.editable;
}
function renderSelection() {
  $('selected-object').value = state.selectedId || '';
  const object = state.project?.scene.objects.find((obj) => obj.id === state.selectedId);
  $('selection-info').textContent = !state.editable ? 'Aperçu en lecture seule · Reviens au projet actuel pour le modifier.'
    : object ? `Cible : ${object.name} · ${object.id.slice(0, 6)} · [${object.position.join(', ')}]. Touche un objet dans la 3D ou choisis-le ici.`
      : 'Cible automatique : dernier objet correspondant. Touche un objet dans la 3D pour le choisir.';
  state.viewer?.select(state.editable ? state.selectedId : null);
}
function selectObject(id) {
  if (!state.editable || state.busy) return;
  state.selectedId = state.project.scene.objects.some((obj) => obj.id === id) ? id : null;
  cacheSet('bca.selection', JSON.stringify({ project: state.project.id, id: state.selectedId }));
  renderSelection();
}
function setView(editable) {
  state.editable = editable; state.review = null;
  $('version-review').hidden = true;
  syncViewControls(); renderSelection();
}
function renderVersions() {
  $('versions').replaceChildren();
  const reasons = { created: 'Création', edited: 'Modification', confirmed: 'Conversation confirmée', restored: 'Restauration', migration: 'Reprise du projet existant' };
  for (const version of state.versions) {
    const option = element('option', `Version ${version.revision} · ${reasons[version.reason]} · ${version.object_count} objet(s)`);
    option.value = version.revision; $('versions').append(option);
  }
}
async function ensureViewer() {
  if (state.viewer) return state.viewer;
  if (state.viewerFailed) return null;
  try {
    const { createViewer } = await import('/static/vendor/viewer.js');
    state.viewer = createViewer($('canvas'), () => {
      state.viewerFailed = true;
      state.viewer?.dispose(); state.viewer = null;
      $('reset-view').hidden = true; $('retry-view').hidden = false;
      if (state.artifact) { $('preview').hidden = false; $('hint').textContent = 'Aperçu image · La 3D peut être réactivée.'; }
      else $('hint').textContent = '3D indisponible sur ce navigateur. Les rendus restent accessibles.';
    }, selectObject);
    state.viewer.select(state.editable ? state.selectedId : null);
    $('reset-view').hidden = false; $('retry-view').hidden = true;
    return state.viewer;
  } catch {
    state.viewerFailed = true;
    $('retry-view').hidden = false;
    return null;
  }
}
async function showSpec(spec, label, editable = false) {
  setView(editable);
  state.artifact = null; state.shown = label;
  $('scene-label').textContent = label;
  $('preview').hidden = true; $('downloads').hidden = true;
  const viewer = await ensureViewer();
  if (viewer) { viewer.showSpec(spec); $('hint').textContent = '1 doigt : tourner · 2 doigts : zoomer / déplacer'; }
  else $('hint').textContent = '3D indisponible · Lance un rendu pour obtenir une image.';
}
async function showJob(job) {
  setView(job.revision === state.project.revision);
  const epoch = state.epoch;
  state.artifact = job; state.shown = job.id;
  $('scene-label').textContent = `Rendu · version ${job.revision}`;
  $('preview').src = job.files['preview.png']; $('preview').hidden = false;
  for (const [id, file] of [['glb-link', 'scene.glb'], ['blend-link', 'scene.blend'], ['png-link', 'preview.png']]) $(id).href = job.files[file];
  $('downloads').hidden = false;
  $('hint').textContent = 'Aperçu Blender';
  const viewer = await ensureViewer();
  if (viewer) {
    try {
      const loaded = await viewer.load(job.files['scene.glb']);
      if (loaded && epoch === state.epoch && state.shown === job.id) { $('preview').hidden = true; $('hint').textContent = '1 doigt : tourner · 2 doigts : zoomer / déplacer'; }
    } catch { if (epoch === state.epoch) $('hint').textContent = 'Aperçu image · Le modèle 3D reste téléchargeable.'; }
  }
}
function renderChat() {
  const nearBottom = $('conversation').scrollHeight - $('conversation').scrollTop - $('conversation').clientHeight < 80;
  $('conversation').replaceChildren();
  for (const proposal of state.proposals) {
    const item = element('article', '', 'chat-item');
    item.append(element('p', proposal.message, 'chat-user'), element('p', proposal.summary, 'chat-answer'));
    if (proposal.supported) {
      const details = element('details');
      details.append(element('summary', `${proposal.scene.objects.length} objet(s) · Voir les valeurs proposées`));
      for (const obj of proposal.scene.objects) details.append(element('p', `${obj.name} (${obj.id.slice(0, 6)}) · ${obj.shape} · taille ${obj.size} · ${obj.color} · [${obj.position.join(', ')}]`, 'chat-preview'));
      item.append(details);
      if (!proposal.job_id && proposal.base_revision === state.project.revision) {
        const preview = element('button', 'Prévisualiser la proposition');
        preview.type = 'button'; preview.addEventListener('click', () => locked(() => showSpec(proposal.scene, 'Proposition · à confirmer')));
        const confirm = element('button', 'Confirmer et lancer le rendu');
        confirm.type = 'button';
        confirm.addEventListener('click', () => locked(async () => {
          const pid = state.project.id;
          await action(`/v1/projects/${pid}/proposals/${proposal.id}/confirm`);
          await openProject(pid); message('Modification enregistrée. Le rendu est dans la file.');
        }));
        item.append(preview, confirm);
      } else item.append(element('small', proposal.job_id ? 'Modification confirmée et enregistrée.' : 'Le projet a changé : prépare une nouvelle demande.', 'muted'));
    }
    $('conversation').append(item);
  }
  if (nearBottom) $('conversation').scrollTop = $('conversation').scrollHeight;
}
function renderJobs() {
  $('jobs').replaceChildren();
  for (const job of state.jobs) {
    const row = element('div', '', 'job'); const text = element('div', `Version ${job.revision} · ${labels[job.status]}`);
    if (job.error_code) text.append(element('small', errors[job.error_code] || 'Rendu interrompu. Tu peux réessayer.'));
    row.append(text);
    if (job.status === 'succeeded') {
      const view = element('button', 'Ouvrir', 'secondary'); view.addEventListener('click', () => locked(() => showJob(job))); row.append(view);
    } else if (['queued', 'running'].includes(job.status)) {
      const cancel = element('button', 'Annuler', 'secondary'); cancel.addEventListener('click', () => locked(async () => { await request(`/v1/jobs/${job.id}/cancel`, { method: 'POST', body: '{}' }); await poll(); })); row.append(cancel);
    }
    $('jobs').append(row);
  }
}
async function loadProjects() {
  const projects = await request('/v1/projects');
  $('projects').replaceChildren(element('option', 'Choisir un projet'));
  $('projects').firstElementChild.value = '';
  for (const project of projects) { const option = element('option', project.name); option.value = project.id; $('projects').append(option); }
  $('projects').value = state.project?.id || '';
  $('empty-state').hidden = projects.length > 0;
  return projects;
}
async function openProject(id) {
  const epoch = ++state.epoch;
  state.shown = null; state.artifact = null;
  const [project, jobs, proposals, versions] = await Promise.all([request(`/v1/projects/${id}`), request(`/v1/projects/${id}/jobs`), request(`/v1/projects/${id}/chat`), request(`/v1/projects/${id}/versions`)]);
  if (epoch !== state.epoch) return;
  Object.assign(state, { project, jobs, proposals, versions }); cacheSet('bca.project', id);
  let selection;
  try { selection = JSON.parse(cacheGet('bca.selection')); } catch { selection = null; }
  state.selectedId = selection?.project === id && project.scene.objects.some((obj) => obj.id === selection.id) ? selection.id : null;
  $('selected-object').replaceChildren(element('option', 'Automatique · dernier objet correspondant'));
  $('selected-object').firstElementChild.value = '';
  for (const object of project.scene.objects) {
    const option = element('option', `${object.name} · ${object.id.slice(0, 6)} · [${object.position.join(', ')}]`);
    option.value = object.id; $('selected-object').append(option);
  }
  $('projects').value = id; $('project-workspace').hidden = false; $('empty-state').hidden = true;
  $('project-name').value = project.name;
  $('export-project').href = `/v1/projects/${id}/export`; $('export-project').hidden = false;
  $('scene-info').textContent = `Version ${project.revision} · ${project.scene.objects.length}/24 objets · Enregistrée sur le serveur`;
  renderChat(); renderJobs(); renderVersions();
  const latest = jobs.find((job) => job.status === 'succeeded' && job.revision === project.revision);
  if (latest) await showJob(latest); else await showSpec(project.scene, `Projet · version ${project.revision}`, true);
}
async function poll() {
  if (!state.authenticated || document.hidden || !state.project) return;
  const epoch = state.epoch;
  const [jobs, capabilities, current] = await Promise.all([request(`/v1/projects/${state.project.id}/jobs`), request('/v1/capabilities'), request(`/v1/projects/${state.project.id}`)]);
  if (epoch !== state.epoch) return;
  if (current.revision !== state.project.revision) { await openProject(current.id); return; }
  $('connection').textContent = 'Atelier connecté';
  $('worker-status').textContent = capabilities.workers_online ? 'Moteur Blender disponible' : 'Moteur hors ligne · Les demandes attendent dans la file';
  const changed = JSON.stringify(jobs.map((job) => [job.id, job.status])) !== JSON.stringify(state.jobs.map((job) => [job.id, job.status]));
  state.jobs = jobs;
  if (changed) {
    renderJobs();
    const latest = jobs.find((job) => job.status === 'succeeded' && job.revision === state.project.revision);
    if (state.editable && latest && state.shown !== latest.id) await showJob(latest);
  }
}
async function startWorkspace() {
  state.authenticated = true; $('login-panel').hidden = true; $('workspace').hidden = false;
  $('connection').textContent = 'Atelier connecté';
  const capabilities = await request('/v1/capabilities');
  state.agentMode = capabilities.agent_mode;
  updatePendingButton();
  try { await resumePending(true); } catch (error) { message(error.message); }
  const projects = await loadProjects();
  const selected = projects.find((project) => project.id === cacheGet('bca.project')) || projects[0];
  if (selected) await openProject(selected.id);
  $('agent-label').textContent = capabilities.agent_mode === 'llm' ? 'Planificateur IA' : 'Assistant guidé';
  if (capabilities.agent_mode === 'llm') $('agent-description').textContent = capabilities.paid_ai_enabled ? 'IA externe activée par l’administrateur · Confirmation avant chaque rendu.' : 'IA externe désactivée. Aucun appel payant autorisé.';
  await poll();
}
$('login-form').addEventListener('submit', (event) => { event.preventDefault(); locked(async () => { await request('/v1/auth/session', { method: 'POST', body: JSON.stringify({ token: $('token').value }) }); $('token').value = ''; await startWorkspace(); }); });
$('logout').addEventListener('click', () => locked(async () => { await request('/v1/auth/session', { method: 'DELETE' }); cacheSet('bca.project', null); cacheSet('bca.pending', null); loginScreen(); }));
$('projects').addEventListener('change', () => { if ($('projects').value) locked(() => openProject($('projects').value)); });
$('new-project').addEventListener('click', () => locked(async () => { const project = await action('/v1/projects', { name: 'Nouveau projet' }); await loadProjects(); await openProject(project.id); }));
$('resume-pending').addEventListener('click', () => locked(async () => { const id = await resumePending(); await loadProjects(); if (id) await openProject(id); await poll(); }));
$('import-project').addEventListener('change', () => locked(async () => {
  const file = $('import-project').files?.[0];
  if (!file) return;
  try {
    if (file.size > 32768) { const error = new Error('Ce fichier dépasse la limite de 32 Kio.'); error.status = 413; throw error; }
    let body;
    try { body = JSON.parse(await file.text()); } catch { const error = new Error('Ce fichier ne contient pas un projet JSON valide.'); error.status = 422; throw error; }
    const project = await action('/v1/projects/import', body);
    await loadProjects(); await openProject(project.id);
    message('Projet importé dans une nouvelle copie.');
  } finally { $('import-project').value = ''; }
}));
$('name-form').addEventListener('submit', (event) => { event.preventDefault(); locked(async () => { const project = await request(`/v1/projects/${state.project.id}`, { method: 'PUT', body: JSON.stringify({ name: $('project-name').value, scene: state.project.scene, revision: state.project.revision }) }); await loadProjects(); await openProject(project.id); }); });
$('chat-form').addEventListener('submit', (event) => { event.preventDefault(); if (!state.editable) return; locked(async () => { const pid = state.project.id; await action(`/v1/projects/${pid}/chat`, { message: $('message').value, revision: state.project.revision, object_id: state.selectedId }); $('message').value = ''; state.proposals = await request(`/v1/projects/${pid}/chat`); renderChat(); }); });
$('selected-object').addEventListener('change', () => selectObject($('selected-object').value));
$('versions').addEventListener('change', () => { state.review = null; $('version-review').hidden = true; });
$('return-current').addEventListener('click', () => locked(() => openProject(state.project.id)));
$('review-version').addEventListener('click', () => locked(async () => {
  const version = await request(`/v1/projects/${state.project.id}/versions/${$('versions').value}`);
  await showSpec(version.scene, `Historique · version ${version.revision}`);
  state.review = { project: state.project.id, revision: state.project.revision, source_revision: version.revision };
  $('version-description').textContent = `Version ${version.revision} · ${version.name} · ${version.object_count} objet(s). ${version.revision === state.project.revision ? 'C’est la version actuelle.' : `La restaurer créera la version ${state.project.revision + 1}, avec ce nom et cette scène. Aucun rendu ne sera lancé.`}`;
  $('restore-version').hidden = version.revision === state.project.revision;
  $('version-review').hidden = false;
}));
$('restore-version').addEventListener('click', () => locked(async () => {
  const review = state.review;
  if (!review || review.project !== state.project.id) return;
  const project = await action(`/v1/projects/${review.project}/restore`, { revision: review.revision, source_revision: review.source_revision });
  await loadProjects(); await openProject(project.id);
  message(`Version ${project.revision} enregistrée. Aucun rendu lancé.`);
}));
for (const suggestion of document.querySelectorAll('[data-prompt]')) suggestion.addEventListener('click', () => { $('message').value = suggestion.dataset.prompt; $('message').focus(); });
$('render').addEventListener('click', () => locked(async () => { await action(`/v1/projects/${state.project.id}/jobs`, { revision: state.project.revision }); await poll(); message('Rendu ajouté à la file.'); }));
$('reset-view').addEventListener('click', () => state.viewer?.reset());
$('retry-view').addEventListener('click', () => locked(async () => { const artifact = state.artifact; state.viewer?.dispose(); state.viewer = null; state.viewerFailed = false; if (artifact) await showJob(artifact); else await showSpec(state.project.scene, `Projet · version ${state.project.revision}`, true); }));
let polling = false;
async function refresh() { if (polling || state.busy) return; polling = true; try { await poll(); } catch { $('connection').textContent = 'Reconnexion…'; } finally { polling = false; } }
setInterval(refresh, 3000);
document.addEventListener('visibilitychange', refresh);
window.addEventListener('online', () => {
  if (state.authenticated && !state.busy && pendingAction()) locked(async () => {
    const id = await resumePending(true); await loadProjects(); if (id) await openProject(id); await poll();
  }); else refresh();
});
request('/v1/auth/session').then((session) => session.authenticated ? locked(startWorkspace) : loginScreen()).catch(() => { loginScreen(); message('Serveur inaccessible. Réessaie après avoir retrouvé une connexion.'); });
