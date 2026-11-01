import React, { useEffect, useRef, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { AnimatePresence, motion } from 'framer-motion';
import { useQueryClient } from '@tanstack/react-query';
import { BookMarked, HelpCircle, History, Lightbulb, MessageCircle, Plus, Send, ShieldCheck, X } from 'lucide-react';
import { keys, useCatalog, useConversations, useTopic } from '@/api/hooks';
import { student } from '@/api/endpoints';
import { ApiError } from '@/api/http';
import type { Citation, DoubtResponse } from '@/api/types';
import { relative } from '@/lib/format';
import { subjectMeta } from '@/lib/subjects';
import { Card, cx, Notice, PageHeader, Pill } from '@/components/ui/primitives';
import { ErrorState } from '@/components/ui/states';
import { ease } from '@/components/ui/motion';

interface Turn {
  id: string;
  role: 'student' | 'tutor';
  text: string;
  mode?: 'explanation' | 'hint';
  response?: DoubtResponse;
  error?: unknown;
  citations?: Citation[];
  grounding?: 'grounded' | 'abstained' | null;
}

const ABSTAIN_TITLE: Record<string, string> = {
  insufficient_evidence: "I couldn't find this in your course material",
  not_authorized: 'That is outside your class material',
  model_unavailable: 'Buddy is not available right now',
  model_timeout: 'Buddy took too long to answer',
  invalid_model_output: "Buddy's answer did not pass its checks",
};

/** Renders **bold** from model text as <strong>; everything else stays plain text (no HTML). */
const Rich: React.FC<{ text: string }> = ({ text }) => (
  <>
    {text.split(/(\*\*[^*]+\*\*)/g).map((part, i) =>
      part.startsWith('**') && part.endsWith('**') ? <strong key={i} className="font-semibold text-ctText-primary">{part.slice(2, -2)}</strong> : <React.Fragment key={i}>{part}</React.Fragment>
    )}
  </>
);

const Citations: React.FC<{ items: Citation[] }> = ({ items }) =>
  items.length ? (
    <div className="mt-3 border-t border-surface-border-subtle pt-3">
      <p className="flex items-center gap-1.5 text-2xs font-bold uppercase tracking-wider text-ctText-muted">
        <BookMarked size={12} aria-hidden /> Sources
      </p>
      <ol className="mt-1.5 space-y-1">
        {items.map((c, i) => (
          <motion.li
            key={`${c.source_id}-${c.pdf_page_index}-${i}`}
            initial={{ opacity: 0, x: -6 }}
            animate={{ opacity: 1, x: 0, transition: { delay: 0.1 + i * 0.06 } }}
            className="flex gap-2 text-xs text-ctText-body"
          >
            <span className="flex h-5 min-w-[1.75rem] shrink-0 items-center justify-center rounded-md bg-brand-50 px-1 text-2xs font-bold text-brand-700">{c.label || i + 1}</span>
            <span>
              {c.item_title ?? 'Course material'}
              {c.printed_page_label ? `, page ${c.printed_page_label}` : c.pdf_page_index != null ? `, PDF page ${c.pdf_page_index + 1}` : ''}
            </span>
          </motion.li>
        ))}
      </ol>
    </div>
  ) : null;

const TutorBubble: React.FC<{ turn: Turn }> = ({ turn }) => {
  if (turn.error) {
    return <ErrorState error={turn.error} compact className="text-left" />;
  }
  const r = turn.response;
  const grounded = r ? r.grounding === 'grounded' : turn.grounding === 'grounded';
  if (!grounded) {
    return (
      <div className="rounded-2xl rounded-tl-md border border-amber-200 bg-amber-50 p-4">
        <p className="flex items-center gap-2 text-sm font-bold text-amber-800">
          <HelpCircle size={16} aria-hidden /> {(r && ABSTAIN_TITLE[r.status]) || 'Buddy could not answer this'}
        </p>
        <p className="mt-1 text-sm text-amber-900/90">{r?.message ?? turn.text}</p>
        <p className="mt-2 text-xs text-amber-900/70">Try rephrasing, pick the subject, or ask your teacher.</p>
      </div>
    );
  }
  return (
    <div className="rounded-2xl rounded-tl-md border border-surface-border bg-white p-4 shadow-card">
      <Pill tone="success" icon={<ShieldCheck size={12} />}>
        Answer built from your course material
      </Pill>
      {r ? (
        <div className="mt-3 space-y-3 text-sm leading-relaxed text-ctText-body">
          {r.concept && <p className="font-semibold text-ctText-primary">{r.concept}</p>}
          {r.hint && <p className="whitespace-pre-line"><Rich text={r.hint} /></p>}
          {r.explanation && <p className="whitespace-pre-line"><Rich text={r.explanation} /></p>}
          {r.steps.length > 0 && (
            <ol className="space-y-1.5">
              {r.steps.map((s, i) => (
                <li key={i} className="flex gap-2.5 rounded-xl bg-surface-subtle px-3 py-2">
                  <span className="font-bold text-brand-600">{i + 1}.</span>
                  <span className="whitespace-pre-line"><Rich text={s} /></span>
                </li>
              ))}
            </ol>
          )}
        </div>
      ) : (
        <p className="mt-3 whitespace-pre-line text-sm leading-relaxed text-ctText-body"><Rich text={turn.text} /></p>
      )}
      <Citations items={r?.citations ?? turn.citations ?? []} />
    </div>
  );
};

export const StudentBuddy: React.FC = () => {
  const [params, setParams] = useSearchParams();
  const kcId = params.get('kc') ?? '';
  const topic = useTopic(kcId);
  const catalog = useCatalog();
  const qc = useQueryClient();
  const [subject, setSubject] = useState(params.get('subject') ?? '');
  const [mode, setMode] = useState<'explanation' | 'hint'>('explanation');
  const [draft, setDraft] = useState('');
  const [turns, setTurns] = useState<Turn[]>([]);
  const [conversationId, setConversationId] = useState<string | null>(null);
  const [pending, setPending] = useState(false);
  const history = useConversations();
  const historyOff = history.error instanceof ApiError && history.error.isFeatureDisabled;
  const endRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' });
  }, [turns, pending]);

  const ask = async (e?: React.FormEvent) => {
    e?.preventDefault();
    const text = draft.trim();
    if (text.length < 5 || pending) return;
    setDraft('');
    const id = `${Date.now()}`;
    setTurns((t) => [...t, { id: `s-${id}`, role: 'student', text, mode }]);
    setPending(true);
    try {
      const response = await student.ask({
        question: text,
        mode,
        kc_id: kcId || undefined,
        subject_id: subject || topic.data?.subject_id || undefined,
        conversation_id: conversationId ?? undefined,
      });
      if (response.conversation_id) setConversationId(response.conversation_id);
      setTurns((t) => [...t, { id: `t-${id}`, role: 'tutor', text: response.message, response }]);
      if (response.conversation_id) qc.invalidateQueries({ queryKey: keys.conversations });
    } catch (err) {
      setTurns((t) => [...t, { id: `t-${id}`, role: 'tutor', text: '', error: err }]);
    } finally {
      setPending(false);
    }
  };

  const openConversation = async (id: string) => {
    try {
      const c = await student.conversation(id);
      setConversationId(c.conversation_id);
      setTurns(
        c.messages.map((m) => ({
          id: `${c.conversation_id}-${m.seq}`,
          role: m.role,
          text: m.content,
          citations: m.citations,
          grounding: m.grounding,
        }))
      );
    } catch (err) {
      setTurns([{ id: 'err', role: 'tutor', text: '', error: err }]);
    }
  };

  const newChat = () => {
    setTurns([]);
    setConversationId(null);
  };

  const subjects = catalog.data?.subjects ?? [];

  return (
    <div>
      <PageHeader
        title="Buddy"
        subtitle="Ask a doubt in your own words. Buddy answers only from your course material and shows where the answer came from."
        actions={
          <button type="button" className="btn btn-secondary" onClick={newChat}>
            <Plus size={15} aria-hidden /> New chat
          </button>
        }
      />
      <div className="grid grid-cols-1 gap-5 lg:grid-cols-[1fr_300px]">
        <Card pad={false} className="flex min-h-[520px] flex-col">
          <div className="flex flex-wrap items-center gap-2 border-b border-surface-border px-4 py-3 sm:px-5">
            {kcId && topic.data ? (
              <span className="pill bg-brand-50 py-1 text-xs text-brand-700 ring-1 ring-inset ring-brand-100">
                Topic: {topic.data.name}
                <button
                  type="button"
                  className="ml-1 rounded-full p-0.5 hover:bg-brand-100 focus-ring"
                  aria-label="Clear topic"
                  onClick={() => {
                    params.delete('kc');
                    setParams(params, { replace: true });
                  }}
                >
                  <X size={12} />
                </button>
              </span>
            ) : (
              <label className="flex items-center gap-2 text-xs font-semibold text-ctText-muted">
                Subject
                <select className="field-select h-8 text-xs" value={subject} onChange={(e) => setSubject(e.target.value)}>
                  <option value="">Any subject</option>
                  {subjects.map((s) => (
                    <option key={s.subject_id} value={s.subject_id}>
                      {subjectMeta(s.subject_id).name}
                    </option>
                  ))}
                </select>
              </label>
            )}
            <div role="radiogroup" aria-label="Answer style" className="ml-auto flex rounded-lg bg-surface-muted p-0.5">
              {(['explanation', 'hint'] as const).map((m) => (
                <button
                  key={m}
                  type="button"
                  role="radio"
                  aria-checked={mode === m}
                  onClick={() => setMode(m)}
                  className={cx('flex h-7 items-center gap-1 rounded-md px-2.5 text-xs font-semibold focus-ring', mode === m ? 'bg-white text-brand-700 shadow-sm' : 'text-ctText-muted')}
                >
                  {m === 'hint' ? <Lightbulb size={12} /> : <MessageCircle size={12} />}
                  {m === 'hint' ? 'Just a hint' : 'Explain'}
                </button>
              ))}
            </div>
          </div>

          <div className="flex-1 space-y-4 overflow-y-auto px-4 py-5 sm:px-5" aria-live="polite">
            {turns.length === 0 && !pending && (
              <div className="mx-auto max-w-sm py-10 text-center">
                <div className="mx-auto mb-3 flex h-12 w-12 items-center justify-center rounded-2xl bg-brand-50 text-brand-600">
                  <MessageCircle size={22} aria-hidden />
                </div>
                <p className="t-card">What would you like to understand?</p>
                <p className="mt-1 text-sm text-ctText-muted">For example: “Why do we take one factor from each group of three when finding a cube root?”</p>
              </div>
            )}
            <AnimatePresence initial={false}>
              {turns.map((turn) => (
                <motion.div
                  key={turn.id}
                  initial={{ opacity: 0, y: 10 }}
                  animate={{ opacity: 1, y: 0, transition: { duration: 0.28, ease } }}
                  className={cx('flex', turn.role === 'student' ? 'justify-end' : 'justify-start')}
                >
                  {turn.role === 'student' ? (
                    <div className="max-w-[85%] rounded-2xl rounded-tr-md bg-brand-500 px-4 py-2.5 text-sm text-white">
                      {turn.mode === 'hint' && <span className="mb-0.5 block text-2xs font-bold uppercase tracking-wider text-white/75">Hint please</span>}
                      {turn.text}
                    </div>
                  ) : (
                    <div className="w-full max-w-[92%]">
                      <TutorBubble turn={turn} />
                    </div>
                  )}
                </motion.div>
              ))}
            </AnimatePresence>
            {pending && (
              <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} className="flex items-center gap-3 rounded-2xl border border-surface-border bg-surface-subtle p-4 text-sm text-ctText-muted" role="status">
                <span className="flex gap-1" aria-hidden>
                  {[0, 1, 2].map((i) => (
                    <motion.span key={i} className="h-2 w-2 rounded-full bg-brand-400" animate={{ y: [0, -4, 0] }} transition={{ repeat: Infinity, duration: 0.9, delay: i * 0.15 }} />
                  ))}
                </span>
                Buddy is reading your course material. This can take up to a minute.
              </motion.div>
            )}
            <div ref={endRef} />
          </div>

          <form onSubmit={ask} className="border-t border-surface-border p-3 sm:p-4">
            <label htmlFor="doubt" className="sr-only">
              Your question
            </label>
            <div className="flex items-end gap-2">
              <textarea
                id="doubt"
                rows={2}
                maxLength={1000}
                value={draft}
                onChange={(e) => setDraft(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter' && !e.shiftKey) ask(e);
                }}
                placeholder="Type your question… (never share your PIN)"
                className="field h-auto min-h-[48px] resize-none py-3"
              />
              <button type="submit" className="btn btn-primary h-12 w-12 shrink-0 px-0" disabled={pending || draft.trim().length < 5} aria-label="Send question">
                <Send size={17} />
              </button>
            </div>
            <p className="mt-1.5 text-2xs text-ctText-subtle">Buddy can be wrong. It only explains — it never marks your answers or changes your progress.</p>
          </form>
        </Card>

        <aside className="space-y-4">
          <Card>
            <h2 className="t-card flex items-center gap-2">
              <History size={16} className="text-brand-500" aria-hidden /> Earlier chats
            </h2>
            {historyOff ? (
              <p className="mt-2 text-sm text-ctText-muted">Saved chat history is not switched on at your school yet. Each question is answered on its own.</p>
            ) : history.isLoading ? (
              <p className="mt-2 text-sm text-ctText-muted">Loading…</p>
            ) : history.error ? (
              <ErrorState error={history.error} compact className="mt-3" onRetry={() => history.refetch()} />
            ) : history.data?.conversations.length ? (
              <ul className="mt-3 space-y-1.5">
                {history.data.conversations.map((c) => (
                  <li key={c.conversation_id}>
                    <button
                      type="button"
                      onClick={() => openConversation(c.conversation_id)}
                      className={cx(
                        'w-full rounded-xl px-3 py-2 text-left text-sm hover:bg-surface-subtle focus-ring',
                        conversationId === c.conversation_id && 'bg-brand-50 text-brand-700'
                      )}
                    >
                      <span className="block font-semibold">{c.subject_id ? subjectMeta(c.subject_id).name : 'General'}</span>
                      <span className="text-xs text-ctText-muted">{relative(c.updated_at)}</span>
                    </button>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="mt-2 text-sm text-ctText-muted">No saved chats yet.</p>
            )}
          </Card>
          <Notice>
            Buddy uses a local AI model (no cloud service) and answers only from stored pages it can cite. If it cannot find
            enough, it says so instead of guessing.
          </Notice>
        </aside>
      </div>
    </div>
  );
};

export default StudentBuddy;
