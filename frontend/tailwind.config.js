/** @type {import('tailwindcss').Config} */
// ConceptTrail design tokens. Brand blue #287A9F, text #444444, white pages, #F0F2F3 surfaces.
// Every colour used by components comes from here; avoid raw hex values in components.
export default {
  content: ['./index.html', './src/**/*.{js,ts,jsx,tsx}'],
  theme: {
    extend: {
      colors: {
        brand: {
          DEFAULT: '#287A9F',
          50: '#F0F7FA',
          100: '#DCEFF8',
          200: '#BFE1F0',
          300: '#8CC6E0',
          400: '#4E9FC2',
          500: '#287A9F',
          600: '#226C8D',
          700: '#1B5F79',
          800: '#154C61',
          900: '#0F3847',
          teal: '#1E8A8A',
          'teal-deep': '#145F66',
          gold: '#F59E0B',
          sun: '#FFD016',
        },
        surface: {
          DEFAULT: '#FFFFFF',
          subtle: '#F8FAFB',
          muted: '#F0F2F3',
          border: '#E3E8EB',
          'border-subtle': '#EEF1F3',
        },
        ctText: {
          primary: '#1F2937',
          body: '#444444',
          muted: '#5F6B76',
          subtle: '#8A96A1',
        },
        subject: {
          math: { DEFAULT: '#3B8FC2', bg: '#E7F3FA', ring: '#C9E3F2', text: '#1E6A96' },
          science: { DEFAULT: '#2EA57F', bg: '#E5F6EF', ring: '#C4EAD9', text: '#17775A' },
          english: { DEFAULT: '#E0A41B', bg: '#FDF7E1', ring: '#F6E6AE', text: '#94690C' },
          hindi: { DEFAULT: '#E07B3C', bg: '#FDEFE5', ring: '#F8D7C2', text: '#A9531F' },
          social: { DEFAULT: '#D9578A', bg: '#FCEBF2', ring: '#F5CBDC', text: '#A43566' },
        },
        band: {
          // validated with the dataviz palette checks (light surface): CVD + normal-vision + 3:1
          mastered: '#1E7D45',
          'mastered-bg': '#DDF3E5',
          developing: '#2F7FB5',
          'developing-bg': '#DDEDF8',
          practice: '#D0591B',
          'practice-bg': '#FCE8DB',
          none: '#8A96A1',
          'none-bg': '#F0F2F3',
        },
        feedback: {
          success: { DEFAULT: '#15803D', bg: '#ECFDF3', border: '#A7E8C3' },
          warning: { DEFAULT: '#B45309', bg: '#FFF8EB', border: '#FBD8A5' },
          error: { DEFAULT: '#B42318', bg: '#FEF3F2', border: '#FECDCA' },
          info: { DEFAULT: '#1B5F79', bg: '#F0F7FA', border: '#BFE1F0' },
        },
      },
      borderRadius: {
        xl: '12px',
        '2xl': '16px',
        '3xl': '24px',
      },
      fontFamily: {
        sans: ['Plus Jakarta Sans', 'Inter', '-apple-system', 'BlinkMacSystemFont', 'Segoe UI', 'Roboto', 'Noto Sans Devanagari', 'sans-serif'],
        hindi: ['Noto Sans Devanagari', 'sans-serif'],
      },
      fontSize: {
        '2xs': ['0.6875rem', { lineHeight: '1rem' }],
      },
      boxShadow: {
        card: '0 1px 2px 0 rgba(16, 24, 40, 0.04), 0 1px 3px 0 rgba(16, 24, 40, 0.04)',
        elevated: '0 12px 28px -8px rgba(27, 95, 121, 0.16), 0 4px 10px -4px rgba(27, 95, 121, 0.08)',
        focus: '0 0 0 3px rgba(40, 122, 159, 0.28)',
      },
      maxWidth: {
        page: '76rem',
      },
    },
  },
  plugins: [],
};
