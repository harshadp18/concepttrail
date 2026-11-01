import { describe, expect, it } from 'vitest';
import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { ApiError } from '@/api/http';
import { MasteryBar } from '@/components/ui/primitives';
import { ErrorState } from '@/components/ui/states';
import { HeatmapGrid } from '@/components/teacher/Heatmap';
import type { Heatmap } from '@/api/types';

describe('MasteryBar', () => {
  it('shows "not started" for null, never 0%', () => {
    render(<MasteryBar p={null} label="Maths" />);
    expect(screen.getByText('Not started')).toBeInTheDocument();
    expect(screen.queryByText('0%')).toBeNull();
    expect(screen.getByRole('meter')).toHaveAttribute('aria-valuetext', 'No evidence yet');
  });
  it('labels the band in text, not only colour', () => {
    render(<MasteryBar p={0.42} label="Squares" />);
    expect(screen.getByRole('meter')).toHaveAttribute('aria-valuetext', '42% estimated, Needs practice');
  });
});

describe('ErrorState', () => {
  it('presents a switched-off feature as "not available yet", not as an error', () => {
    render(<ErrorState error={new ApiError(503, 'feature_not_enabled', 'off')} feature="Alerts" />);
    expect(screen.getByText('Alerts is not available yet')).toBeInTheDocument();
    expect(screen.getByRole('status')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /try again/i })).toBeNull();
  });
  it('offers a retry for network failures', () => {
    render(<ErrorState error={new ApiError(0, 'network_error', 'Cannot reach')} onRetry={() => {}} />);
    expect(screen.getByRole('alert')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /try again/i })).toBeInTheDocument();
  });
});

const heat: Heatmap = {
  classroom_id: 'c',
  grade_level: 7,
  subject_id: null,
  item_id: null,
  window_days: null,
  learner_count: 2,
  topics: [
    { kc_id: 'A', name: 'Fractions', subject_id: 'mathematics', item_id: 'I', item_title: 'Ch', learners_with_estimate: 1, learners_needing_practice: 1, average_mastery_probability: 0.3 },
  ],
  learners: [
    { learner_id: 'l1', display_name: 'Asha', topics_with_estimate: 1, average_mastery_probability: 0.3, cells: [{ mastery_probability: 0.3, evidence_count: 3, attempts: 4, correct: 1, last_attempt_at: null, band: 'needs_practice' }] },
    { learner_id: 'l2', display_name: 'Ravi', topics_with_estimate: 0, average_mastery_probability: null, cells: [{ mastery_probability: null, evidence_count: 0, attempts: 0, correct: 0, last_attempt_at: null, band: 'no_data' }] },
  ],
  truncated: false,
  thresholds_provisional: true,
  note: '',
};

describe('HeatmapGrid', () => {
  it('renders values and missing data distinctly, with readable labels', () => {
    render(
      <MemoryRouter>
        <HeatmapGrid data={heat} />
      </MemoryRouter>
    );
    expect(screen.getByRole('button', { name: /Asha, Fractions: estimated mastery 30%/ })).toHaveTextContent('30');
    const empty = screen.getByRole('button', { name: /Ravi, Fractions: no attempts yet/ });
    expect(empty).toHaveTextContent('—');
    expect(empty).not.toHaveTextContent('0');
    // roving focus: exactly one cell is in the tab order
    expect(screen.getAllByRole('button').filter((b) => b.getAttribute('tabindex') === '0')).toHaveLength(1);
  });
});
