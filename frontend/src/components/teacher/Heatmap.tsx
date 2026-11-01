import React, { useCallback, useMemo, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import { AnimatePresence, motion } from 'framer-motion';
import { ArrowRight, X } from 'lucide-react';
import type { HeatBand, HeatCell, Heatmap } from '@/api/types';
import { dateTime, pct, plural } from '@/lib/format';
import { subjectMeta } from '@/lib/subjects';
import { cx } from '@/components/ui/primitives';

export const BAND_STYLE: Record<HeatBand, { cell: string; label: string; swatch: string }> = {
  mastered: { cell: 'bg-band-mastered text-white', label: 'Mastered (95% or more)', swatch: 'bg-band-mastered' },
  developing: { cell: 'bg-band-developing text-white', label: 'Developing (50–94%)', swatch: 'bg-band-developing' },
  needs_practice: { cell: 'bg-band-practice text-white', label: 'Needs practice (below 50%)', swatch: 'bg-band-practice' },
  insufficient_evidence: {
    cell: 'bg-[repeating-linear-gradient(45deg,#E3E8EB_0_4px,#F6F8F9_4px_8px)] text-ctText-muted',
    label: 'Started, not enough answers yet',
    swatch: 'bg-[repeating-linear-gradient(45deg,#C9D2D8_0_3px,#F6F8F9_3px_6px)]',
  },
  no_data: { cell: 'bg-surface-subtle text-ctText-subtle', label: 'No attempts yet', swatch: 'bg-surface-subtle border border-surface-border' },
};

export const HeatmapLegend: React.FC<{ className?: string }> = ({ className }) => (
  <ul className={cx('flex flex-wrap gap-x-4 gap-y-2 text-xs text-ctText-body', className)} aria-label="Legend">
    {(Object.keys(BAND_STYLE) as HeatBand[]).map((b) => (
      <li key={b} className="flex items-center gap-1.5">
        <span className={cx('h-3.5 w-3.5 rounded', BAND_STYLE[b].swatch)} aria-hidden />
        {BAND_STYLE[b].label}
      </li>
    ))}
  </ul>
);

function cellText(c: HeatCell): string {
  if (c.mastery_probability != null) return String(Math.round(c.mastery_probability * 100));
  return c.band === 'insufficient_evidence' ? '·' : '—';
}

function cellLabel(learner: string, topic: string, c: HeatCell): string {
  const est = c.mastery_probability == null ? (c.band === 'no_data' ? 'no attempts yet' : 'not enough answers for an estimate') : `estimated mastery ${pct(c.mastery_probability)}`;
  return `${learner}, ${topic}: ${est}; ${plural(c.attempts, 'attempt')}, ${c.correct} correct`;
}

interface Selected {
  row: number;
  col: number;
}

/** Learners × topics. One focusable cell at a time (arrow keys move), Enter/Space opens details. */
export const HeatmapGrid: React.FC<{ data: Heatmap; maxRows?: number; showDetail?: boolean }> = ({ data, maxRows, showDetail = true }) => {
  const rows = useMemo(() => (maxRows ? data.learners.slice(0, maxRows) : data.learners), [data.learners, maxRows]);
  const [focus, setFocus] = useState<Selected>({ row: 0, col: 0 });
  const [selected, setSelected] = useState<Selected | null>(null);
  const [hover, setHover] = useState<{ sel: Selected; x: number; y: number } | null>(null);
  const tableRef = useRef<HTMLTableElement>(null);

  const move = useCallback(
    (e: React.KeyboardEvent, r: number, c: number) => {
      const map: Record<string, [number, number]> = { ArrowRight: [0, 1], ArrowLeft: [0, -1], ArrowDown: [1, 0], ArrowUp: [-1, 0] };
      if (e.key === 'Enter' || e.key === ' ') {
        e.preventDefault();
        setSelected({ row: r, col: c });
        return;
      }
      if (e.key === 'Home' || e.key === 'End') {
        e.preventDefault();
        const nc = e.key === 'Home' ? 0 : data.topics.length - 1;
        setFocus({ row: r, col: nc });
        tableRef.current?.querySelector<HTMLElement>(`[data-cell="${r}-${nc}"]`)?.focus();
        return;
      }
      const d = map[e.key];
      if (!d) return;
      e.preventDefault();
      const nr = Math.max(0, Math.min(rows.length - 1, r + d[0]));
      const nc = Math.max(0, Math.min(data.topics.length - 1, c + d[1]));
      setFocus({ row: nr, col: nc });
      tableRef.current?.querySelector<HTMLElement>(`[data-cell="${nr}-${nc}"]`)?.focus();
    },
    [rows.length, data.topics.length]
  );

  const detail = selected && rows[selected.row] ? { learner: rows[selected.row], topic: data.topics[selected.col], cell: rows[selected.row].cells[selected.col] } : null;
  const tip = hover && rows[hover.sel.row] ? { learner: rows[hover.sel.row], topic: data.topics[hover.sel.col], cell: rows[hover.sel.row].cells[hover.sel.col] } : null;

  return (
    <div className="relative">
      <div className="overflow-x-auto rounded-2xl border border-surface-border bg-white" onMouseLeave={() => setHover(null)}>
        <table ref={tableRef} className="border-separate border-spacing-[3px] text-xs" role="grid" aria-label="Class mastery heatmap: learners by topic">
          <thead>
            <tr>
              <th scope="col" className="sticky left-0 z-10 min-w-[150px] bg-white px-2 pb-2 text-left align-bottom text-2xs font-bold uppercase tracking-wider text-ctText-muted">
                Learner
              </th>
              {data.topics.map((t) => {
                const s = subjectMeta(t.subject_id);
                return (
                  <th key={t.kc_id} scope="col" className="w-[76px] min-w-[76px] px-0.5 pb-2 align-bottom font-semibold text-ctText-body" title={`${t.name} · ${t.item_title ?? ''}`}>
                    <span className={cx('mb-1 block h-1 rounded-full', s.bar)} aria-hidden />
                    <span className="line-clamp-3 text-[10.5px] leading-tight">{t.name}</span>
                  </th>
                );
              })}
            </tr>
          </thead>
          <tbody>
            {rows.map((r, ri) => (
              <tr key={r.learner_id}>
                <th scope="row" className="sticky left-0 z-10 bg-white px-2 text-left font-semibold text-ctText-primary">
                  <Link to={`/teacher/learners/${r.learner_id}`} className="block max-w-[170px] truncate hover:text-brand-700 hover:underline">
                    {r.display_name ?? 'Learner'}
                  </Link>
                  <span className="block text-[10.5px] font-normal text-ctText-muted">
                    {r.average_mastery_probability == null ? 'No estimates yet' : `Avg ${pct(r.average_mastery_probability)}`}
                  </span>
                </th>
                {r.cells.map((c, ci) => {
                  const isFocus = focus.row === ri && focus.col === ci;
                  const isSel = selected?.row === ri && selected?.col === ci;
                  return (
                    <td key={ci} className="p-0">
                      <motion.button
                        type="button"
                        data-cell={`${ri}-${ci}`}
                        tabIndex={isFocus ? 0 : -1}
                        aria-label={cellLabel(r.display_name ?? 'Learner', data.topics[ci].name ?? data.topics[ci].kc_id, c)}
                        aria-pressed={isSel}
                        onKeyDown={(e) => move(e, ri, ci)}
                        onFocus={() => setFocus({ row: ri, col: ci })}
                        onClick={() => setSelected({ row: ri, col: ci })}
                        onMouseEnter={(e) => {
                          const rect = (e.currentTarget as HTMLElement).getBoundingClientRect();
                          setHover({ sel: { row: ri, col: ci }, x: rect.left + rect.width / 2, y: rect.top });
                        }}
                        initial={{ opacity: 0, scale: 0.85 }}
                        animate={{ opacity: 1, scale: 1 }}
                        transition={{ duration: 0.25, delay: Math.min(0.4, ci * 0.012 + ri * 0.008) }}
                        className={cx(
                          'flex h-10 w-full items-center justify-center rounded-lg text-xs font-bold tabular-nums transition-shadow focus-ring',
                          BAND_STYLE[c.band].cell,
                          isSel && 'ring-2 ring-offset-1 ring-brand-900'
                        )}
                      >
                        {cellText(c)}
                      </motion.button>
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
          <tfoot>
            <tr>
              <th scope="row" className="sticky left-0 z-10 bg-white px-2 pt-2 text-left text-2xs font-bold uppercase tracking-wider text-ctText-muted">
                Class
              </th>
              {data.topics.map((t) => (
                <td key={t.kc_id} className="px-0.5 pt-2 text-center text-[10.5px] text-ctText-muted">
                  <span className="block font-bold text-ctText-primary">{t.average_mastery_probability == null ? '—' : pct(t.average_mastery_probability)}</span>
                  {t.learners_with_estimate}/{data.learner_count} est.
                </td>
              ))}
            </tr>
          </tfoot>
        </table>
      </div>

      {tip && (
        <div
          role="tooltip"
          className="pointer-events-none fixed z-50 w-60 -translate-x-1/2 -translate-y-full rounded-xl border border-surface-border bg-white p-3 text-xs shadow-elevated"
          style={{ left: hover!.x, top: hover!.y - 8 }}
        >
          <p className="font-bold text-ctText-primary">{tip.learner.display_name}</p>
          <p className="text-ctText-muted">{tip.topic.name}</p>
          <p className="mt-1.5 font-semibold text-ctText-primary">
            {tip.cell.mastery_probability == null ? BAND_STYLE[tip.cell.band].label : `Estimated mastery ${pct(tip.cell.mastery_probability)}`}
          </p>
          <p className="text-ctText-muted">
            {plural(tip.cell.evidence_count, 'scored answer')} in the estimate · {plural(tip.cell.attempts, 'attempt')}
            {data.window_days ? ` in ${data.window_days} days` : ''}, {tip.cell.correct} correct
          </p>
        </div>
      )}

      <AnimatePresence>
        {showDetail && detail && (
          <motion.div
            initial={{ opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: 8 }}
            className="mt-4 flex flex-col gap-4 rounded-2xl border border-brand-200 bg-brand-50/60 p-4 sm:flex-row sm:items-center"
            aria-live="polite"
          >
            <div className="min-w-0 flex-1">
              <p className="t-eyebrow text-brand-700">{detail.topic.item_title}</p>
              <p className="t-card">
                {detail.learner.display_name} · {detail.topic.name}
              </p>
              <p className="mt-1 text-sm text-ctText-body">
                {detail.cell.mastery_probability == null ? BAND_STYLE[detail.cell.band].label : `Estimated mastery ${pct(detail.cell.mastery_probability)}`} ·{' '}
                {plural(detail.cell.attempts, 'attempt')} ({detail.cell.correct} correct) · last {dateTime(detail.cell.last_attempt_at)}
              </p>
            </div>
            <div className="flex gap-2">
              <Link to={`/teacher/learners/${detail.learner.learner_id}`} className="btn btn-primary btn-sm">
                Learner details <ArrowRight size={14} aria-hidden />
              </Link>
              <button type="button" className="btn btn-ghost btn-sm" onClick={() => setSelected(null)} aria-label="Close details">
                <X size={14} />
              </button>
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
};
