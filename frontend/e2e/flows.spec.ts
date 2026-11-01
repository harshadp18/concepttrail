import { expect, test, type Page } from '@playwright/test';
import fs from 'node:fs';
import path from 'node:path';

const creds: Record<string, string> = JSON.parse(
  fs.readFileSync(path.resolve(import.meta.dirname, '../../.local/demo_credentials.json'), 'utf8')
);
const STUDENT = 'demo-l8-03';
const TEACHER_A = 'demo.teacher.a@example.invalid';
const TEACHER_B = 'demo.teacher.b@example.invalid';

async function login(page: Page, role: 'student' | 'teacher', user: string) {
  await page.goto(`/login?role=${role}`);
  await page.getByLabel(role === 'student' ? 'Username' : 'School email').fill(user);
  await page.getByLabel(role === 'student' ? '8-digit PIN' : 'Password', { exact: true }).fill(creds[user]);
  await page.getByRole('button', { name: /sign in/i }).click();
  await page.waitForURL(role === 'student' ? /\/student\/home/ : /\/teacher\/classes/);
}

test('protected routes send visitors to the right sign-in screen', async ({ page }) => {
  await page.goto('/teacher/heatmap');
  await expect(page).toHaveURL(/\/login\?role=teacher/);
  await expect(page.getByRole('heading', { name: 'See progress. Support every learner.' })).toBeVisible();
});

test('wrong credentials and the wrong role are explained', async ({ page }) => {
  await page.goto('/login');
  await page.getByLabel('Username').fill(STUDENT);
  await page.getByLabel('8-digit PIN').fill('00000000');
  await page.getByRole('button', { name: 'Sign in' }).click();
  await expect(page.getByRole('alert')).toContainText(/don't match|Too many attempts/);
  await page.getByRole('tab', { name: /teacher/i }).click();
  await page.getByLabel('School email').fill(STUDENT);
  await page.getByLabel('Password', { exact: true }).fill(creds[STUDENT]);
  await page.getByRole('button', { name: /sign in/i }).click();
  await expect(page.getByRole('alert')).toContainText('This is a student account');
  await expect(page).toHaveURL(/\/login/);
});

test('student journey: subject → chapter → practice → scored attempt → progress', async ({ page }) => {
  await login(page, 'student', STUDENT);
  await expect(page.getByRole('heading', { name: 'Dashboard' })).toBeVisible();
  await page.getByRole('link', { name: 'Mathematics: open chapters' }).click();
  await expect(page).toHaveURL(/\/student\/subjects\/mathematics/);
  await page.locator('a[href^="/student/chapters/"]').first().click();
  await expect(page.getByRole('heading', { level: 2, name: /topics? in this chapter/ })).toBeVisible();
  await page.getByRole('link', { name: /^Practise \d+ question/ }).first().click();
  await expect(page.getByText(/Question 1 of \d/)).toBeVisible();
  const before = await page.request.get('http://localhost:8020/health');
  expect(before.ok()).toBeTruthy();
  const choice = page.getByRole('radio').first();
  if (await choice.count()) await choice.click();
  else await page.getByLabel('Your answer').fill('1');
  await page.getByRole('button', { name: 'Submit answer' }).click();
  await expect(page.getByText(/Correct — well done!|Not quite this time\./)).toBeVisible();
  await expect(page.getByText(/Your estimate for this topic is now|Your answer was saved/)).toBeVisible();
  await page.getByRole('link', { name: 'Progress' }).first().click();
  await expect(page.getByRole('heading', { name: 'My progress' })).toBeVisible();
  // refresh keeps the session; back/forward keeps working
  await page.reload();
  await expect(page.getByRole('heading', { name: 'My progress' })).toBeVisible();
  await page.goBack();
  await expect(page).toHaveURL(/practice/);
  await page.goForward();
  await expect(page).toHaveURL(/\/student\/progress/);
  // a student cannot open teacher pages
  await page.goto('/teacher/classes');
  await expect(page).toHaveURL(/\/student\/home/);
});

test('teacher journey: dashboard, Bell Ringer cycle, heatmap, roster', async ({ page }) => {
  await login(page, 'teacher', TEACHER_A);
  await expect(page.getByRole('heading', { name: 'Classes overview' })).toBeVisible();
  await page.getByLabel('Choose class').selectOption({ label: 'Class 8 DEMO-A' });
  await page.getByRole('link', { name: 'Bell Ringer' }).first().click();
  await expect(page.getByRole('heading', { name: /Flagged topics \(\d+\)/ })).toBeVisible();
  const cards = page.locator('article').filter({ hasText: 'Learners struggling' });
  expect(await cards.count()).toBeGreaterThan(1); // separate topic-level cycles, not one plan
  await expect(cards.first()).toContainText(/with estimate/);
  await cards.first().getByRole('button', { name: 'Plan this Bell Ringer' }).click();
  await expect(page).toHaveURL(/\/teacher\/bell-ringer\/[0-9a-f-]{36}/);
  await expect(page.getByRole('heading', { name: 'Follow-up' })).toBeVisible();
  const run = page.getByRole('button', { name: 'Mark as run in class' });
  if (await run.count()) {
    await run.click();
    await expect(page.getByText('In class').first()).toBeVisible();
  }
  await page.getByRole('link', { name: 'Heatmap' }).first().click();
  await expect(page.getByRole('grid', { name: /Class mastery heatmap/ })).toBeVisible();
  const cell = page.locator('[data-cell="0-0"]');
  await cell.focus();
  await page.keyboard.press('ArrowRight');
  await expect(page.locator('[data-cell="0-1"]')).toBeFocused();
  await page.keyboard.press('Enter');
  await expect(page.getByRole('link', { name: /Learner details/ })).toBeVisible();
  await page.getByLabel('Subject').selectOption('science');
  await expect(page.getByRole('grid')).toBeVisible();
  await page.getByRole('link', { name: 'Learners' }).first().click();
  await expect(page.getByRole('table')).toContainText('DEMO Learner 8-');
});

test('a teacher only sees assigned classes', async ({ page }) => {
  await login(page, 'teacher', TEACHER_B);
  const options = page.getByLabel('Choose class').locator('option');
  await expect(options).toHaveText(['Class 7 DEMO-A']);
  // a direct API call for another class is refused by the server, not just hidden in the UI
  const token = await page.evaluate(() => JSON.parse(sessionStorage.getItem('concepttrail.session') ?? '{}').token);
  const res = await page.request.get('http://localhost:8020/api/v1/teacher/classes/7c0767ea-8df2-59fd-8eab-a3735c39b147/heatmap', {
    headers: { Authorization: `Bearer ${token}` },
  });
  expect(res.status()).toBe(403);
});

test('sign out clears the session', async ({ page }) => {
  await login(page, 'student', STUDENT);
  await page.getByRole('button', { name: 'Account menu' }).click();
  await page.getByRole('menuitem', { name: 'Sign out' }).click();
  await expect(page).toHaveURL(/\/login/);
  await page.goto('/student/home');
  await expect(page).toHaveURL(/\/login/);
});

test('@llm Buddy answers with sources or abstains', async ({ page }) => {
  test.skip(!process.env.E2E_LLM, 'set E2E_LLM=1 to include the local model');
  test.setTimeout(240_000);
  await login(page, 'student', STUDENT);
  await page.goto('/student/buddy');
  await page.getByLabel('Your question').fill('How do I find the cube root of a number using prime factorisation?');
  await page.getByRole('button', { name: 'Send question' }).click();
  await expect(page.getByText(/Answer built from your course material|couldn't find this|not available right now|took too long|did not pass/)).toBeVisible({
    timeout: 200_000,
  });
});
