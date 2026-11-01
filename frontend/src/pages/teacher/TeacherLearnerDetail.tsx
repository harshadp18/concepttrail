import React from 'react';
import { Link, useParams } from 'react-router-dom';
import { motion } from 'framer-motion';
import { CheckCircle2, Target, XCircle } from 'lucide-react';
import { useLearnerProgress } from '@/api/hooks';
import { teacherClassName, useTeacherClass } from '@/context/TeacherClassContext';
import { dateTime, pct } from '@/lib/format';
import { subjectMeta, SUBJECT_ORDER } from '@/lib/subjects';
import { BandPill, Card, cx, EstimateNote, MasteryBar, PageHeader, SectionHeader } from '@/components/ui/primitives';
import { EmptyState, QueryView } from '@/components/ui/states';
import { fadeUp, stagger } from '@/components/ui/motion';

export const TeacherLearnerDetail: React.FC = () => {
  const { learnerId = '' } = useParams();
  const { classId, selected } = useTeacherClass();
  const detail = useLearnerProgress(classId, learnerId);
  return (
    <QueryView query={detail}>
      {(d) => (
        <motion.div initial="hidden" animate="show" variants={stagger(0.06)}>
          <PageHeader
            eyebrow={teacherClassName(selected)}
            title={d.display_name ?? 'Learner'}
            crumbs={[{ label: 'Learners', to: '/teacher/learners' }, { label: d.display_name ?? 'Learner' }]}
            actions={
              <Link to="/teacher/interventions" className="btn btn-secondary">
                Plan support
              </Link>
            }
          />
          <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
            <motion.section variants={fadeUp} className="space-y-6 lg:col-span-2">
              <Card>
                <h2 className="t-section">By subject</h2>
                <ul className="mt-4 space-y-4">
                  {[...d.subjects]
                    .sort((a, b) => SUBJECT_ORDER.indexOf(a.subject_id) - SUBJECT_ORDER.indexOf(b.subject_id))
                    .map((s) => {
                      const m = subjectMeta(s.subject_id);
                      return (
                        <li key={s.subject_id}>
                          <MasteryBar p={s.average_mastery_probability} fill={m.bar} label={`${s.display_name} · ${s.topics_started}/${s.topics_total} topics started`} />
                        </li>
                      );
                    })}
                </ul>
              </Card>
              <section aria-labelledby="chapters-title">
                <SectionHeader id="chapters-title" title="Topics" />
                <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
                  {d.chapters.map((c) => {
                    const m = subjectMeta(c.subject_id);
                    return (
                      <Card key={c.item_id}>
                        <p className={cx('t-eyebrow', m.ink)}>{m.name}</p>
                        <p className="t-card mt-0.5">{c.title}</p>
                        <ul className="mt-3 space-y-1.5">
                          {c.topics.map((t) => (
                            <li key={t.kc_id} className="flex items-center justify-between gap-2 text-xs">
                              <span className="min-w-0 truncate text-ctText-body">{t.name}</span>
                              <span className={cx('shrink-0 tabular-nums', t.mastery_probability == null ? 'text-ctText-subtle' : 'font-semibold text-ctText-primary')}>
                                {t.mastery_probability == null ? 'Not started' : pct(t.mastery_probability)}
                              </span>
                            </li>
                          ))}
                        </ul>
                      </Card>
                    );
                  })}
                </div>
              </section>
            </motion.section>
            <motion.aside variants={fadeUp} className="space-y-6">
              <Card>
                <h2 className="t-card flex items-center gap-2">
                  <Target size={16} className="text-band-practice" aria-hidden /> Needs practice
                </h2>
                {d.weak_areas.length ? (
                  <ul className="mt-3 space-y-3">
                    {d.weak_areas.map((w) => (
                      <li key={w.kc_id} className="rounded-xl bg-band-practice-bg/60 p-3">
                        <div className="flex items-start justify-between gap-2">
                          <span className="text-sm font-semibold text-ctText-primary">{w.name}</span>
                          <BandPill p={w.mastery_probability} />
                        </div>
                        <p className="mt-1 text-xs text-ctText-muted">{w.reason}</p>
                      </li>
                    ))}
                  </ul>
                ) : (
                  <p className="mt-2 text-sm text-ctText-muted">No topic below 50% with enough evidence.</p>
                )}
              </Card>
              <Card>
                <h2 className="t-card">Recent activity</h2>
                {d.recent_activity.count === 0 ? (
                  <EmptyState compact art={null} title="No answers yet" className="mt-3" />
                ) : (
                  <ul className="mt-3 space-y-2.5">
                    {d.recent_activity.attempts.map((a) => (
                      <li key={a.attempt_id} className="flex gap-2.5 text-xs">
                        {a.scored_correct ? (
                          <CheckCircle2 size={15} className="mt-0.5 shrink-0 text-feedback-success" aria-label="Correct" />
                        ) : (
                          <XCircle size={15} className="mt-0.5 shrink-0 text-feedback-warning" aria-label="Not correct" />
                        )}
                        <span className="min-w-0 flex-1">
                          <span className="line-clamp-2 text-ctText-body">{a.question_stem}</span>
                          <span className="text-ctText-subtle">{dateTime(a.attempted_at)}</span>
                        </span>
                      </li>
                    ))}
                  </ul>
                )}
              </Card>
              <EstimateNote />
            </motion.aside>
          </div>
        </motion.div>
      )}
    </QueryView>
  );
};

export default TeacherLearnerDetail;
