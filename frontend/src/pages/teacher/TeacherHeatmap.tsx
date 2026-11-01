import React, { useMemo, useState } from 'react';
import { useHeatmap } from '@/api/hooks';
import type { HeatBand } from '@/api/types';
import { teacherClassName, useTeacherClass } from '@/context/TeacherClassContext';
import { plural } from '@/lib/format';
import { subjectMeta, SUBJECT_ORDER } from '@/lib/subjects';
import { cx, EstimateNote, PageHeader } from '@/components/ui/primitives';
import { EmptyState, QueryView, Skeleton } from '@/components/ui/states';
import { BAND_STYLE, HeatmapGrid, HeatmapLegend } from '@/components/teacher/Heatmap';

export const TeacherHeatmap: React.FC = () => {
  const { classId, selected } = useTeacherClass();
  const [subject, setSubject] = useState('mathematics');
  const [item, setItem] = useState('');
  const [windowDays, setWindowDays] = useState<number | ''>('');
  const filters = { subject_id: subject || undefined, item_id: item || undefined, window_days: windowDays || undefined };
  const heat = useHeatmap(classId, filters);
  // chapter options come from the unfiltered subject view so the list does not shrink to one
  const subjectView = useHeatmap(classId, { subject_id: subject || undefined });
  const chapters = useMemo(() => {
    const seen = new Map<string, string>();
    for (const t of subjectView.data?.topics ?? []) if (!seen.has(t.item_id)) seen.set(t.item_id, t.item_title ?? t.item_id);
    return [...seen.entries()];
  }, [subjectView.data]);

  const counts = useMemo(() => {
    const out: Record<HeatBand, number> = { mastered: 0, developing: 0, needs_practice: 0, insufficient_evidence: 0, no_data: 0 };
    for (const r of heat.data?.learners ?? []) for (const c of r.cells) out[c.band] += 1;
    return out;
  }, [heat.data]);

  return (
    <div>
      <PageHeader
        title="Learning heatmap"
        eyebrow={teacherClassName(selected)}
        subtitle="Every learner in this class against every topic: the current mastery estimate, with attempts on hover or focus."
        crumbs={[{ label: 'Classes', to: '/teacher/classes' }, { label: 'Heatmap' }]}
      />
      <div className="mb-4 flex flex-wrap items-end gap-3">
        <label className="text-xs font-semibold text-ctText-muted">
          Subject
          <select
            className="field-select mt-1 block"
            value={subject}
            onChange={(e) => {
              setSubject(e.target.value);
              setItem('');
            }}
          >
            <option value="">All subjects</option>
            {SUBJECT_ORDER.map((id) => (
              <option key={id} value={id}>
                {subjectMeta(id).name}
              </option>
            ))}
          </select>
        </label>
        <label className="text-xs font-semibold text-ctText-muted">
          Chapter
          <select className="field-select mt-1 block max-w-[260px]" value={item} onChange={(e) => setItem(e.target.value)}>
            <option value="">All chapters</option>
            {chapters.map(([id, title]) => (
              <option key={id} value={id}>
                {title}
              </option>
            ))}
          </select>
        </label>
        <label className="text-xs font-semibold text-ctText-muted">
          Attempts counted
          <select className="field-select mt-1 block" value={windowDays} onChange={(e) => setWindowDays(e.target.value ? Number(e.target.value) : '')}>
            <option value="">All time</option>
            {[7, 14, 30].map((d) => (
              <option key={d} value={d}>
                Last {d} days
              </option>
            ))}
          </select>
        </label>
      </div>
      <HeatmapLegend className="mb-4" />
      <QueryView query={heat} loading={<Skeleton className="h-96" />}>
        {(h) =>
          h.learner_count === 0 ? (
            <EmptyState title="No learners enrolled" body="Learners appear here once the school enrols them in this class." />
          ) : h.topics.length === 0 ? (
            <EmptyState title="No topics for this selection" body="Try another subject or chapter." />
          ) : (
            <div className={cx('transition-opacity', heat.isFetching && 'opacity-60')}>
              <p className="mb-3 text-sm text-ctText-body" aria-live="polite">
                {plural(h.learner_count, 'learner')} × {plural(h.topics.length, 'topic')}:{' '}
                {(['needs_practice', 'developing', 'mastered', 'insufficient_evidence', 'no_data'] as HeatBand[])
                  .map((b) => `${counts[b]} ${BAND_STYLE[b].label.split(' (')[0].toLowerCase()}`)
                  .join(' · ')}
                .
              </p>
              <HeatmapGrid key={JSON.stringify(filters)} data={h} />
              {h.truncated && <p className="mt-2 text-xs text-ctText-muted">Showing the first {h.topics.length} topics. Pick a subject or chapter to narrow it.</p>}
              <p className="mt-3 text-xs text-ctText-muted">
                Use the arrow keys to move between cells and Enter to open a cell. The window only changes the attempt counts; estimates are always current.
              </p>
              <EstimateNote className="mt-1" />
            </div>
          )
        }
      </QueryView>
    </div>
  );
};

export default TeacherHeatmap;
