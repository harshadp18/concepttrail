import React, { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { AnimatePresence, motion } from 'framer-motion';
import { AlertTriangle, ChevronDown, Clock, Eye, GitBranch, Play, Users } from 'lucide-react';
import type { BellRingerCriteria, BellRingerTopic, TeacherQuestionView, WarmUpCard } from '@/api/types';
import { useCycleActions } from '@/api/hooks';
import { ApiError } from '@/api/http';
import { pct, plural } from '@/lib/format';
import { subjectMeta } from '@/lib/subjects';
import { cx, Notice, Pill } from '@/components/ui/primitives';
import { ErrorState } from '@/components/ui/states';
import { fadeUp } from '@/components/ui/motion';
import { SHOW_DEMO_NOTICES } from '@/lib/flags';

const LETTERS = 'ABCDEFGH';

const QuestionBlock: React.FC<{ title: string; q: TeacherQuestionView | null; note?: string }> = ({ title, q, note }) => (
  <div className="rounded-2xl border border-surface-border bg-white p-4">
    <p className="t-eyebrow text-brand-600">{title}</p>
    {q ? (
      <>
        <p className="mt-1.5 text-sm font-semibold leading-snug text-ctText-primary">{q.stem}</p>
        {q.options.length > 0 && (
          <ul className="mt-2 space-y-1">
            {q.options.map((o, i) => (
              <li key={o.option_key} className={cx('flex gap-2 rounded-lg px-2 py-1 text-xs', o.is_correct ? 'bg-band-mastered-bg font-semibold text-band-mastered' : 'text-ctText-body')}>
                <span className="w-4 shrink-0 font-bold">{LETTERS[i]}</span>
                <span className="min-w-0 flex-1">{o.option_text}</span>
                {o.is_correct && <span className="shrink-0">Answer</span>}
              </li>
            ))}
          </ul>
        )}
        {q.expected_answer != null && q.options.length === 0 && (
          <p className="mt-2 text-xs font-semibold text-band-mastered">Answer: {JSON.stringify(q.expected_answer)}</p>
        )}
        {note && <p className="mt-2 text-2xs text-ctText-muted">{note}</p>}
      </>
    ) : (
      <p className="mt-1.5 text-sm text-ctText-muted">No deliverable question is stored for this topic yet.</p>
    )}
  </div>
);

export const WarmUp: React.FC<{ card: WarmUpCard; demo?: boolean }> = ({ card, demo }) => (
  <div className="space-y-4">
    <ol className="grid grid-cols-1 gap-2 sm:grid-cols-3" aria-label="Timed steps">
      {card.steps.map((s, i) => (
        <li key={s.label} className="rounded-2xl bg-brand-700 p-3.5 text-white">
          <p className="flex items-center gap-1.5 text-2xs font-bold uppercase tracking-wider text-brand-sun">
            <Clock size={12} aria-hidden /> Step {i + 1} · {s.minutes} min
          </p>
          <p className="mt-1 text-sm font-bold">{s.label}</p>
          <p className="text-xs text-white/80">{s.detail}</p>
        </li>
      ))}
    </ol>
    <div className="grid grid-cols-1 gap-3 lg:grid-cols-2">
      <QuestionBlock title="On the board" q={card.board_question} />
      <QuestionBlock title="Bridge to the lesson" q={card.bridge_question} />
    </div>
    {card.watch_for && (
      <div className="flex gap-3 rounded-2xl border border-amber-200 bg-amber-50 p-4 text-sm">
        <Eye size={18} className="mt-0.5 shrink-0 text-amber-700" aria-hidden />
        <div>
          <p className="font-bold text-amber-800">Watch for</p>
          {card.watch_for.source === 'class_attempts' ? (
            <p className="text-amber-900/90">
              “{card.watch_for.option_text}” — the wrong answer this class chose most often ({plural(card.watch_for.wrong_attempts, 'time')}).
            </p>
          ) : (
            <p className="text-amber-900/90">
              {card.watch_for.text} <span className="text-2xs">(misconception note stored with the question)</span>
            </p>
          )}
        </div>
      </div>
    )}
    <p className="text-2xs text-ctText-subtle">
      Built from stored questions by a fixed template; no AI writes or picks this card.{' '}
      {SHOW_DEMO_NOTICES && demo && 'The questions are AI-drafted demo content awaiting teacher review — check them before using them in class.'}
    </p>
  </div>
);

export const CriteriaNote: React.FC<{ criteria: BellRingerCriteria; enrolled: number; windowDays: number }> = ({ criteria, enrolled, windowDays }) => (
  <Notice>
    A topic is flagged when at least {pct(criteria.min_coverage)} of the {enrolled} enrolled learners have enough answers for an estimate (≥{' '}
    {criteria.min_evidence}), at least {criteria.min_affected_learners} different learners are below {pct(criteria.weak_below)} estimated mastery, and they
    make up at least {pct(criteria.min_affected_share)} of those learners. Each learner counts once, however many times they answered. Recent activity
    covers the last {windowDays} days. Thresholds are provisional.
  </Notice>
);

/** One topic-level opportunity. Counts are unique learners with their denominators. */
export const BellRingerTopicCard: React.FC<{
  classId: string;
  topic: BellRingerTopic;
  cyclesEnabled: boolean;
  demo?: boolean;
  defaultOpen?: boolean;
}> = ({ classId, topic, cyclesEnabled, demo, defaultOpen }) => {
  const [open, setOpen] = useState(!!defaultOpen);
  const { open: openCycle } = useCycleActions(classId);
  const navigate = useNavigate();
  const s = subjectMeta(topic.subject_id);
  const share = topic.affected_share ?? 0;

  const start = () =>
    openCycle.mutate(
      { kc_id: topic.kc_id },
      { onSuccess: (cycle) => navigate(`/teacher/bell-ringer/${cycle.cycle_id}`) }
    );

  return (
    <motion.article variants={fadeUp} layout className="card overflow-hidden">
      <div className="flex flex-col gap-4 p-5 sm:flex-row sm:items-start">
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            {topic.rank && <span className="flex h-6 w-6 items-center justify-center rounded-full bg-brand-700 text-2xs font-bold text-white">{topic.rank}</span>}
            <span className={cx('t-eyebrow', s.ink)}>{s.name}</span>
            {topic.severity === 'high' ? (
              <Pill tone="error" icon={<AlertTriangle size={11} />}>
                High attention
              </Pill>
            ) : (
              <Pill tone="warning">Needs attention</Pill>
            )}
          </div>
          <h3 className="t-card mt-1.5">{topic.name}</h3>
          <p className="text-xs text-ctText-muted">{topic.item_title}</p>

          <dl className="mt-4 grid grid-cols-2 gap-3 text-xs sm:grid-cols-4">
            <div>
              <dt className="text-ctText-muted">Learners struggling</dt>
              <dd className="text-lg font-extrabold text-ctText-primary">
                {topic.learners_below_threshold}
                <span className="text-xs font-semibold text-ctText-muted"> / {topic.learners_with_evidence} with estimate</span>
              </dd>
            </div>
            <div>
              <dt className="text-ctText-muted">Share struggling</dt>
              <dd className="text-lg font-extrabold text-ctText-primary">{pct(topic.affected_share)}</dd>
            </div>
            <div>
              <dt className="text-ctText-muted">Not attempted</dt>
              <dd className="text-lg font-extrabold text-ctText-primary">
                {topic.learners_not_attempted}
                <span className="text-xs font-semibold text-ctText-muted"> / {topic.enrolled_learners}</span>
              </dd>
            </div>
            <div>
              <dt className="text-ctText-muted">Wrong answers (recent)</dt>
              <dd className="text-lg font-extrabold text-ctText-primary">
                {topic.recent_failed_attempts}
                <span className="text-xs font-semibold text-ctText-muted"> by {plural(topic.recent_learners_with_failed_attempts, 'learner')}</span>
              </dd>
            </div>
          </dl>
          <div className="mt-3 h-2 overflow-hidden rounded-full bg-surface-muted" aria-hidden>
            <motion.div className="h-full rounded-full bg-band-practice" initial={{ width: 0 }} animate={{ width: `${share * 100}%` }} transition={{ duration: 0.6 }} />
          </div>

          {topic.root_gap && (
            <p className="mt-3 flex items-start gap-2 text-xs text-ctText-body">
              <GitBranch size={14} className="mt-0.5 shrink-0 text-brand-500" aria-hidden />
              <span>
                {topic.root_gap.is_prerequisite ? (
                  <>
                    Likely root gap: <strong>{topic.root_gap.target_name}</strong>. {topic.root_gap.explanation}
                  </>
                ) : (
                  topic.root_gap.explanation
                )}
                {SHOW_DEMO_NOTICES && topic.root_gap.edge_provenance === 'ai_proposed_demo' && ' (Topic links are AI-proposed demo data.)'}
              </span>
            </p>
          )}
        </div>
        <div className="flex shrink-0 flex-row gap-2 sm:flex-col">
          <button type="button" className="btn btn-secondary btn-sm" onClick={() => setOpen((o) => !o)} aria-expanded={open}>
            <ChevronDown size={14} className={cx('transition-transform', open && 'rotate-180')} aria-hidden /> {open ? 'Hide warm-up' : 'View warm-up'}
          </button>
          <button
            type="button"
            className="btn btn-primary btn-sm"
            onClick={start}
            disabled={!cyclesEnabled || openCycle.isPending}
            title={cyclesEnabled ? undefined : 'Saving cycles awaits approval of the database migration'}
          >
            <Play size={14} aria-hidden /> {openCycle.isPending ? 'Opening…' : 'Plan this Bell Ringer'}
          </button>
        </div>
      </div>
      {!cyclesEnabled && (
        <p className="border-t border-surface-border-subtle bg-surface-subtle px-5 py-2 text-2xs text-ctText-muted">
          You can view and use this warm-up. Saving it as a tracked cycle is not switched on yet.
        </p>
      )}
      {openCycle.error ? (
        <div className="px-5 pb-4">
          <ErrorState error={openCycle.error} compact feature="Saving Bell Ringer cycles" />
        </div>
      ) : null}
      <AnimatePresence initial={false}>
        {open && topic.activity && (
          <motion.div initial={{ height: 0, opacity: 0 }} animate={{ height: 'auto', opacity: 1 }} exit={{ height: 0, opacity: 0 }} className="overflow-hidden">
            <div className="border-t border-surface-border bg-surface-subtle p-5">
              <div className="mb-3 flex items-center gap-2 text-sm font-bold text-ctText-primary">
                <Users size={16} className="text-brand-500" aria-hidden /> Five-minute warm-up for {topic.root_gap?.target_name ?? topic.name}
              </div>
              <WarmUp card={topic.activity} demo={demo} />
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </motion.article>
  );
};

export function isFeatureOff(err: unknown) {
  return err instanceof ApiError && err.isFeatureDisabled;
}
