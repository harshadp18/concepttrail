import type { Variants } from 'framer-motion';

/** Shared motion language: short, eased, transform/opacity only. Reduced motion is honoured via
 * <MotionConfig reducedMotion="user"> in App and the CSS media query in index.css. */
export const ease: [number, number, number, number] = [0.16, 1, 0.3, 1];

export const fadeUp: Variants = {
  hidden: { opacity: 0, y: 10 },
  show: { opacity: 1, y: 0, transition: { duration: 0.35, ease } },
};

export const stagger = (step = 0.05, delay = 0): Variants => ({
  hidden: {},
  show: { transition: { staggerChildren: step, delayChildren: delay } },
});

export const pageTransition = {
  initial: { opacity: 0, y: 8 },
  animate: { opacity: 1, y: 0, transition: { duration: 0.28, ease } },
  exit: { opacity: 0, y: -4, transition: { duration: 0.15 } },
};
