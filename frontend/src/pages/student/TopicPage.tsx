import React from 'react';
import { Link, useParams } from 'react-router-dom';
import { motion } from 'framer-motion';
import { ArrowRight, CheckCircle2, CircleDashed, GitBranch, MessageCircle, NotebookText } from 'lucide-react';
import { usePrerequisites, useStudentProgress, useTopic } from '@/api/hooks';
import { subjectMeta } from '@/lib/subjects';
import { pct, plural } from '@/lib/format';
import { BandPill, Card, cx, EstimateNote, MasteryBar, Notice, PageHeader } from '@/components/ui/primitives';
import { EmptyState, ErrorState, QueryView, Skeleton } from '@/components/ui/states';
import { fadeUp, stagger } from '@/components/ui/motion';
import { SHOW_DEMO_NOTICES } from '@/lib/flags';

export const TopicPage: React.FC = () => {
  const { kcId = '' } = useParams();
  const topic = useTopic(kcId);
  const prereqs = usePrerequisites(kcId);
  const progress = useStudentProgress();
  const estimate = progress.data?.mastery_estimates.find((m) => m.kc_id === kcId);

  return (
    <QueryView query={topic}>
      {(t) => {
        const s = subjectMeta(t.subject_id);
        const chapter = t.curriculum_mappings[0];
        return (
          <motion.div initial="hidden" animate="show" variants={stagger(0.06)}>
            <PageHeader
              eyebrow={`${s.name}${chapter ? ` · Class ${chapter.grade_level}` : ''}`}
              title={t.name}
              subtitle={t.description}
              crumbs={[
                { label: s.name, to: `/student/subjects/${t.subject_id}` },
                ...(chapter ? [{ label: chapter.item_title ?? 'Chapter', to: `/student/chapters/${encodeURIComponent(chapter.item_id)}` }] : []),
                { label: 'Topic' },
              ]}
              actions={
                <>
                  <Link to={`/student/buddy?kc=${encodeURIComponent(kcId)}&subject=${t.subject_id ?? ''}`} className="btn btn-secondary">
                    <MessageCircle size={16} aria-hidden /> Ask Buddy
                  </Link>
                  <Link to={`/student/topics/${encodeURIComponent(kcId)}/practice`} className="btn btn-primary">
                    Practise <ArrowRight size={16} aria-hidden />
                  </Link>
                </>
              }
            />
            <div className="grid grid-cols-1 gap-5 lg:grid-cols-3">
              <motion.div variants={fadeUp} className="space-y-5 lg:col-span-2">
                <Card>
                  <h2 className="t-section flex items-center gap-2">
                    <NotebookText size={18} className="text-brand-500" aria-hidden /> Learn
                  </h2>
                  {t.notes.length ? (
                    <div className="mt-4 space-y-5">
                      {t.notes.map((n) => (
                        <article key={n.note_id} lang={n.language === 'hi' ? 'hi' : undefined}>
                          {n.title && <h3 className="t-card">{n.title}</h3>}
                          <p className="mt-1.5 whitespace-pre-line text-sm leading-relaxed text-ctText-body">{n.content_markdown}</p>
                        </article>
                      ))}
                    </div>
                  ) : (
                    <EmptyState
                      compact
                      className="mt-4"
                      title="No lesson notes for this topic yet"
                      body="Practise the questions, or ask Buddy to explain the idea using your course material."
                    />
                  )}
                </Card>
              </motion.div>

              <motion.div variants={fadeUp} className="space-y-5">
                <Card>
                  <div className="flex items-center justify-between gap-2">
                    <h2 className="t-card">Your mastery</h2>
                    <BandPill p={estimate?.mastery_probability ?? null} />
                  </div>
                  {progress.isLoading ? (
                    <Skeleton className="mt-4 h-8" />
                  ) : (
                    <div className="mt-4">
                      <MasteryBar p={estimate?.mastery_probability ?? null} fill={s.bar} height="h-2.5" />
                      <p className="mt-2 text-xs text-ctText-muted">
                        {estimate ? `Based on ${plural(estimate.evidence_count, 'scored answer')}.` : 'Answer a few questions to get an estimate.'}
                      </p>
                    </div>
                  )}
                  <EstimateNote className="mt-3" />
                </Card>

                <Card>
                  <h2 className="t-card flex items-center gap-2">
                    <GitBranch size={16} className="text-brand-500" aria-hidden /> Builds on
                  </h2>
                  {prereqs.isLoading && <Skeleton className="mt-3 h-16" />}
                  {prereqs.error ? <ErrorState error={prereqs.error} compact className="mt-3" /> : null}
                  {prereqs.data &&
                    (!prereqs.data.graph_available ? (
                      <p className="mt-2 text-sm text-ctText-muted">Topic links are not available for this topic yet.</p>
                    ) : prereqs.data.direct.length === 0 ? (
                      <p className="mt-2 text-sm text-ctText-muted">This topic does not depend on another one. A good place to start.</p>
                    ) : (
                      <>
                        <ul className="mt-3 space-y-2">
                          {prereqs.data.direct.map((p) => (
                            <li key={p.kc_id}>
                              <Link
                                to={`/student/topics/${encodeURIComponent(p.kc_id)}`}
                                className="flex items-center gap-2.5 rounded-xl border border-surface-border p-3 hover:border-brand-200 hover:bg-brand-50 focus-ring"
                              >
                                {p.ready ? (
                                  <CheckCircle2 size={18} className="shrink-0 text-band-mastered" aria-label="Ready" />
                                ) : (
                                  <CircleDashed size={18} className="shrink-0 text-band-practice" aria-label="Worth revisiting" />
                                )}
                                <span className="min-w-0 flex-1 text-sm font-semibold text-ctText-primary">{p.name}</span>
                                <span className={cx('text-xs tabular-nums', p.mastery_probability == null ? 'text-ctText-subtle' : 'text-ctText-body')}>
                                  {p.mastery_probability == null ? 'Not started' : pct(p.mastery_probability)}
                                </span>
                              </Link>
                            </li>
                          ))}
                        </ul>
                        {SHOW_DEMO_NOTICES && prereqs.data.edge_provenance === 'ai_proposed_demo' && (
                          <Notice className="mt-3">These links between topics were proposed by AI for this demo and are not yet teacher-approved.</Notice>
                        )}
                      </>
                    ))}
                </Card>
              </motion.div>
            </div>
          </motion.div>
        );
      }}
    </QueryView>
  );
};

export default TopicPage;
