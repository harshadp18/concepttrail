import React from 'react';
import { Link } from 'react-router-dom';
import { motion } from 'framer-motion';
import { ArrowRight, BookOpen, CheckCircle2, ClipboardCheck, Target, Trophy } from 'lucide-react';
import { useChapterProgress, useWeakAreas } from '@/api/hooks';
import { subjectMeta, SUBJECT_ORDER } from '@/lib/subjects';
import { pct, plural } from '@/lib/format';
import { BandPill, Card, cx, EstimateNote, MasteryBar, PageHeader, SectionHeader, StatTile } from '@/components/ui/primitives';
import { EmptyState, QueryView } from '@/components/ui/states';
import { fadeUp, stagger } from '@/components/ui/motion';

export const StudentProgress: React.FC = () => {
  const progress = useChapterProgress();
  const weak = useWeakAreas();
  return (
    <div>
      <PageHeader
        title="My progress"
        subtitle="Your estimated mastery for every subject, chapter and topic, updated after each answer."
        actions={
          <Link to="/student/history" className="btn btn-secondary">
            Learning history
          </Link>
        }
      />
      <QueryView query={progress}>
        {(data) => {
          const subjects = [...data.subjects].sort((a, b) => SUBJECT_ORDER.indexOf(a.subject_id) - SUBJECT_ORDER.indexOf(b.subject_id));
          const attempts = subjects.reduce((n, s) => n + s.attempts, 0);
          const correct = subjects.reduce((n, s) => n + s.correct_attempts, 0);
          const started = subjects.reduce((n, s) => n + s.topics_started, 0);
          const mastered = subjects.reduce((n, s) => n + s.topics_mastered, 0);
          return (
            <motion.div initial="hidden" animate="show" variants={stagger(0.06)} className="space-y-8">
              <motion.section variants={stagger(0.05)} className="card grid grid-cols-2 lg:grid-cols-4 lg:divide-x divide-surface-border-subtle" aria-label="Totals">
                <StatTile icon={<ClipboardCheck size={20} />} iconClass="bg-brand-50 text-brand-600" value={attempts} label="Questions answered" />
                <StatTile
                  icon={<CheckCircle2 size={20} />}
                  iconClass="bg-band-mastered-bg text-band-mastered"
                  value={attempts ? Math.round((correct / attempts) * 100) : null}
                  format={(n) => `${Math.round(n)}%`}
                  label="Answered correctly"
                />
                <StatTile icon={<BookOpen size={20} />} iconClass="bg-band-developing-bg text-band-developing" value={started} label="Topics started" />
                <StatTile icon={<Trophy size={20} />} iconClass="bg-amber-50 text-amber-700" value={mastered} label="Topics mastered" />
              </motion.section>

              <motion.section variants={fadeUp} aria-labelledby="by-subject">
                <SectionHeader id="by-subject" title="By subject" subtitle="Average estimate over the topics you have started." />
                <Card>
                  <ul className="space-y-5">
                    {subjects.map((s) => {
                      const meta = subjectMeta(s.subject_id);
                      return (
                        <li key={s.subject_id} className="grid grid-cols-1 items-center gap-2 sm:grid-cols-[180px_1fr_auto] sm:gap-5">
                          <Link to={`/student/subjects/${s.subject_id}`} className="flex items-center gap-2.5 font-semibold text-ctText-primary hover:text-brand-700">
                            <span className={cx('h-2.5 w-2.5 rounded-full', meta.dot)} aria-hidden />
                            {s.display_name}
                          </Link>
                          <MasteryBar p={s.average_mastery_probability} fill={meta.bar} showValue={false} label={undefined} height="h-3" />
                          <span className="text-sm tabular-nums text-ctText-body sm:w-48 sm:text-right">
                            <strong className="text-ctText-primary">{s.average_mastery_probability == null ? 'Not started' : pct(s.average_mastery_probability)}</strong>
                            <span className="text-ctText-muted"> · {s.topics_mastered}/{s.topics_total} mastered</span>
                          </span>
                        </li>
                      );
                    })}
                  </ul>
                  <EstimateNote className="mt-5" />
                </Card>
              </motion.section>

              <motion.section variants={fadeUp} aria-labelledby="needs-practice">
                <SectionHeader
                  id="needs-practice"
                  title="Needs practice"
                  subtitle="Topics where your estimate is below 50% after at least two answers."
                />
                <QueryView query={weak} compact>
                  {(w) =>
                    w.weak_areas.length === 0 ? (
                      <EmptyState compact icon={<Target size={22} />} title="Nothing flagged right now" body="Keep practising: topics appear here only when there is enough evidence." />
                    ) : (
                      <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
                        {w.weak_areas.map((a) => (
                          <Card key={a.kc_id} pad={false} className="flex items-center gap-4 p-4">
                            <div className="min-w-0 flex-1">
                              <p className="t-card truncate">{a.name}</p>
                              <p className="mt-0.5 text-xs text-ctText-muted">{a.reason}</p>
                            </div>
                            <Link to={`/student/topics/${encodeURIComponent(a.kc_id)}/practice`} className="btn btn-primary btn-sm shrink-0">
                              Practise
                            </Link>
                          </Card>
                        ))}
                      </div>
                    )
                  }
                </QueryView>
              </motion.section>

              <motion.section variants={fadeUp} aria-labelledby="by-chapter">
                <SectionHeader id="by-chapter" title="By chapter" />
                <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
                  {data.chapters.map((c) => {
                    const meta = subjectMeta(c.subject_id);
                    return (
                      <Card key={c.item_id}>
                        <div className="flex items-start justify-between gap-3">
                          <div className="min-w-0">
                            <p className={cx('t-eyebrow', meta.ink)}>{meta.name}</p>
                            <Link to={`/student/chapters/${encodeURIComponent(c.item_id)}`} className="t-card mt-0.5 block hover:text-brand-700">
                              {c.title}
                            </Link>
                          </div>
                          <BandPill p={c.average_mastery_probability} />
                        </div>
                        <MasteryBar className="mt-3" p={c.average_mastery_probability} fill={meta.bar} label={`${c.topics_started}/${plural(c.topics_total, 'topic')} started`} />
                        <p className="mt-2 text-xs text-ctText-muted">
                          {c.attempts ? `${plural(c.attempts, 'answer')} · ${pct(c.accuracy)} correct` : 'Not practised yet'}
                        </p>
                        <ul className="mt-3 space-y-1.5 border-t border-surface-border-subtle pt-3">
                          {c.topics.map((t) => (
                            <li key={t.kc_id} className="flex items-center justify-between gap-3 text-xs">
                              <Link to={`/student/topics/${encodeURIComponent(t.kc_id)}`} className="min-w-0 truncate text-ctText-body hover:text-brand-700">
                                {t.name}
                              </Link>
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
                <Link to="/student/recommendations" className="btn btn-ghost mt-4">
                  What should I do next? <ArrowRight size={15} aria-hidden />
                </Link>
              </motion.section>
            </motion.div>
          );
        }}
      </QueryView>
    </div>
  );
};

export default StudentProgress;
