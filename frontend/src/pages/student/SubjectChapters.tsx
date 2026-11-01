import React from 'react';
import { Link, useParams } from 'react-router-dom';
import { motion } from 'framer-motion';
import { ChevronRight } from 'lucide-react';
import { useChapterProgress, useCurriculum } from '@/api/hooks';
import { subjectMeta } from '@/lib/subjects';
import { plural } from '@/lib/format';
import { cx, DemoContentNotice, EstimateNote, MasteryBar, PageHeader, Pill } from '@/components/ui/primitives';
import { EmptyState, QueryView } from '@/components/ui/states';
import { fadeUp, stagger } from '@/components/ui/motion';

export const SubjectChapters: React.FC = () => {
  const { subjectId = '' } = useParams();
  const s = subjectMeta(subjectId);
  const curriculum = useCurriculum();
  const progress = useChapterProgress();
  const subjectProgress = progress.data?.subjects.find((x) => x.subject_id === subjectId);

  return (
    <div>
      <PageHeader
        title={s.name}
        subtitle={s.blurb}
        crumbs={[{ label: 'Subjects', to: '/student/subjects' }, { label: s.name }]}
      />
      <div className={cx('mb-6 flex flex-col gap-5 rounded-3xl border p-5 sm:flex-row sm:items-center sm:p-6', s.tint, s.ring)}>
        <img src={s.art} alt="" className="h-24 w-auto self-start sm:h-28" />
        <div className="min-w-0 flex-1">
          <p className={cx('t-eyebrow', s.ink)}>Your mastery in {s.name}</p>
          <div className="mt-2 max-w-md">
            <MasteryBar p={subjectProgress?.average_mastery_probability ?? null} fill={s.bar} height="h-2.5" showValue />
          </div>
          {subjectProgress && (
            <p className="mt-2 text-xs text-ctText-body">
              {subjectProgress.topics_mastered} of {plural(subjectProgress.topics_total, 'topic')} mastered ·{' '}
              {plural(subjectProgress.attempts, 'question')} answered
            </p>
          )}
        </div>
      </div>

      <QueryView query={curriculum}>
        {(data) => {
          const entries = data.curricula.filter((c) => c.subject.subject_id === subjectId);
          const items = entries.flatMap((e) => e.items.filter((i) => !i.parent_item_id));
          if (!items.length) {
            return <EmptyState title={`No ${s.name} chapters yet`} body="Chapters will appear here once they are available for your class." />;
          }
          const demo = entries.some((e) => e.coverage.state === 'demo_release');
          return (
            <>
              {demo && <DemoContentNotice className="mb-4" />}
              <h2 className="t-section mb-3">Chapters</h2>
              <motion.ul initial="hidden" animate="show" variants={stagger(0.05)} className="space-y-3">
                {items.map((item) => {
                  const row = progress.data?.chapters.find((c) => c.item_id === item.item_id);
                  return (
                    <motion.li key={item.item_id} variants={fadeUp}>
                      <Link
                        to={`/student/chapters/${encodeURIComponent(item.item_id)}`}
                        className="card card-hover flex flex-col gap-4 p-4 focus-ring sm:flex-row sm:items-center sm:p-5"
                      >
                        <div className="min-w-0 flex-1">
                          <p className={cx('t-eyebrow', s.ink)}>{item.sequence_label ?? 'Chapter'}</p>
                          <h3 className="t-card mt-0.5 break-words">{item.title}</h3>
                          <div className="mt-2 flex flex-wrap gap-2">
                            {row && <Pill tone="neutral">{plural(row.topics_total, 'topic')}</Pill>}
                            {row && row.topics_mastered > 0 && <Pill tone="success">{row.topics_mastered} mastered</Pill>}
                          </div>
                        </div>
                        <div className="w-full sm:w-56">
                          <MasteryBar p={row?.average_mastery_probability ?? null} fill={s.bar} label="Mastery" />
                        </div>
                        <ChevronRight className="hidden shrink-0 text-ctText-subtle sm:block" aria-hidden />
                      </Link>
                    </motion.li>
                  );
                })}
              </motion.ul>
              <EstimateNote className="mt-4" />
            </>
          );
        }}
      </QueryView>
    </div>
  );
};

export default SubjectChapters;
