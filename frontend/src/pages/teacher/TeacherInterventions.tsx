import React, { useState } from 'react';
import { AnimatePresence, motion } from 'framer-motion';
import { Plus } from 'lucide-react';
import { useBellRingerTopics, useInterventionActions, useInterventions, useRoster } from '@/api/hooks';
import type { InterventionStatus, InterventionType } from '@/api/types';
import { teacherClassName, useTeacherClass } from '@/context/TeacherClassContext';
import { shortDate } from '@/lib/format';
import { Card, PageHeader, Pill } from '@/components/ui/primitives';
import { EmptyState, ErrorState, QueryView } from '@/components/ui/states';

const TYPES: Record<InterventionType, string> = {
  reteach: 'Reteach to the class',
  small_group: 'Small group',
  individual_support: 'One-to-one support',
  practice_assignment: 'Practice assignment',
  other: 'Other',
};
const STATUS: Record<InterventionStatus, { label: string; tone: 'brand' | 'teal' | 'success' | 'neutral' }> = {
  planned: { label: 'Planned', tone: 'brand' },
  in_progress: { label: 'In progress', tone: 'teal' },
  completed: { label: 'Completed', tone: 'success' },
  cancelled: { label: 'Cancelled', tone: 'neutral' },
};

export const TeacherInterventions: React.FC = () => {
  const { classId, selected } = useTeacherClass();
  const list = useInterventions(classId);
  const roster = useRoster(classId);
  const topics = useBellRingerTopics(classId, {});
  const { create, setStatus } = useInterventionActions(classId);
  const [open, setOpen] = useState(false);
  const [form, setForm] = useState<{ intervention_type: InterventionType; kc_id: string; learner_id: string; note: string }>({
    intervention_type: 'small_group',
    kc_id: '',
    learner_id: '',
    note: '',
  });
  const names = new Map((roster.data?.learners ?? []).map((l) => [l.learner_id, l.display_name]));
  const topicNames = new Map((topics.data?.topics ?? []).map((t) => [t.kc_id, t.name]));

  return (
    <div>
      <PageHeader
        title="Support plans"
        eyebrow={teacherClassName(selected)}
        subtitle="Plan a reteach, a small group or one-to-one support for a topic, and track it to completion."
        actions={
          list.data && (
            <button type="button" className="btn btn-primary" onClick={() => setOpen((o) => !o)} aria-expanded={open}>
              <Plus size={16} aria-hidden /> New plan
            </button>
          )
        }
      />
      <QueryView query={list} feature="Support plans">
        {(data) => (
          <>
            <AnimatePresence>
              {open && (
                <motion.div initial={{ opacity: 0, height: 0 }} animate={{ opacity: 1, height: 'auto' }} exit={{ opacity: 0, height: 0 }} className="overflow-hidden">
                  <Card className="mb-6">
                    <form
                      className="grid grid-cols-1 gap-4 md:grid-cols-2"
                      onSubmit={(e) => {
                        e.preventDefault();
                        create.mutate(
                          {
                            intervention_type: form.intervention_type,
                            kc_id: form.kc_id || undefined,
                            learner_id: form.learner_id || undefined,
                            note: form.note.trim() || undefined,
                          },
                          {
                            onSuccess: () => {
                              setOpen(false);
                              setForm({ intervention_type: 'small_group', kc_id: '', learner_id: '', note: '' });
                            },
                          }
                        );
                      }}
                    >
                      <label className="field-label">
                        Type
                        <select className="field-select mt-1.5 w-full" value={form.intervention_type} onChange={(e) => setForm({ ...form, intervention_type: e.target.value as InterventionType })}>
                          {Object.entries(TYPES).map(([v, l]) => (
                            <option key={v} value={v}>
                              {l}
                            </option>
                          ))}
                        </select>
                      </label>
                      <label className="field-label">
                        Topic (optional)
                        <select className="field-select mt-1.5 w-full" value={form.kc_id} onChange={(e) => setForm({ ...form, kc_id: e.target.value })}>
                          <option value="">Not tied to one topic</option>
                          {(topics.data?.topics ?? []).map((t) => (
                            <option key={t.kc_id} value={t.kc_id}>
                              {t.name}
                            </option>
                          ))}
                        </select>
                      </label>
                      <label className="field-label">
                        Learner (optional)
                        <select className="field-select mt-1.5 w-full" value={form.learner_id} onChange={(e) => setForm({ ...form, learner_id: e.target.value })}>
                          <option value="">Whole class</option>
                          {(roster.data?.learners ?? []).map((l) => (
                            <option key={l.learner_id} value={l.learner_id}>
                              {l.display_name}
                            </option>
                          ))}
                        </select>
                      </label>
                      <label className="field-label md:col-span-2">
                        Note (do not include personal details)
                        <textarea className="field mt-1.5 h-auto py-3" rows={3} maxLength={2000} value={form.note} onChange={(e) => setForm({ ...form, note: e.target.value })} />
                      </label>
                      {create.error ? <ErrorState error={create.error} compact className="md:col-span-2" /> : null}
                      <div className="flex gap-2 md:col-span-2">
                        <button type="submit" className="btn btn-primary" disabled={create.isPending}>
                          {create.isPending ? 'Saving…' : 'Save plan'}
                        </button>
                        <button type="button" className="btn btn-ghost" onClick={() => setOpen(false)}>
                          Cancel
                        </button>
                      </div>
                    </form>
                  </Card>
                </motion.div>
              )}
            </AnimatePresence>
            {setStatus.error ? <ErrorState error={setStatus.error} compact className="mb-4" /> : null}
            {data.count === 0 ? (
              <EmptyState title="No support plans yet" body="Create one for a topic, a group or a learner." />
            ) : (
              <ul className="space-y-3">
                {data.interventions.map((i) => (
                  <motion.li layout key={i.intervention_id} className="card flex flex-col gap-3 p-4 sm:flex-row sm:items-center sm:p-5">
                    <div className="min-w-0 flex-1">
                      <div className="flex flex-wrap items-center gap-2">
                        <span className="t-card">{TYPES[i.intervention_type]}</span>
                        <Pill tone={STATUS[i.status].tone}>{STATUS[i.status].label}</Pill>
                      </div>
                      <p className="mt-1 text-xs text-ctText-muted">
                        {i.kc_id ? topicNames.get(i.kc_id) ?? i.kc_id : 'Any topic'} · {i.learner_id ? names.get(i.learner_id) ?? 'One learner' : 'Whole class'} · created{' '}
                        {shortDate(i.created_at)}
                      </p>
                      {i.note && <p className="mt-1.5 text-sm text-ctText-body">{i.note}</p>}
                    </div>
                    {(i.status === 'planned' || i.status === 'in_progress') && (
                      <div className="flex shrink-0 gap-2">
                        {i.status === 'planned' && (
                          <button type="button" className="btn btn-secondary btn-sm" onClick={() => setStatus.mutate({ id: i.intervention_id, status: 'in_progress' })}>
                            Start
                          </button>
                        )}
                        <button type="button" className="btn btn-primary btn-sm" onClick={() => setStatus.mutate({ id: i.intervention_id, status: 'completed' })}>
                          Complete
                        </button>
                        <button type="button" className="btn btn-ghost btn-sm" onClick={() => setStatus.mutate({ id: i.intervention_id, status: 'cancelled' })}>
                          Cancel
                        </button>
                      </div>
                    )}
                  </motion.li>
                ))}
              </ul>
            )}
          </>
        )}
      </QueryView>
    </div>
  );
};

export default TeacherInterventions;
