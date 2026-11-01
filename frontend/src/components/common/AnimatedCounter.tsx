import React, { useEffect, useRef, useState } from 'react';

export interface AnimatedCounterProps {
  value?: number;
  to?: number;
  duration?: number;
  formatter?: (val: number) => string;
  className?: string;
  prefix?: string;
  suffix?: string;
}

function prefersReducedMotion(): boolean {
  return typeof window !== 'undefined' && window.matchMedia?.('(prefers-reduced-motion: reduce)').matches;
}

/** Counts from the previously shown value to the new one; the final frame is always exact. */
export const AnimatedCounter: React.FC<AnimatedCounterProps> = ({
  value,
  to,
  duration = 700,
  formatter = (v) => Math.round(v).toString(),
  className = '',
  prefix = '',
  suffix = '',
}) => {
  const target = to ?? value ?? 0;
  const [display, setDisplay] = useState<number>(() => (prefersReducedMotion() ? target : 0));
  const shown = useRef(display);

  useEffect(() => {
    if (prefersReducedMotion()) {
      shown.current = target;
      setDisplay(target);
      return;
    }
    const from = shown.current;
    let start: number | null = null;
    let frame = 0;
    const step = (t: number) => {
      if (start === null) start = t;
      const progress = Math.min((t - start) / duration, 1);
      const eased = 1 - Math.pow(1 - progress, 3);
      const next = progress < 1 ? from + (target - from) * eased : target;
      shown.current = next;
      setDisplay(next);
      if (progress < 1) frame = requestAnimationFrame(step);
    };
    frame = requestAnimationFrame(step);
    return () => cancelAnimationFrame(frame);
  }, [target, duration]);

  return (
    <span className={`inline-block tabular-nums ${className}`} aria-label={`${prefix}${formatter(target)}${suffix}`}>
      <span aria-hidden>
        {prefix}
        {formatter(display)}
        {suffix}
      </span>
    </span>
  );
};

export default AnimatedCounter;
