import { test, expect } from '@playwright/test';
import { createHmac, randomBytes } from 'node:crypto';
const TOKEN = 'e2e-test-key-only-never-production-123456789';
async function signIn(page, ui = false) {
  if (!ui) {
    const message = `${Math.floor(Date.now() / 1000)}.${randomBytes(16).toString('hex')}`;
    const value = `${message}.${createHmac('sha256', TOKEN).update(message).digest('hex')}`;
    await page.context().addCookies([{ name: 'bca_session', value, url: 'http://127.0.0.1:8765', httpOnly: true, sameSite: 'Strict' }]);
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
}
async function propose(page, prompt) {
  await page.getByLabel('Ta demande', { exact: true }).fill(prompt);
  await page.locator('#send').click();
  await expect(page.getByRole('button', { name: 'Confirmer et lancer le rendu', exact: true })).toBeVisible();
}

test('mobile login, proposal review, render, persistence and downloads', async ({ page }) => {
  test.skip(!process.env.BLENDER_BIN, 'Requires real Blender');
  const errors = [];
  const external = [];
  page.on('pageerror', (error) => errors.push(error.message));
  page.on('request', (request) => { if (!request.url().startsWith('http://127.0.0.1:8765')) external.push(request.url()); });
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
  test.skip(!process.env.BLENDER_BIN, 'Requires real Blender');
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
