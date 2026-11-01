import math from '@/assets/illustrations/subject-mathematics.svg';
import science from '@/assets/illustrations/subject-science.svg';
import english from '@/assets/illustrations/subject-english.svg';
import hindi from '@/assets/illustrations/subject-hindi.svg';
import social from '@/assets/illustrations/subject-social-science.svg';

export interface SubjectMeta {
  id: string;
  name: string;
  blurb: string;
  art: string;
  /** Tailwind classes, kept as full strings so the JIT compiler can see them. */
  tint: string; // card background
  ring: string; // card border
  ink: string; // accent text
  bar: string; // progress fill
  dot: string; // small marker
}

export const SUBJECTS: Record<string, SubjectMeta> = {
  mathematics: {
    id: 'mathematics',
    name: 'Mathematics',
    blurb: 'Numbers, equations and shapes, explored step by step.',
    art: math,
    tint: 'bg-subject-math-bg',
    ring: 'border-subject-math-ring',
    ink: 'text-subject-math-text',
    bar: 'bg-subject-math',
    dot: 'bg-subject-math',
  },
  science: {
    id: 'science',
    name: 'Science',
    blurb: 'Discover how the world works through ideas and experiments.',
    art: science,
    tint: 'bg-subject-science-bg',
    ring: 'border-subject-science-ring',
    ink: 'text-subject-science-text',
    bar: 'bg-subject-science',
    dot: 'bg-subject-science',
  },
  english: {
    id: 'english',
    name: 'English',
    blurb: 'Grow your reading, grammar and writing confidence.',
    art: english,
    tint: 'bg-subject-english-bg',
    ring: 'border-subject-english-ring',
    ink: 'text-subject-english-text',
    bar: 'bg-subject-english',
    dot: 'bg-subject-english',
  },
  hindi: {
    id: 'hindi',
    name: 'Hindi',
    blurb: 'Build your language skills and love for the language.',
    art: hindi,
    tint: 'bg-subject-hindi-bg',
    ring: 'border-subject-hindi-ring',
    ink: 'text-subject-hindi-text',
    bar: 'bg-subject-hindi',
    dot: 'bg-subject-hindi',
  },
  social_science: {
    id: 'social_science',
    name: 'Social Science',
    blurb: 'Explore history, geography and how societies work.',
    art: social,
    tint: 'bg-subject-social-bg',
    ring: 'border-subject-social-ring',
    ink: 'text-subject-social-text',
    bar: 'bg-subject-social',
    dot: 'bg-subject-social',
  },
};

export const SUBJECT_ORDER = ['mathematics', 'science', 'english', 'hindi', 'social_science'];

export function subjectMeta(id: string | null | undefined): SubjectMeta {
  return (
    (id && SUBJECTS[id]) || {
      id: id ?? 'unknown',
      name: id ?? 'Subject',
      blurb: '',
      art: math,
      tint: 'bg-surface-muted',
      ring: 'border-surface-border',
      ink: 'text-ctText-body',
      bar: 'bg-brand-500',
      dot: 'bg-brand-500',
    }
  );
}
