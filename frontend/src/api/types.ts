/**
 * Response types for the ConceptTrail API v1. Typed responses mirror docs/openapi/openapi-v1.json;
 * routes the backend declares as plain objects are typed from their implementation
 * (app/api/v1/*.py). `null` always means "no evidence yet", never zero.
 */

export type ReleaseState = 'published' | 'demo_release' | 'not_available';

export interface ClassroomContext {
  classroom_id: string;
  grade_level: number | null;
  section_label: string | null;
  academic_session: string | null;
  school_label: string | null;
}

export interface Me {
  user_id: string;
  login_identifier: string;
  roles: string[];
  learner_id: string | null;
  display_name: string | null;
  enrolled_classrooms: ClassroomContext[];
  assigned_classrooms: ClassroomContext[];
}

export interface LoginResponse {
  access_token: string;
  token_type: string;
  expires_in: number;
  identity: Me;
}

export interface Paged {
  count: number;
  limit: number;
  offset: number;
}

// --- catalog and curriculum -------------------------------------------------------------------

export interface CatalogCombination {
  grade_level: number;
  subject_id: string;
  subject_name: string;
  chapters: number;
  topics: number;
  state: ReleaseState;
}

export interface Catalog {
  content_release: 'production' | 'demo';
  grade_levels: number[];
  subjects: { subject_id: string; display_name: string }[];
  combinations: CatalogCombination[];
  note: string;
}

export interface CurriculumItemSummary {
  item_id: string;
  parent_item_id: string | null;
  item_type: string;
  title: string | null;
  sequence_label: string | null;
  learning_objectives: unknown;
}

export interface CurriculumEntry {
  curriculum_version_id: string;
  board: string;
  academic_session: string;
  grade_level: number;
  course_or_language: string | null;
  subject: { subject_id: string; display_name: string; subject_family: string | null };
  coverage: { published_item_count: number; state: ReleaseState };
  items: CurriculumItemSummary[];
}

export interface CurriculumList extends Paged {
  curricula: CurriculumEntry[];
}

export interface TopicSummary {
  kc_id: string;
  name: string | null;
  description: string | null;
  kc_type: string | null;
  difficulty_tier: number | null;
  question_count: number;
  mastery_probability: number | null;
  evidence_count: number;
}

export interface ChapterDetail {
  item_id: string;
  item_type: string;
  title: string | null;
  sequence_label: string | null;
  grade_level: number;
  subject_id: string | null;
  subject_name: string | null;
  learning_objectives: unknown;
  release_state: 'published' | 'demo_release';
  sub_items: { item_id: string; title: string | null; sequence_label: string | null }[];
  topics: TopicSummary[];
  topics_available: boolean;
}

export interface TopicNote {
  note_id: string;
  title: string | null;
  content_markdown: string | null;
  language: string | null;
  note_type: string | null;
  content_version: string | null;
}

export interface TopicDetail {
  kc_id: string;
  subject_id: string | null;
  name: string | null;
  description: string | null;
  kc_type: string | null;
  difficulty_tier: number | null;
  misconceptions: unknown;
  curriculum_mappings: {
    item_id: string;
    item_title: string | null;
    grade_level: number;
    curriculum_version_id: string;
  }[];
  notes: TopicNote[];
}

export interface PrerequisiteView {
  kc_id: string;
  name: string | null;
  mastery_probability: number | null;
  ready: boolean | null;
}

export interface Prerequisites {
  kc_id: string;
  graph_available: boolean;
  reason?: string;
  graph_version?: string;
  edge_provenance?: 'ai_proposed_demo' | 'released_snapshot';
  readiness_threshold?: number;
  direct: PrerequisiteView[];
  transitive: PrerequisiteView[];
  all_direct_ready?: boolean | null;
}

// --- questions and attempts -------------------------------------------------------------------

export type AnswerShape = 'option_key' | 'option_keys' | 'value';

export interface DeliveredQuestion {
  question_id: string;
  version: number;
  item_type: string;
  answer_shape: AnswerShape;
  stem: string | null;
  difficulty: number | null;
  options: { option_key: string; option_text: string | null; display_order: number }[];
}

export interface QuestionPage extends Paged {
  kc_id: string;
  questions: DeliveredQuestion[];
}

export interface SubmittedAnswer {
  option_key?: string;
  option_keys?: string[];
  value?: number;
}

export interface AttemptResult {
  attempt_id: string;
  question_id: string;
  question_version: number;
  scored_correct: boolean;
  score: number;
  score_method: string;
  duplicate_replay: boolean;
  bkt: {
    updated: boolean;
    kc_id: string | null;
    mastery_probability: number | null;
    config_version: string | null;
    reason: string | null;
  };
}

// --- student progress ---------------------------------------------------------------------------

export interface MasteryEstimate {
  kc_id: string;
  topic_name: string | null;
  mastery_probability: number | null;
  evidence_count: number;
  bkt_config_version: string | null;
  updated_at: string | null;
}

export interface StudentProgress {
  learner_id: string;
  attempt_summary: { total_attempts: number; correct_attempts: number; incorrect_attempts: number };
  mastery_estimates: MasteryEstimate[];
}

export interface ChapterProgressTopic {
  kc_id: string;
  name: string | null;
  mastery_probability: number | null;
  evidence_count: number;
}

export interface ChapterProgress {
  item_id: string;
  title: string | null;
  subject_id: string | null;
  class_level: number;
  topics_total: number;
  topics_started: number;
  topics_mastered: number;
  average_mastery_probability: number | null;
  attempts: number;
  correct_attempts: number;
  accuracy: number | null;
  topics: ChapterProgressTopic[];
}

export interface SubjectProgress {
  subject_id: string;
  display_name: string;
  chapters_total: number;
  chapters_started: number;
  topics_total: number;
  topics_started: number;
  topics_mastered: number;
  average_mastery_probability: number | null;
  attempts: number;
  correct_attempts: number;
}

export interface ChapterProgressResponse {
  mastered_threshold: number;
  thresholds_provisional: boolean;
  subjects: SubjectProgress[];
  chapters: ChapterProgress[];
  note: string;
}

export interface WeakArea {
  kc_id: string;
  name: string | null;
  mastery_probability: number;
  evidence_count: number;
  reason: string;
}

export interface WeakAreasResponse {
  weak_below: number;
  min_evidence: number;
  thresholds_provisional: boolean;
  weak_areas: WeakArea[];
  note: string;
}

export interface RetryQuestion {
  question_id: string;
  item_type: string;
  stem: string | null;
  kc_ids: string[];
  last_attempted_at: string | null;
}

export interface ActivityAttempt {
  attempt_id: string;
  question_id: string;
  question_stem: string | null;
  item_type: string | null;
  scored_correct: boolean | null;
  hint_tier: number | null;
  attempted_at: string | null;
}

export interface ActivityPage extends Paged {
  attempts: ActivityAttempt[];
}

export interface Recommendation {
  status: 'ok' | 'insufficient_data';
  reason: string | null;
  detail: string[];
  kc_id: string | null;
  question_id: string | null;
  category: 'remediate_prerequisite' | 'continue' | 'new' | null;
  rationale: string[];
  mastery_probability: number | null;
  policy_version: string;
  graph_version: string | null;
  thresholds: Record<string, number | boolean> | null;
  content_release: 'production' | 'demo';
}

// --- tutor -----------------------------------------------------------------------------------

export interface Citation {
  source_id: string;
  label: string;
  item_title: string | null;
  pdf_page_index: number | null;
  printed_page_label: string | null;
}

export type DoubtStatus =
  | 'ok'
  | 'insufficient_evidence'
  | 'not_authorized'
  | 'model_unavailable'
  | 'model_timeout'
  | 'invalid_model_output';

export interface DoubtResponse {
  status: DoubtStatus;
  grounding: 'grounded' | 'abstained';
  message: string;
  concept: string;
  explanation: string;
  steps: string[];
  hint: string;
  citations: Citation[];
  model_id: string | null;
  prompt_version: string;
  content_release: 'production' | 'demo';
  conversation_id: string | null;
}

export interface ConversationSummary {
  conversation_id: string;
  class_level: number;
  subject_id: string | null;
  kc_id: string | null;
  updated_at: string;
}

export interface ConversationList extends Paged {
  conversations: ConversationSummary[];
}

export interface ConversationMessage {
  seq: number;
  role: 'student' | 'tutor';
  content: string;
  grounding: 'grounded' | 'abstained' | null;
  status: string | null;
  citations: Citation[];
  created_at: string;
}

export interface Conversation {
  conversation_id: string;
  class_level: number;
  subject_id: string | null;
  kc_id: string | null;
  messages: ConversationMessage[];
}

// --- notifications -----------------------------------------------------------------------------

export interface AppNotification {
  notification_id: string;
  kind: 'class_weak_area' | 'intervention_update' | 'review_outcome' | 'system';
  title: string;
  body: string | null;
  classroom_id: string | null;
  payload: Record<string, unknown> | null;
  is_synthetic: boolean;
  created_at: string;
  read_at: string | null;
}

export interface NotificationList extends Paged {
  unread_count: number;
  notifications: AppNotification[];
}

// --- teacher -----------------------------------------------------------------------------------

export interface TeacherClass extends ClassroomContext {
  learner_count: number;
}

export interface TeacherClassList {
  count: number;
  classes: TeacherClass[];
}

export interface TopicSignal {
  kc_id: string;
  topic_name: string | null;
  students_with_estimate: number;
  average_mastery_probability: number | null;
  below_0_5_count: number;
}

export interface ClassDashboard {
  classroom: ClassroomContext;
  learner_count: number;
  attempt_summary: { total_attempts: number; correct_attempts: number };
  topic_signals: TopicSignal[];
}

export interface RosterLearner {
  learner_id: string;
  display_name: string | null;
  attempts: number;
  correct_attempts: number;
  accuracy: number | null;
  topics_started: number;
  average_mastery_probability: number | null;
  last_attempt_at: string | null;
}

export interface Roster extends Paged {
  learners: RosterLearner[];
  note: string;
}

export interface LearnerProgress extends ChapterProgressResponse {
  learner_id: string;
  display_name: string | null;
  weak_areas: WeakArea[];
  recent_activity: ActivityPage;
}

export interface ClassWeakArea {
  kc_id: string;
  name: string | null;
  learners_with_evidence: number;
  learners_below_threshold: number;
  share_below_threshold: number;
  average_mastery_probability: number;
}

export interface ClassWeakAreas {
  learner_count: number;
  weak_below: number;
  min_evidence: number;
  thresholds_provisional: boolean;
  weak_areas: ClassWeakArea[];
  note: string;
}

export interface ReviewOption {
  option_key: string;
  option_text: string | null;
  is_correct: boolean;
  explanation: string | null;
}

export interface ReviewQuestion {
  question_id: string;
  version: number;
  item_type: string;
  stem: string | null;
  review_status: string;
  active: boolean;
  difficulty: number | null;
  expected_answer: unknown;
  options: ReviewOption[];
  explanation: string | null;
  origin: string | null;
  source_refs: { source_id?: string; pdf_page_index?: number }[];
  knowledge_components: { kc_id: string; name: string | null }[];
  ai_review: { verdict?: string; note?: string; reviewer?: string; date?: string } | null;
  human_reviews: { decision?: string; rationale?: string; reviewer?: string; reviewed_at?: string }[];
}

export interface ReviewQueue extends Paged {
  questions: ReviewQuestion[];
}

export type InterventionType =
  | 'reteach'
  | 'small_group'
  | 'individual_support'
  | 'practice_assignment'
  | 'other';
export type InterventionStatus = 'planned' | 'in_progress' | 'completed' | 'cancelled';

export interface Intervention {
  intervention_id: string;
  classroom_id: string;
  kc_id: string | null;
  learner_id: string | null;
  intervention_type: InterventionType;
  status: InterventionStatus;
  note: string | null;
  created_at: string | null;
  completed_at: string | null;
}

export interface InterventionList {
  count: number;
  interventions: Intervention[];
}

// --- Bell-Ringer and heatmap ------------------------------------------------------------------

export interface TeacherQuestionView {
  question_id: string;
  item_type: string;
  stem: string | null;
  difficulty: number | null;
  options: { option_key: string; option_text: string | null; is_correct: boolean }[];
  expected_answer: unknown;
  recorded_misconception: string | null;
  review_status: string | null;
}

export interface WarmUpCard {
  format: string;
  total_minutes: number;
  steps: { minutes: number; label: string; detail: string }[];
  board_question: TeacherQuestionView | null;
  bridge_question: TeacherQuestionView | null;
  watch_for:
    | { source: 'class_attempts'; option_key: string; option_text: string | null; wrong_attempts: number }
    | { source: 'recorded_misconception'; text: string }
    | null;
  available_questions: { target: number; topic: number };
  generated_by: string;
}

export interface RootGap {
  target_kc_id: string;
  target_name: string | null;
  is_prerequisite: boolean;
  graph_available: boolean;
  graph_version?: string;
  edge_provenance?: 'ai_proposed_demo' | 'released_snapshot';
  reason?: string;
  explanation: string;
  candidates: {
    kc_id: string;
    name: string | null;
    affected_learners_weak: number;
    affected_learners_without_evidence: number;
  }[];
}

export type UnmetCriterion =
  | 'coverage_below_minimum'
  | 'too_few_affected_learners'
  | 'affected_share_below_minimum';

export interface BellRingerTopic {
  kc_id: string;
  name: string | null;
  subject_id: string | null;
  item_id: string;
  item_title: string | null;
  enrolled_learners: number;
  learners_with_evidence: number;
  learners_below_threshold: number;
  learners_not_attempted: number;
  coverage: number;
  affected_share: number | null;
  average_mastery_probability: number | null;
  recent_attempts: number;
  recent_failed_attempts: number;
  recent_learners_with_failed_attempts: number;
  flagged: boolean;
  severity: 'high' | 'medium' | null;
  unmet_criteria: UnmetCriterion[];
  rank: number | null;
  root_gap?: RootGap;
  activity?: WarmUpCard;
}

export interface BellRingerCriteria {
  weak_below: number;
  min_evidence: number;
  min_coverage: number;
  min_affected_learners: number;
  min_affected_share: number;
  window_days: number;
  provisional: boolean;
}

export interface BellRingerTopics {
  classroom_id: string;
  grade_level: number | null;
  subject_id: string | null;
  enrolled_learners: number;
  window: { days: number; since: string; until: string };
  criteria: BellRingerCriteria;
  flagged_count: number;
  topics: BellRingerTopic[];
  cycles_enabled: boolean;
  note: string;
}

export type CycleStatus = 'planned' | 'in_progress' | 'completed' | 'cancelled';

export interface BellRingerCycle {
  cycle_id: string;
  classroom_id: string;
  kc_id: string;
  topic_name: string | null;
  root_kc_id: string | null;
  root_name: string | null;
  subject_id: string | null;
  item_title: string | null;
  status: CycleStatus;
  board_question_id: string | null;
  bridge_question_id: string | null;
  teacher_note: string | null;
  baseline: {
    captured_at?: string;
    window?: { days: number; since: string; until: string };
    flagged_at_creation?: boolean;
    enrolled_learners?: number;
    learners_with_evidence?: number;
    learners_below_threshold?: number;
    learners_not_attempted?: number;
    coverage?: number;
    affected_share?: number | null;
    average_mastery_probability?: number | null;
    recent_failed_attempts?: number;
    root_gap_explanation?: string;
    edge_provenance?: string;
  };
  affected_count: number;
  created_by: string;
  created_at: string | null;
  updated_at: string | null;
  started_at: string | null;
  completed_at: string | null;
}

export interface CycleFollowUp {
  since: string | null;
  affected_at_start: number;
  still_enrolled: number;
  now_at_or_above_cut_off: number;
  practised_since_start: number;
  weak_below: number;
  learners: {
    learner_id: string;
    display_name: string | null;
    mastery_at_start: number | null;
    mastery_now: number | null;
    now_at_or_above_cut_off: boolean;
    attempts_since_start: number;
    correct_since_start: number;
  }[];
  note: string;
}

export interface BellRingerCycleDetail extends BellRingerCycle {
  activity: WarmUpCard;
  follow_up: CycleFollowUp;
  created?: boolean;
}

export interface CycleList {
  count: number;
  cycles: BellRingerCycle[];
}

export type HeatBand = 'mastered' | 'developing' | 'needs_practice' | 'insufficient_evidence' | 'no_data';

export interface HeatCell {
  mastery_probability: number | null;
  evidence_count: number;
  attempts: number;
  correct: number;
  last_attempt_at: string | null;
  band: HeatBand;
}

export interface Heatmap {
  classroom_id: string;
  grade_level: number | null;
  subject_id: string | null;
  item_id: string | null;
  window_days: number | null;
  learner_count: number;
  topics: {
    kc_id: string;
    name: string | null;
    subject_id: string | null;
    item_id: string;
    item_title: string | null;
    learners_with_estimate: number;
    learners_needing_practice: number;
    average_mastery_probability: number | null;
  }[];
  learners: {
    learner_id: string;
    display_name: string | null;
    topics_with_estimate: number;
    average_mastery_probability: number | null;
    cells: HeatCell[];
  }[];
  truncated: boolean;
  thresholds_provisional: boolean;
  note: string;
}
