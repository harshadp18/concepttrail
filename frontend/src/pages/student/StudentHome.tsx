import React from 'react';
import { Link } from 'react-router-dom';
import { motion } from 'framer-motion';
import { ArrowRight, BookOpen, ClipboardCheck, Compass, Target, Trophy } from 'lucide-react';
import { useCatalog, useChapterProgress, useRecommendation, useTopic, useWeakAreas } from '@/api/hooks';
import type { Recommendation } from '@/api/types';
import { classLabel, useAuth } from '@/context/AuthContext';
import { SubjectCard } from '@/components/student/SubjectCard';
import { DemoContentNotice, EstimateNote, SectionHeader } from '@/components/ui/primitives';
import { StatTile } from '@/components/ui/primitives';
import { ErrorState, QueryView, Skeleton } from '@/components/ui/states';
import { fadeUp, stagger } from '@/components/ui/motion';
import { CATEGORY_LABEL, readableRationale, recommendationMessage } from '@/lib/recommendation';
import { SUBJECT_ORDER, subjectMeta } from '@/lib/subjects';
import { pct } from '@/lib/format';
import trailArt from '@/assets/illustrations/trail-banner.svg';

function greeting() {
  const h = new Date().getHours();
  return h < 12 ? 'Good morning' : h < 17 ? 'Good afternoon' : 'Good evening';
}

const ContinueBanner: React.FC<{ rec: Recommendation }> = ({ rec }) => {
  const topic = useTopic(rec.status === 'ok' ? rec.kc_id ?? '' : '');
  const ok = rec.status === 'ok' && rec.kc_id;
  const subject = subjectMeta(topic.data?.subject_id);
  const p = rec.mastery_probability;
  const filled = p == null ? 0 : Math.min(4, Math.floor(p * 4 + 0.0001));
  return (
    <motion.section
      variants={fadeUp}
      aria-labelledby="continue-title"
      className="relative overflow-hidden rounded-[26px] bg-gradient-to-br from-brand-500 via-[#1F6B88] to-brand-teal-deep p-6 text-white shadow-elevated sm:p-8"
    >
      <img src={trailArt} alt="" className="pointer-events-none absolute -right-6 bottom-0 hidden h-full w-auto select-none opacity-95 sm:block" />
      <div className="relative z-10 max-w-lg space-y-3">
        <p className="flex items-center gap-2 text-xs font-bold tracking-wide text-brand-sun">
          <span className="h-2 w-2 rounded-full bg-brand-sun" aria-hidden /> {ok ? 'Continue learning' : 'Your next step'}
        </p>
        {ok ? (
          <>
            <p className="text-xs font-medium text-white/85">
              {topic.data ? subject.name : <Skeleton className="inline-block h-3 w-24 bg-white/20" />} ·{' '}
              {CATEGORY_LABEL[rec.category ?? ''] ?? 'Suggested'}
            </p>
            <h2 id="continue-title" className="text-2xl font-extrabold tracking-tight text-white sm:text-3xl">
              {topic.data?.name ?? <Skeleton className="h-8 w-64 bg-white/20" />}
            </h2>
            <div className="flex flex-wrap items-center gap-2.5">
              <span className="rounded-full bg-white px-3 py-0.5 text-xs font-bold text-brand-700">
                {p == null ? 'Not started' : `Estimated mastery ${pct(p)}`}
              </span>
            </div>
            <div className="grid max-w-[260px] grid-cols-4 gap-2" aria-hidden>
              {[0, 1, 2, 3].map((i) => (
                <motion.div
                  key={i}
                  className="h-2 origin-left rounded-full"
                  initial={{ scaleX: 0, backgroundColor: '#4D8EAA' }}
                  animate={{ scaleX: 1, backgroundColor: i < filled ? '#FFD016' : '#4D8EAA' }}
                  transition={{ delay: 0.15 + i * 0.08, duration: 0.4 }}
                />
              ))}
            </div>
            <ul className="space-y-0.5 text-xs text-white/90">
              {readableRationale(rec.rationale).map((r) => (
                <li key={r}>{r}</li>
              ))}
            </ul>
            <div className="flex flex-wrap gap-2 pt-2">
              <Link
                to={`/student/topics/${encodeURIComponent(rec.kc_id!)}/practice${rec.question_id ? `?start=${encodeURIComponent(rec.question_id)}` : ''}`}
                className="btn rounded-full bg-white text-brand-700 hover:bg-brand-50"
              >
                Start practice <ArrowRight size={15} aria-hidden />
              </Link>
              <Link to={`/student/topics/${encodeURIComponent(rec.kc_id!)}`} className="btn rounded-full bg-white/10 text-white ring-1 ring-inset ring-white/40 hover:bg-white/20">
                About this topic
              </Link>
            </div>
          </>
        ) : (
          <>
            <h2 id="continue-title" className="text-2xl font-extrabold tracking-tight text-white sm:text-3xl">
              Choose where to start
            </h2>
            <p className="text-sm text-white/90">{recommendationMessage(rec)}</p>
            <Link to="/student/subjects" className="btn mt-2 rounded-full bg-white text-brand-700 hover:bg-brand-50">
              <Compass size={15} aria-hidden /> Browse subjects
            </Link>
          </>
        )}
      </div>
    </motion.section>
  );
};

export const StudentHome: React.FC = () => {
  const { user } = useAuth();
  const catalog = useCatalog();
  const chapters = useChapterProgress();
  const weak = useWeakAreas();
  const rec = useRecommendation();
  const firstName = (user?.display_name ?? '').split(' ').slice(0, 2).join(' ') || user?.login_identifier;

  const subjects = chapters.data?.subjects ?? [];
  const sum = (k: 'topics_mastered' | 'topics_started' | 'attempts') => subjects.reduce((n, s) => n + s[k], 0);
  const ready = !!chapters.data;

  return (
    <motion.div initial="hidden" animate="show" variants={stagger(0.06)} className="space-y-8">
      <motion.header variants={fadeUp} className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="t-page">Dashboard</h1>
          <p className="mt-1 text-base font-bold text-brand-600 sm:text-lg">
            {greeting()}, {firstName}!
          </p>
          <p className="text-sm text-ctText-muted">{classLabel(user?.primaryClass)} · Ready to explore something new today?</p>
        </div>
      </motion.header>

      {catalog.data?.content_release === 'demo' && <DemoContentNotice />}

      <motion.section
        variants={stagger(0.05)}
        aria-label="Your progress at a glance"
        className="card grid grid-cols-2 divide-surface-border-subtle lg:grid-cols-4 lg:divide-x [&>*:nth-child(-n+2)]:border-b [&>*:nth-child(-n+2)]:border-surface-border-subtle lg:[&>*]:border-b-0"
      >
        <StatTile icon={<Trophy size={20} />} iconClass="bg-band-mastered-bg text-band-mastered" value={ready ? sum('topics_mastered') : null} label="Topics mastered" />
        <StatTile
          icon={<BookOpen size={20} />}
          iconClass="bg-brand-50 text-brand-600"
          value={ready ? sum('topics_started') - sum('topics_mastered') : null}
          label="Topics in progress"
        />
        <StatTile icon={<Target size={20} />} iconClass="bg-band-practice-bg text-band-practice" value={weak.data ? weak.data.weak_areas.length : null} label="Need practice" />
        <StatTile icon={<ClipboardCheck size={20} />} iconClass="bg-band-developing-bg text-band-developing" value={ready ? sum('attempts') : null} label="Questions answered" />
      </motion.section>
      {chapters.error && <ErrorState error={chapters.error} onRetry={() => chapters.refetch()} compact />}

      <QueryView query={rec} loading={<Skeleton className="h-60 rounded-[26px]" />} compact>
        {(r) => <ContinueBanner rec={r} />}
      </QueryView>

      <motion.section variants={fadeUp} aria-labelledby="subjects-title">
        <SectionHeader
          id="subjects-title"
          title="My subjects"
          subtitle="Choose what you'd like to explore today."
          action={
            <Link to="/student/progress" className="btn btn-ghost btn-sm">
              See all progress <ArrowRight size={14} aria-hidden />
            </Link>
          }
        />
        <QueryView query={catalog} loading={<div className="grid grid-cols-2 gap-4 lg:grid-cols-5">{[...Array(5)].map((_, i) => <Skeleton key={i} className="h-64 rounded-3xl" />)}</div>}>
          {(c) => {
            const level = c.grade_levels[0];
            const combos = SUBJECT_ORDER.map((id) => c.combinations.find((x) => x.subject_id === id && x.grade_level === level)).filter(
              (x): x is NonNullable<typeof x> => !!x
            );
            return (
              <motion.div variants={stagger(0.05)} initial="hidden" animate="show" className="grid grid-cols-2 gap-3 sm:gap-4 lg:grid-cols-5">
                {combos.map((combo) => (
                  <SubjectCard key={combo.subject_id} combo={combo} progress={subjects.find((s) => s.subject_id === combo.subject_id)} compact />
                ))}
              </motion.div>
            );
          }}
        </QueryView>
        <EstimateNote className="mt-3" />
      </motion.section>
    </motion.div>
  );
};

export default StudentHome;
