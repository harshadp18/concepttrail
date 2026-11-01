import React from 'react';
import { Link } from 'react-router-dom';
import { motion } from 'framer-motion';
import { RotateCcw } from 'lucide-react';
import { useRetryList } from '@/api/hooks';
import { relative } from '@/lib/format';
import { PageHeader, Pill } from '@/components/ui/primitives';
import { EmptyState, QueryView } from '@/components/ui/states';
import { fadeUp, stagger } from '@/components/ui/motion';

const TYPE: Record<string, string> = {
  single_choice: 'Single choice',
  multiple_select: 'Multiple select',
  true_false: 'True or false',
  numeric: 'Numeric',
};

export const StudentReview: React.FC = () => {
  const retry = useRetryList();
  return (
    <div>
      <PageHeader
        title="Retry wrong answers"
        subtitle="Questions whose most recent answer was not correct. A fresh attempt is scored and saved like any other."
        crumbs={[{ label: 'Next steps', to: '/student/recommendations' }, { label: 'Retry' }]}
      />
      <QueryView query={retry}>
        {(r) =>
          r.questions.length === 0 ? (
            <EmptyState title="Nothing to retry" body="When you answer a question incorrectly, it waits here until you get it right." />
          ) : (
            <motion.ul initial="hidden" animate="show" variants={stagger(0.05)} className="space-y-3">
              {r.questions.map((q) => {
                const kc = q.kc_ids[0];
                return (
                  <motion.li key={q.question_id} variants={fadeUp} className="card flex flex-col gap-3 p-4 sm:flex-row sm:items-center sm:p-5">
                    <div className="min-w-0 flex-1">
                      <div className="mb-1.5 flex flex-wrap gap-2">
                        <Pill>{TYPE[q.item_type] ?? q.item_type}</Pill>
                        <Pill tone="warning">Last tried {relative(q.last_attempted_at).toLowerCase()}</Pill>
                      </div>
                      <p className="text-sm font-semibold leading-snug text-ctText-primary">{q.stem}</p>
                    </div>
                    {kc ? (
                      <Link
                        to={`/student/topics/${encodeURIComponent(kc)}/practice?start=${encodeURIComponent(q.question_id)}`}
                        className="btn btn-primary btn-sm shrink-0"
                      >
                        <RotateCcw size={14} aria-hidden /> Retry
                      </Link>
                    ) : (
                      <span className="text-xs text-ctText-muted">Topic unavailable</span>
                    )}
                  </motion.li>
                );
              })}
            </motion.ul>
          )
        }
      </QueryView>
    </div>
  );
};

export default StudentReview;
