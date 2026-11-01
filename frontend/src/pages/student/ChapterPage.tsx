import React from 'react';
import { Link, useParams } from 'react-router-dom';
import { motion } from 'framer-motion';
import { ArrowRight, Layers } from 'lucide-react';
import { useChapter } from '@/api/hooks';
import { subjectMeta } from '@/lib/subjects';
import { plural } from '@/lib/format';
import { BandPill, cx, DemoContentNotice, EstimateNote, MasteryBar, PageHeader } from '@/components/ui/primitives';
import { EmptyState, QueryView } from '@/components/ui/states';
import { fadeUp, stagger } from '@/components/ui/motion';

const KC_TYPE: Record<string, string> = { concept: 'Concept', procedure: 'Skill', fact: 'Fact', skill: 'Skill' };

export const ChapterPage: React.FC = () => {
  const { itemId = '' } = useParams();
  const chapter = useChapter(itemId);
  return (
    <QueryView query={chapter}>
      {(c) => {
        const s = subjectMeta(c.subject_id);
        return (
          <div>
            <PageHeader
              eyebrow={`${s.name} · Class ${c.grade_level} · ${c.sequence_label ?? 'Chapter'}`}
              title={c.title}
              crumbs={[
                { label: 'Subjects', to: '/student/subjects' },
                { label: s.name, to: `/student/subjects/${c.subject_id}` },
                { label: c.sequence_label ?? 'Chapter' },
              ]}
            />
            {c.release_state === 'demo_release' && <DemoContentNotice className="mb-5" />}
            {!c.topics_available ? (
              <EmptyState title="No topics yet" body="This chapter has no practice topics available yet." />
            ) : (
              <>
                <h2 className="t-section mb-3 flex items-center gap-2">
                  <Layers size={18} className="text-brand-500" aria-hidden /> {plural(c.topics.length, 'topic')} in this chapter
                </h2>
                <motion.ul initial="hidden" animate="show" variants={stagger(0.05)} className="grid grid-cols-1 gap-4 md:grid-cols-2">
                  {c.topics.map((t) => (
                    <motion.li key={t.kc_id} variants={fadeUp} className="card flex flex-col p-5">
                      <div className="flex items-start justify-between gap-3">
                        <div className="min-w-0">
                          <p className={cx('t-eyebrow', s.ink)}>
                            {KC_TYPE[t.kc_type ?? ''] ?? 'Topic'}
                            {t.difficulty_tier ? ` · Level ${t.difficulty_tier}` : ''}
                          </p>
                          <h3 className="t-card mt-0.5">{t.name}</h3>
                        </div>
                        <BandPill p={t.mastery_probability} className="shrink-0" />
                      </div>
                      {t.description && <p className="mt-2 text-sm leading-relaxed text-ctText-muted">{t.description}</p>}
                      <div className="mt-4">
                        <MasteryBar p={t.mastery_probability} fill={s.bar} label={t.evidence_count ? `${plural(t.evidence_count, 'answer')} so far` : 'Mastery'} />
                      </div>
                      <div className="mt-4 flex flex-wrap gap-2 border-t border-surface-border-subtle pt-4">
                        {t.question_count > 0 ? (
                          <Link to={`/student/topics/${encodeURIComponent(t.kc_id)}/practice`} className="btn btn-primary btn-sm">
                            Practise {t.question_count} question{t.question_count === 1 ? '' : 's'} <ArrowRight size={14} aria-hidden />
                          </Link>
                        ) : (
                          <span className="text-xs text-ctText-muted">No practice questions yet</span>
                        )}
                        <Link to={`/student/topics/${encodeURIComponent(t.kc_id)}`} className="btn btn-ghost btn-sm">
                          Topic details
                        </Link>
                      </div>
                    </motion.li>
                  ))}
                </motion.ul>
                <EstimateNote className="mt-4" />
              </>
            )}
          </div>
        );
      }}
    </QueryView>
  );
};

export default ChapterPage;
