import React from 'react';
import { Link } from 'react-router-dom';
import { motion } from 'framer-motion';
import { ArrowRight, Compass, RotateCcw, Sparkles, Target } from 'lucide-react';
import { useRecommendation, useRetryList, useTopic, useWeakAreas } from '@/api/hooks';
import { subjectMeta } from '@/lib/subjects';
import { pct } from '@/lib/format';
import { CATEGORY_LABEL, readableRationale, recommendationMessage } from '@/lib/recommendation';
import { Card, EstimateNote, Notice, PageHeader, Pill, SectionHeader } from '@/components/ui/primitives';
import { EmptyState, QueryView, Skeleton } from '@/components/ui/states';
import { fadeUp, stagger } from '@/components/ui/motion';
import { SHOW_DEMO_NOTICES } from '@/lib/flags';

export const StudentRecommendations: React.FC = () => {
  const rec = useRecommendation();
  const topic = useTopic(rec.data?.status === 'ok' ? rec.data.kc_id ?? '' : '');
  const weak = useWeakAreas();
  const retry = useRetryList();
  return (
    <motion.div initial="hidden" animate="show" variants={stagger(0.06)}>
      <PageHeader title="Your next steps" subtitle="Chosen by ConceptTrail's learning rules from your own answers — not by AI." />
      <QueryView query={rec} loading={<Skeleton className="h-56 rounded-3xl" />}>
        {(r) =>
          r.status === 'ok' && r.kc_id ? (
            <motion.div variants={fadeUp}>
              <Card className="relative overflow-hidden border-brand-200">
                <div className="absolute inset-y-0 left-0 w-1.5 bg-brand-500" aria-hidden />
                <div className="flex flex-col gap-5 sm:flex-row sm:items-start sm:justify-between">
                  <div className="min-w-0">
                    <Pill tone="brand" icon={<Sparkles size={12} />}>
                      Start here · {CATEGORY_LABEL[r.category ?? ''] ?? 'Suggested'}
                    </Pill>
                    <p className="mt-3 text-xs font-semibold text-ctText-muted">{topic.data ? subjectMeta(topic.data.subject_id).name : ' '}</p>
                    <h2 className="text-2xl font-extrabold text-ctText-primary">{topic.data?.name ?? <Skeleton className="h-7 w-64" />}</h2>
                    {topic.data?.description && <p className="mt-1 max-w-xl text-sm text-ctText-muted">{topic.data.description}</p>}
                    <div className="mt-4 rounded-2xl bg-brand-50 p-4">
                      <p className="text-xs font-bold text-brand-700">Why this?</p>
                      <ul className="mt-1 list-disc space-y-0.5 pl-4 text-sm text-ctText-body">
                        {readableRationale(r.rationale).map((line) => (
                          <li key={line}>{line}</li>
                        ))}
                        <li>Your current estimate: {r.mastery_probability == null ? 'not started yet' : pct(r.mastery_probability)}.</li>
                      </ul>
                    </div>
                  </div>
                  <div className="flex shrink-0 flex-col gap-2">
                    <Link
                      to={`/student/topics/${encodeURIComponent(r.kc_id)}/practice${r.question_id ? `?start=${encodeURIComponent(r.question_id)}` : ''}`}
                      className="btn btn-primary"
                    >
                      Start practice <ArrowRight size={15} aria-hidden />
                    </Link>
                    <Link to={`/student/topics/${encodeURIComponent(r.kc_id)}`} className="btn btn-secondary">
                      About this topic
                    </Link>
                  </div>
                </div>
                {SHOW_DEMO_NOTICES && r.content_release === 'demo' && (
                  <Notice className="mt-5">The topic links behind this suggestion were proposed by AI for this demo and have not been teacher-approved.</Notice>
                )}
              </Card>
            </motion.div>
          ) : (
            <EmptyState icon={<Compass size={22} />} title="No suggested step right now" body={recommendationMessage(r)} action={<Link to="/student/subjects" className="btn btn-primary">Browse subjects</Link>} />
          )
        }
      </QueryView>

      <div className="mt-8 grid grid-cols-1 gap-6 lg:grid-cols-2">
        <motion.section variants={fadeUp} aria-labelledby="weak-title">
          <SectionHeader id="weak-title" title="Topics to strengthen" />
          <QueryView query={weak} compact>
            {(w) =>
              w.weak_areas.length ? (
                <ul className="space-y-2.5">
                  {w.weak_areas.map((a) => (
                    <li key={a.kc_id}>
                      <Link to={`/student/topics/${encodeURIComponent(a.kc_id)}/practice`} className="card card-hover flex items-center gap-3 p-4 focus-ring">
                        <Target size={18} className="shrink-0 text-band-practice" aria-hidden />
                        <span className="min-w-0 flex-1">
                          <span className="t-card block truncate">{a.name}</span>
                          <span className="text-xs text-ctText-muted">Estimate {pct(a.mastery_probability)} after {a.evidence_count} answers</span>
                        </span>
                        <ArrowRight size={16} className="text-ctText-subtle" aria-hidden />
                      </Link>
                    </li>
                  ))}
                </ul>
              ) : (
                <EmptyState compact icon={<Target size={22} />} title="Nothing to strengthen yet" body="Topics show up here once you have answered enough questions." />
              )
            }
          </QueryView>
        </motion.section>
        <motion.section variants={fadeUp} aria-labelledby="retry-title">
          <SectionHeader
            id="retry-title"
            title="Questions to retry"
            action={
              <Link to="/student/review" className="btn btn-ghost btn-sm">
                See all
              </Link>
            }
          />
          <QueryView query={retry} compact>
            {(r) =>
              r.questions.length ? (
                <ul className="space-y-2.5">
                  {r.questions.slice(0, 4).map((q) => (
                    <li key={q.question_id} className="card flex items-center gap-3 p-4">
                      <RotateCcw size={18} className="shrink-0 text-brand-500" aria-hidden />
                      <span className="min-w-0 flex-1 truncate text-sm text-ctText-body">{q.stem}</span>
                    </li>
                  ))}
                </ul>
              ) : (
                <EmptyState compact icon={<RotateCcw size={22} />} title="No questions to retry" body="Questions you last answered incorrectly will appear here." />
              )
            }
          </QueryView>
        </motion.section>
      </div>
      <EstimateNote className="mt-6" />
    </motion.div>
  );
};

export default StudentRecommendations;
