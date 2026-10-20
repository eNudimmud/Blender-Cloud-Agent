import { test, expect } from '@playwright/test';
import { createHmac, randomBytes } from 'node:crypto';
import { readFile } from 'node:fs/promises';
const TOKEN = process.env.BCA_E2E_TOKEN || 'e2e-test-key-only-never-production-123456789';
const BASE_URL = process.env.BCA_E2E_BASE_URL || 'http://127.0.0.1:8765';
const REAL_WORKER = Boolean(process.env.BLENDER_BIN || process.env.BCA_E2E_REAL_WORKER);
async function signIn(page, ui = false) {
  if (!ui) {
    const message = `${Math.floor(Date.now() / 1000)}.${randomBytes(16).toString('hex')}`;
    const value = `${message}.${createHmac('sha256', TOKEN).update(message).digest('hex')}`;
    await page.context().addCookies([{ name: 'bca_session', value, url: BASE_URL, secure: BASE_URL.startsWith('https:'), httpOnly: true, sameSite: 'Strict' }]);
    await page.goto('/');
    await expect(page.locator('#workspace')).toBeVisible();
    await expect(page.getByRole('button', {name: '+ Nouveau', exact: true})).toBeEnabled();
    return;
  }
  await page.goto('/');
  await page.getByLabel('Clé d’accès à l’atelier').fill(TOKEN);
  await page.getByRole('button', { name: 'Se connecter', exact: true }).click();
  await expect(page.locator('#workspace')).toBeVisible();
  await expect(page.getByRole('button', {name: '+ Nouveau', exact: true})).toBeEnabled();
}
async function newProject(page) {
  await page.getByRole('button', { name: '+ Nouveau', exact: true }).click();
  await expect(page.locator('#project-workspace')).toBeVisible();
  await expect(page.getByRole('button', { name: '+ Nouveau', exact: true })).toBeEnabled();
}
async function propose(page, prompt) {
  await page.getByLabel('Ta demande', { exact: true }).fill(prompt);
  await page.locator('#send').click();
  await expect(page.getByRole('button', { name: 'Confirmer et lancer le rendu', exact: true })).toBeVisible();
}

test('mobile login, proposal review, render, persistence and downloads', async ({ page }) => {
  test.skip(!REAL_WORKER, 'Requires real Blender');
  const errors = [];
  const external = [];
  page.on('pageerror', (error) => errors.push(error.message));
  page.on('request', (request) => { if (!request.url().startsWith(BASE_URL)) external.push(request.url()); });
  await signIn(page, true); await newProject(page);
  await page.getByLabel('Nom du projet', { exact: true }).fill('Atelier Android validé');
  await page.getByRole('button', { name: 'Renommer', exact: true }).click();
  await expect(page.locator('#scene-info')).toContainText('Version 2');
  await propose(page, 'Ajoute un cube rouge de taille 2');
  await expect(page.locator('#jobs .job')).toHaveCount(0);
  await page.getByRole('button', { name: 'Prévisualiser la proposition', exact: true }).click();
  await expect(page.locator('#canvas')).toHaveAttribute('data-model-loaded', 'true');
  await expect(page.locator('#scene-label')).toContainText('Proposition');
  await page.getByRole('button', { name: 'Confirmer et lancer le rendu', exact: true }).click();
  await expect(page.locator('#jobs')).toContainText('Terminé', { timeout: 55000 });
  await expect(page.locator('#downloads')).toBeVisible();
  await expect(page.locator('#preview')).toBeHidden();
  for (const id of ['glb-link', 'blend-link', 'png-link']) {
    const href = await page.locator(`#${id}`).getAttribute('href');
    const response = await page.request.get(href);
    expect(response.status()).toBe(200);
    expect((await response.body()).length).toBeGreaterThan(100);
  }
  await page.reload();
  await expect(page.locator('#project-name')).toHaveValue('Atelier Android validé');
  await expect(page.locator('#conversation')).toContainText('Ajoute un cube rouge');
  await expect(page.locator('#downloads')).toBeVisible();
  await expect(page.locator('#canvas')).toHaveAttribute('data-model-loaded', 'true');
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  expect(errors).toEqual([]); expect(external).toEqual([]);
  if (test.info().project.name === 'android-chromium') {
    await page.evaluate(() => window.scrollTo(0, 0));
    await page.screenshot({ path: 'test-results/android-workspace.png', fullPage: true });
  }
});

test('touch orbit and pinch zoom on the proposed scene', async ({ page, context, isMobile }) => {
  test.skip(!isMobile, 'Android touch gestures');
  await signIn(page); await newProject(page); await propose(page, 'Ajoute un cylindre orange x=2');
  await page.getByRole('button', { name: 'Prévisualiser la proposition', exact: true }).click();
  await expect(page.locator('#canvas')).toHaveAttribute('data-model-loaded', 'true');
  await page.locator('#canvas').scrollIntoViewIfNeeded();
  const bounds = await page.locator('#canvas').boundingBox();
  const x = bounds.x + bounds.width / 2, y = bounds.y + bounds.height / 2;
  const cdp = await context.newCDPSession(page);
  const before = await page.locator('#canvas').screenshot();
  await cdp.send('Input.dispatchTouchEvent', { type: 'touchStart', touchPoints: [{ x, y, id: 0 }] });
  for (let step = 1; step <= 8; step++) await cdp.send('Input.dispatchTouchEvent', { type: 'touchMove', touchPoints: [{ x: x + step * 10, y: y + step * 4, id: 0 }] });
  await cdp.send('Input.dispatchTouchEvent', { type: 'touchEnd', touchPoints: [] });
  await page.waitForTimeout(400);
  const rotated = await page.locator('#canvas').screenshot();
  expect(rotated.equals(before)).toBe(false);
  await cdp.send('Input.dispatchTouchEvent', { type: 'touchStart', touchPoints: [{ x: x - 30, y, id: 0 }, { x: x + 30, y, id: 1 }] });
  for (let step = 1; step <= 5; step++) await cdp.send('Input.dispatchTouchEvent', { type: 'touchMove', touchPoints: [{ x: x - 30 - step * 8, y, id: 0 }, { x: x + 30 + step * 8, y, id: 1 }] });
  await cdp.send('Input.dispatchTouchEvent', { type: 'touchEnd', touchPoints: [] });
  await page.waitForTimeout(400);
  expect((await page.locator('#canvas').screenshot()).equals(rotated)).toBe(false);
});

test('network loss preserves a pending creation and resumes once', async ({ page, context }) => {
  await signIn(page);
  const previous = await page.request.get('/v1/projects');
  const count = (await previous.json()).length;
  await context.setOffline(true);
  await page.getByRole('button', { name: '+ Nouveau', exact: true }).click();
  await expect(page.locator('#feedback')).toContainText('Connexion interrompue');
  await context.setOffline(false);
  await page.reload();
  await expect(page.locator('#project-workspace')).toBeVisible();
  await expect(page.getByRole('button', {name: '+ Nouveau', exact: true})).toBeEnabled();
  const response = await page.request.get('/v1/projects');
  expect((await response.json()).length).toBe(count + 1);
  expect(await page.evaluate(() => sessionStorage.getItem('bca.pending'))).toBeNull();
});

test('WebGL failure keeps real PNG preview and artifact links', async ({ page }) => {
  test.skip(!REAL_WORKER, 'Requires real Blender');
  await page.route('**/static/vendor/viewer.js', (route) => route.abort());
  await signIn(page); await newProject(page); await propose(page, 'Ajoute une sphere bleue');
  await page.getByRole('button', { name: 'Confirmer et lancer le rendu', exact: true }).click();
  await expect(page.locator('#jobs')).toContainText('Terminé', { timeout: 55000 });
  await expect(page.locator('#preview')).toBeVisible();
  await expect(page.locator('#downloads')).toBeVisible();
  expect(await page.locator('#preview').evaluate((img) => img.complete && img.naturalWidth === 640)).toBe(true);
});

test('320px layout and safe text rendering', async ({ page }) => {
  await signIn(page); await newProject(page);
  await page.setViewportSize({ width: 320, height: 720 });
  await page.getByLabel('Nom du projet', { exact: true }).fill('<img src=x onerror=alert(1)>');
  await page.getByRole('button', { name: 'Renommer', exact: true }).click();
  await expect(page.locator('#project-name')).toHaveValue('<img src=x onerror=alert(1)>');
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  expect(await page.locator('#projects img').count()).toBe(0);
});


test('Android project download imports as a separate copy with the same scene', async ({ page }) => {
  await signIn(page); await newProject(page);
  const originalId = await page.evaluate(() => sessionStorage.getItem('bca.project'));
  await propose(page, 'Ajoute une sphère bleue x=3');
  const proposals = await (await page.request.get(`/v1/projects/${originalId}/chat`)).json();
  const scene = proposals.at(-1).scene;
  expect(scene.objects[0].color).toBe('#5d9ddd');
  const original = await (await page.request.get(`/v1/projects/${originalId}`)).json();
  await page.request.put(`/v1/projects/${originalId}`, {headers: {'X-CSRF-Token': '1'}, data: {name: 'Mon projet portable', scene, revision: original.revision}});
  await page.reload();
  await expect(page.locator('#project-name')).toHaveValue('Mon projet portable');
  const downloadPromise = page.waitForEvent('download');
  await page.getByRole('link', {name: 'Exporter le projet', exact: true}).click();
  const download = await downloadPromise;
  const buffer = await readFile(await download.path());
  const portable = JSON.parse(buffer.toString('utf8'));
  expect(portable.project.scene.objects[0].color).toBe('#5d9ddd');
  await expect(page.locator('#import-project')).toBeEnabled();
  await page.locator('#import-project').setInputFiles({name: download.suggestedFilename(), mimeType: 'application/json', buffer});
  await expect(page.locator('#feedback')).toContainText('Projet importé dans une nouvelle copie');
  const copiedId = await page.evaluate(() => sessionStorage.getItem('bca.project'));
  expect(copiedId).not.toBe(originalId);
  const copied = await (await page.request.get(`/v1/projects/${copiedId}`)).json();
  expect(copied.scene).toEqual(scene);
  expect(await (await page.request.get(`/v1/projects/${copiedId}/jobs`)).json()).toEqual([]);
  expect((await (await page.request.get(`/v1/projects/${originalId}`)).json()).scene).toEqual(scene);
});

test('invalid import leaves existing mobile projects untouched', async ({page}) => {
  await signIn(page); await newProject(page);
  const before = await (await page.request.get('/v1/projects')).json();
  await page.locator('#import-project').setInputFiles({name: 'bad.json', mimeType: 'application/json', buffer: Buffer.from('not JSON')});
  await expect(page.locator('#feedback')).toContainText('JSON valide');
  await page.locator('#import-project').setInputFiles({name: 'large.json', mimeType: 'application/json', buffer: Buffer.alloc(32769)});
  await expect(page.locator('#feedback')).toContainText('32 Kio');
  expect(await (await page.request.get('/v1/projects')).json()).toEqual(before);
});

test('lost response is resumed without reload or duplicate project creation', async ({page}) => {
  await signIn(page); await newProject(page);
  const oldId = await page.evaluate(() => sessionStorage.getItem('bca.project'));
  const before = (await (await page.request.get('/v1/projects')).json()).length;
  let loseOnce = true;
  await page.route('**/v1/projects', async route => {
    if (route.request().method() === 'POST' && loseOnce) {
      loseOnce = false;
      const response = await route.fetch();
      expect(response.status()).toBe(201);
      await route.abort();
    } else await route.continue();
  });
  await page.getByRole('button', {name: '+ Nouveau', exact: true}).click();
  await expect(page.getByRole('button', {name: 'Reprendre l’envoi', exact: true})).toBeVisible();
  await page.getByRole('button', {name: 'Reprendre l’envoi', exact: true}).click();
  await expect(page.locator('#resume-pending')).toBeHidden();
  const selected = await page.evaluate(() => sessionStorage.getItem('bca.project'));
  expect(selected).not.toBe(oldId);
  expect((await (await page.request.get('/v1/projects')).json()).length).toBe(before + 1);
});

test('viewer follows a foldable viewport change without page overflow', async ({page}) => {
  await signIn(page); await newProject(page); await propose(page, 'un cube orange');
  await page.getByRole('button', {name: 'Prévisualiser la proposition', exact: true}).click();
  for (const width of [344, 822, 393]) {
    await page.setViewportSize({width, height: 850});
    await expect(page.locator('#canvas')).toHaveAttribute('data-model-loaded', 'true');
    await expect.poll(() => page.locator('#canvas').evaluate(node => Math.abs(node.clientWidth - node.querySelector('canvas').clientWidth))).toBeLessThan(2);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  }
});

async function seedProject(page, objects) {
  const response = await page.request.post('/v1/projects', {
    headers: {'X-CSRF-Token': '1', 'Idempotency-Key': randomBytes(16).toString('hex')},
    data: {name: 'Atelier des objets', scene: {schema_version: 1, objects}},
  });
  expect(response.status()).toBe(201);
  const project = await response.json();
  await page.evaluate(id => sessionStorage.setItem('bca.project', id), project.id);
  await page.reload();
  await expect(page.locator('#project-name')).toHaveValue(project.name);
  await expect(page.locator('#selected-object')).toBeEnabled();
  return project;
}

const firstObject = {id: 'a'.repeat(32), name: 'Cube', shape: 'cube', color: '#e55b59', size: 2, position: [0, 0, 0]};
const secondObject = {id: 'b'.repeat(32), name: 'Cube', shape: 'cube', color: '#5d9ddd', size: 2, position: [4, 0, 0]};

test('explicit selection edits the first matching object and persists in a real GLB', async ({page}) => {
  test.skip(!REAL_WORKER, 'Requires real Blender');
  await signIn(page);
  const project = await seedProject(page, [firstObject, secondObject]);
  await page.getByLabel('Objet à modifier', {exact: true}).selectOption(firstObject.id);
  await expect(page.locator('#selection-info')).toContainText('aaaaaa');
  await expect(page.locator('#canvas canvas')).toHaveAttribute('data-selected-object', firstObject.id);
  await propose(page, 'Change sa couleur en vert');
  const proposals = await (await page.request.get(`/v1/projects/${project.id}/chat`)).json();
  expect(proposals.at(-1).scene.objects[0].color).toBe('#77caba');
  expect(proposals.at(-1).scene.objects[1]).toEqual(secondObject);
  await page.getByRole('button', {name: 'Confirmer et lancer le rendu', exact: true}).click();
  await expect(page.locator('#jobs')).toContainText('Terminé', {timeout: 55000});
  await expect(page.locator('#scene-label')).toContainText('Rendu');
  await expect(page.locator('#canvas canvas')).toHaveAttribute('data-selected-object', firstObject.id);
  await page.reload();
  await expect(page.getByLabel('Objet à modifier', {exact: true})).toHaveValue(firstObject.id);
  await expect(page.locator('#canvas canvas')).toHaveAttribute('data-selected-object', firstObject.id);
});

test('tap picks both declarative and real GLB objects while orbit does not pick', async ({page, context, isMobile}) => {
  test.skip(!REAL_WORKER, 'Requires real Blender');
  await signIn(page);
  await seedProject(page, [firstObject]);
  async function centerTap() {
    await page.locator('#canvas').scrollIntoViewIfNeeded();
    const box = await page.locator('#canvas').boundingBox();
    if (isMobile) await page.touchscreen.tap(box.x + box.width / 2, box.y + box.height / 2);
    else await page.mouse.click(box.x + box.width / 2, box.y + box.height / 2);
  }
  await centerTap();
  await expect(page.locator('#selected-object')).toHaveValue(firstObject.id);
  await page.locator('#selected-object').selectOption('');
  await page.locator('#canvas').scrollIntoViewIfNeeded();
  const box = await page.locator('#canvas').boundingBox();
  const x = box.x + box.width / 2, y = box.y + box.height / 2;
  if (isMobile) {
    const cdp = await context.newCDPSession(page);
    await cdp.send('Input.dispatchTouchEvent', {type: 'touchStart', touchPoints: [{x, y, id: 0}]});
    for (let n = 1; n <= 8; n++) await cdp.send('Input.dispatchTouchEvent', {type: 'touchMove', touchPoints: [{x: x + n * 9, y, id: 0}]});
    await cdp.send('Input.dispatchTouchEvent', {type: 'touchEnd', touchPoints: []});
    await cdp.send('Input.dispatchTouchEvent', {type: 'touchStart', touchPoints: [{x: x - 20, y, id: 0}, {x: x + 20, y, id: 1}]});
    await cdp.send('Input.dispatchTouchEvent', {type: 'touchMove', touchPoints: [{x: x - 40, y, id: 0}, {x: x + 40, y, id: 1}]});
    await cdp.send('Input.dispatchTouchEvent', {type: 'touchEnd', touchPoints: []});
    await cdp.detach();
  } else {
    await page.mouse.move(x, y); await page.mouse.down(); await page.mouse.move(x + 72, y, {steps: 8}); await page.mouse.up();
  }
  await expect(page.locator('#selected-object')).toHaveValue('');
  await expect(page.locator('#canvas canvas')).toHaveAttribute('data-selected-object', '');
  await page.getByRole('button', {name: 'Lancer un rendu de cette version', exact: true}).click();
  await expect(page.locator('#jobs')).toContainText('Terminé', {timeout: 55000});
  await expect(page.locator('#scene-label')).toContainText('Rendu');
  await centerTap();
  await expect(page.locator('#selected-object')).toHaveValue(firstObject.id);
  await expect(page.locator('#canvas canvas')).toHaveAttribute('data-selected-object', firstObject.id);
});

test('reviewed history restores a new version once after a server-committed response is lost', async ({page}) => {
  await signIn(page);
  const project = await seedProject(page, [firstObject]);
  await page.getByLabel('Nom du projet', {exact: true}).fill('Un autre nom');
  await page.getByRole('button', {name: 'Renommer', exact: true}).click();
  await expect(page.locator('#scene-info')).toContainText('Version 2');
  await page.getByText('Historique du projet', {exact: true}).click();
  await page.getByLabel('Version enregistrée', {exact: true}).selectOption('1');
  await page.getByRole('button', {name: 'Examiner cette version', exact: true}).click();
  await expect(page.locator('#scene-label')).toContainText('Historique · version 1');
  await expect(page.locator('#send')).toBeDisabled();
  await expect(page.locator('#selected-object')).toBeDisabled();
  await expect(page.locator('#render')).toBeDisabled();
  let loseOnce = true;
  await page.route('**/restore', async route => {
    if (loseOnce) { loseOnce = false; expect((await route.fetch()).status()).toBe(200); await route.abort(); }
    else await route.continue();
  });
  await page.getByRole('button', {name: 'Confirmer la restauration', exact: true}).click();
  await expect(page.locator('#resume-pending')).toBeVisible();
  await page.getByRole('button', {name: 'Reprendre l’envoi', exact: true}).click();
  await expect(page.locator('#scene-info')).toContainText('Version 3');
  await expect(page.locator('#project-name')).toHaveValue('Atelier des objets');
  await expect(page.locator('#send')).toBeEnabled();
  await expect(page.locator('#version-review')).toBeHidden();
  const restored = await (await page.request.get(`/v1/projects/${project.id}`)).json();
  expect(restored.revision).toBe(3); expect(restored.scene).toEqual(project.scene);
  expect(await (await page.request.get(`/v1/projects/${project.id}/jobs`)).json()).toEqual([]);
  expect((await (await page.request.get(`/v1/projects/${project.id}/versions`)).json()).map(v => v.revision)).toEqual([3, 2, 1]);
});

test('history confirmation refuses a concurrent edit and return-current unlocks editing', async ({page}) => {
  await signIn(page);
  const project = await seedProject(page, [firstObject]);
  await page.getByLabel('Nom du projet', {exact: true}).fill('Deux');
  await page.getByRole('button', {name: 'Renommer', exact: true}).click();
  await expect(page.locator('#scene-info')).toContainText('Version 2');
  await page.getByText('Historique du projet', {exact: true}).click();
  await page.getByLabel('Version enregistrée', {exact: true}).selectOption('1');
  await page.getByRole('button', {name: 'Examiner cette version', exact: true}).click();
  await expect(page.locator('#send')).toBeDisabled();
  await page.getByRole('button', {name: 'Revenir au projet actuel', exact: true}).click();
  await expect(page.locator('#send')).toBeEnabled();
  await page.getByLabel('Version enregistrée', {exact: true}).selectOption('1');
  await page.getByRole('button', {name: 'Examiner cette version', exact: true}).click();
  // Commit the competing edit after the reviewed restore has actually been sent.
  await page.route('**/restore', async route => {
    const changed = await page.request.put(`/v1/projects/${project.id}`, {headers: {'X-CSRF-Token': '1'}, data: {
      name: 'Changement concurrent', scene: project.scene, revision: 2,
    }});
    expect(changed.status()).toBe(200);
    await route.continue();
  });
  await page.getByRole('button', {name: 'Confirmer la restauration', exact: true}).click();
  await expect(page.locator('#feedback')).toContainText('Le projet a changé');
  await expect(page.locator('#project-name')).toHaveValue('Changement concurrent');
  await expect(page.locator('#scene-info')).toContainText('Version 3');
  expect(await (await page.request.get(`/v1/projects/${project.id}/jobs`)).json()).toEqual([]);
});
