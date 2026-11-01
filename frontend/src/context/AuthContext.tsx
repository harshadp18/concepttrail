import React, { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useQueryClient } from '@tanstack/react-query';
import { auth } from '@/api/endpoints';
import { ApiError, UNAUTHORIZED_EVENT, session } from '@/api/http';
import type { ClassroomContext, Me } from '@/api/types';

export type UserRole = 'student' | 'teacher';

export interface AuthUser extends Me {
  role: UserRole;
  /** Learners have one active class; teachers may have several. */
  primaryClass: ClassroomContext | null;
}

interface AuthContextType {
  user: AuthUser | null;
  role: UserRole | null;
  isAuthenticated: boolean;
  /** True while an existing session is being restored on page load. */
  isRestoring: boolean;
  sessionExpired: boolean;
  login: (identifier: string, credential: string, role: UserRole) => Promise<void>;
  logout: (redirectTo?: string) => void;
}

const AuthContext = createContext<AuthContextType | undefined>(undefined);

function toUser(me: Me): AuthUser | null {
  const role: UserRole | null = me.roles.includes('teacher')
    ? 'teacher'
    : me.roles.includes('student')
      ? 'student'
      : null;
  if (!role) return null;
  const classes = role === 'student' ? me.enrolled_classrooms : me.assigned_classrooms;
  return { ...me, role, primaryClass: classes[0] ?? null };
}

export class RoleMismatchError extends Error {
  constructor(readonly actualRole: UserRole) {
    super(
      actualRole === 'teacher'
        ? 'This is a teacher account. Switch to "Teacher" to sign in.'
        : 'This is a student account. Switch to "Student" to sign in.'
    );
  }
}

export const AuthProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [user, setUser] = useState<AuthUser | null>(null);
  const [isRestoring, setIsRestoring] = useState<boolean>(() => session.read() !== null);
  const [sessionExpired, setSessionExpired] = useState(false);

  useEffect(() => {
    if (!session.read()) return;
    let cancelled = false;
    auth
      .me()
      .then((me) => {
        if (!cancelled) setUser(toUser(me));
      })
      .catch(() => {
        if (!cancelled) session.clear();
      })
      .finally(() => {
        if (!cancelled) setIsRestoring(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    const onUnauthorized = () => {
      setUser((current) => {
        if (current) setSessionExpired(true);
        return null;
      });
      queryClient.clear();
    };
    window.addEventListener(UNAUTHORIZED_EVENT, onUnauthorized);
    return () => window.removeEventListener(UNAUTHORIZED_EVENT, onUnauthorized);
  }, [queryClient]);

  const login = useCallback(
    async (identifier: string, credential: string, role: UserRole) => {
      const result = await auth.login(identifier.trim(), credential);
      const next = toUser(result.identity);
      if (!next) throw new ApiError(403, 'forbidden_role', 'This account has no ConceptTrail role.');
      if (next.role !== role) throw new RoleMismatchError(next.role);
      session.write(result.access_token, result.expires_in);
      queryClient.clear();
      setSessionExpired(false);
      setUser(next);
    },
    [queryClient]
  );

  const logout = useCallback(
    (redirectTo = '/login') => {
      session.clear();
      queryClient.clear();
      setUser(null);
      setSessionExpired(false);
      navigate(redirectTo, { replace: true });
    },
    [navigate, queryClient]
  );

  const value = useMemo(
    () => ({
      user,
      role: user?.role ?? null,
      isAuthenticated: !!user,
      isRestoring,
      sessionExpired,
      login,
      logout,
    }),
    [user, isRestoring, sessionExpired, login, logout]
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
};

export const useAuth = () => {
  const context = useContext(AuthContext);
  if (!context) throw new Error('useAuth must be used within an AuthProvider');
  return context;
};

export function classLabel(c: ClassroomContext | null | undefined): string {
  if (!c) return 'No class';
  const section = c.section_label ?? '';
  return `Class ${c.grade_level ?? '?'}${section ? (section.length <= 2 ? section : ` · ${section}`) : ''}`;
}

/**
 * A person's name for display. Learners have a stored display name; teacher accounts have none in
 * the schema, so a "first.last@school" sign-in email is shown as "First Last" (never invented).
 */
export function personName(user: Pick<Me, 'display_name' | 'login_identifier'> | null | undefined): string {
  if (!user) return '';
  if (user.display_name) return user.display_name;
  const local = user.login_identifier.split('@')[0];
  if (user.login_identifier.includes('@') && local.includes('.')) {
    return local
      .split(/[._-]+/)
      .filter((w) => w && !/^\d+$/.test(w))
      .map((w) => w[0].toUpperCase() + w.slice(1))
      .join(' ');
  }
  return user.login_identifier;
}
