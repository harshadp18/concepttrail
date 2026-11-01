import { describe, expect, it } from 'vitest';
import { masteryBand, newIdempotencyKey, pct } from '@/lib/format';

describe('format helpers', () => {
  it('never turns missing data into zero', () => {
    expect(pct(null)).toBe('—');
    expect(pct(undefined)).toBe('—');
    expect(pct(0)).toBe('0%');
    expect(pct(0.6667)).toBe('67%');
  });
  it('uses the backend cut-offs for bands', () => {
    expect(masteryBand(null)).toBe('none');
    expect(masteryBand(0.95)).toBe('mastered');
    expect(masteryBand(0.5)).toBe('developing');
    expect(masteryBand(0.49)).toBe('needs_practice');
  });
  it('makes idempotency keys the backend accepts (16-128 chars, unique)', () => {
    const a = newIdempotencyKey('web');
    const b = newIdempotencyKey('web');
    expect(a).not.toBe(b);
    expect(a.length).toBeGreaterThanOrEqual(16);
    expect(a.length).toBeLessThanOrEqual(128);
  });
});
