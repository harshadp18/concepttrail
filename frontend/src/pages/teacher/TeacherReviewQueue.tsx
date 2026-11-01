import React, { useEffect, useState } from 'react';
import { AnimatePresence, motion } from 'framer-motion';
import { Bot, CheckCircle2, ChevronLeft, ChevronRight, FileText, UserCheck } from 'lucide-react';
import { useReviewQueue, useSubmitReview } from '@/api/hooks';
import type { ReviewQuestion } from '@/api/types';
import { dateTime } from '@/lib/format';
import { Card, cx, Notice, PageHeader, Pill } from '@/components/ui/primitives';
import { EmptyState, ErrorState, QueryView } from '@/components/ui/states';

const LETTERS = 'ABCDEFGH';
const STATUS_LABEL: Record<string, string> = {
  demo_release: 'Demo (AI-drafted)',
  validated_draft: 'Validated draft',
  in_review: 'In review',
};
const DECISIONS = [
  { value: 'approved', label: 'Approve', hint: 'Correct and ready for learners.' },
  { value: 'revision_required', label: 'Needs revision', hint: 'Fixable problems; send back.' },
  { value: 'rejected', label: 'Reject', hint: 'Should not be used.' },
] as const;

const Detail: React.FC<{ q: ReviewQuestion }> = ({ q }) => {
  const [decision, setDecision] = useState<(typeof DECISIONS)[number]['value']>('revision_required');
  const [rationale, setRationale] = useState('');
  const submit = useSubmitReview();
  useEffect(() => {
    setRationale('');
    submit.reset();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [q.question_id]);

  return (
    <motion.div key={q.question_id} initial={{ opacity: 0, x: 12 }} animate={{ opacity: 1, x: 0 }} className="space-y-4">
      <Card>
        <div className="flex flex-wrap gap-2">
          <Pill tone={q.review_status === 'demo_release' ? 'gold' : 'brand'}>{STATUS_LABEL[q.review_status] ?? q.review_status}</Pill>
          {q.knowledge_components.map((k) => (
            <Pill key={k.kc_id}>{k.name}</Pill>
          ))}
        </div>
        <h2 className="mt-3 text-base font-bold leading-snug text-ctText-primary">{q.stem}</h2>
        <ul className="mt-3 space-y-1.5">
          {q.options.map((o, i) => (
            <li key={o.option_key} className={cx('rounded-xl border px-3 py-2 text-sm', o.is_correct ? 'border-feedback-success-border bg-feedback-success-bg' : 'border-surface-border')}>
              <span className="mr-2 font-bold">{LETTERS[i]}</span>
              {o.option_text}
              {o.is_correct && <span className="ml-2 text-xs font-bold text-feedback-success">Answer key</span>}
            </li>
          ))}
        </ul>
        {q.explanation && (
          <div className="mt-4 rounded-xl bg-surface-subtle p-3 text-sm">
            <p className="text-xs font-bold text-ctText-muted">Stored explanation</p>
            <p className="mt-1 whitespace-pre-line text-ctText-body">{q.explanation}</p>
          </div>
        )}
        {q.source_refs.length > 0 && (
          <p className="mt-3 flex items-center gap-1.5 text-xs text-ctText-muted">
            <FileText size={13} aria-hidden /> Sources: {q.source_refs.map((r) => `${r.source_id}${r.pdf_page_index != null ? ` p.${r.pdf_page_index + 1}` : ''}`).join(', ')}
          </p>
        )}
      </Card>
      {q.ai_review && (
        <Notice icon={<Bot size={14} />}>
          <strong>AI check (not a teacher review):</strong> {q.ai_review.verdict?.replace(/_/g, ' ')}
          {q.ai_review.note ? ` — ${q.ai_review.note}` : ''}
        </Notice>
      )}
      {q.human_reviews.length > 0 && (
        <Card>
          <h3 className="t-card flex items-center gap-2">
            <UserCheck size={16} aria-hidden /> Teacher reviews
          </h3>
          <ul className="mt-2 space-y-2 text-sm">
            {q.human_reviews.map((r, i) => (
              <li key={i} className="rounded-xl bg-surface-subtle p-3">
                <span className="font-semibold">{r.decision?.replace(/_/g, ' ')}</span>
                {r.reviewed_at && <span className="text-xs text-ctText-muted"> · {dateTime(r.reviewed_at)}</span>}
                {r.rationale && <p className="mt-1 text-ctText-body">{r.rationale}</p>}
              </li>
            ))}
          </ul>
        </Card>
      )}
      <Card>
        <form
          onSubmit={(e) => {
            e.preventDefault();
            submit.mutate({ questionId: q.question_id, decision, rationale: rationale.trim() });
          }}
        >
          <fieldset>
            <legend className="t-card">Your decision</legend>
            <div className="mt-3 grid grid-cols-1 gap-2 sm:grid-cols-3">
              {DECISIONS.map((d) => (
                <label key={d.value} className={cx('cursor-pointer rounded-xl border-2 p-3 text-sm', decision === d.value ? 'border-brand-500 bg-brand-50' : 'border-surface-border')}>
                  <input type="radio" name="decision" value={d.value} checked={decision === d.value} onChange={() => setDecision(d.value)} className="sr-only" />
                  <span className="block font-bold text-ctText-primary">{d.label}</span>
                  <span className="text-xs text-ctText-muted">{d.hint}</span>
                </label>
              ))}
            </div>
          </fieldset>
          <label htmlFor="rationale" className="field-label mt-4">
            Reason (recorded with your name)
          </label>
          <textarea id="rationale" required minLength={3} maxLength={2000} rows={3} className="field h-auto py-3" value={rationale} onChange={(e) => setRationale(e.target.value)} />
          <AnimatePresence>
            {submit.isSuccess && (
              <motion.p initial={{ opacity: 0 }} animate={{ opacity: 1 }} className="mt-3 flex items-center gap-2 text-sm font-semibold text-feedback-success" role="status">
                <CheckCircle2 size={16} aria-hidden /> Decision recorded. Status is now “{STATUS_LABEL[submit.data.review_status] ?? submit.data.review_status}”.
              </motion.p>
            )}
          </AnimatePresence>
          {submit.error ? <ErrorState error={submit.error} compact className="mt-3" /> : null}
          <button type="submit" className="btn btn-primary mt-4" disabled={submit.isPending || rationale.trim().length < 3}>
            {submit.isPending ? 'Recording…' : 'Record decision'}
          </button>
          {q.review_status === 'demo_release' && decision === 'approved' && (
            <p className="mt-2 text-xs text-ctText-muted">Demo questions must be re-validated before they can be approved; the server will refuse a direct approval.</p>
          )}
        </form>
      </Card>
    </motion.div>
  );
};

export const TeacherReviewQueue: React.FC = () => {
  const [status, setStatus] = useState<string>('');
  const [offset, setOffset] = useState(0);
  const queue = useReviewQueue(status || undefined, offset);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const selected = queue.data?.questions.find((q) => q.question_id === selectedId) ?? queue.data?.questions[0];

  return (
    <div>
      <PageHeader
        title="Question review"
        subtitle="Check AI-drafted questions for the class levels you teach. Your decision is recorded with your name; the AI check is shown separately."
        actions={
          <select
            aria-label="Filter by status"
            className="field-select"
            value={status}
            onChange={(e) => {
              setStatus(e.target.value);
              setOffset(0);
            }}
          >
            <option value="">All awaiting review</option>
            <option value="demo_release">Demo (AI-drafted)</option>
            <option value="validated_draft">Validated drafts</option>
            <option value="in_review">In review</option>
          </select>
        }
      />
      <QueryView query={queue}>
        {(data) =>
          data.count === 0 ? (
            <EmptyState title="Nothing waiting for review" />
          ) : (
            <div className="grid grid-cols-1 gap-5 lg:grid-cols-[minmax(0,2fr)_minmax(0,3fr)]">
              <Card pad={false} className="self-start">
                <ul className="max-h-[70vh] divide-y divide-surface-border-subtle overflow-y-auto">
                  {data.questions.map((q) => (
                    <li key={q.question_id}>
                      <button
                        type="button"
                        onClick={() => setSelectedId(q.question_id)}
                        aria-current={selected?.question_id === q.question_id}
                        className={cx('w-full px-4 py-3 text-left hover:bg-surface-subtle focus-ring', selected?.question_id === q.question_id && 'bg-brand-50')}
                      >
                        <span className="line-clamp-2 text-sm font-semibold text-ctText-primary">{q.stem}</span>
                        <span className="text-xs text-ctText-muted">
                          {q.knowledge_components[0]?.name ?? '—'} · {q.human_reviews.length ? `${q.human_reviews.length} review(s)` : 'Not yet reviewed'}
                        </span>
                      </button>
                    </li>
                  ))}
                </ul>
                <div className="flex items-center justify-between border-t border-surface-border px-4 py-2.5 text-xs text-ctText-muted">
                  <span>
                    {offset + 1}–{Math.min(offset + 20, data.count)} of {data.count}
                  </span>
                  <div className="flex gap-1.5">
                    <button type="button" className="btn btn-secondary btn-sm" aria-label="Previous page" disabled={offset === 0} onClick={() => setOffset(offset - 20)}>
                      <ChevronLeft size={14} />
                    </button>
                    <button type="button" className="btn btn-secondary btn-sm" aria-label="Next page" disabled={offset + 20 >= data.count} onClick={() => setOffset(offset + 20)}>
                      <ChevronRight size={14} />
                    </button>
                  </div>
                </div>
              </Card>
              {selected && <Detail q={selected} />}
            </div>
          )
        }
      </QueryView>
    </div>
  );
};

export default TeacherReviewQueue;
