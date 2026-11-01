import React from 'react';
import { motion } from 'framer-motion';
import { useCatalog, useChapterProgress } from '@/api/hooks';
import { classLabel, useAuth } from '@/context/AuthContext';
import { SubjectCard } from '@/components/student/SubjectCard';
import { DemoContentNotice, EstimateNote, PageHeader } from '@/components/ui/primitives';
import { EmptyState, QueryView, Skeleton } from '@/components/ui/states';
import { stagger } from '@/components/ui/motion';
import { SUBJECT_ORDER } from '@/lib/subjects';

export const StudentSubjects: React.FC = () => {
  const { user } = useAuth();
  const catalog = useCatalog();
  const progress = useChapterProgress();
  return (
    <div>
      <PageHeader
        title="Subjects"
        subtitle={`Everything available for ${classLabel(user?.primaryClass)}. Open a subject to see its chapters and topics.`}
        crumbs={[{ label: 'Home', to: '/student/home' }, { label: 'Subjects' }]}
      />
      <QueryView
        query={catalog}
        loading={<div className="grid grid-cols-1 gap-5 sm:grid-cols-2 lg:grid-cols-3">{[...Array(5)].map((_, i) => <Skeleton key={i} className="h-80 rounded-3xl" />)}</div>}
      >
        {(c) => {
          if (!c.grade_levels.length) {
            return <EmptyState title="You are not enrolled in a class yet" body="Ask your teacher or school office to add you to your class." />;
          }
          const combos = c.combinations
            .filter((x) => x.grade_level === c.grade_levels[0])
            .sort((a, b) => SUBJECT_ORDER.indexOf(a.subject_id) - SUBJECT_ORDER.indexOf(b.subject_id));
          return (
            <>
              {c.content_release === 'demo' && <DemoContentNotice className="mb-5" />}
              <motion.div initial="hidden" animate="show" variants={stagger(0.06)} className="grid grid-cols-1 gap-5 sm:grid-cols-2 lg:grid-cols-3">
                {combos.map((combo) => (
                  <SubjectCard key={combo.subject_id} combo={combo} progress={progress.data?.subjects.find((s) => s.subject_id === combo.subject_id)} />
                ))}
              </motion.div>
              <EstimateNote className="mt-4" />
            </>
          );
        }}
      </QueryView>
    </div>
  );
};

export default StudentSubjects;
