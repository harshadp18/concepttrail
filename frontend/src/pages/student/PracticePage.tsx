import React, { useMemo, useRef, useState } from 'react';
import { Link, useParams, useSearchParams } from 'react-router-dom';
import { AnimatePresence, motion } from 'framer-motion';
import confetti from 'canvas-confetti';
import { ArrowRight, Check, CheckCircle2, Lightbulb, RotateCcw, Trophy, X, XCircle } from 'lucide-react';
import { useQuestions, useStudentProgress, useSubmitAttempt, useTopic } from '@/api/hooks';
import { student } from '@/api/endpoints';
import { ApiError } from '@/api/http';
import type { AttemptResult, DeliveredQuestion, DoubtResponse, SubmittedAnswer } from '@/api/types';
import { subjectMeta } from '@/lib/subjects';
import { newIdempotencyKey, pct } from '@/lib/format';
import { Card, cx, EstimateNote, MasteryBar, PageHeader, Pill } from '@/components/ui/primitives';
import { EmptyState, ErrorState, QueryView } from '@/components/ui/states';
import { ease } from '@/components/ui/motion';

const SET_SIZE = 5;
const LETTERS = 'ABCDEFGH';

interface Outcome {
  result: AttemptResult;
  before: number | null;
}

function answerFor(q: DeliveredQuestion, picked: string[], numeric: string): SubmittedAnswer | null {
  if (q.answer_shape === 'option_keys') return picked.length ? { option_keys: picked } : null;
  if (q.answer_shape === 'value') {
    const v = Number(numeric.replace(',', '.'));
    return numeric.trim() !== '' && Number.isFinite(v) ? { value: v } : null;
  }
  return picked[0] ? { option_key: picked[0] } : null;
}

const HintPanel: React.FC<{ state: { loading: boolean; data?: DoubtResponse; error?: unknown } }> = ({ state }) => (
  <motion.div
    initial={{ opacity: 0, height: 0 }}
    animate={{ opacity: 1, height: 'auto' }}
    className="overflow-hidden"
  >
    <div className="mt-4 rounded-2xl border border-amber-200 bg-amber-50 p-4 text-sm" aria-live="polite">
      <p className="flex items-center gap-2 font-bold text-amber-800">
        <Lightbulb size={16} aria-hidden /> Hint from Buddy
      </p>
      {state.loading && <p className="mt-2 text-amber-900/80">Buddy is looking through your course material… this can take a little while.</p>}
      {state.error ? <p className="mt-2 text-amber-900/80">{state.error instanceof ApiError ? state.error.message : 'Buddy could not answer right now.'}</p> : null}
      {state.data &&
        (state.data.grounding === 'grounded' ? (
          <>
            <p className="mt-2 whitespace-pre-line text-ctText-body">{state.data.hint || state.data.explanation}</p>
            {state.data.citations.length > 0 && (
              <p className="mt-2 text-2xs text-ctText-muted">Source: {state.data.citations.map((c) => c.label).join('; ')}</p>
            )}
          </>
        ) : (
          <p className="mt-2 text-amber-900/80">{state.data.message}</p>
        ))}
    </div>
  </motion.div>
);

export const PracticePage: React.FC = () => {
  const { kcId = '' } = useParams();
  const [params] = useSearchParams();
  const topic = useTopic(kcId);
  const questions = useQuestions(kcId);
  const submit = useSubmitAttempt();
  const progress = useStudentProgress();
  const initial = progress.data?.mastery_estimates.find((m) => m.kc_id === kcId)?.mastery_probability ?? null;

  const set = useMemo(() => {
    const all = questions.data?.questions ?? [];
    const start = params.get('start');
    const first = all.find((q) => q.question_id === start);
    return (first ? [first, ...all.filter((q) => q !== first)] : all).slice(0, SET_SIZE);
  }, [questions.data, params]);

  const [index, setIndex] = useState(0);
  const [picked, setPicked] = useState<string[]>([]);
  const [numeric, setNumeric] = useState('');
  const [outcomes, setOutcomes] = useState<Record<number, Outcome>>({});
  const [hint, setHint] = useState<{ loading: boolean; data?: DoubtResponse; error?: unknown } | null>(null);
  const [error, setError] = useState<unknown>(null);
  const keyRef = useRef<string>(newIdempotencyKey('web'));
  const masteryRef = useRef<number | null>(null);
  const [done, setDone] = useState(false);

  const q = set[index];
  const outcome = outcomes[index];
  const s = subjectMeta(topic.data?.subject_id);

  const reset = (next: number) => {
    setIndex(next);
    setPicked([]);
    setNumeric('');
    setHint(null);
    setError(null);
    keyRef.current = newIdempotencyKey('web');
  };

  const toggle = (key: string) => {
    if (outcome) return;
    if (q.answer_shape === 'option_keys') setPicked((p) => (p.includes(key) ? p.filter((k) => k !== key) : [...p, key]));
    else setPicked([key]);
  };

  const onSubmit = async () => {
    const answer = answerFor(q, picked, numeric);
    if (!answer) return;
    setError(null);
    try {
      const result = await submit.mutateAsync({
        question_id: q.question_id,
        question_version: q.version,
        submitted_answer: answer,
        hint_tier: hint ? 1 : 0,
        idempotency_key: keyRef.current, // a network retry replays this key; the server never double-counts
      });
      const before = masteryRef.current ?? initial;
      if (result.bkt.mastery_probability != null) masteryRef.current = result.bkt.mastery_probability;
      setOutcomes((o) => ({ ...o, [index]: { result, before } }));
      const crossed = (before ?? 0) < 0.95 && (result.bkt.mastery_probability ?? 0) >= 0.95;
      if (crossed && !window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
        confetti({ particleCount: 70, spread: 60, origin: { y: 0.7 }, colors: ['#287A9F', '#FFD016', '#15803D'] });
      }
    } catch (err) {
      setError(err);
    }
  };

  const retry = () => {
    // a new attempt at the same question gets a new key: it is genuinely a second answer
    setOutcomes((o) => {
      const copy = { ...o };
      delete copy[index];
      return copy;
    });
    setPicked([]);
    setNumeric('');
    keyRef.current = newIdempotencyKey('web');
  };

  const askHint = async () => {
    setHint({ loading: true });
    try {
      const data = await student.ask({
        question: (q.stem ?? '').slice(0, 1000), // mode "hint" asks for a nudge, not the answer
        mode: 'hint',
        kc_id: kcId,
        subject_id: topic.data?.subject_id ?? undefined,
      });
      setHint({ loading: false, data });
    } catch (err) {
      setHint({ loading: false, error: err });
    }
  };

  const answered = Object.values(outcomes);
  const correct = answered.filter((o) => o.result.scored_correct).length;
  const lastMastery = masteryRef.current ?? initial;
  const chapter = topic.data?.curriculum_mappings[0];

  return (
    <div>
      <PageHeader
        eyebrow={`${s.name} · Practice`}
        title={topic.data?.name ?? 'Practice'}
        crumbs={[
          { label: s.name, to: `/student/subjects/${topic.data?.subject_id ?? ''}` },
          ...(chapter ? [{ label: chapter.item_title ?? 'Chapter', to: `/student/chapters/${encodeURIComponent(chapter.item_id)}` }] : []),
          { label: 'Practice' },
        ]}
        actions={
          <Link to={`/student/topics/${encodeURIComponent(kcId)}`} className="btn btn-ghost btn-sm">
            <X size={14} aria-hidden /> Exit practice
          </Link>
        }
      />
      <QueryView query={questions}>
        {() =>
          !set.length ? (
            <EmptyState title="No practice questions for this topic yet" body="Try another topic in this chapter, or ask Buddy about it." />
          ) : done ? (
            <motion.div initial={{ opacity: 0, scale: 0.98 }} animate={{ opacity: 1, scale: 1, transition: { duration: 0.35, ease } }}>
              <Card className="text-center">
                <div className="mx-auto mb-3 flex h-14 w-14 items-center justify-center rounded-2xl bg-band-mastered-bg text-band-mastered">
                  <Trophy size={26} aria-hidden />
                </div>
                <p className="t-eyebrow text-brand-600">Set complete</p>
                <h2 className="mt-1 text-3xl font-extrabold text-ctText-primary">
                  {correct} / {answered.length} correct
                </h2>
                <p className="mt-1 text-sm text-ctText-muted">Your answers were scored and saved. Your estimate for this topic is updated.</p>
                <div className="mx-auto mt-5 max-w-sm text-left">
                  <MasteryBar p={lastMastery} fill={s.bar} label="Estimated mastery now" height="h-2.5" />
                </div>
                <div className="mt-6 flex flex-wrap justify-center gap-2">
                  <Link to="/student/recommendations" className="btn btn-primary">
                    See my next step <ArrowRight size={15} aria-hidden />
                  </Link>
                  <Link to="/student/review" className="btn btn-secondary">
                    Retry wrong answers
                  </Link>
                  {chapter && (
                    <Link to={`/student/chapters/${encodeURIComponent(chapter.item_id)}`} className="btn btn-ghost">
                      Back to chapter
                    </Link>
                  )}
                </div>
                <EstimateNote className="mt-5" />
              </Card>
            </motion.div>
          ) : (
            <div className="grid grid-cols-1 gap-5 lg:grid-cols-3">
              <div className="lg:col-span-2">
                <div className="mb-3 flex items-center justify-between text-xs font-semibold text-ctText-muted">
                  <span>
                    Question {index + 1} of {set.length}
                  </span>
                  <span>{q.item_type === 'multiple_select' ? 'Choose all that apply' : q.answer_shape === 'value' ? 'Type a number' : 'Choose one answer'}</span>
                </div>
                <div className="mb-4 grid gap-1.5" style={{ gridTemplateColumns: `repeat(${set.length}, minmax(0,1fr))` }} aria-hidden>
                  {set.map((_, i) => (
                    <div key={i} className="h-1.5 overflow-hidden rounded-full bg-surface-muted">
                      <motion.div
                        className={cx('h-full', outcomes[i] ? (outcomes[i].result.scored_correct ? 'bg-band-mastered' : 'bg-band-practice') : 'bg-brand-400')}
                        initial={{ width: 0 }}
                        animate={{ width: outcomes[i] || i === index ? '100%' : '0%' }}
                        transition={{ duration: 0.35 }}
                      />
                    </div>
                  ))}
                </div>
                <AnimatePresence mode="wait">
                  <motion.div
                    key={q.question_id}
                    initial={{ opacity: 0, x: 16 }}
                    animate={{ opacity: 1, x: 0, transition: { duration: 0.28, ease } }}
                    exit={{ opacity: 0, x: -16, transition: { duration: 0.15 } }}
                  >
                    <Card>
                      <h2 className="text-lg font-bold leading-snug text-ctText-primary" id="q-stem">
                        {q.stem}
                      </h2>
                      {q.answer_shape === 'value' ? (
                        <div className="mt-5 max-w-xs">
                          <label htmlFor="numeric" className="field-label">
                            Your answer
                          </label>
                          <input
                            id="numeric"
                            inputMode="decimal"
                            className="field"
                            value={numeric}
                            disabled={!!outcome}
                            onChange={(e) => setNumeric(e.target.value)}
                          />
                        </div>
                      ) : (
                        <div role={q.answer_shape === 'option_keys' ? 'group' : 'radiogroup'} aria-labelledby="q-stem" className="mt-5 space-y-2.5">
                          {[...q.options]
                            .sort((a, b) => a.display_order - b.display_order)
                            .map((o, i) => {
                              const selected = picked.includes(o.option_key);
                              const graded = outcome && selected;
                              return (
                                <motion.button
                                  key={o.option_key}
                                  type="button"
                                  role={q.answer_shape === 'option_keys' ? 'checkbox' : 'radio'}
                                  aria-checked={selected}
                                  disabled={!!outcome}
                                  onClick={() => toggle(o.option_key)}
                                  whileTap={{ scale: 0.99 }}
                                  className={cx(
                                    'flex w-full items-center gap-3 rounded-2xl border-2 p-3.5 text-left text-sm transition-colors focus-ring',
                                    graded
                                      ? outcome.result.scored_correct
                                        ? 'border-band-mastered bg-band-mastered-bg'
                                        : 'border-band-practice bg-band-practice-bg'
                                      : selected
                                        ? 'border-brand-500 bg-brand-50'
                                        : 'border-surface-border bg-white hover:border-brand-200 hover:bg-surface-subtle',
                                    outcome && !selected && 'opacity-60'
                                  )}
                                >
                                  <span
                                    className={cx(
                                      'flex h-7 w-7 shrink-0 items-center justify-center rounded-full text-xs font-bold',
                                      selected ? 'bg-brand-500 text-white' : 'bg-surface-muted text-ctText-muted'
                                    )}
                                  >
                                    {q.answer_shape === 'option_keys' && selected ? <Check size={14} /> : LETTERS[i]}
                                  </span>
                                  <span className="min-w-0 flex-1 font-medium text-ctText-primary">{o.option_text}</span>
                                </motion.button>
                              );
                            })}
                        </div>
                      )}

                      <AnimatePresence>
                        {outcome && (
                          <motion.div
                            initial={{ opacity: 0, y: 8 }}
                            animate={{ opacity: 1, y: 0, transition: { duration: 0.3, ease } }}
                            className={cx(
                              'mt-5 flex items-start gap-3 rounded-2xl border p-4',
                              outcome.result.scored_correct ? 'border-feedback-success-border bg-feedback-success-bg' : 'border-feedback-warning-border bg-feedback-warning-bg'
                            )}
                            role="status"
                          >
                            {outcome.result.scored_correct ? (
                              <CheckCircle2 className="mt-0.5 shrink-0 text-feedback-success" size={20} aria-hidden />
                            ) : (
                              <XCircle className="mt-0.5 shrink-0 text-feedback-warning" size={20} aria-hidden />
                            )}
                            <div className="text-sm">
                              <p className={cx('font-bold', outcome.result.scored_correct ? 'text-feedback-success' : 'text-feedback-warning')}>
                                {outcome.result.scored_correct ? 'Correct — well done!' : 'Not quite this time.'}
                              </p>
                              <p className="mt-0.5 text-ctText-body">
                                {outcome.result.bkt.mastery_probability != null
                                  ? `Your estimate for this topic is now ${pct(outcome.result.bkt.mastery_probability)}${
                                      outcome.before != null ? ` (was ${pct(outcome.before)})` : ''
                                    }.`
                                  : 'Your answer was saved.'}
                                {!outcome.result.scored_correct && ' Try again, or ask Buddy for a hint.'}
                              </p>
                              {outcome.result.duplicate_replay && <p className="mt-1 text-2xs text-ctText-muted">This answer had already been saved.</p>}
                            </div>
                          </motion.div>
                        )}
                      </AnimatePresence>

                      {hint && <HintPanel state={hint} />}
                      {error ? <ErrorState error={error} compact className="mt-4" onRetry={onSubmit} /> : null}

                      <div className="mt-6 flex flex-wrap items-center justify-between gap-3 border-t border-surface-border-subtle pt-5">
                        <button type="button" onClick={askHint} disabled={!!outcome || hint?.loading || !!hint} className="btn btn-ghost btn-sm">
                          <Lightbulb size={15} aria-hidden /> {hint ? 'Hint requested' : 'Ask Buddy for a hint'}
                        </button>
                        <div className="flex flex-wrap gap-2">
                          {!outcome ? (
                            <>
                              {index < set.length - 1 && (
                                <button type="button" className="btn btn-secondary" onClick={() => reset(index + 1)}>
                                  Skip for now
                                </button>
                              )}
                              <button
                                type="button"
                                className="btn btn-primary"
                                disabled={!answerFor(q, picked, numeric) || submit.isPending}
                                onClick={onSubmit}
                              >
                                {submit.isPending ? 'Checking…' : 'Submit answer'}
                              </button>
                            </>
                          ) : (
                            <>
                              {!outcome.result.scored_correct && (
                                <button type="button" className="btn btn-secondary" onClick={retry}>
                                  <RotateCcw size={15} aria-hidden /> Try again
                                </button>
                              )}
                              {index < set.length - 1 ? (
                                <button type="button" className="btn btn-primary" onClick={() => reset(index + 1)}>
                                  Next question <ArrowRight size={15} aria-hidden />
                                </button>
                              ) : (
                                <button type="button" className="btn btn-primary" onClick={() => setDone(true)}>
                                  See results <ArrowRight size={15} aria-hidden />
                                </button>
                              )}
                            </>
                          )}
                        </div>
                      </div>
                    </Card>
                  </motion.div>
                </AnimatePresence>
              </div>

              <aside className="space-y-4">
                <Card>
                  <h2 className="t-card">This set</h2>
                  <ol className="mt-3 space-y-2">
                    {set.map((item, i) => {
                      const o = outcomes[i];
                      return (
                        <li key={item.question_id} className={cx('flex items-center gap-2.5 rounded-xl p-2 text-sm', i === index && 'bg-brand-50')}>
                          <span
                            className={cx(
                              'flex h-6 w-6 shrink-0 items-center justify-center rounded-full text-2xs font-bold',
                              o ? (o.result.scored_correct ? 'bg-band-mastered text-white' : 'bg-band-practice text-white') : 'bg-surface-muted text-ctText-muted'
                            )}
                          >
                            {o ? o.result.scored_correct ? <Check size={12} /> : <X size={12} /> : i + 1}
                          </span>
                          <span className="min-w-0 flex-1 truncate text-ctText-body">{item.stem}</span>
                        </li>
                      );
                    })}
                  </ol>
                  <div className="mt-3 flex gap-2">
                    <Pill tone="success">{correct} correct</Pill>
                    <Pill tone="neutral">{answered.length - correct} to revisit</Pill>
                  </div>
                </Card>
                <Card>
                  <h2 className="t-card">Take your time</h2>
                  <p className="mt-1 text-sm text-ctText-muted">
                    Every answer is saved and updates your mastery estimate. Using a hint is fine — it is recorded so the estimate
                    stays fair.
                  </p>
                </Card>
              </aside>
            </div>
          )
        }
      </QueryView>
    </div>
  );
};

export default PracticePage;
