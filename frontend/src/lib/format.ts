/** Display helpers. `null` stays visible as "no evidence", never as 0. */

export const NO_DATA = '—';

export function pct(value: number | null | undefined, digits = 0): string {
  if (value === null || value === undefined || Number.isNaN(value)) return NO_DATA;
  return `${(value * 100).toFixed(digits)}%`;
}

export function shortDate(iso: string | null | undefined): string {
  if (!iso) return NO_DATA;
  const d = new Date(iso);
  return d.toLocaleDateString(undefined, { day: 'numeric', month: 'short' });
}

export function dateTime(iso: string | null | undefined): string {
  if (!iso) return NO_DATA;
  const d = new Date(iso);
  return d.toLocaleString(undefined, {
    day: 'numeric',
    month: 'short',
    hour: '2-digit',
    minute: '2-digit',
  });
}

export function relative(iso: string | null | undefined): string {
  if (!iso) return 'No activity yet';
  const diff = Date.now() - new Date(iso).getTime();
  const min = Math.round(diff / 60000);
  if (min < 1) return 'Just now';
  if (min < 60) return `${min} min ago`;
  const h = Math.round(min / 60);
  if (h < 24) return `${h} h ago`;
  const d = Math.round(h / 24);
  return d === 1 ? 'Yesterday' : `${d} days ago`;
}

export function plural(n: number, one: string, many = `${one}s`): string {
  return `${n} ${n === 1 ? one : many}`;
}

export type MasteryBand = 'mastered' | 'developing' | 'needs_practice' | 'none';

/** Same cut-offs as the backend (provisional): 0.95 mastered, below 0.5 needs practice. */
export function masteryBand(p: number | null | undefined, mastered = 0.95, weak = 0.5): MasteryBand {
  if (p === null || p === undefined) return 'none';
  if (p >= mastered) return 'mastered';
  if (p >= weak) return 'developing';
  return 'needs_practice';
}

export const BAND_LABEL: Record<MasteryBand, string> = {
  mastered: 'Mastered',
  developing: 'Developing',
  needs_practice: 'Needs practice',
  none: 'Not started',
};

export function newIdempotencyKey(prefix: string): string {
  const random =
    typeof crypto !== 'undefined' && 'randomUUID' in crypto
      ? crypto.randomUUID()
      : `${Date.now()}-${Math.random().toString(36).slice(2)}`;
  return `${prefix}-${random}`.slice(0, 120);
}
