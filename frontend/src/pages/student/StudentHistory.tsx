import React, { useState } from 'react';
import { CheckCircle2, ChevronLeft, ChevronRight, Lightbulb, XCircle } from 'lucide-react';
import { useActivity } from '@/api/hooks';
import { dateTime } from '@/lib/format';
import { Card, PageHeader } from '@/components/ui/primitives';
import { EmptyState, QueryView } from '@/components/ui/states';

const PAGE = 15;

export const StudentHistory: React.FC = () => {
  const [offset, setOffset] = useState(0);
  const activity = useActivity(PAGE, offset);
  return (
    <div>
      <PageHeader
        title="Learning history"
        subtitle="Every answer you have submitted, newest first."
        crumbs={[{ label: 'Progress', to: '/student/progress' }, { label: 'History' }]}
      />
      <QueryView query={activity}>
        {(page) =>
          page.count === 0 ? (
            <EmptyState title="No answers yet" body="Your practice history will build up here as you answer questions." />
          ) : (
            <Card pad={false}>
              <div className="overflow-x-auto">
                <table className="w-full min-w-[560px] text-sm">
                  <caption className="sr-only">Your answers, newest first</caption>
                  <thead>
                    <tr className="border-b border-surface-border text-left text-2xs font-bold uppercase tracking-wider text-ctText-muted">
                      <th scope="col" className="px-5 py-3">Question</th>
                      <th scope="col" className="px-4 py-3">Result</th>
                      <th scope="col" className="px-4 py-3">When</th>
                    </tr>
                  </thead>
                  <tbody>
                    {page.attempts.map((a) => (
                      <tr key={a.attempt_id} className="border-b border-surface-border-subtle last:border-0">
                        <td className="max-w-md px-5 py-3.5">
                          <p className="line-clamp-2 text-ctText-primary">{a.question_stem}</p>
                          {!!a.hint_tier && (
                            <p className="mt-0.5 flex items-center gap-1 text-2xs text-amber-700">
                              <Lightbulb size={11} aria-hidden /> Hint used
                            </p>
                          )}
                        </td>
                        <td className="whitespace-nowrap px-4 py-3.5">
                          {a.scored_correct ? (
                            <span className="inline-flex items-center gap-1.5 font-semibold text-feedback-success">
                              <CheckCircle2 size={15} aria-hidden /> Correct
                            </span>
                          ) : (
                            <span className="inline-flex items-center gap-1.5 font-semibold text-feedback-warning">
                              <XCircle size={15} aria-hidden /> Not correct
                            </span>
                          )}
                        </td>
                        <td className="whitespace-nowrap px-4 py-3.5 text-ctText-muted">{dateTime(a.attempted_at)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <div className="flex items-center justify-between gap-3 border-t border-surface-border px-5 py-3 text-xs text-ctText-muted">
                <span>
                  {offset + 1}–{Math.min(offset + PAGE, page.count)} of {page.count}
                </span>
                <div className="flex gap-2">
                  <button type="button" className="btn btn-secondary btn-sm" disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - PAGE))}>
                    <ChevronLeft size={14} aria-hidden /> Newer
                  </button>
                  <button type="button" className="btn btn-secondary btn-sm" disabled={offset + PAGE >= page.count} onClick={() => setOffset(offset + PAGE)}>
                    Older <ChevronRight size={14} aria-hidden />
                  </button>
                </div>
              </div>
            </Card>
          )
        }
      </QueryView>
    </div>
  );
};

export default StudentHistory;
