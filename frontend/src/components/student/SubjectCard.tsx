import React from 'react';
import { Link } from 'react-router-dom';
import { motion } from 'framer-motion';
import { Lock } from 'lucide-react';
import type { CatalogCombination, SubjectProgress } from '@/api/types';
import { subjectMeta } from '@/lib/subjects';
import { plural } from '@/lib/format';
import { cx, MasteryBar } from '@/components/ui/primitives';
import { fadeUp } from '@/components/ui/motion';
import { SHOW_DEMO_NOTICES } from '@/lib/flags';

/** One subject for the learner's class: art, availability, and their own progress. */
export const SubjectCard: React.FC<{
  combo: CatalogCombination;
  progress?: SubjectProgress;
  compact?: boolean;
}> = ({ combo, progress, compact }) => {
  const s = subjectMeta(combo.subject_id);
  const available = combo.state !== 'not_available';
  const body = (
    <>
      <div className="relative">
        <img src={s.art} alt="" className={cx('w-full object-contain', compact ? 'aspect-[16/10] p-2' : 'aspect-[3/2] p-3')} />
        {SHOW_DEMO_NOTICES && combo.state === 'demo_release' && (
          <span className="pill absolute right-3 top-3 bg-white/90 text-ctText-muted ring-1 ring-inset ring-surface-border">Demo</span>
        )}
      </div>
      <div className="flex flex-1 flex-col px-4 pb-4 sm:px-5 sm:pb-5">
        <h3 className="text-base font-extrabold text-ctText-primary">{s.name}</h3>
        {!compact && <p className="mt-0.5 text-xs leading-snug text-ctText-body">{s.blurb}</p>}
        {available ? (
          <>
            <p className={cx('mt-2 text-2xs font-semibold', s.ink)}>
              {plural(combo.chapters, 'chapter')} · {plural(combo.topics, 'topic')}
            </p>
            <div className="mt-auto pt-3">
              <MasteryBar p={progress?.average_mastery_probability ?? null} fill={s.bar} label="Mastery" />
            </div>
          </>
        ) : (
          <p className="mt-auto flex items-center gap-1.5 pt-3 text-xs font-semibold text-ctText-muted">
            <Lock size={13} aria-hidden /> Not available for your class yet
          </p>
        )}
      </div>
    </>
  );
  const shell = cx('flex h-full flex-col overflow-hidden rounded-3xl border', s.tint, s.ring);
  return (
    <motion.div variants={fadeUp} className="h-full">
      {available ? (
        <Link to={`/student/subjects/${combo.subject_id}`} className={cx(shell, 'card-hover focus-ring')} aria-label={`${s.name}: open chapters`}>
          {body}
        </Link>
      ) : (
        <div className={cx(shell, 'opacity-75')} aria-disabled>
          {body}
        </div>
      )}
    </motion.div>
  );
};
