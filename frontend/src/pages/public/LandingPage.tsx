import React, { useState } from 'react';
import { Link } from 'react-router-dom';
import { AnimatePresence, motion } from 'framer-motion';
import {
  ArrowRight,
  BarChart3,
  BellRing,
  BookOpen,
  Check,
  ClipboardCheck,
  GraduationCap,
  MessageCircle,
  School,
  Sparkles,
  Target,
  TrendingUp,
  Users,
} from 'lucide-react';
import { BrandLogo } from '@/components/brand/BrandLogo';
import { cx } from '@/components/ui/primitives';
import { ease, fadeUp, stagger } from '@/components/ui/motion';
import { SUBJECT_ORDER, subjectMeta } from '@/lib/subjects';
import heroArt from '@/assets/illustrations/hero-learner.webp';

const FEATURES = [
  { title: 'Personalised learning', body: 'Your next step is chosen from what you already know.', icon: Target, tone: 'bg-band-mastered-bg text-band-mastered' },
  { title: 'Buddy doubt solver', body: 'Answers built from your course material, with sources.', icon: MessageCircle, tone: 'bg-brand-50 text-brand-700' },
  { title: 'Adaptive practice', body: 'Questions on the exact topic you are working on.', icon: ClipboardCheck, tone: 'bg-band-developing-bg text-band-developing' },
  { title: 'Track your progress', body: 'See your mastery estimate per topic and subject.', icon: TrendingUp, tone: 'bg-band-practice-bg text-band-practice' },
  { title: 'For teachers', body: 'Class heatmaps and five-minute Bell Ringers.', icon: Users, tone: 'bg-amber-50 text-amber-700' },
];

const STEPS = [
  {
    title: 'Pick a topic',
    sub: 'From your class chapters',
    icon: BookOpen,
    heading: 'Every chapter is broken into small topics',
    body: 'Open a subject, choose a chapter and see each topic with your own mastery estimate beside it. Topics that depend on earlier ideas show which ones to revisit first.',
  },
  {
    title: 'Practise',
    sub: 'Questions scored instantly',
    icon: ClipboardCheck,
    heading: 'Answers are checked by the system, not guessed by AI',
    body: 'Multiple-choice, true/false and numeric questions are scored against stored answer keys. Every answer updates your mastery estimate for that topic.',
  },
  {
    title: 'See your mastery',
    sub: 'Updated after every answer',
    icon: BarChart3,
    heading: 'Mastery, not just marks',
    body: 'ConceptTrail estimates how well you know each topic using Bayesian Knowledge Tracing, which allows for lucky guesses and small slips. It is an estimate to guide practice, not a grade.',
  },
  {
    title: 'Ask Buddy',
    sub: 'Grounded explanations',
    icon: MessageCircle,
    heading: 'Buddy explains from your course material — or says it cannot',
    body: 'Ask a doubt in your own words. Buddy answers only from the stored pages it can cite, shows those sources, and tells you honestly when it does not have enough to go on.',
  },
];

export const LandingPage: React.FC = () => {
  const [step, setStep] = useState(0);
  const active = STEPS[step];

  return (
    <div className="min-h-screen overflow-x-hidden bg-surface-subtle text-ctText-body">
      <header className="sticky top-0 z-50 border-b border-surface-border bg-white/95 backdrop-blur">
        <div className="mx-auto flex h-16 sm:h-20 max-w-7xl items-center justify-between gap-4 px-4 sm:px-6 lg:px-8">
          <div className="flex items-center gap-10">
            <BrandLogo size="lg" linkTo="/" />
            <nav aria-label="Page sections" className="hidden items-center gap-7 text-sm font-semibold text-ctText-muted lg:flex">
              <a href="#subjects" className="hover:text-brand-600 focus-ring rounded">Subjects</a>
              <a href="#how-it-works" className="hover:text-brand-600 focus-ring rounded">How it works</a>
              <a href="#get-started" className="hover:text-brand-600 focus-ring rounded">For teachers</a>
            </nav>
          </div>
          <div className="flex items-center gap-2 sm:gap-3">
            {/* Existing users: straight to the sign-in screen */}
            <Link to="/login" className="btn btn-secondary rounded-xl px-4 sm:px-6">
              Log in
            </Link>
            {/* New visitors: choose the student or teacher experience */}
            <a href="#get-started" className="btn btn-primary rounded-xl px-4 sm:px-6">
              Get started
            </a>
          </div>
        </div>
      </header>

      <section className="relative overflow-hidden border-b border-surface-border bg-gradient-to-b from-white via-[#F6FAFC] to-surface-subtle pb-14 pt-8 md:pb-20 md:pt-14">
        <div className="mx-auto grid max-w-7xl grid-cols-1 items-center gap-10 px-4 sm:px-6 lg:grid-cols-12 lg:gap-6 lg:px-8">
          <motion.div initial="hidden" animate="show" variants={stagger(0.08)} className="space-y-6 lg:col-span-5">
            <motion.div variants={fadeUp} className="inline-flex items-center gap-2 rounded-full border border-brand-200 bg-brand-50 px-3.5 py-1.5 text-xs font-bold text-brand-700">
              <Sparkles className="h-3.5 w-3.5" aria-hidden />
              Adaptive learning · CBSE Classes 6–10
            </motion.div>
            <motion.h1 variants={fadeUp} className="text-4xl font-black leading-[1.1] tracking-tight text-ctText-primary sm:text-5xl lg:text-[54px]">
              Build stronger concepts. <span className="text-brand-500">Unlock your potential.</span>
            </motion.h1>
            <motion.p variants={fadeUp} className="max-w-lg text-base leading-relaxed text-ctText-muted sm:text-lg">
              ConceptTrail finds the topic that is holding you back, gives you practice on exactly that, and shows your
              teacher who needs help and why.
            </motion.p>
            <motion.div variants={fadeUp} className="flex flex-wrap items-center gap-3 pt-1">
              {/* A tour of the student experience; it does not promise a sign-up that does not exist */}
              <a href="#how-it-works" className="btn btn-primary btn-lg rounded-full px-7 shadow-md hover:shadow-elevated">
                Explore the student journey <ArrowRight className="h-5 w-5" aria-hidden />
              </a>
              <span className="text-xs text-ctText-muted">Accounts are provided by your school.</span>
            </motion.div>
          </motion.div>
          <motion.div
            initial={{ opacity: 0, scale: 0.98 }}
            animate={{ opacity: 1, scale: 1, transition: { duration: 0.6, ease } }}
            className="flex justify-center lg:col-span-7"
          >
            <img
              src={heroArt}
              alt="A student studying at a desk, surrounded by cards for Mathematics, Science, English, Hindi and Social Science"
              width={1238}
              height={800}
              className="h-auto w-full max-w-[680px] select-none rounded-[28px] shadow-elevated"
            />
          </motion.div>
        </div>
      </section>

      <section className="border-b border-surface-border bg-white py-14 sm:py-20" aria-labelledby="features-title">
        <div className="mx-auto max-w-7xl space-y-10 px-4 sm:px-6 lg:px-8">
          <h2 id="features-title" className="text-center text-2xl font-extrabold tracking-tight text-ctText-primary sm:text-3xl lg:text-4xl">
            Everything you need to learn better
          </h2>
          <motion.ul
            initial="hidden"
            whileInView="show"
            viewport={{ once: true, margin: '-60px' }}
            variants={stagger(0.07)}
            className="grid grid-cols-1 gap-8 text-center sm:grid-cols-2 sm:gap-6 lg:grid-cols-5"
          >
            {FEATURES.map((f) => (
              <motion.li key={f.title} variants={fadeUp} className="group flex flex-col items-center gap-3 px-2">
                <div className={cx('flex h-16 w-16 items-center justify-center rounded-full transition-transform duration-200 group-hover:-translate-y-1', f.tone)}>
                  <f.icon className="h-7 w-7" aria-hidden />
                </div>
                <h3 className="text-base font-extrabold text-ctText-primary">{f.title}</h3>
                <p className="max-w-[220px] text-sm leading-relaxed text-ctText-muted">{f.body}</p>
              </motion.li>
            ))}
          </motion.ul>
        </div>
      </section>

      <section id="subjects" className="scroll-mt-20 border-b border-surface-border bg-surface-subtle py-16 sm:py-24" aria-labelledby="subjects-title">
        <div className="mx-auto max-w-7xl space-y-12 px-4 sm:px-6 lg:px-8">
          <div className="mx-auto max-w-3xl space-y-3 text-center">
            <span className="t-eyebrow rounded-full border border-brand-100 bg-brand-50 px-3.5 py-1.5 text-brand-700">Five subjects</span>
            <h2 id="subjects-title" className="text-3xl font-black tracking-tight text-ctText-primary sm:text-4xl">
              Five core subjects. Designed for mastery.
            </h2>
            <p className="text-base text-ctText-muted">
              Chapters for Classes 6–10 are broken into topics, each with practice questions and a mastery estimate.
              What you see depends on your class.
            </p>
          </div>
          <motion.div
            initial="hidden"
            whileInView="show"
            viewport={{ once: true, margin: '-60px' }}
            variants={stagger(0.06)}
            className="grid grid-cols-1 gap-5 sm:grid-cols-2 lg:grid-cols-5"
          >
            {SUBJECT_ORDER.map((id) => {
              const s = subjectMeta(id);
              return (
                <motion.article key={id} variants={fadeUp} className={cx('flex flex-col overflow-hidden rounded-3xl border card-hover', s.tint, s.ring)}>
                  <img src={s.art} alt="" className="aspect-[3/2] w-full object-contain p-3" loading="lazy" />
                  <div className="flex flex-1 flex-col px-5 pb-6">
                    <h3 className="text-lg font-black text-ctText-primary">{s.name}</h3>
                    <p className="mt-1 text-sm leading-snug text-ctText-body">{s.blurb}</p>
                  </div>
                </motion.article>
              );
            })}
          </motion.div>
        </div>
      </section>

      <section id="how-it-works" className="scroll-mt-20 border-b border-surface-border bg-white py-16 sm:py-24" aria-labelledby="how-title">
        <div className="mx-auto max-w-7xl space-y-10 px-4 sm:px-6 lg:px-8">
          <div className="mx-auto max-w-2xl space-y-3 text-center">
            <span className="t-eyebrow rounded-full border border-brand-100 bg-brand-50 px-3.5 py-1.5 text-brand-700">The student journey</span>
            <h2 id="how-title" className="text-3xl font-black tracking-tight text-ctText-primary sm:text-4xl">
              A simple path to stronger concepts
            </h2>
            <p className="text-base text-ctText-muted">Algorithms decide what you need next. AI only helps explain.</p>
          </div>
          <div role="tablist" aria-label="Steps" className="mx-auto grid max-w-4xl grid-cols-2 gap-3 md:grid-cols-4">
            {STEPS.map((s, i) => (
              <button
                key={s.title}
                role="tab"
                id={`step-tab-${i}`}
                aria-selected={step === i}
                aria-controls="step-panel"
                onClick={() => setStep(i)}
                className={cx(
                  'rounded-2xl border p-4 text-left transition-all focus-ring',
                  step === i ? 'border-brand-500 bg-brand-50 shadow-sm ring-1 ring-brand-500' : 'border-surface-border bg-white hover:bg-surface-subtle'
                )}
              >
                <div className={cx('mb-2 flex h-8 w-8 items-center justify-center rounded-full text-sm font-black', step === i ? 'bg-brand-500 text-white' : 'bg-surface-muted text-ctText-muted')}>
                  {i + 1}
                </div>
                <p className="text-sm font-extrabold text-ctText-primary">{s.title}</p>
                <p className="text-2xs font-medium text-ctText-muted">{s.sub}</p>
              </button>
            ))}
          </div>
          <div id="step-panel" role="tabpanel" aria-labelledby={`step-tab-${step}`} className="mx-auto max-w-4xl rounded-3xl border border-surface-border bg-surface-subtle p-6 sm:p-8">
            <AnimatePresence mode="wait">
              <motion.div
                key={step}
                initial={{ opacity: 0, y: 10 }}
                animate={{ opacity: 1, y: 0, transition: { duration: 0.28, ease } }}
                exit={{ opacity: 0, y: -6, transition: { duration: 0.12 } }}
                className="flex flex-col gap-5 sm:flex-row sm:items-start"
              >
                <div className="flex h-14 w-14 shrink-0 items-center justify-center rounded-2xl bg-white text-brand-600 shadow-card">
                  <active.icon className="h-7 w-7" aria-hidden />
                </div>
                <div>
                  <p className="t-eyebrow text-brand-600">Step {step + 1}</p>
                  <h3 className="mt-1 text-xl font-black text-ctText-primary sm:text-2xl">{active.heading}</h3>
                  <p className="mt-2 text-sm leading-relaxed text-ctText-muted">{active.body}</p>
                </div>
              </motion.div>
            </AnimatePresence>
          </div>
        </div>
      </section>

      <section id="get-started" className="mx-auto max-w-7xl scroll-mt-20 px-4 py-16 sm:px-6 lg:px-8" aria-labelledby="audience-title">
        <h2 id="audience-title" className="mb-8 text-center text-2xl font-extrabold tracking-tight text-ctText-primary sm:text-3xl">
          Choose your ConceptTrail
        </h2>
        <div className="grid grid-cols-1 gap-6 md:grid-cols-2 md:gap-8">
          <article className="flex flex-col justify-between gap-6 rounded-3xl border-2 border-brand-100 bg-gradient-to-br from-white to-brand-50 p-7 shadow-card sm:p-8">
            <div className="space-y-4">
              <span className="t-eyebrow inline-block rounded-full bg-brand-100 px-3.5 py-1.5 text-brand-700">For students</span>
              <h3 className="text-2xl font-black text-ctText-primary sm:text-3xl">Ready to build mastery?</h3>
              <p className="text-sm leading-relaxed text-ctText-muted">
                Sign in with the username and 8-digit PIN from your school to reach your subjects, practice and Buddy.
              </p>
              <ul className="space-y-2.5 pt-1 text-sm font-semibold text-ctText-body">
                {[
                  'A next step chosen from your own answers',
                  'Practice questions in five subjects for your class',
                  'Buddy explanations with sources, or an honest "I don\'t know"',
                ].map((t) => (
                  <li key={t} className="flex items-start gap-2">
                    <Check className="mt-0.5 h-4 w-4 shrink-0 text-brand-600" aria-hidden />
                    {t}
                  </li>
                ))}
              </ul>
            </div>
            <Link to="/login?role=student" className="btn btn-primary btn-lg w-fit">
              <GraduationCap className="h-4 w-4" aria-hidden /> Student sign in <ArrowRight className="h-4 w-4" aria-hidden />
            </Link>
          </article>

          <article className="flex flex-col justify-between gap-6 rounded-3xl border-2 border-[#CFE6E2] bg-gradient-to-br from-white to-[#EEF5F3] p-7 shadow-card sm:p-8">
            <div className="space-y-4">
              <span className="t-eyebrow inline-block rounded-full bg-[#D9EEEA] px-3.5 py-1.5 text-brand-teal-deep">For teachers and schools</span>
              <h3 className="text-2xl font-black text-ctText-primary sm:text-3xl">Empower your classroom</h3>
              <p className="text-sm leading-relaxed text-ctText-muted">
                Teachers sign in with the school account their administrator provides and see only the classes assigned
                to them.
              </p>
              <ul className="space-y-2.5 pt-1 text-sm font-semibold text-ctText-body">
                {[
                  'Get clear, real-time insights into class progress and learning needs',
                  'Five-minute Bell Ringers for the topics each class finds hardest',
                  'Review AI-drafted questions before learners rely on them',
                ].map((t) => (
                  <li key={t} className="flex items-start gap-2">
                    <Check className="mt-0.5 h-4 w-4 shrink-0 text-brand-teal" aria-hidden />
                    {t}
                  </li>
                ))}
              </ul>
            </div>
            <Link to="/login?role=teacher" className="btn btn-lg w-fit bg-brand-700 text-white hover:bg-brand-800">
              <School className="h-4 w-4" aria-hidden /> Teacher sign in <ArrowRight className="h-4 w-4" aria-hidden />
            </Link>
          </article>
        </div>
        <p className="mt-6 flex items-center justify-center gap-2 text-center text-xs text-ctText-muted">
          <BellRing className="h-3.5 w-3.5" aria-hidden /> There is no public sign-up: schools create student and teacher accounts.
        </p>
      </section>

      <footer className="border-t border-surface-border bg-white py-10">
        <div className="mx-auto max-w-7xl space-y-6 px-4 sm:px-6 lg:px-8">
          <div className="flex flex-col items-start justify-between gap-6 md:flex-row md:items-center">
            <BrandLogo size="md" linkTo="/" />
            <nav aria-label="Footer" className="flex flex-wrap gap-x-6 gap-y-2 text-sm font-semibold text-ctText-muted">
              <Link to="/login?role=student" className="hover:text-brand-600">Student sign in</Link>
              <Link to="/login?role=teacher" className="hover:text-brand-600">Teacher sign in</Link>
              <a href="#subjects" className="hover:text-brand-600">Subjects</a>
              <a href="#how-it-works" className="hover:text-brand-600">How it works</a>
            </nav>
          </div>
          <div className="flex flex-col items-center justify-between gap-2 border-t border-surface-border-subtle pt-6 text-xs text-ctText-subtle sm:flex-row">
            <p>© {new Date().getFullYear()} ConceptTrail · CBSE Classes 6–10</p>
            <p>Mastery figures are estimates to guide practice, not grades.</p>
          </div>
        </div>
      </footer>
    </div>
  );
};

export default LandingPage;
