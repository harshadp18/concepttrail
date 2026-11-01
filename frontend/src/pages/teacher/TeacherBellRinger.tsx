import React, { useState } from 'react';
import { Link } from 'react-router-dom';
import { AnimatePresence, motion } from 'framer-motion';
import { ArrowRight, ChevronDown, ListChecks } from 'lucide-react';
import { useBellRingerTopics, useCatalog, useCycles } from '@/api/hooks';
import { ApiError } from '@/api/http';
import type { CycleStatus, UnmetCriterion } from '@/api/types';
import { teacherClassName, useTeacherClass } from '@/context/TeacherClassContext';
import { pct, plural, shortDate } from '@/lib/format';
import { subjectMeta, SUBJECT_ORDER } from '@/lib/subjects';
import { Card, cx, PageHeader, Pill, SectionHeader } from '@/components/ui/primitives';
import { EmptyState, ErrorState, QueryView, Skeleton } from '@/components/ui/states';
import { stagger } from '@/components/ui/motion';
import { BellRingerTopicCard, CriteriaNote } from '@/components/teacher/BellRinger';

const UNMET: Record<UnmetCriterion, string> = {
  coverage_below_minimum: 'too few learners with an estimate',
  too_few_affected_learners: 'too few learners struggling',
  affected_share_below_minimum: 'share struggling below threshold',
};

export const STATUS: Record<CycleStatus, { label: string; tone: 'brand' | 'teal' | 'success' | 'neutral' }> = {
  planned: { label: 'Planned', tone: 'brand' },
  in_progress: { label: 'In class', tone: 'teal' },
  completed: { label: 'Completed', tone: 'success' },
  cancelled: { label: 'Cancelled', tone: 'neutral' },
};

export const TeacherBellRinger: React.FC = () => {
  const { classId, selected } = useTeacherClass();
  const [subject, setSubject] = useState('');
  const [windowDays, setWindowDays] = useState(14);
  const [showAll, setShowAll] = useState(false);
  const filters = { subject_id: subject || undefined, window_days: windowDays };
  const topics = useBellRingerTopics(classId, filters);
  const cyclesOn = topics.data?.cycles_enabled ?? false;
  const cycles = useCycles(classId, cyclesOn);
  const catalog = useCatalog();
  const demo = catalog.data?.content_release === 'demo';

  return (
    <div>
      <PageHeader
        title="Bell Ringer"
        eyebrow={teacherClassName(selected)}
        subtitle="Topic-specific five-minute warm-ups for the gaps your class shares. Each topic gets its own cycle: plan it, run it, then check who has moved."
        crumbs={[{ label: 'Classes', to: '/teacher/classes' }, { label: 'Bell Ringer' }]}
      />

      <div className="mb-5 flex flex-wrap items-end gap-3">
        <label className="text-xs font-semibold text-ctText-muted">
          Subject
          <select className="field-select mt-1 block" value={subject} onChange={(e) => setSubject(e.target.value)}>
            <option value="">All subjects</option>
            {SUBJECT_ORDER.map((id) => (
              <option key={id} value={id}>
                {subjectMeta(id).name}
              </option>
            ))}
          </select>
        </label>
        <label className="text-xs font-semibold text-ctText-muted">
          Recent activity
          <select className="field-select mt-1 block" value={windowDays} onChange={(e) => setWindowDays(Number(e.target.value))}>
            {[7, 14, 30, 60].map((d) => (
              <option key={d} value={d}>
                Last {d} days
              </option>
            ))}
          </select>
        </label>
      </div>

      <QueryView query={topics} loading={<div className="space-y-4"><Skeleton className="h-40" /><Skeleton className="h-40" /></div>}>
        {(b) => {
          const flagged = b.topics.filter((t) => t.flagged);
          const others = b.topics.filter((t) => !t.flagged);
          return (
            <div className={cx('space-y-8 transition-opacity', topics.isFetching && 'opacity-60')}>
              <CriteriaNote criteria={b.criteria} enrolled={b.enrolled_learners} windowDays={b.window.days} />

              <section aria-labelledby="flagged-title">
                <SectionHeader id="flagged-title" title={`Flagged topics (${flagged.length})`} subtitle="Ranked by the share of learners struggling, then by how many." />
                {flagged.length ? (
                  <motion.div initial="hidden" animate="show" variants={stagger(0.06)} className="space-y-4" key={`${subject}-${windowDays}`}>
                    {flagged.map((t, i) => (
                      <BellRingerTopicCard key={t.kc_id} classId={classId} topic={t} cyclesEnabled={b.cycles_enabled} demo={demo} defaultOpen={i === 0} />
                    ))}
                  </motion.div>
                ) : (
                  <EmptyState title="No topic needs a Bell Ringer right now" body="None of this class's topics meets all three criteria. The full list below shows why each was not flagged." />
                )}
              </section>

              <section aria-labelledby="cycles-title">
                <SectionHeader id="cycles-title" title="Cycles for this class" subtitle="Each cycle is one topic. Several topics can be active at the same time." />
                {!b.cycles_enabled ? (
                  <ErrorState
                    compact
                    feature="Saving Bell Ringer cycles"
                    error={new ApiError(503, 'feature_not_enabled', 'Cycles are switched off.')}
                  />
                ) : (
                  <QueryView query={cycles} compact>
                    {(c) =>
                      c.cycles.length ? (
                        <Card pad={false}>
                          <ul className="divide-y divide-surface-border-subtle">
                            {c.cycles.map((cy) => (
                              <li key={cy.cycle_id}>
                                <Link to={`/teacher/bell-ringer/${cy.cycle_id}`} className="flex flex-wrap items-center gap-3 px-5 py-4 hover:bg-surface-subtle focus-ring">
                                  <ListChecks size={18} className="text-brand-500" aria-hidden />
                                  <span className="min-w-0 flex-1">
                                    <span className="block font-semibold text-ctText-primary">{cy.topic_name}</span>
                                    <span className="text-xs text-ctText-muted">
                                      {subjectMeta(cy.subject_id).name} · {plural(cy.affected_count, 'learner')} at the start · opened {shortDate(cy.created_at)}
                                    </span>
                                  </span>
                                  <Pill tone={STATUS[cy.status].tone}>{STATUS[cy.status].label}</Pill>
                                  <ArrowRight size={16} className="text-ctText-subtle" aria-hidden />
                                </Link>
                              </li>
                            ))}
                          </ul>
                        </Card>
                      ) : (
                        <EmptyState compact title="No cycles yet" body="Choose “Plan this Bell Ringer” on a flagged topic to start one." />
                      )
                    }
                  </QueryView>
                )}
              </section>

              <section aria-labelledby="all-title">
                <button type="button" onClick={() => setShowAll((v) => !v)} aria-expanded={showAll} className="btn btn-ghost -ml-3 h-auto whitespace-normal py-2 text-left">
                  <ChevronDown size={16} className={cx('transition-transform', showAll && 'rotate-180')} aria-hidden />
                  <span id="all-title">All other topics ({others.length}) and why they were not flagged</span>
                </button>
                <AnimatePresence initial={false}>
                  {showAll && (
                    <motion.div initial={{ opacity: 0, height: 0 }} animate={{ opacity: 1, height: 'auto' }} exit={{ opacity: 0, height: 0 }} className="overflow-hidden">
                      <Card pad={false} className="mt-3 overflow-x-auto">
                        <table className="w-full min-w-[640px] text-sm">
                          <thead>
                            <tr className="border-b border-surface-border text-left text-2xs font-bold uppercase tracking-wider text-ctText-muted">
                              <th scope="col" className="px-5 py-3">Topic</th>
                              <th scope="col" className="px-3 py-3">With estimate</th>
                              <th scope="col" className="px-3 py-3">Struggling</th>
                              <th scope="col" className="px-3 py-3">Average</th>
                              <th scope="col" className="px-3 py-3">Not flagged because</th>
                            </tr>
                          </thead>
                          <tbody>
                            {others.map((t) => (
                              <tr key={t.kc_id} className="border-b border-surface-border-subtle last:border-0">
                                <td className="px-5 py-3">
                                  <span className="font-semibold text-ctText-primary">{t.name}</span>
                                  <span className="block text-xs text-ctText-muted">{subjectMeta(t.subject_id).name}</span>
                                </td>
                                <td className="px-3 py-3 tabular-nums">
                                  {t.learners_with_evidence}/{t.enrolled_learners}
                                </td>
                                <td className="px-3 py-3 tabular-nums">{t.learners_below_threshold}</td>
                                <td className="px-3 py-3 tabular-nums">{pct(t.average_mastery_probability)}</td>
                                <td className="px-3 py-3 text-xs text-ctText-muted">{t.unmet_criteria.map((u) => UNMET[u]).join('; ')}</td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </Card>
                    </motion.div>
                  )}
                </AnimatePresence>
              </section>
            </div>
          );
        }}
      </QueryView>
    </div>
  );
};

export default TeacherBellRinger;
