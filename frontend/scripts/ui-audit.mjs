// Visual audit: screenshots of every page at four viewports, written to ../.local/ui-audit/<label>/.
// Usage: node scripts/ui-audit.mjs <baseUrl> <label> [--login]
// With --login it signs in through the real login form using the Git-ignored demo credentials
// (.local/demo_credentials.json); passwords are never printed.
import { chromium } from '@playwright/test';
import fs from 'node:fs';
import path from 'node:path';

const [base = 'http://localhost:5173', label = 'run', flag] = process.argv.slice(2);
const root = path.resolve(import.meta.dirname, '..', '..');
const out = path.join(root, '.local', 'ui-audit', label);
fs.mkdirSync(out, { recursive: true });
const VIEWPORTS = { desktop: [1440, 900], laptop: [1280, 800], tablet: [1024, 768], mobile: [390, 844] };
const only = (process.env.VIEWPORTS || Object.keys(VIEWPORTS).join(',')).split(',');
const PUBLIC = ['/', '/login'];
const STUDENT = (process.env.STUDENT_PATHS || '/student/home,/student/subjects,/student/subjects/mathematics,/student/chapters/CT-C08-MAT-002,/student/topics/KC-MAT-50017,/student/topics/KC-MAT-50017/practice,/student/progress,/student/buddy,/student/alerts,/student/recommendations,/student/history,/student/review,/student/profile').split(',');
const TEACHER = (process.env.TEACHER_PATHS || '/teacher/classes,/teacher/learners,/teacher/heatmap,/teacher/bell-ringer,/teacher/reviews,/teacher/interventions,/teacher/alerts,/teacher/profile').split(',');
const creds = flag === '--login'
  ? JSON.parse(fs.readFileSync(path.join(root, '.local', process.env.CREDS_FILE || 'demo_credentials.json'), 'utf8'))
  : null;
const problems = [];

async function login(page, role) {
  const user = role === 'student' ? (process.env.DEMO_STUDENT || 'demo-l8-02') : (process.env.DEMO_TEACHER || 'demo.teacher.a@example.invalid');
  await page.goto(`${base}/login?role=${role}`);
  await page.getByLabel(role === 'student' ? 'Username' : 'School email').fill(user);
  await page.getByLabel(role === 'student' ? '8-digit PIN' : 'Password', { exact: true }).fill(creds[user]);
  await page.getByRole('button', { name: /sign in/i }).click();
  await page.waitForURL(new RegExp(role === 'student' ? '/student/' : '/teacher/'), { timeout: 15000 });
}

async function shoot(page, vp, route, tag) {
  await page.goto(`${base}${route}`, { waitUntil: 'networkidle' }).catch(() => {});
  await page.waitForTimeout(500);
  // scroll like a visitor so scroll-triggered entrances run before the full-page capture
  await page.evaluate(async () => {
    for (let y = 0; y < document.body.scrollHeight; y += 400) {
      window.scrollTo(0, y);
      await new Promise((r) => setTimeout(r, 60));
    }
    window.scrollTo(0, 0);
  });
  await page.waitForTimeout(500);
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
  if (overflow > 1) problems.push(`${vp} ${route}: horizontal overflow ${overflow}px`);
  const name = `${vp}-${tag}${route.replace(/[/?=&]+/g, '_') || '_root'}.png`;
  await page.screenshot({ path: path.join(out, name), fullPage: process.env.FULLPAGE !== '0' });
}

const browser = await chromium.launch();
for (const vp of only) {
  const [width, height] = VIEWPORTS[vp];
  const ctx = await browser.newContext({ viewport: { width, height }, reducedMotion: 'reduce' });
  const page = await ctx.newPage();
  page.on('pageerror', (e) => problems.push(`${vp} pageerror: ${e.message}`));
  page.on('console', (m) => { if (m.type() === 'error') problems.push(`${vp} console: ${m.text().slice(0, 200)}`); });
  for (const r of PUBLIC) await shoot(page, vp, r, 'public');
  if (creds) {
    await login(page, 'student');
    for (const r of STUDENT) await shoot(page, vp, r, 'student');
    await ctx.clearCookies();
    await page.evaluate(() => sessionStorage.clear());
    await login(page, 'teacher');
    for (const r of TEACHER) await shoot(page, vp, r, 'teacher');
  } else {
    for (const r of [...STUDENT, ...TEACHER]) await shoot(page, vp, r, 'app');
  }
  await ctx.close();
}
await browser.close();
fs.writeFileSync(path.join(out, 'problems.txt'), problems.join('\n') + '\n');
console.log(`screenshots in ${out}; ${problems.length} problem(s)`);
for (const p of problems.slice(0, 40)) console.log(' -', p);
