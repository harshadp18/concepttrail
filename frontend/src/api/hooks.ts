/** React Query hooks over `endpoints`. Components use these, never `fetch` directly. */
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { catalog, notifications, student, teacher } from './endpoints';
import type { CycleStatus, InterventionStatus, InterventionType, SubmittedAnswer } from './types';

export const keys = {
  catalog: ['catalog'] as const,
  curriculum: ['curriculum'] as const,
  chapter: (id: string) => ['chapter', id] as const,
  topic: (id: string) => ['topic', id] as const,
  prereqs: (id: string) => ['prereqs', id] as const,
  questions: (id: string) => ['questions', id] as const,
  progress: ['student', 'progress'] as const,
  chapters: ['student', 'chapters'] as const,
  activity: (limit: number, offset: number) => ['student', 'activity', limit, offset] as const,
  weak: ['student', 'weak'] as const,
  review: ['student', 'review'] as const,
  recommendation: ['student', 'recommendation'] as const,
  conversations: ['student', 'conversations'] as const,
  conversation: (id: string) => ['student', 'conversation', id] as const,
  notifications: ['notifications'] as const,
  teacherClasses: ['teacher', 'classes'] as const,
  dashboard: (c: string) => ['teacher', c, 'dashboard'] as const,
  roster: (c: string) => ['teacher', c, 'roster'] as const,
  learner: (c: string, l: string) => ['teacher', c, 'learner', l] as const,
  classWeak: (c: string) => ['teacher', c, 'weak'] as const,
  heatmap: (c: string, f: object) => ['teacher', c, 'heatmap', f] as const,
  bellTopics: (c: string, f: object) => ['teacher', c, 'bell', 'topics', f] as const,
  cycles: (c: string) => ['teacher', c, 'bell', 'cycles'] as const,
  cycle: (c: string, id: string) => ['teacher', c, 'bell', 'cycle', id] as const,
  interventions: (c: string) => ['teacher', c, 'interventions'] as const,
  reviewQueue: (s: string | undefined, o: number) => ['teacher', 'review', s, o] as const,
};

// ----- catalog -----
export const useCatalog = () => useQuery({ queryKey: keys.catalog, queryFn: catalog.classes });
export const useCurriculum = () => useQuery({ queryKey: keys.curriculum, queryFn: catalog.curriculum });
export const useChapter = (id: string) =>
  useQuery({ queryKey: keys.chapter(id), queryFn: () => catalog.chapter(id), enabled: !!id });
export const useTopic = (id: string) =>
  useQuery({ queryKey: keys.topic(id), queryFn: () => catalog.topic(id), enabled: !!id });
export const usePrerequisites = (id: string) =>
  useQuery({ queryKey: keys.prereqs(id), queryFn: () => catalog.prerequisites(id), enabled: !!id });
export const useQuestions = (id: string) =>
  useQuery({
    queryKey: keys.questions(id),
    queryFn: () => catalog.questions(id),
    enabled: !!id,
    staleTime: Infinity, // keep the set stable while a learner works through it
  });

// ----- student -----
export const useStudentProgress = () => useQuery({ queryKey: keys.progress, queryFn: student.progress });
export const useChapterProgress = () => useQuery({ queryKey: keys.chapters, queryFn: student.chapters });
export const useActivity = (limit: number, offset: number) =>
  useQuery({
    queryKey: keys.activity(limit, offset),
    queryFn: () => student.activity(limit, offset),
    placeholderData: (prev) => prev,
  });
export const useWeakAreas = () => useQuery({ queryKey: keys.weak, queryFn: student.weakAreas });
export const useRetryList = () => useQuery({ queryKey: keys.review, queryFn: student.review });
export const useRecommendation = () =>
  useQuery({ queryKey: keys.recommendation, queryFn: student.recommendation });
export const useConversations = (enabled = true) =>
  useQuery({ queryKey: keys.conversations, queryFn: student.conversations, enabled });

export function useSubmitAttempt() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (v: {
      question_id: string;
      question_version: number;
      submitted_answer: SubmittedAnswer;
      hint_tier: number;
      idempotency_key: string;
    }) => student.submitAttempt(v),
    onSuccess: () => {
      // progress, recommendations and retry lists are derived from attempts on the server
      for (const k of [keys.progress, keys.chapters, keys.weak, keys.review, keys.recommendation]) {
        qc.invalidateQueries({ queryKey: k });
      }
      qc.invalidateQueries({ queryKey: ['student', 'activity'] });
      qc.invalidateQueries({ queryKey: ['chapter'] });
    },
  });
}

// ----- notifications -----
export const useNotifications = () =>
  useQuery({
    queryKey: keys.notifications,
    queryFn: () => notifications.list(),
    // poll once a minute (no push channel); stop while the feature is off or failing
    refetchInterval: (q) => (q.state.error ? false : 60000),
  });

export function useNotificationActions() {
  const qc = useQueryClient();
  const done = () => qc.invalidateQueries({ queryKey: keys.notifications });
  return {
    markRead: useMutation({ mutationFn: notifications.markRead, onSuccess: done }),
    markAll: useMutation({ mutationFn: notifications.markAllRead, onSuccess: done }),
  };
}

// ----- teacher -----
export const useTeacherClasses = () => useQuery({ queryKey: keys.teacherClasses, queryFn: teacher.classes });
export const useClassDashboard = (c: string) =>
  useQuery({ queryKey: keys.dashboard(c), queryFn: () => teacher.dashboard(c), enabled: !!c });
export const useRoster = (c: string) =>
  useQuery({ queryKey: keys.roster(c), queryFn: () => teacher.roster(c), enabled: !!c });
export const useLearnerProgress = (c: string, l: string) =>
  useQuery({ queryKey: keys.learner(c, l), queryFn: () => teacher.learner(c, l), enabled: !!c && !!l });
export const useClassWeakAreas = (c: string) =>
  useQuery({ queryKey: keys.classWeak(c), queryFn: () => teacher.weakAreas(c), enabled: !!c });
export const useHeatmap = (c: string, f: { subject_id?: string; item_id?: string; window_days?: number }) =>
  useQuery({
    queryKey: keys.heatmap(c, f),
    queryFn: () => teacher.heatmap(c, f),
    enabled: !!c,
    placeholderData: (prev) => prev,
  });
export const useBellRingerTopics = (c: string, f: { subject_id?: string; window_days?: number }) =>
  useQuery({
    queryKey: keys.bellTopics(c, f),
    queryFn: () => teacher.bellRingerTopics(c, f),
    enabled: !!c,
    placeholderData: (prev) => prev,
  });
export const useCycles = (c: string, enabled = true) =>
  useQuery({ queryKey: keys.cycles(c), queryFn: () => teacher.cycles(c), enabled: !!c && enabled });
export const useCycle = (c: string, id: string) =>
  useQuery({ queryKey: keys.cycle(c, id), queryFn: () => teacher.cycle(c, id), enabled: !!c && !!id });

export function useCycleActions(c: string) {
  const qc = useQueryClient();
  const refresh = () => qc.invalidateQueries({ queryKey: ['teacher', c, 'bell'] });
  return {
    open: useMutation({
      mutationFn: (v: { kc_id: string; note?: string; window_days?: number }) => teacher.openCycle(c, v),
      onSuccess: refresh,
    }),
    setStatus: useMutation({
      mutationFn: (v: { id: string; status: Exclude<CycleStatus, 'planned'> }) =>
        teacher.setCycleStatus(c, v.id, v.status),
      onSuccess: refresh,
    }),
  };
}

export const useInterventions = (c: string) =>
  useQuery({ queryKey: keys.interventions(c), queryFn: () => teacher.interventions(c), enabled: !!c });

export function useInterventionActions(c: string) {
  const qc = useQueryClient();
  const refresh = () => qc.invalidateQueries({ queryKey: keys.interventions(c) });
  return {
    create: useMutation({
      mutationFn: (v: { intervention_type: InterventionType; kc_id?: string; learner_id?: string; note?: string }) =>
        teacher.createIntervention(c, v),
      onSuccess: refresh,
    }),
    setStatus: useMutation({
      mutationFn: (v: { id: string; status: Exclude<InterventionStatus, 'planned'> }) =>
        teacher.setInterventionStatus(c, v.id, v.status),
      onSuccess: refresh,
    }),
  };
}

export const useReviewQueue = (status: string | undefined, offset: number) =>
  useQuery({
    queryKey: keys.reviewQueue(status, offset),
    queryFn: () => teacher.reviewQueue(status, 20, offset),
    placeholderData: (prev) => prev,
  });

export function useSubmitReview() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (v: { questionId: string; decision: 'approved' | 'rejected' | 'revision_required'; rationale: string }) =>
      teacher.submitReview(v.questionId, { decision: v.decision, rationale: v.rationale }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['teacher', 'review'] }),
  });
}
