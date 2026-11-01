import React from 'react';
import { Link } from 'react-router-dom';
import { motion } from 'framer-motion';
import { ChevronRight, Info } from 'lucide-react';
import { AnimatedCounter } from '@/components/common/AnimatedCounter';
import { BAND_LABEL, MasteryBand, masteryBand, pct } from '@/lib/format';
import { ease, fadeUp } from './motion';
import { SHOW_DEMO_NOTICES } from '@/lib/flags';

export function cx(...parts: Array<string | false | null | undefined>): string {
  return parts.filter(Boolean).join(' ');
}

export interface Crumb {
  label: string;
  to?: string;
}

export const PageHeader: React.FC<{
  title: React.ReactNode;
  subtitle?: React.ReactNode;
  eyebrow?: React.ReactNode;
  crumbs?: Crumb[];
  actions?: React.ReactNode;
}> = ({ title, subtitle, eyebrow, crumbs, actions }) => (
  <header className="mb-6 sm:mb-8 flex flex-col gap-4 md:flex-row md:items-end md:justify-between">
    <div className="min-w-0">
      {crumbs && crumbs.length > 0 && (
        <nav aria-label="Breadcrumb" className="mb-2 flex flex-wrap items-center gap-1 text-xs font-medium text-ctText-muted">
          {crumbs.map((c, i) => (
            <React.Fragment key={`${c.label}-${i}`}>
              {i > 0 && <ChevronRight size={12} className="text-ctText-subtle" aria-hidden />}
              {c.to ? (
                <Link to={c.to} className="hover:text-brand-700 hover:underline focus-ring rounded">
                  {c.label}
                </Link>
              ) : (
                <span className="text-ctText-body" aria-current="page">
                  {c.label}
                </span>
              )}
            </React.Fragment>
          ))}
        </nav>
      )}
      {eyebrow && <div className="t-eyebrow text-brand-600 mb-1.5">{eyebrow}</div>}
      <h1 className="t-page break-words">{title}</h1>
      {subtitle && <p className="mt-1.5 text-sm text-ctText-muted max-w-2xl">{subtitle}</p>}
    </div>
    {actions && <div className="flex flex-wrap items-center gap-2 shrink-0">{actions}</div>}
  </header>
);

export const SectionHeader: React.FC<{
  title: React.ReactNode;
  subtitle?: React.ReactNode;
  action?: React.ReactNode;
  id?: string;
}> = ({ title, subtitle, action, id }) => (
  <div className="mb-4 flex flex-wrap items-end justify-between gap-3">
    <div className="min-w-0">
      <h2 id={id} className="t-section">
        {title}
      </h2>
      {subtitle && <p className="mt-0.5 text-sm text-ctText-muted">{subtitle}</p>}
    </div>
    {action}
  </div>
);

export const Card: React.FC<
  React.HTMLAttributes<HTMLDivElement> & { as?: 'div' | 'section' | 'article'; pad?: boolean; hover?: boolean }
> = ({ as = 'div', pad = true, hover = false, className, children, ...rest }) => {
  const Tag = as as 'div';
  return (
    <Tag className={cx('card', pad && 'card-pad', hover && 'card-hover', className)} {...rest}>
      {children}
    </Tag>
  );
};

type Tone = 'brand' | 'success' | 'warning' | 'error' | 'neutral' | 'gold' | 'teal';
const TONES: Record<Tone, string> = {
  brand: 'bg-brand-50 text-brand-700 ring-1 ring-inset ring-brand-100',
  success: 'bg-feedback-success-bg text-feedback-success ring-1 ring-inset ring-feedback-success-border',
  warning: 'bg-feedback-warning-bg text-feedback-warning ring-1 ring-inset ring-feedback-warning-border',
  error: 'bg-feedback-error-bg text-feedback-error ring-1 ring-inset ring-feedback-error-border',
  neutral: 'bg-surface-muted text-ctText-body ring-1 ring-inset ring-surface-border',
  gold: 'bg-amber-50 text-amber-800 ring-1 ring-inset ring-amber-200',
  teal: 'bg-band-developing-bg text-band-developing ring-1 ring-inset ring-[#B9D8EE]',
};

export const Pill: React.FC<{ tone?: Tone; children: React.ReactNode; className?: string; icon?: React.ReactNode }> = ({
  tone = 'neutral',
  children,
  className,
  icon,
}) => (
  <span className={cx('pill', TONES[tone], className)}>
    {icon}
    {children}
  </span>
);

const BAND_TONE: Record<MasteryBand, Tone> = {
  mastered: 'success',
  developing: 'teal',
  needs_practice: 'warning',
  none: 'neutral',
};

export const BandPill: React.FC<{ p: number | null | undefined; className?: string }> = ({ p, className }) => {
  const band = masteryBand(p);
  return (
    <Pill tone={BAND_TONE[band]} className={className}>
      {BAND_LABEL[band]}
    </Pill>
  );
};

const BAND_FILL: Record<MasteryBand, string> = {
  mastered: 'bg-band-mastered',
  developing: 'bg-band-developing',
  needs_practice: 'bg-band-practice',
  none: 'bg-transparent',
};

/** A mastery estimate bar. `null` renders an empty, labelled track — never a zero-length "0%". */
export const MasteryBar: React.FC<{
  p: number | null | undefined;
  label?: string;
  showValue?: boolean;
  fill?: string;
  className?: string;
  height?: string;
}> = ({ p, label, showValue = true, fill, className, height = 'h-2' }) => {
  const band = masteryBand(p);
  const width = p === null || p === undefined ? 0 : Math.max(2, Math.min(100, p * 100));
  return (
    <div className={cx('w-full', className)}>
      {(label || showValue) && (
        <div className="mb-1 flex items-center justify-between gap-2 text-xs">
          {label && <span className="truncate font-medium text-ctText-body">{label}</span>}
          {showValue && (
            <span className={cx('tabular-nums font-semibold', p == null ? 'text-ctText-subtle' : 'text-ctText-primary')}>
              {p == null ? 'Not started' : pct(p)}
            </span>
          )}
        </div>
      )}
      <div
        className={cx('w-full overflow-hidden rounded-full bg-surface-muted', height, p == null && 'bg-[repeating-linear-gradient(135deg,#F0F2F3_0_6px,#E7EBEE_6px_12px)]')}
        role="meter"
        aria-label={label ? `${label} estimated mastery` : 'Estimated mastery'}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={p == null ? undefined : Math.round(p * 100)}
        aria-valuetext={p == null ? 'No evidence yet' : `${pct(p)} estimated, ${BAND_LABEL[band]}`}
      >
        <motion.div
          className={cx('h-full rounded-full', fill ?? BAND_FILL[band])}
          initial={{ width: 0 }}
          animate={{ width: `${width}%` }}
          transition={{ duration: 0.7, ease }}
        />
      </div>
    </div>
  );
};

export const StatTile: React.FC<{
  icon: React.ReactNode;
  iconClass: string;
  value: number | null;
  label: string;
  hint?: string;
  format?: (n: number) => string;
}> = ({ icon, iconClass, value, label, hint, format }) => (
  <motion.div variants={fadeUp} className="flex items-center gap-3.5 p-4 sm:p-5 min-w-0">
    <div className={cx('h-11 w-11 shrink-0 rounded-2xl flex items-center justify-center', iconClass)} aria-hidden>
      {icon}
    </div>
    <div className="min-w-0">
      <div className="text-2xl sm:text-[28px] font-extrabold leading-none text-ctText-primary tabular-nums">
        {value === null ? <span className="text-ctText-subtle">—</span> : <AnimatedCounter value={value} formatter={format} />}
      </div>
      <p className="mt-1 text-xs font-medium leading-tight text-ctText-muted">{label}</p>
      {hint && <p className="text-2xs text-ctText-subtle truncate">{hint}</p>}
    </div>
  </motion.div>
);

export const Notice: React.FC<{ tone?: 'info' | 'warning'; children: React.ReactNode; className?: string; icon?: React.ReactNode }> = ({
  tone = 'info',
  children,
  className,
  icon,
}) => (
  <div
    className={cx(
      'flex items-start gap-2.5 rounded-xl border px-3.5 py-2.5 text-xs leading-relaxed',
      tone === 'info'
        ? 'border-feedback-info-border bg-feedback-info-bg text-feedback-info'
        : 'border-feedback-warning-border bg-feedback-warning-bg text-feedback-warning',
      className
    )}
  >
    <span className="mt-0.5 shrink-0" aria-hidden>
      {icon ?? <Info size={14} />}
    </span>
    <div className="min-w-0">{children}</div>
  </div>
);

/** Shown wherever AI-generated, not-yet-teacher-reviewed demo content is on screen. */
export const DemoContentNotice: React.FC<{ className?: string }> = ({ className }) =>
  !SHOW_DEMO_NOTICES ? null : (
  <Notice tone="warning" className={className}>
    <strong className="font-semibold">Demo content.</strong> This content was drafted with AI and has not yet been
    reviewed by a teacher. Learners and results shown are synthetic.
  </Notice>
);

export const EstimateNote: React.FC<{ className?: string }> = ({ className }) => (
  <p className={cx('text-2xs text-ctText-subtle', className)}>
    Mastery is a provisional estimate from your answers (BKT), not a grade.
  </p>
);
