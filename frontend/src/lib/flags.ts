/**
 * Demo labelling. On by default: AI-drafted, not-yet-reviewed content and synthetic learners are
 * labelled. Set VITE_SHOW_DEMO_NOTICES=false (for example in a Git-ignored .env.development.local)
 * only for a recorded walkthrough; the data and content are unchanged either way.
 */
export const SHOW_DEMO_NOTICES = import.meta.env.VITE_SHOW_DEMO_NOTICES !== 'false';
