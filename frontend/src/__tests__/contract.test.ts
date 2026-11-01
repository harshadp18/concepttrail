import { describe, expect, it } from 'vitest';
import fs from 'node:fs';
import path from 'node:path';

// Every path the frontend calls must exist in the backend's generated OpenAPI contract.
const root = path.resolve(__dirname, '../../..');
const spec = JSON.parse(fs.readFileSync(path.join(root, 'docs/openapi/openapi-v1.json'), 'utf8'));
const source = fs.readFileSync(path.resolve(__dirname, '../api/endpoints.ts'), 'utf8');

function frontendPaths(): string[] {
  const found = new Set<string>();
  const re = /api<[^>]*>\(\s*[`']([^`']+)[`']/g;
  let m: RegExpExecArray | null;
  while ((m = re.exec(source))) {
    const p = m[1]
      .replace(/\$\{cls\([^)]*\)\}/g, '/teacher/classes/{x}')
      .replace(/\$\{enc\([^)]*\)\}/g, '{x}');
    found.add(`/api/v1${p}`);
  }
  return [...found];
}

describe('API contract', () => {
  const backend = Object.keys(spec.paths).map((p) => new RegExp(`^${p.replace(/\{[^}]+\}/g, '[^/]+')}$`));
  const used = frontendPaths();

  it('finds the endpoint definitions', () => {
    expect(used.length).toBeGreaterThan(30);
  });

  it.each(used)('%s exists in docs/openapi/openapi-v1.json', (p) => {
    expect(backend.some((re) => re.test(p.replace(/\{x\}/g, 'id')))).toBe(true);
  });
});
