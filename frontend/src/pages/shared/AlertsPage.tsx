import React, { useState } from 'react';
import { Link } from 'react-router-dom';
import { AnimatePresence, motion } from 'framer-motion';
import { BellRing, CheckCheck, ClipboardCheck, ListTodo, Megaphone, TriangleAlert } from 'lucide-react';
import { useNotificationActions, useNotifications } from '@/api/hooks';
import type { AppNotification } from '@/api/types';
import { useAuth } from '@/context/AuthContext';
import { relative } from '@/lib/format';
import { cx, PageHeader, Pill } from '@/components/ui/primitives';
import { EmptyState, ErrorState, QueryView } from '@/components/ui/states';
import { SHOW_DEMO_NOTICES } from '@/lib/flags';

const KIND: Record<AppNotification['kind'], { icon: React.ReactNode; label: string; tone: string }> = {
  class_weak_area: { icon: <TriangleAlert size={18} />, label: 'Class needs support', tone: 'bg-band-practice-bg text-band-practice' },
  intervention_update: { icon: <ListTodo size={18} />, label: 'Support plan', tone: 'bg-brand-50 text-brand-700' },
  review_outcome: { icon: <ClipboardCheck size={18} />, label: 'Question review', tone: 'bg-band-mastered-bg text-band-mastered' },
  system: { icon: <Megaphone size={18} />, label: 'Notice', tone: 'bg-surface-muted text-ctText-body' },
};

export const AlertsPage: React.FC = () => {
  const { role } = useAuth();
  const query = useNotifications();
  const { markRead, markAll } = useNotificationActions();
  const [filter, setFilter] = useState<'all' | 'unread'>('all');
  return (
    <div>
      <PageHeader
        title="Alerts"
        subtitle={role === 'teacher' ? 'Updates about your classes, support plans and reviews.' : 'Messages and updates about your learning.'}
        actions={
          query.data && query.data.unread_count > 0 ? (
            <button type="button" className="btn btn-secondary" disabled={markAll.isPending} onClick={() => markAll.mutate()}>
              <CheckCheck size={15} aria-hidden /> Mark all as read
            </button>
          ) : undefined
        }
      />
      {markAll.error || markRead.error ? <ErrorState error={markAll.error ?? markRead.error} compact className="mb-4" /> : null}
      <QueryView query={query} feature="Alerts">
        {(data) => {
          const items = filter === 'unread' ? data.notifications.filter((n) => !n.read_at) : data.notifications;
          return (
            <>
              <div role="tablist" aria-label="Filter alerts" className="mb-4 flex gap-2">
                {(['all', 'unread'] as const).map((f) => (
                  <button
                    key={f}
                    role="tab"
                    aria-selected={filter === f}
                    onClick={() => setFilter(f)}
                    className={cx('btn btn-sm rounded-full', filter === f ? 'bg-brand-700 text-white' : 'btn-secondary')}
                  >
                    {f === 'all' ? `All (${data.notifications.length})` : `Unread (${data.unread_count})`}
                  </button>
                ))}
              </div>
              {items.length === 0 ? (
                <EmptyState icon={<BellRing size={22} />} title={filter === 'unread' ? 'You are all caught up' : 'No alerts yet'} body="New alerts appear here." />
              ) : (
                <ul className="space-y-3">
                  <AnimatePresence initial={false}>
                    {items.map((n) => {
                      const k = KIND[n.kind] ?? KIND.system;
                      return (
                        <motion.li
                          key={n.notification_id}
                          layout
                          initial={{ opacity: 0, y: 6 }}
                          animate={{ opacity: 1, y: 0 }}
                          exit={{ opacity: 0 }}
                          className={cx('card flex gap-4 p-4 sm:p-5', !n.read_at && 'border-brand-200 bg-brand-50/40')}
                        >
                          <div className={cx('flex h-10 w-10 shrink-0 items-center justify-center rounded-xl', k.tone)} aria-hidden>
                            {k.icon}
                          </div>
                          <div className="min-w-0 flex-1">
                            <div className="flex flex-wrap items-center gap-2">
                              <span className="t-eyebrow text-ctText-muted">{k.label}</span>
                              {!n.read_at && <Pill tone="brand">New</Pill>}
                              {SHOW_DEMO_NOTICES && n.is_synthetic && <Pill tone="gold">Demo data</Pill>}
                            </div>
                            <p className="t-card mt-1">{n.title}</p>
                            {n.body && <p className="mt-0.5 text-sm text-ctText-muted">{n.body}</p>}
                            <div className="mt-2 flex flex-wrap items-center gap-3 text-xs text-ctText-subtle">
                              <span>{relative(n.created_at)}</span>
                              {role === 'teacher' && n.kind === 'class_weak_area' && (
                                <Link to="/teacher/bell-ringer" className="font-semibold text-brand-700 hover:underline">
                                  Open Bell Ringer
                                </Link>
                              )}
                              {!n.read_at && (
                                <button type="button" className="font-semibold text-brand-700 hover:underline" onClick={() => markRead.mutate(n.notification_id)}>
                                  Mark as read
                                </button>
                              )}
                            </div>
                          </div>
                        </motion.li>
                      );
                    })}
                  </AnimatePresence>
                </ul>
              )}
            </>
          );
        }}
      </QueryView>
    </div>
  );
};

export default AlertsPage;
