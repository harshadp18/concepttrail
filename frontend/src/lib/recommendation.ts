import type { Recommendation } from '@/api/types';

export const CATEGORY_LABEL: Record<string, string> = {
  remediate_prerequisite: 'Strengthen a building block',
  continue: 'Keep going',
  new: 'Start something new',
};

const REASONS: Record<string, string> = {
  no_active_enrollment: 'You are not enrolled in a class yet. Ask your teacher to add you.',
  graph_not_released: 'Personalised next steps are not switched on for your class yet. Pick any subject to practise.',
  all_scoped_kcs_mastered: 'You have mastered every topic available for your class. Brilliant work!',
  no_kcs_released: 'Personalised next steps are not switched on for your class yet. Pick any subject to practise.',
  demo_graph_empty: 'Personalised next steps are not switched on for your class yet. Pick any subject to practise.',
  no_servable_content: 'There are no practice questions for your class yet.',
  no_questions_available: 'There are no practice questions for your next topic yet.',
};

export function recommendationMessage(r: Recommendation): string {
  if (r.status === 'ok') return '';
  return (r.reason && REASONS[r.reason]) || 'There is no suggested next step right now. Choose a subject to keep practising.';
}

/** The backend rationale is short machine text; make it readable without changing its meaning. */
export function readableRationale(lines: string[]): string[] {
  return lines.map((line) =>
    line
      .replace(/^prerequisite gap \(no evidence, below readiness ([\d.]+)\)$/, 'You have not practised this building block yet.')
      .replace(/^prerequisite gap \(([\d.]+) below readiness ([\d.]+)\)$/, 'Your estimate here is below the readiness level, so it is worth strengthening first.')
      .replace(/^blocks: (.+)$/, (_m, list: string) => {
        const n = list.split(',').length;
        return `It unlocks ${n} later topic${n === 1 ? '' : 's'}.`;
      })
  );
}
