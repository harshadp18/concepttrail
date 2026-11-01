import React from 'react';
import { Link, useParams } from 'react-router-dom';
import { motion } from 'framer-motion';
import { CheckCircle2, CircleDashed, Play, XCircle } from 'lucide-react';
import { useCatalog, useCycle, useCycleActions } from '@/api/hooks';
import { useTeacherClass } from '@/context/TeacherClassContext';
import { dateTime, pct, plural } from '@/lib/format';
import { subjectMeta } from '@/lib/subjects';
import { Card, cx, Notice, PageHeader, Pill } from '@/components/ui/primitives';
import { ErrorState, QueryView } from '@/components/ui/states';
import { fadeUp, stagger } from '@/components/ui/motion';
import { WarmUp } from '@/components/teacher/BellRinger';
import { STATUS } from './TeacherBellRinger';

const STEPS = [
  { key: 'planned', label: 'Planned' },
  { key: 'in_progress', label: 'Run in class' },
  { key: 'completed', label: 'Completed' },
] as const;

export const TeacherCycleDetail: React.FC = () => {
  const { cycleId = '' } = useParams();
  const { classId } = useTeacherClass();
  const cycle = useCycle(classId, cycleId);
  const { setStatus } = useCycleActions(classId);
  const catalog = useCatalog();

  return (
    <QueryView query={cycle} feature="Saving Bell Ringer cycles">
      {(c) => {
        const s = subjectMeta(c.subject_id);
        const reached = STEPS.findIndex((st) => st.key === c.status);
        const f = c.follow_up;
        const closed = c.status === 'completed' || c.status === 'cancelled';
        return (
          <motion.div initial="hidden" animate="show" variants={stagger(0.06)}>
            <PageHeader
              eyebrow={`${s.name} · Bell Ringer cycle`}
              title={c.topic_name}
              subtitle={c.item_title}
              crumbs={[{ label: 'Bell Ringer', to: '/teacher/bell-ringer' }, { label: 'Cycle' }]}
              actions={<Pill tone={STATUS[c.status].tone}>{STATUS[c.status].label}</Pill>}
            />

            <motion.div variants={fadeUp} className="card mb-6 p-5">
              <ol className="flex flex-wrap items-center gap-3" aria-label="Cycle progress">
                {STEPS.map((st, i) => {
                  const done = c.status !== 'cancelled' && i <= reached;
                  return (
                    <li key={st.key} className="flex items-center gap-2 text-sm">
                      {done ? <CheckCircle2 size={18} className="text-band-mastered" aria-hidden /> : <CircleDashed size={18} className="text-ctText-subtle" aria-hidden />}
                      <span className={cx('font-semibold', done ? 'text-ctText-primary' : 'text-ctText-muted')}>{st.label}</span>
                      {i < STEPS.length - 1 && <span className="mx-1 h-px w-8 bg-surface-border" aria-hidden />}
                    </li>
                  );
                })}
              </ol>
              <div className="mt-4 flex flex-wrap gap-2">
                {c.status === 'planned' && (
                  <button type="button" className="btn btn-primary" disabled={setStatus.isPending} onClick={() => setStatus.mutate({ id: c.cycle_id, status: 'in_progress' })}>
                    <Play size={15} aria-hidden /> Mark as run in class
                  </button>
                )}
                {!closed && (
                  <button type="button" className="btn btn-secondary" disabled={setStatus.isPending} onClick={() => setStatus.mutate({ id: c.cycle_id, status: 'completed' })}>
                    <CheckCircle2 size={15} aria-hidden /> Mark completed
                  </button>
                )}
                {!closed && (
                  <button type="button" className="btn btn-danger" disabled={setStatus.isPending} onClick={() => setStatus.mutate({ id: c.cycle_id, status: 'cancelled' })}>
                    <XCircle size={15} aria-hidden /> Cancel cycle
                  </button>
                )}
              </div>
              {setStatus.error ? <ErrorState error={setStatus.error} compact className="mt-3" /> : null}
              <p className="mt-3 text-2xs text-ctText-muted">
                Opened {dateTime(c.created_at)}
                {c.started_at && ` · run ${dateTime(c.started_at)}`}
                {c.completed_at && ` · completed ${dateTime(c.completed_at)}`}
              </p>
            </motion.div>

            <div className="grid grid-cols-1 gap-6 lg:grid-cols-5">
              <motion.section variants={fadeUp} className="lg:col-span-3" aria-labelledby="warm-title">
                <Card>
                  <h2 id="warm-title" className="t-section mb-1">
                    The warm-up
                  </h2>
                  <p className="mb-4 text-sm text-ctText-muted">
                    Targets <strong>{c.root_name ?? c.topic_name}</strong>
                    {c.root_name ? ', the earlier topic the gap seems to start from.' : '.'}
                  </p>
                  <WarmUp card={c.activity} demo={catalog.data?.content_release === 'demo'} />
                </Card>
              </motion.section>

              <motion.section variants={fadeUp} className="space-y-5 lg:col-span-2" aria-labelledby="why-title">
                <Card>
                  <h2 id="why-title" className="t-card">
                    Why it was flagged
                  </h2>
                  <dl className="mt-3 grid grid-cols-2 gap-3 text-xs">
                    <div>
                      <dt className="text-ctText-muted">Struggling at the start</dt>
                      <dd className="text-lg font-extrabold text-ctText-primary">
                        {c.baseline.learners_below_threshold ?? '—'}
                        <span className="text-xs font-semibold text-ctText-muted"> / {c.baseline.learners_with_evidence ?? '—'} with estimate</span>
                      </dd>
                    </div>
                    <div>
                      <dt className="text-ctText-muted">Enrolled</dt>
                      <dd className="text-lg font-extrabold text-ctText-primary">{c.baseline.enrolled_learners ?? '—'}</dd>
                    </div>
                    <div>
                      <dt className="text-ctText-muted">Class average then</dt>
                      <dd className="text-lg font-extrabold text-ctText-primary">{pct(c.baseline.average_mastery_probability)}</dd>
                    </div>
                    <div>
                      <dt className="text-ctText-muted">Period</dt>
                      <dd className="text-sm font-bold text-ctText-primary">{c.baseline.window ? `${c.baseline.window.days} days` : '—'}</dd>
                    </div>
                  </dl>
                  {c.baseline.root_gap_explanation && <p className="mt-3 text-xs text-ctText-body">{c.baseline.root_gap_explanation}</p>}
                  {c.baseline.flagged_at_creation === false && <Notice className="mt-3">This topic was not flagged when the cycle was opened.</Notice>}
                </Card>

                <Card>
                  <h2 className="t-card">Follow-up</h2>
                  <p className="mt-1 text-xs text-ctText-muted">
                    The learners who were struggling at the start, re-checked now with the same cut-off ({pct(f.weak_below)}).
                  </p>
                  <div className="mt-3 flex items-baseline gap-2">
                    <span className="text-3xl font-extrabold text-band-mastered">{f.now_at_or_above_cut_off}</span>
                    <span className="text-sm text-ctText-body">
                      of {f.affected_at_start} now at or above the cut-off · {plural(f.practised_since_start, 'learner')} practised since
                    </span>
                  </div>
                  {f.learners.length > 0 && (
                    <ul className="mt-4 divide-y divide-surface-border-subtle text-sm">
                      {f.learners.map((l) => (
                        <li key={l.learner_id} className="flex items-center gap-3 py-2.5">
                          {l.now_at_or_above_cut_off ? (
                            <CheckCircle2 size={16} className="shrink-0 text-band-mastered" aria-label="At or above cut-off" />
                          ) : (
                            <CircleDashed size={16} className="shrink-0 text-band-practice" aria-label="Still below cut-off" />
                          )}
                          <Link to={`/teacher/learners/${l.learner_id}`} className="min-w-0 flex-1 truncate font-semibold text-ctText-primary hover:text-brand-700">
                            {l.display_name}
                          </Link>
                          <span className="text-xs tabular-nums text-ctText-muted">
                            {pct(l.mastery_at_start)} → <strong className="text-ctText-primary">{pct(l.mastery_now)}</strong>
                          </span>
                        </li>
                      ))}
                    </ul>
                  )}
                  <p className="mt-3 text-2xs text-ctText-subtle">{f.note}</p>
                </Card>
                {c.teacher_note && (
                  <Card>
                    <h2 className="t-card">Your note</h2>
                    <p className="mt-1 whitespace-pre-line text-sm text-ctText-body">{c.teacher_note}</p>
                  </Card>
                )}
              </motion.section>
            </div>
          </motion.div>
        );
      }}
    </QueryView>
  );
};

export default TeacherCycleDetail;
