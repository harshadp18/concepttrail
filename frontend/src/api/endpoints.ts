/** One function per backend route used by the app. Paths match docs/openapi/openapi-v1.json. */
import { api } from './http';
import type {
  ActivityPage,
  AttemptResult,
  BellRingerCycleDetail,
  BellRingerTopics,
  Catalog,
  ChapterDetail,
  ChapterProgressResponse,
  ClassDashboard,
  ClassWeakAreas,
  Conversation,
  ConversationList,
  CurriculumList,
  CycleList,
  CycleStatus,
  DoubtResponse,
  Heatmap,
  Intervention,
  InterventionList,
  InterventionStatus,
  InterventionType,
  LearnerProgress,
  LoginResponse,
  Me,
  NotificationList,
  Prerequisites,
  QuestionPage,
  Recommendation,
  RetryQuestion,
  ReviewQueue,
  Roster,
  StudentProgress,
  SubmittedAnswer,
  TeacherClassList,
  TopicDetail,
  WeakAreasResponse,
} from './types';

const enc = encodeURIComponent;

export const auth = {
  login: (login_identifier: string, credential: string) =>
    api<LoginResponse>('/auth/login', {
      method: 'POST',
      body: { login_identifier, credential },
      anonymous: true,
    }),
  me: () => api<Me>('/me'),
};

export const catalog = {
  classes: () => api<Catalog>('/catalog/classes'),
  curriculum: () => api<CurriculumList>('/curriculum', { query: { limit: 100 } }),
  chapter: (itemId: string) => api<ChapterDetail>(`/curriculum/items/${enc(itemId)}`),
  topic: (kcId: string) => api<TopicDetail>(`/topics/${enc(kcId)}`),
  prerequisites: (kcId: string) => api<Prerequisites>(`/topics/${enc(kcId)}/prerequisites`),
  questions: (kcId: string) =>
    api<QuestionPage>(`/topics/${enc(kcId)}/questions`, { query: { limit: 20 } }),
};

export const student = {
  submitAttempt: (body: {
    question_id: string;
    question_version: number;
    submitted_answer: SubmittedAnswer;
    hint_tier: number;
    idempotency_key: string;
  }) => api<AttemptResult>('/attempts', { method: 'POST', body }),
  progress: () => api<StudentProgress>('/student/progress'),
  chapters: () => api<ChapterProgressResponse>('/student/progress/chapters'),
  activity: (limit: number, offset: number) =>
    api<ActivityPage>('/student/activity', { query: { limit, offset } }),
  weakAreas: () => api<WeakAreasResponse>('/student/weak-areas'),
  review: () => api<{ questions: RetryQuestion[] }>('/student/review'),
  recommendation: () => api<Recommendation>('/student/recommendation'),
  ask: (body: {
    question: string;
    mode: 'explanation' | 'hint';
    kc_id?: string;
    subject_id?: string;
    conversation_id?: string;
  }) =>
    // the local model can take tens of seconds; the backend applies its own timeout
    api<DoubtResponse>('/doubts', { method: 'POST', body, timeoutMs: 180000 }),
  conversations: () =>
    api<ConversationList>('/student/doubts/conversations', { query: { limit: 20 } }),
  conversation: (id: string) => api<Conversation>(`/student/doubts/conversations/${enc(id)}`),
  archiveConversation: (id: string) =>
    api<unknown>(`/student/doubts/conversations/${enc(id)}/archive`, { method: 'POST' }),
};

export const notifications = {
  list: (unreadOnly = false) =>
    api<NotificationList>('/notifications', { query: { unread_only: unreadOnly || undefined, limit: 50 } }),
  markRead: (id: string) => api<unknown>(`/notifications/${enc(id)}/read`, { method: 'POST' }),
  markAllRead: () => api<unknown>('/notifications/read-all', { method: 'POST' }),
};

const cls = (classId: string) => `/teacher/classes/${enc(classId)}`;

export const teacher = {
  classes: () => api<TeacherClassList>('/teacher/classes'),
  dashboard: (classId: string) => api<ClassDashboard>(`${cls(classId)}/dashboard`),
  roster: (classId: string, limit = 100, offset = 0) =>
    api<Roster>(`${cls(classId)}/learners`, { query: { limit, offset } }),
  learner: (classId: string, learnerId: string) =>
    api<LearnerProgress>(`${cls(classId)}/learners/${enc(learnerId)}/progress`),
  weakAreas: (classId: string) =>
    api<ClassWeakAreas>(`${cls(classId)}/weak-areas`, { query: { limit: 20 } }),
  heatmap: (classId: string, filters: { subject_id?: string; item_id?: string; window_days?: number }) =>
    api<Heatmap>(`${cls(classId)}/heatmap`, { query: filters }),
  bellRingerTopics: (classId: string, filters: { subject_id?: string; window_days?: number }) =>
    api<BellRingerTopics>(`${cls(classId)}/bell-ringer/topics`, { query: filters }),
  cycles: (classId: string) => api<CycleList>(`${cls(classId)}/bell-ringer/cycles`),
  cycle: (classId: string, cycleId: string) =>
    api<BellRingerCycleDetail>(`${cls(classId)}/bell-ringer/cycles/${enc(cycleId)}`),
  openCycle: (classId: string, body: { kc_id: string; note?: string; window_days?: number }) =>
    api<BellRingerCycleDetail>(`${cls(classId)}/bell-ringer/cycles`, { method: 'POST', body }),
  setCycleStatus: (classId: string, cycleId: string, status: Exclude<CycleStatus, 'planned'>) =>
    api<BellRingerCycleDetail>(`${cls(classId)}/bell-ringer/cycles/${enc(cycleId)}/status`, {
      method: 'POST',
      body: { status },
    }),
  interventions: (classId: string) => api<InterventionList>(`${cls(classId)}/interventions`),
  createIntervention: (
    classId: string,
    body: { intervention_type: InterventionType; kc_id?: string; learner_id?: string; note?: string }
  ) => api<Intervention>(`${cls(classId)}/interventions`, { method: 'POST', body }),
  setInterventionStatus: (classId: string, id: string, status: Exclude<InterventionStatus, 'planned'>) =>
    api<Intervention>(`${cls(classId)}/interventions/${enc(id)}/status`, {
      method: 'POST',
      body: { status },
    }),
  reviewQueue: (status: string | undefined, limit: number, offset: number) =>
    api<ReviewQueue>('/teacher/review/questions', { query: { status, limit, offset } }),
  submitReview: (
    questionId: string,
    body: { decision: 'approved' | 'rejected' | 'revision_required'; rationale: string }
  ) =>
    api<{ question_id: string; review_status: string; human_reviews: number }>(
      `/teacher/review/questions/${enc(questionId)}`,
      { method: 'POST', body }
    ),
};
