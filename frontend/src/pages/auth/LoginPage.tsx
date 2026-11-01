import React, { useEffect, useRef, useState } from 'react';
import { Link, Navigate, useNavigate, useSearchParams } from 'react-router-dom';
import { AnimatePresence, motion } from 'framer-motion';
import { AlertCircle, ArrowLeft, Eye, EyeOff, GraduationCap, Info, School } from 'lucide-react';
import { BrandLogo } from '@/components/brand/BrandLogo';
import { ApiError } from '@/api/http';
import { RoleMismatchError, useAuth, UserRole } from '@/context/AuthContext';
import { cx } from '@/components/ui/primitives';
import { ease } from '@/components/ui/motion';
import studentArt from '@/assets/illustrations/student-learning.svg';
import teacherArt from '@/assets/illustrations/teacher-insights.svg';

const PANEL: Record<
  UserRole,
  { eyebrow: string; headline: string; body: string; card: string; cardBody: string; chips: [string, string][]; art: string; artAlt: string }
> = {
  student: {
    eyebrow: 'Your learning, your pace',
    headline: 'Learn, practise and grow.',
    body: 'Pick up where you left off across Mathematics, Science, English, Hindi and Social Science.',
    card: 'Made for CBSE Classes 6–10',
    cardBody: 'Understand an idea, practise it, and watch your mastery estimate grow with every answer.',
    chips: [
      ['Learn', 'bg-brand-50 text-brand-700'],
      ['Practise', 'bg-band-practice-bg text-band-practice'],
      ['Grow', 'bg-band-mastered-bg text-band-mastered'],
    ],
    art: studentArt,
    artAlt: 'An open book on a winding learning trail with progress cards',
  },
  teacher: {
    eyebrow: 'Teacher workspace',
    headline: 'See progress. Support every learner.',
    body: 'Find where your classes are struggling, plan a five-minute Bell Ringer, and follow up with the learners who need it.',
    card: 'Insight you can act on tomorrow',
    cardBody: 'Class heatmaps, topic-level Bell Ringers and question reviews for the classes your school assigns you.',
    chips: [
      ['Understand', 'bg-brand-50 text-brand-700'],
      ['Guide', 'bg-amber-50 text-amber-800'],
      ['Empower', 'bg-band-mastered-bg text-band-mastered'],
    ],
    art: teacherArt,
    artAlt: 'A class heatmap grid next to a Bell Ringer icon',
  },
};

function errorMessage(err: unknown, role: UserRole): { title: string; body: string } {
  if (err instanceof RoleMismatchError) return { title: 'Wrong sign-in option', body: err.message };
  if (err instanceof ApiError) {
    if (err.code === 'too_many_login_attempts' || err.status === 429) {
      return {
        title: 'Too many attempts',
        body: err.retryAfter
          ? `Sign-in is paused for this account. Try again in about ${Math.ceil(err.retryAfter / 60)} minute(s).`
          : 'Sign-in is paused for a short time. Please wait and try again.',
      };
    }
    if (err.isNetwork) return { title: 'Cannot reach ConceptTrail', body: err.message };
    if (err.status === 401 || err.code === 'invalid_credentials') {
      return role === 'student'
        ? { title: "That username and PIN don't match", body: 'Check both fields and try again.' }
        : { title: "That email and password don't match", body: 'Check both fields and try again.' };
    }
    if (err.status === 422) return { title: 'Check the form', body: 'Please fill in both fields correctly.' };
    return { title: 'Sign-in failed', body: err.message };
  }
  return { title: 'Sign-in failed', body: 'Please try again.' };
}

export const LoginPage: React.FC = () => {
  const [params] = useSearchParams();
  const { login, user, sessionExpired } = useAuth();
  const navigate = useNavigate();
  const [role, setRole] = useState<UserRole>(params.get('role') === 'teacher' ? 'teacher' : 'student');
  // each role keeps its own fields so switching tabs never wipes what was typed
  const [fields, setFields] = useState({ student: { id: '', secret: '' }, teacher: { id: '', secret: '' } });
  const [showSecret, setShowSecret] = useState(false);
  const [error, setError] = useState<{ title: string; body: string } | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const idRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    setError(null);
    setShowSecret(false);
  }, [role]);

  if (user) return <Navigate to={user.role === 'teacher' ? '/teacher/classes' : '/student/home'} replace />;

  const panel = PANEL[role];
  const isStudent = role === 'student';
  const current = fields[role];
  const pinInvalid = isStudent && current.secret.length > 0 && !/^\d{8}$/.test(current.secret);

  const update = (key: 'id' | 'secret', value: string) =>
    setFields((f) => ({ ...f, [role]: { ...f[role], [key]: isStudent && key === 'secret' ? value.replace(/\D/g, '').slice(0, 8) : value } }));

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (isStudent && !/^\d{8}$/.test(current.secret)) {
      setError({ title: 'Check your PIN', body: 'Your PIN has exactly 8 digits.' });
      return;
    }
    setSubmitting(true);
    setError(null);
    try {
      await login(current.id, current.secret, role);
      const next = params.get('next');
      const home = isStudent ? '/student/home' : '/teacher/classes';
      navigate(next && next.startsWith(isStudent ? '/student/' : '/teacher/') ? next : home, { replace: true });
    } catch (err) {
      setError(errorMessage(err, role));
      setFields((f) => ({ ...f, [role]: { ...f[role], secret: '' } }));
      idRef.current?.focus();
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="min-h-screen bg-white md:grid md:grid-cols-[minmax(0,5fr)_minmax(0,7fr)]">
      {/* Role-specific brand panel */}
      <aside
        className={cx(
          'relative overflow-hidden px-6 py-8 sm:px-10 lg:px-14 lg:py-12 md:min-h-screen flex flex-col transition-colors duration-500',
          isStudent ? 'bg-brand-50' : 'bg-[#EEF5F3]'
        )}
      >
        <BrandLogo size="lg" linkTo="/" />
        <AnimatePresence mode="wait">
          <motion.div
            key={role}
            initial={{ opacity: 0, y: 12 }}
            animate={{ opacity: 1, y: 0, transition: { duration: 0.35, ease } }}
            exit={{ opacity: 0, y: -8, transition: { duration: 0.15 } }}
            className="mt-8 md:mt-14 lg:mt-16 max-w-md"
          >
            <p className={cx('t-eyebrow', isStudent ? 'text-brand-600' : 'text-brand-teal-deep')}>{panel.eyebrow}</p>
            <h2 className="mt-3 text-3xl lg:text-[40px] font-extrabold leading-[1.12] tracking-tight text-ctText-primary">
              {panel.headline}
            </h2>
            <p className="mt-4 text-sm leading-relaxed text-ctText-body">{panel.body}</p>
            <img src={panel.art} alt={panel.artAlt} className="mt-6 hidden w-full max-w-sm md:block" />
            <div className="mt-6 hidden md:block rounded-2xl border border-white bg-white/85 p-5 shadow-card">
              <h3 className="t-card">{panel.card}</h3>
              <p className="mt-1.5 text-xs leading-relaxed text-ctText-muted">{panel.cardBody}</p>
              <div className="mt-4 flex flex-wrap gap-2">
                {panel.chips.map(([label, cls]) => (
                  <span key={label} className={cx('pill text-xs px-3 py-1', cls)}>
                    {label}
                  </span>
                ))}
              </div>
            </div>
          </motion.div>
        </AnimatePresence>
        <p className="mt-auto hidden pt-8 text-2xs text-ctText-subtle md:block">
          Accounts are provided by your school. There is no public sign-up.
        </p>
      </aside>

      {/* Form */}
      <main className="flex items-start justify-center px-6 py-10 sm:px-10 md:items-center lg:px-16">
        <div className="w-full max-w-md">
          <Link to="/" className="inline-flex items-center gap-1.5 text-xs font-semibold text-brand-600 hover:text-brand-700 focus-ring rounded">
            <ArrowLeft size={14} /> Back to ConceptTrail
          </Link>

          <h1 className="mt-6 t-page">{isStudent ? 'Welcome back!' : 'Welcome, teacher'}</h1>
          <p className="mt-1.5 text-sm text-ctText-muted">
            {isStudent
              ? 'Sign in with the username and 8-digit PIN your school gave you.'
              : 'Sign in with your school email and password.'}
          </p>

          <div role="tablist" aria-label="Sign in as" className="mt-6 grid grid-cols-2 gap-1 rounded-xl bg-surface-muted p-1">
            {(['student', 'teacher'] as UserRole[]).map((r) => (
              <button
                key={r}
                role="tab"
                type="button"
                aria-selected={role === r}
                aria-controls="login-form"
                onClick={() => setRole(r)}
                className={cx(
                  'relative flex h-10 items-center justify-center gap-2 rounded-lg text-sm font-semibold transition-colors focus-ring',
                  role === r ? 'text-brand-700' : 'text-ctText-muted hover:text-ctText-primary'
                )}
              >
                {role === r && (
                  <motion.span layoutId="role-tab" className="absolute inset-0 rounded-lg bg-white shadow-sm" transition={{ type: 'spring', stiffness: 500, damping: 38 }} />
                )}
                <span className="relative flex items-center gap-2">
                  {r === 'student' ? <GraduationCap size={16} /> : <School size={16} />}
                  {r === 'student' ? 'Student' : 'Teacher'}
                </span>
              </button>
            ))}
          </div>

          {sessionExpired && !error && (
            <p className="mt-5 rounded-xl border border-feedback-info-border bg-feedback-info-bg px-4 py-3 text-xs text-feedback-info" role="status">
              Your session ended. Please sign in again.
            </p>
          )}

          <AnimatePresence>
            {error && (
              <motion.div
                key="err"
                initial={{ opacity: 0, height: 0 }}
                animate={{ opacity: 1, height: 'auto' }}
                exit={{ opacity: 0, height: 0 }}
                className="overflow-hidden"
              >
                <div role="alert" className="mt-5 flex items-start gap-3 rounded-xl border border-feedback-error-border bg-feedback-error-bg p-4">
                  <AlertCircle className="mt-0.5 shrink-0 text-feedback-error" size={18} />
                  <div className="text-xs">
                    <p className="font-bold text-feedback-error">{error.title}</p>
                    <p className="mt-0.5 text-feedback-error/90">{error.body}</p>
                  </div>
                </div>
              </motion.div>
            )}
          </AnimatePresence>

          <form id="login-form" onSubmit={submit} className="mt-6 space-y-4" noValidate>
            <div>
              <label htmlFor="login-id" className="field-label">
                {isStudent ? 'Username' : 'School email'}
              </label>
              <input
                id="login-id"
                ref={idRef}
                type={isStudent ? 'text' : 'email'}
                autoComplete="username"
                autoCapitalize="none"
                spellCheck={false}
                value={current.id}
                onChange={(e) => update('id', e.target.value)}
                placeholder={isStudent ? 'Username from your school' : 'name@school.example'}
                required
                className={cx('field', error && 'border-feedback-error-border')}
              />
            </div>
            <div>
              <label htmlFor="login-secret" className="field-label">
                {isStudent ? '8-digit PIN' : 'Password'}
              </label>
              <div className="relative">
                <input
                  id="login-secret"
                  type={showSecret ? 'text' : 'password'}
                  inputMode={isStudent ? 'numeric' : undefined}
                  autoComplete="current-password"
                  value={current.secret}
                  onChange={(e) => update('secret', e.target.value)}
                  maxLength={isStudent ? 8 : 256}
                  required
                  aria-invalid={pinInvalid || undefined}
                  aria-describedby="secret-help"
                  className={cx('field pr-12', (error || pinInvalid) && 'border-feedback-error-border')}
                />
                <button
                  type="button"
                  onClick={() => setShowSecret((s) => !s)}
                  className="absolute right-2 top-1/2 -translate-y-1/2 rounded-lg p-2 text-ctText-subtle hover:text-ctText-body focus-ring"
                  aria-label={showSecret ? `Hide ${isStudent ? 'PIN' : 'password'}` : `Show ${isStudent ? 'PIN' : 'password'}`}
                >
                  {showSecret ? <EyeOff size={16} /> : <Eye size={16} />}
                </button>
              </div>
              <p id="secret-help" className={cx('mt-1.5 text-2xs', pinInvalid ? 'text-feedback-error' : 'text-ctText-muted')}>
                {isStudent
                  ? pinInvalid
                    ? `Your PIN has 8 digits (${current.secret.length} entered).`
                    : 'Keep your PIN private. Never type it into Buddy.'
                  : 'Use the password issued by your school.'}
              </p>
            </div>
            <button type="submit" disabled={submitting || !current.id || !current.secret} className="btn btn-primary btn-lg w-full rounded-full">
              {submitting ? 'Signing in…' : isStudent ? 'Sign in' : 'Sign in to teacher workspace'}
            </button>
          </form>

          <div className="mt-8 flex items-start gap-3 rounded-2xl border border-surface-border bg-surface-subtle p-4 text-xs">
            <Info className="mt-0.5 shrink-0 text-brand-600" size={16} />
            <div>
              <p className="font-bold text-ctText-primary">
                {isStudent ? 'Forgot your username or PIN?' : 'Need access or a password reset?'}
              </p>
              <p className="mt-0.5 leading-relaxed text-ctText-muted">
                {isStudent
                  ? 'Ask your class teacher or the school office. ConceptTrail accounts are created by your school.'
                  : 'Contact your school administrator. Class assignments are managed by the school.'}
              </p>
            </div>
          </div>
        </div>
      </main>
    </div>
  );
};

export default LoginPage;
