import React, { useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import { motion } from 'framer-motion';
import { ArrowRight, Search } from 'lucide-react';
import { useRoster } from '@/api/hooks';
import type { RosterLearner } from '@/api/types';
import { teacherClassName, useTeacherClass } from '@/context/TeacherClassContext';
import { pct, relative } from '@/lib/format';
import { BandPill, Card, EstimateNote, MasteryBar, PageHeader, StatTile } from '@/components/ui/primitives';
import { EmptyState, QueryView } from '@/components/ui/states';
import { fadeUp, stagger } from '@/components/ui/motion';
import { Users, UserX, Target } from 'lucide-react';

type Sort = 'name' | 'mastery' | 'activity';

function sortRows(rows: RosterLearner[], sort: Sort) {
  const copy = [...rows];
  if (sort === 'mastery') copy.sort((a, b) => (a.average_mastery_probability ?? 2) - (b.average_mastery_probability ?? 2));
  if (sort === 'activity') copy.sort((a, b) => (b.last_attempt_at ?? '').localeCompare(a.last_attempt_at ?? ''));
  return copy;
}

export const TeacherLearners: React.FC = () => {
  const { classId, selected } = useTeacherClass();
  const roster = useRoster(classId);
  const [q, setQ] = useState('');
  const [sort, setSort] = useState<Sort>('name');
  const rows = useMemo(
    () => sortRows((roster.data?.learners ?? []).filter((l) => (l.display_name ?? '').toLowerCase().includes(q.toLowerCase())), sort),
    [roster.data, q, sort]
  );
  const all = roster.data?.learners ?? [];
  return (
    <div>
      <PageHeader
        title="Learners"
        eyebrow={teacherClassName(selected)}
        subtitle="Everyone actively enrolled in this class, with their own activity and average estimate."
        crumbs={[{ label: 'Classes', to: '/teacher/classes' }, { label: 'Learners' }]}
      />
      <QueryView query={roster}>
        {(r) =>
          r.count === 0 ? (
            <EmptyState title="No learners enrolled yet" />
          ) : (
            <motion.div initial="hidden" animate="show" variants={stagger(0.05)}>
              <motion.section variants={stagger(0.05)} className="card mb-6 grid grid-cols-1 sm:grid-cols-3 sm:divide-x divide-surface-border-subtle" aria-label="Class summary">
                <StatTile icon={<Users size={20} />} iconClass="bg-brand-50 text-brand-600" value={r.count} label="Enrolled learners" />
                <StatTile
                  icon={<Target size={20} />}
                  iconClass="bg-band-practice-bg text-band-practice"
                  value={all.filter((l) => l.average_mastery_probability != null && l.average_mastery_probability < 0.5).length}
                  label="Average estimate below 50%"
                />
                <StatTile icon={<UserX size={20} />} iconClass="bg-surface-muted text-ctText-muted" value={all.filter((l) => l.attempts === 0).length} label="No practice yet" />
              </motion.section>
              <div className="mb-4 flex flex-wrap items-center gap-3">
                <label className="relative min-w-[220px] flex-1">
                  <span className="sr-only">Search learners</span>
                  <Search size={16} className="absolute left-3.5 top-1/2 -translate-y-1/2 text-ctText-subtle" aria-hidden />
                  <input className="field pl-10" placeholder="Search by name" value={q} onChange={(e) => setQ(e.target.value)} />
                </label>
                <label className="flex items-center gap-2 text-xs font-semibold text-ctText-muted">
                  Sort
                  <select className="field-select" value={sort} onChange={(e) => setSort(e.target.value as Sort)}>
                    <option value="name">Name</option>
                    <option value="mastery">Lowest estimate first</option>
                    <option value="activity">Most recently active</option>
                  </select>
                </label>
              </div>
              <motion.div variants={fadeUp}>
                <Card pad={false} className="hidden overflow-x-auto md:block">
                  <table className="w-full text-sm">
                    <caption className="sr-only">Learners in {teacherClassName(selected)}</caption>
                    <thead>
                      <tr className="border-b border-surface-border text-left text-2xs font-bold uppercase tracking-wider text-ctText-muted">
                        <th scope="col" className="px-5 py-3">Learner</th>
                        <th scope="col" className="w-56 px-4 py-3">Average estimate</th>
                        <th scope="col" className="px-4 py-3">Answers</th>
                        <th scope="col" className="px-4 py-3">Last active</th>
                        <th scope="col" className="px-4 py-3"><span className="sr-only">Open</span></th>
                      </tr>
                    </thead>
                    <tbody>
                      {rows.map((l) => (
                        <tr key={l.learner_id} className="border-b border-surface-border-subtle last:border-0 hover:bg-surface-subtle">
                          <td className="px-5 py-3">
                            <span className="font-semibold text-ctText-primary">{l.display_name}</span>
                            <span className="ml-2 align-middle">
                              <BandPill p={l.average_mastery_probability} />
                            </span>
                          </td>
                          <td className="px-4 py-3">
                            <MasteryBar p={l.average_mastery_probability} label={`${l.topics_started} topics`} />
                          </td>
                          <td className="px-4 py-3 tabular-nums text-ctText-body">
                            {l.attempts} {l.attempts > 0 && <span className="text-ctText-muted">({pct(l.accuracy)} correct)</span>}
                          </td>
                          <td className="px-4 py-3 text-ctText-muted">{relative(l.last_attempt_at)}</td>
                          <td className="px-4 py-3 text-right">
                            <Link to={`/teacher/learners/${l.learner_id}`} className="btn btn-ghost btn-sm">
                              View <ArrowRight size={14} aria-hidden />
                            </Link>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </Card>
                <ul className="space-y-3 md:hidden">
                  {rows.map((l) => (
                    <li key={l.learner_id}>
                      <Link to={`/teacher/learners/${l.learner_id}`} className="card block p-4 focus-ring">
                        <div className="flex items-center justify-between gap-2">
                          <span className="font-semibold text-ctText-primary">{l.display_name}</span>
                          <BandPill p={l.average_mastery_probability} />
                        </div>
                        <MasteryBar className="mt-3" p={l.average_mastery_probability} label={`${l.attempts} answers`} />
                        <p className="mt-2 text-xs text-ctText-muted">Last active: {relative(l.last_attempt_at)}</p>
                      </Link>
                    </li>
                  ))}
                </ul>
                {rows.length === 0 && <EmptyState compact title="No learner matches that search" />}
              </motion.div>
              <EstimateNote className="mt-3" />
            </motion.div>
          )
        }
      </QueryView>
    </div>
  );
};

export default TeacherLearners;
