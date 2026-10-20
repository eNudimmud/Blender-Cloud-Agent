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
    return;
  }
  await page.goto('/');
  await page.getByLabel('Clé d’accès à l’atelier').fill(TOKEN);
  await page.getByRole('button', { name: 'Se connecter', exact: true }).click();
  await expect(page.locator('#workspace')).toBeVisible();
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
