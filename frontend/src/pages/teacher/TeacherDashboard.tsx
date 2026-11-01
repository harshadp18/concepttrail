import React, { useState } from 'react';
import { Link } from 'react-router-dom';
import { motion } from 'framer-motion';
import { ArrowRight, BellRing, CheckCircle2, ClipboardList, GraduationCap, Users } from 'lucide-react';
import { useBellRingerTopics, useCatalog, useClassDashboard, useHeatmap } from '@/api/hooks';
import { teacherClassName, useTeacherClass } from '@/context/TeacherClassContext';
import { personName, useAuth } from '@/context/AuthContext';
import { pct, plural } from '@/lib/format';
import { subjectMeta, SUBJECT_ORDER } from '@/lib/subjects';
import { Card, cx, DemoContentNotice, PageHeader, Pill, SectionHeader, StatTile } from '@/components/ui/primitives';
import { EmptyState, ErrorState, QueryView, Skeleton } from '@/components/ui/states';
import { fadeUp, stagger } from '@/components/ui/motion';
import { BellRingerTopicCard } from '@/components/teacher/BellRinger';
import { HeatmapGrid, HeatmapLegend } from '@/components/teacher/Heatmap';
import bellArt from '@/assets/illustrations/bell-ringer.svg';

export const TeacherDashboard: React.FC = () => {
  const { classes, selected, select, classId, isLoading, error, refetch } = useTeacherClass();
  const { user } = useAuth();
  const firstName = personName(user).split(' ')[0];
  const dashboard = useClassDashboard(classId);
  const bell = useBellRingerTopics(classId, {});
  const [subject, setSubject] = useState('mathematics');
  const heat = useHeatmap(classId, { subject_id: subject });
  const catalog = useCatalog();
  const learners = classes.reduce((n, c) => n + c.learner_count, 0);
  const d = dashboard.data;

  return (
    <motion.div initial="hidden" animate="show" variants={stagger(0.06)}>
      <PageHeader
        title="Classes overview"
        eyebrow={firstName ? `Welcome back, ${firstName}` : undefined}
        subtitle="Where your classes are, where they are struggling, and what to do in tomorrow's first five minutes."
        actions={
          <Link to="/teacher/bell-ringer" className="btn btn-primary">
            <BellRing size={16} aria-hidden /> Bell Ringer
          </Link>
        }
      />
      {isLoading && <Skeleton className="h-40" />}
      {error ? <ErrorState error={error} onRetry={() => refetch()} /> : null}
      {!isLoading && !error && classes.length === 0 && (
        <EmptyState title="No classes assigned yet" body="Your school administrator assigns classes. Once that is done they will appear here." />
      )}
      {classes.length > 0 && (
        <>
          {catalog.data?.content_release === 'demo' && <DemoContentNotice className="mb-5" />}
          <motion.section variants={stagger(0.05)} className="card mb-8 grid grid-cols-2 lg:grid-cols-4 lg:divide-x divide-surface-border-subtle" aria-label="Summary">
            <StatTile icon={<GraduationCap size={20} />} iconClass="bg-brand-50 text-brand-600" value={classes.length} label="Assigned classes" />
            <StatTile icon={<Users size={20} />} iconClass="bg-band-developing-bg text-band-developing" value={learners} label="Learners enrolled" />
            <StatTile
              icon={<ClipboardList size={20} />}
              iconClass="bg-amber-50 text-amber-700"
              value={d ? d.attempt_summary.total_attempts : null}
              label={`Answers in ${teacherClassName(selected)}`}
            />
            <StatTile
              icon={<CheckCircle2 size={20} />}
              iconClass="bg-band-mastered-bg text-band-mastered"
              value={d && d.attempt_summary.total_attempts ? Math.round((d.attempt_summary.correct_attempts / d.attempt_summary.total_attempts) * 100) : null}
              format={(n) => `${Math.round(n)}%`}
              label="Answered correctly"
            />
          </motion.section>

          <motion.section variants={fadeUp} aria-labelledby="classes-title" className="mb-10">
            <SectionHeader id="classes-title" title="Your classes" subtitle="Choose a class to see its Bell Ringer and heatmap below." />
            <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
              {classes.map((c) => {
                const active = c.classroom_id === classId;
                return (
                  <button
                    key={c.classroom_id}
                    type="button"
                    onClick={() => select(c.classroom_id)}
                    aria-pressed={active}
                    className={cx('card card-hover p-5 text-left focus-ring', active && 'border-brand-500 ring-1 ring-brand-500')}
                  >
                    <div className="flex items-start justify-between gap-3">
                      <div className="min-w-0">
                        <p className="t-card">{teacherClassName(c)}</p>
                        <p className="text-xs text-ctText-muted">
                          {c.school_label ?? 'School'} · {c.academic_session ?? ''}
                        </p>
                      </div>
                      {active && <Pill tone="brand">Viewing</Pill>}
                    </div>
                    <p className="mt-3 text-sm text-ctText-body">{plural(c.learner_count, 'learner')}</p>
                  </button>
                );
              })}
            </div>
          </motion.section>

          <motion.section variants={fadeUp} aria-labelledby="bell-title" className="mb-10">
            <div className="mb-4 flex flex-col gap-4 rounded-3xl border border-amber-100 bg-gradient-to-r from-[#FFFBEB] to-white p-5 sm:flex-row sm:items-center">
              <img src={bellArt} alt="" className="h-20 w-auto self-start" />
              <div className="min-w-0 flex-1">
                <h2 id="bell-title" className="t-section">
                  Bell Ringer · {teacherClassName(selected)}
                </h2>
                <p className="mt-0.5 text-sm text-ctText-muted">
                  Topics where several different learners are struggling, each with a ready five-minute warm-up built from stored questions.
                </p>
              </div>
              <Link to="/teacher/bell-ringer" className="btn btn-secondary shrink-0">
                All topics and cycles <ArrowRight size={15} aria-hidden />
              </Link>
            </div>
            <QueryView query={bell} loading={<Skeleton className="h-48" />} compact>
              {(b) => {
                const flagged = b.topics.filter((t) => t.flagged).slice(0, 3);
                return flagged.length ? (
                  <motion.div initial="hidden" animate="show" variants={stagger(0.06)} className="space-y-4">
                    {flagged.map((t) => (
                      <BellRingerTopicCard key={t.kc_id} classId={classId} topic={t} cyclesEnabled={b.cycles_enabled} demo={catalog.data?.content_release === 'demo'} />
                    ))}
                    <p className="text-xs text-ctText-muted">
                      {plural(b.flagged_count, 'topic')} flagged out of {b.topics.length} for {plural(b.enrolled_learners, 'enrolled learner')}; recent activity covers{' '}
                      {b.window.days} days.
                    </p>
                  </motion.div>
                ) : (
                  <EmptyState compact title="No topic needs a Bell Ringer right now" body="No topic meets the flagging criteria for this class. Open the Bell Ringer page to see every topic and why." />
                );
              }}
            </QueryView>
          </motion.section>

          <motion.section variants={fadeUp} aria-labelledby="heat-title" className="mb-10">
            <SectionHeader
              id="heat-title"
              title={`Learning heatmap · ${teacherClassName(selected)}`}
              subtitle="Each cell is one learner's current estimate for one topic."
              action={
                <div className="flex items-center gap-2">
                  <label htmlFor="dash-subject" className="sr-only">
                    Subject
                  </label>
                  <select id="dash-subject" className="field-select" value={subject} onChange={(e) => setSubject(e.target.value)}>
                    {SUBJECT_ORDER.map((id) => (
                      <option key={id} value={id}>
                        {subjectMeta(id).name}
                      </option>
                    ))}
                  </select>
                  <Link to="/teacher/heatmap" className="btn btn-secondary">
                    Full heatmap
                  </Link>
                </div>
              }
            />
            <HeatmapLegend className="mb-3" />
            <QueryView query={heat} loading={<Skeleton className="h-72" />}>
              {(h) =>
                h.topics.length === 0 ? (
                  <EmptyState compact title={`No ${subjectMeta(subject).name} topics for this class`} />
                ) : (
                  <div className={cx('transition-opacity', heat.isFetching && 'opacity-60')}>
                    <HeatmapGrid data={h} maxRows={10} />
                  </div>
                )
              }
            </QueryView>
          </motion.section>

          <motion.section variants={fadeUp} aria-labelledby="signals-title">
            <SectionHeader id="signals-title" title="Lowest class estimates" subtitle="Average estimate among learners with any estimate, lowest first." />
            <QueryView query={dashboard} compact>
              {(dash) =>
                dash.topic_signals.length === 0 ? (
                  <EmptyState compact title="No estimates yet" body="Signals appear once learners start answering questions." />
                ) : (
                  <Card pad={false}>
                    <ul className="divide-y divide-surface-border-subtle">
                      {dash.topic_signals.slice(0, 6).map((sg) => (
                        <li key={sg.kc_id} className="flex flex-wrap items-center gap-3 px-5 py-3 text-sm">
                          <span className="min-w-0 flex-1 font-semibold text-ctText-primary">{sg.topic_name}</span>
                          <span className="text-xs text-ctText-muted">
                            {sg.below_0_5_count} of {sg.students_with_estimate} below 50%
                          </span>
                          <span className="w-14 text-right font-bold tabular-nums text-ctText-primary">{pct(sg.average_mastery_probability)}</span>
                        </li>
                      ))}
                    </ul>
                  </Card>
                )
              }
            </QueryView>
          </motion.section>
        </>
      )}
    </motion.div>
  );
};

export default TeacherDashboard;
