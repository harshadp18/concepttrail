import React, { createContext, useContext, useEffect, useMemo, useState } from 'react';
import { useTeacherClasses } from '@/api/hooks';
import type { TeacherClass } from '@/api/types';

/**
 * The class a teacher is looking at. Options come only from GET /teacher/classes (server-side
 * assignments); every class-level request is still authorised by the backend.
 */
interface TeacherClassContextType {
  classes: TeacherClass[];
  selected: TeacherClass | null;
  classId: string;
  select: (id: string) => void;
  isLoading: boolean;
  error: unknown;
  refetch: () => unknown;
}

const Ctx = createContext<TeacherClassContextType | undefined>(undefined);
const KEY = 'concepttrail.teacher.class';

export const TeacherClassProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const query = useTeacherClasses();
  const classes = useMemo(() => query.data?.classes ?? [], [query.data]);
  const [chosen, setChosen] = useState<string>(() => {
    try {
      return sessionStorage.getItem(KEY) ?? '';
    } catch {
      return '';
    }
  });

  const selected = classes.find((c) => c.classroom_id === chosen) ?? classes[0] ?? null;

  useEffect(() => {
    if (selected && selected.classroom_id !== chosen) setChosen(selected.classroom_id);
  }, [selected, chosen]);

  const select = (id: string) => {
    setChosen(id);
    try {
      sessionStorage.setItem(KEY, id);
    } catch {
      // ignore
    }
  };

  return (
    <Ctx.Provider
      value={{
        classes,
        selected,
        classId: selected?.classroom_id ?? '',
        select,
        isLoading: query.isLoading,
        error: query.error,
        refetch: query.refetch,
      }}
    >
      {children}
    </Ctx.Provider>
  );
};

export function useTeacherClass() {
  const ctx = useContext(Ctx);
  if (!ctx) throw new Error('useTeacherClass must be used inside TeacherClassProvider');
  return ctx;
}

export function teacherClassName(c: TeacherClass | null | undefined): string {
  if (!c) return 'No class';
  const section = c.section_label ?? '';
  return `Class ${c.grade_level ?? '?'}${section ? (section.length <= 2 ? section : ` ${section}`) : ''}`;
}
