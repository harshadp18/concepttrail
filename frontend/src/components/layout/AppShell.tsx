import React from 'react';
import { Link, Navigate, NavLink, useLocation, useNavigate, useOutlet } from 'react-router-dom';
import { AnimatePresence, motion } from 'framer-motion';
import * as DropdownMenu from '@radix-ui/react-dropdown-menu';
import type { LucideIcon } from 'lucide-react';
import { Bell, ChevronDown, LogOut, UserRound } from 'lucide-react';
import { BrandLogo } from '@/components/brand/BrandLogo';
import { useNotifications } from '@/api/hooks';
import { classLabel, personName, useAuth, UserRole } from '@/context/AuthContext';
import { teacherClassName, TeacherClassProvider, useTeacherClass } from '@/context/TeacherClassContext';
import { LoadingState } from '@/components/ui/states';
import { cx } from '@/components/ui/primitives';
import { pageTransition } from '@/components/ui/motion';

export interface NavItem {
  label: string;
  to: string;
  icon: LucideIcon;
  /** Shown in the mobile bottom bar (max five). */
  mobile?: boolean;
  /** Extra path prefixes that keep this item active. */
  match?: string[];
}

function isActive(pathname: string, item: NavItem) {
  return [item.to, ...(item.match ?? [])].some((p) => pathname === p || pathname.startsWith(`${p}/`));
}

const Sidebar: React.FC<{ items: NavItem[]; label: string }> = ({ items, label }) => {
  const { pathname } = useLocation();
  return (
    <aside className="hidden md:flex fixed inset-y-0 left-0 z-40 w-[88px] flex-col items-center border-r border-surface-border bg-white py-5">
      <BrandLogo variant="mark" size="md" linkTo={null} className="mb-8" />
      <nav aria-label={label} className="flex w-full flex-1 flex-col items-center gap-1.5 px-2">
        {items.map((item) => {
          const active = isActive(pathname, item);
          const Icon = item.icon;
          return (
            <NavLink
              key={item.to}
              to={item.to}
              aria-current={active ? 'page' : undefined}
              className={cx(
                'relative flex h-[60px] w-full flex-col items-center justify-center gap-1 rounded-2xl text-[11px] font-semibold transition-colors focus-ring',
                active ? 'text-white' : 'text-ctText-muted hover:bg-surface-muted hover:text-ctText-primary'
              )}
            >
              {active && (
                <motion.span
                  layoutId={`${label}-active`}
                  className="absolute inset-0 rounded-2xl bg-brand-700 shadow-sm"
                  transition={{ type: 'spring', stiffness: 420, damping: 36 }}
                />
              )}
              <Icon size={20} className="relative" aria-hidden />
              <span className="relative leading-none">{item.label}</span>
            </NavLink>
          );
        })}
      </nav>
    </aside>
  );
};

const MobileNav: React.FC<{ items: NavItem[]; label: string }> = ({ items, label }) => {
  const { pathname } = useLocation();
  const shown = items.filter((i) => i.mobile).slice(0, 5);
  return (
    <nav
      aria-label={`${label} (mobile)`}
      className="md:hidden fixed inset-x-0 bottom-0 z-40 border-t border-surface-border bg-white/95 backdrop-blur pb-[env(safe-area-inset-bottom)]"
    >
      <ul className="grid" style={{ gridTemplateColumns: `repeat(${shown.length}, minmax(0, 1fr))` }}>
        {shown.map((item) => {
          const active = isActive(pathname, item);
          const Icon = item.icon;
          return (
            <li key={item.to}>
              <NavLink
                to={item.to}
                aria-current={active ? 'page' : undefined}
                className={cx(
                  'flex h-16 flex-col items-center justify-center gap-1 text-[11px] font-semibold focus-ring',
                  active ? 'text-brand-700' : 'text-ctText-muted'
                )}
              >
                <span className={cx('flex h-8 w-12 items-center justify-center rounded-full transition-colors', active && 'bg-brand-50')}>
                  <Icon size={19} aria-hidden />
                </span>
                {item.label}
              </NavLink>
            </li>
          );
        })}
      </ul>
    </nav>
  );
};

const NotificationBell: React.FC<{ to: string }> = ({ to }) => {
  const query = useNotifications();
  const unread = query.data?.unread_count ?? 0;
  return (
    <Link
      to={to}
      aria-label={unread ? `Alerts, ${unread} unread` : 'Alerts'}
      className="relative flex h-10 w-10 items-center justify-center rounded-full border border-surface-border bg-white text-ctText-body shadow-card hover:bg-surface-subtle focus-ring"
    >
      <Bell size={17} aria-hidden />
      <AnimatePresence>
        {unread > 0 && (
          <motion.span
            initial={{ scale: 0 }}
            animate={{ scale: 1 }}
            exit={{ scale: 0 }}
            className="absolute -right-0.5 -top-0.5 min-w-[18px] rounded-full bg-feedback-error px-1 text-center text-[10px] font-bold leading-[18px] text-white ring-2 ring-white"
          >
            {unread > 9 ? '9+' : unread}
          </motion.span>
        )}
      </AnimatePresence>
    </Link>
  );
};

const ClassSwitcher: React.FC = () => {
  const { classes, selected, select } = useTeacherClass();
  if (!classes.length) return null;
  return (
    <label className="flex items-center gap-2">
      <span className="sr-only">Class</span>
      <select
        className="field-select max-w-[150px] sm:max-w-[200px]"
        value={selected?.classroom_id ?? ''}
        onChange={(e) => select(e.target.value)}
        aria-label="Choose class"
      >
        {classes.map((c) => (
          <option key={c.classroom_id} value={c.classroom_id}>
            {teacherClassName(c)}
          </option>
        ))}
      </select>
    </label>
  );
};

const TopBar: React.FC<{ role: UserRole; profilePath: string; alertsPath: string }> = ({ role, profilePath, alertsPath }) => {
  const { user, logout } = useAuth();
  const navigate = useNavigate();
  const name = personName(user);
  const initials =
    name
      .replace(/[^A-Za-z0-9 ]/g, ' ')
      .split(/\s+/)
      .filter(Boolean)
      .slice(0, 2)
      .map((w) => w[0]?.toUpperCase())
      .join('') || (role === 'teacher' ? 'T' : 'S');
  return (
    <div className="sticky top-0 z-30 border-b border-surface-border/70 bg-surface-subtle/85 backdrop-blur">
      <div className="mx-auto flex h-16 max-w-page items-center justify-between gap-3 px-4 sm:px-6 lg:px-8">
        <div className="flex items-center gap-3 min-w-0">
          <span className="md:hidden">
            <BrandLogo variant="mark" size="sm" linkTo={null} />
          </span>
          <span className={cx('pill', role === 'teacher' ? 'hidden sm:inline-flex bg-brand-700 text-white' : 'bg-brand-50 text-brand-700 ring-1 ring-inset ring-brand-100')}>
            {role === 'teacher' ? 'Teacher' : 'Student'}
          </span>
          {role === 'student' ? (
            <span className="hidden sm:inline text-xs font-semibold text-ctText-muted truncate">{classLabel(user?.primaryClass)}</span>
          ) : (
            <ClassSwitcher />
          )}
        </div>
        <div className="flex items-center gap-2.5">
          <NotificationBell to={alertsPath} />
          <DropdownMenu.Root>
            <DropdownMenu.Trigger asChild>
              <button
                type="button"
                className="flex items-center gap-1.5 rounded-full border border-surface-border bg-white py-1 pl-1 pr-2 shadow-card hover:bg-surface-subtle focus-ring"
                aria-label="Account menu"
              >
                <span className="flex h-8 w-8 items-center justify-center rounded-full bg-brand-100 text-xs font-bold text-brand-700">
                  {initials}
                </span>
                <ChevronDown size={14} className="text-ctText-muted" aria-hidden />
              </button>
            </DropdownMenu.Trigger>
            <DropdownMenu.Portal>
              <DropdownMenu.Content
                align="end"
                sideOffset={8}
                className="z-50 w-64 rounded-2xl border border-surface-border bg-white p-2 shadow-elevated"
              >
                <div className="border-b border-surface-border-subtle px-3 py-2.5">
                  <p className="truncate text-sm font-bold text-ctText-primary">{name}</p>
                  <p className="truncate text-xs text-ctText-muted">{user?.login_identifier}</p>
                </div>
                <DropdownMenu.Item
                  onSelect={() => navigate(profilePath)}
                  className="mt-1 flex cursor-pointer items-center gap-2.5 rounded-xl px-3 py-2 text-sm text-ctText-body outline-none data-[highlighted]:bg-brand-50 data-[highlighted]:text-brand-700"
                >
                  <UserRound size={15} aria-hidden /> Profile and preferences
                </DropdownMenu.Item>
                <DropdownMenu.Item
                  onSelect={() => logout('/login')}
                  className="flex cursor-pointer items-center gap-2.5 rounded-xl px-3 py-2 text-sm text-feedback-error outline-none data-[highlighted]:bg-feedback-error-bg"
                >
                  <LogOut size={15} aria-hidden /> Sign out
                </DropdownMenu.Item>
              </DropdownMenu.Content>
            </DropdownMenu.Portal>
          </DropdownMenu.Root>
        </div>
      </div>
    </div>
  );
};

/** Authenticated shell for one role. Route protection is UX only; the API enforces access. */
export const AppShell: React.FC<{
  role: UserRole;
  items: NavItem[];
  profilePath: string;
  alertsPath: string;
}> = ({ role, items, profilePath, alertsPath }) => {
  const { user, isRestoring } = useAuth();
  const location = useLocation();
  // Capture this route's element: an exiting page must keep rendering its own route, otherwise
  // <Outlet> inside the exiting child would mount the next page twice during the transition.
  const outlet = useOutlet();
  if (isRestoring) {
    return (
      <div className="mx-auto max-w-page p-8">
        <LoadingState label="Restoring your session" />
      </div>
    );
  }
  if (!user) {
    const next = encodeURIComponent(location.pathname + location.search);
    return <Navigate to={`/login?role=${role}&next=${next}`} replace />;
  }
  if (user.role !== role) {
    return <Navigate to={user.role === 'teacher' ? '/teacher/classes' : '/student/home'} replace />;
  }
  const body = (
    <div className="min-h-screen bg-surface-subtle">
      <a href="#main" className="sr-only focus:not-sr-only focus:fixed focus:left-3 focus:top-3 focus:z-50 btn btn-primary">
        Skip to content
      </a>
      <Sidebar items={items} label={role === 'teacher' ? 'Teacher navigation' : 'Student navigation'} />
      <div className="md:pl-[88px]">
        <TopBar role={role} profilePath={profilePath} alertsPath={alertsPath} />
        <main id="main" className="mx-auto max-w-page px-4 pb-28 pt-6 sm:px-6 md:pb-14 lg:px-8 lg:pt-8">
          <AnimatePresence mode="wait" initial={false}>
            <motion.div key={location.pathname} {...pageTransition}>
              {outlet}
            </motion.div>
          </AnimatePresence>
        </main>
      </div>
      <MobileNav items={items} label={role === 'teacher' ? 'Teacher navigation' : 'Student navigation'} />
    </div>
  );
  return role === 'teacher' ? <TeacherClassProvider>{body}</TeacherClassProvider> : body;
};
