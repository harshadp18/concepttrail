import React, { Suspense, lazy } from 'react';
import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MotionConfig } from 'framer-motion';
import {
  BarChart3,
  Bell,
  BellRing,
  BookOpen,
  ClipboardCheck,
  GraduationCap,
  Grid3x3,
  History,
  Home,
  ListTodo,
  MessageCircle,
  Sparkles,
  Users,
} from 'lucide-react';
import { ApiError } from '@/api/http';
import { AuthProvider } from '@/context/AuthContext';
import { AppShell, NavItem } from '@/components/layout/AppShell';
import { ErrorBoundary } from '@/components/common/ErrorBoundary';
import { LoadingState } from '@/components/ui/states';
import { LandingPage } from '@/pages/public/LandingPage';
import { LoginPage } from '@/pages/auth/LoginPage';

const StudentHome = lazy(() => import('@/pages/student/StudentHome'));
const StudentSubjects = lazy(() => import('@/pages/student/StudentSubjects'));
const SubjectChapters = lazy(() => import('@/pages/student/SubjectChapters'));
const ChapterPage = lazy(() => import('@/pages/student/ChapterPage'));
const TopicPage = lazy(() => import('@/pages/student/TopicPage'));
const PracticePage = lazy(() => import('@/pages/student/PracticePage'));
const StudentProgress = lazy(() => import('@/pages/student/StudentProgress'));
const StudentRecommendations = lazy(() => import('@/pages/student/StudentRecommendations'));
const StudentHistory = lazy(() => import('@/pages/student/StudentHistory'));
const StudentReview = lazy(() => import('@/pages/student/StudentReview'));
const StudentBuddy = lazy(() => import('@/pages/student/StudentBuddy'));
const AlertsPage = lazy(() => import('@/pages/shared/AlertsPage'));
const ProfilePage = lazy(() => import('@/pages/shared/ProfilePage'));

const TeacherDashboard = lazy(() => import('@/pages/teacher/TeacherDashboard'));
const TeacherLearners = lazy(() => import('@/pages/teacher/TeacherLearners'));
const TeacherLearnerDetail = lazy(() => import('@/pages/teacher/TeacherLearnerDetail'));
const TeacherHeatmap = lazy(() => import('@/pages/teacher/TeacherHeatmap'));
const TeacherBellRinger = lazy(() => import('@/pages/teacher/TeacherBellRinger'));
const TeacherCycleDetail = lazy(() => import('@/pages/teacher/TeacherCycleDetail'));
const TeacherReviewQueue = lazy(() => import('@/pages/teacher/TeacherReviewQueue'));
const TeacherInterventions = lazy(() => import('@/pages/teacher/TeacherInterventions'));

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      refetchOnWindowFocus: false,
      staleTime: 30_000,
      // client errors (4xx) and switched-off features are answers, not glitches: do not retry
      retry: (count, error) =>
        count < 1 && !(error instanceof ApiError && (error.status >= 400 && error.status < 500 || error.isFeatureDisabled)),
    },
  },
});

const STUDENT_NAV: NavItem[] = [
  { label: 'Home', to: '/student/home', icon: Home, mobile: true },
  { label: 'Subjects', to: '/student/subjects', icon: BookOpen, mobile: true, match: ['/student/chapters', '/student/topics'] },
  { label: 'Progress', to: '/student/progress', icon: BarChart3, mobile: true },
  { label: 'Next steps', to: '/student/recommendations', icon: Sparkles, match: ['/student/review'] },
  { label: 'Buddy', to: '/student/buddy', icon: MessageCircle, mobile: true },
  { label: 'History', to: '/student/history', icon: History },
  { label: 'Alerts', to: '/student/alerts', icon: Bell, mobile: true },
];

const TEACHER_NAV: NavItem[] = [
  { label: 'Classes', to: '/teacher/classes', icon: GraduationCap, mobile: true },
  { label: 'Learners', to: '/teacher/learners', icon: Users, mobile: true },
  { label: 'Heatmap', to: '/teacher/heatmap', icon: Grid3x3, mobile: true },
  { label: 'Bell Ringer', to: '/teacher/bell-ringer', icon: BellRing, mobile: true },
  { label: 'Reviews', to: '/teacher/reviews', icon: ClipboardCheck },
  { label: 'Plans', to: '/teacher/interventions', icon: ListTodo },
  { label: 'Alerts', to: '/teacher/alerts', icon: Bell, mobile: true },
];

const Page: React.FC<{ children: React.ReactNode }> = ({ children }) => (
  <ErrorBoundary>
    <Suspense fallback={<LoadingState label="Loading page" />}>{children}</Suspense>
  </ErrorBoundary>
);

export const App: React.FC = () => (
  <QueryClientProvider client={queryClient}>
    <MotionConfig reducedMotion="user">
      <BrowserRouter>
        <AuthProvider>
          <Routes>
            <Route path="/" element={<LandingPage />} />
            <Route path="/login" element={<LoginPage />} />

            <Route
              path="/student"
              element={<AppShell role="student" items={STUDENT_NAV} profilePath="/student/profile" alertsPath="/student/alerts" />}
            >
              <Route index element={<Navigate to="home" replace />} />
              <Route path="home" element={<Page><StudentHome /></Page>} />
              <Route path="subjects" element={<Page><StudentSubjects /></Page>} />
              <Route path="subjects/:subjectId" element={<Page><SubjectChapters /></Page>} />
              <Route path="chapters/:itemId" element={<Page><ChapterPage /></Page>} />
              <Route path="topics/:kcId" element={<Page><TopicPage /></Page>} />
              <Route path="topics/:kcId/practice" element={<Page><PracticePage /></Page>} />
              <Route path="progress" element={<Page><StudentProgress /></Page>} />
              <Route path="recommendations" element={<Page><StudentRecommendations /></Page>} />
              <Route path="review" element={<Page><StudentReview /></Page>} />
              <Route path="history" element={<Page><StudentHistory /></Page>} />
              <Route path="buddy" element={<Page><StudentBuddy /></Page>} />
              <Route path="alerts" element={<Page><AlertsPage /></Page>} />
              <Route path="profile" element={<Page><ProfilePage /></Page>} />
              <Route path="learn/*" element={<Navigate to="/student/subjects" replace />} />
              <Route path="*" element={<Navigate to="/student/home" replace />} />
            </Route>

            <Route
              path="/teacher"
              element={<AppShell role="teacher" items={TEACHER_NAV} profilePath="/teacher/profile" alertsPath="/teacher/alerts" />}
            >
              <Route index element={<Navigate to="classes" replace />} />
              <Route path="classes" element={<Page><TeacherDashboard /></Page>} />
              <Route path="learners" element={<Page><TeacherLearners /></Page>} />
              <Route path="learners/:learnerId" element={<Page><TeacherLearnerDetail /></Page>} />
              <Route path="heatmap" element={<Page><TeacherHeatmap /></Page>} />
              <Route path="bell-ringer" element={<Page><TeacherBellRinger /></Page>} />
              <Route path="bell-ringer/:cycleId" element={<Page><TeacherCycleDetail /></Page>} />
              <Route path="reviews" element={<Page><TeacherReviewQueue /></Page>} />
              <Route path="interventions" element={<Page><TeacherInterventions /></Page>} />
              <Route path="alerts" element={<Page><AlertsPage /></Page>} />
              <Route path="profile" element={<Page><ProfilePage /></Page>} />
              <Route path="settings" element={<Navigate to="/teacher/profile" replace />} />
              <Route path="*" element={<Navigate to="/teacher/classes" replace />} />
            </Route>

            <Route path="*" element={<Navigate to="/" replace />} />
          </Routes>
        </AuthProvider>
      </BrowserRouter>
    </MotionConfig>
  </QueryClientProvider>
);

export default App;
