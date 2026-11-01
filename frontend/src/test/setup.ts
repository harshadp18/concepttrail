import '@testing-library/jest-dom';
import { MotionGlobalConfig } from 'framer-motion';

// happy-dom implements only part of the Web Animations API; animations are visual-only, so
// tests run with them finished instantly.
MotionGlobalConfig.skipAnimations = true;
