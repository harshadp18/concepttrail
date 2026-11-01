import React from 'react';
import { motion } from 'framer-motion';
import { AlertTriangle, Clock, Lock, RefreshCw, SearchX, WifiOff } from 'lucide-react';
import { ApiError } from '@/api/http';
import emptyArt from '@/assets/illustrations/empty-trail.svg';
import { cx } from './primitives';
import { ease } from './motion';

export const Skeleton: React.FC<{ className?: string }> = ({ className }) => (
  // a span so it can sit inside headings and paragraphs while text loads
  <span className={cx('skeleton', className?.includes('inline-block') ? '' : 'block', className)} aria-hidden />
);

/** Placeholder blocks shaped like the content; announces loading to assistive tech. */
export const LoadingState: React.FC<{ label?: string; rows?: number; className?: string }> = ({
  label = 'Loading',
  rows = 3,
  className,
}) => (
  <div className={cx('space-y-3', className)} role="status" aria-live="polite">
    <span className="sr-only">{label}…</span>
    {Array.from({ length: rows }).map((_, i) => (
      <Skeleton key={i} className={i === 0 ? 'h-24' : 'h-16'} />
    ))}
  </div>
);

export const EmptyState: React.FC<{
  title: string;
  body?: React.ReactNode;
  action?: React.ReactNode;
  art?: string | null;
  icon?: React.ReactNode;
  compact?: boolean;
  className?: string;
}> = ({ title, body, action, art = emptyArt, icon, compact, className }) => (
  <motion.div
    initial={{ opacity: 0, y: 6 }}
    animate={{ opacity: 1, y: 0 }}
    transition={{ duration: 0.3, ease }}
    className={cx(
      'flex flex-col items-center text-center rounded-2xl border border-dashed border-surface-border bg-white',
      compact ? 'px-4 py-6' : 'px-6 py-10',
      className
    )}
  >
    {icon ? (
      <div className="mb-3 h-12 w-12 rounded-2xl bg-surface-muted text-ctText-muted flex items-center justify-center">{icon}</div>
    ) : (
      art && <img src={art} alt="" className={cx('mb-3 w-auto select-none', compact ? 'h-16' : 'h-24')} />
    )}
    <p className="t-card">{title}</p>
    {body && <div className="mt-1 max-w-md text-sm text-ctText-muted">{body}</div>}
    {action && <div className="mt-4">{action}</div>}
  </motion.div>
);

interface ErrorCopy {
  icon: React.ReactNode;
  title: string;
  body: string;
  retry: boolean;
}

function describe(error: unknown, feature?: string): ErrorCopy {
  if (error instanceof ApiError) {
    if (error.isFeatureDisabled) {
      return {
        icon: <Clock size={22} />,
        title: `${feature ?? 'This feature'} is not available yet`,
        body: 'It is built but switched off until the school approves the database change it needs.',
        retry: false,
      };
    }
    if (error.isNetwork) {
      return {
        icon: <WifiOff size={22} />,
        title: 'Cannot reach ConceptTrail',
        body: error.message,
        retry: true,
      };
    }
    if (error.status === 403) {
      return {
        icon: <Lock size={22} />,
        title: 'You do not have access to this',
        body: 'This page belongs to another class or role. Ask your school administrator if you think this is wrong.',
        retry: false,
      };
    }
    if (error.status === 404) {
      return { icon: <SearchX size={22} />, title: 'Not found', body: error.message, retry: false };
    }
    if (error.status === 429) {
      return {
        icon: <Clock size={22} />,
        title: 'Please wait a moment',
        body: error.retryAfter ? `${error.message} Try again in ${error.retryAfter} seconds.` : error.message,
        retry: true,
      };
    }
    return { icon: <AlertTriangle size={22} />, title: 'Something went wrong', body: error.message, retry: true };
  }
  return {
    icon: <AlertTriangle size={22} />,
    title: 'Something went wrong',
    body: 'An unexpected error occurred.',
    retry: true,
  };
}

export const ErrorState: React.FC<{
  error: unknown;
  onRetry?: () => void;
  feature?: string;
  compact?: boolean;
  className?: string;
}> = ({ error, onRetry, feature, compact, className }) => {
  const copy = describe(error, feature);
  const disabled = error instanceof ApiError && error.isFeatureDisabled;
  return (
    <div
      role={disabled ? 'status' : 'alert'}
      className={cx(
        'flex flex-col items-center text-center rounded-2xl border',
        disabled ? 'border-surface-border bg-surface-subtle' : 'border-feedback-error-border bg-feedback-error-bg/60',
        compact ? 'px-4 py-5' : 'px-6 py-9',
        className
      )}
    >
      <div
        className={cx(
          'mb-3 h-11 w-11 rounded-2xl flex items-center justify-center',
          disabled ? 'bg-white text-ctText-muted border border-surface-border' : 'bg-white text-feedback-error'
        )}
      >
        {copy.icon}
      </div>
      <p className="t-card">{copy.title}</p>
      <p className="mt-1 max-w-md text-sm text-ctText-muted">{copy.body}</p>
      {error instanceof ApiError && error.requestId && !disabled && (
        <p className="mt-2 text-2xs text-ctText-subtle">Reference: {error.requestId}</p>
      )}
      {copy.retry && onRetry && (
        <button type="button" onClick={onRetry} className="btn btn-secondary btn-sm mt-4">
          <RefreshCw size={14} /> Try again
        </button>
      )}
    </div>
  );
};

/** Renders loading / error / content for one query. */
export function QueryView<T>({
  query,
  children,
  loading,
  feature,
  compact,
}: {
  query: { data: T | undefined; isLoading: boolean; error: unknown; refetch: () => unknown };
  children: (data: T) => React.ReactNode;
  loading?: React.ReactNode;
  feature?: string;
  compact?: boolean;
}) {
  if (query.isLoading) return <>{loading ?? <LoadingState />}</>;
  if (query.error && !query.data)
    return <ErrorState error={query.error} onRetry={() => query.refetch()} feature={feature} compact={compact} />;
  if (query.data === undefined) return <>{loading ?? <LoadingState />}</>;
  return <>{children(query.data)}</>;
}
