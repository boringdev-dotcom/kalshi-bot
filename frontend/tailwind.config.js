/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      // Calm, flat palette: neutral blacks, one green, one red. The names are kept
      // from the first version so every screen picks up the new look together.
      colors: {
        ink: {
          950: '#0b0b0c', // page
          900: '#151517', // card
          800: '#1d1d20', // raised: inputs, hover, selected rows
          700: '#28282c',
          600: '#37373d',
        },
        mint: '#19c37d', // up, win, the "yes this is fine" colour
        coral: '#f2594b', // down, loss, danger
        gold: '#e6a93c', // caution
        peri: '#8fa3ff', // the agent
        mute: '#a1a3ab', // secondary text
        dim: '#6f7179', // tertiary text
      },
      borderColor: {
        hair: 'rgba(255,255,255,0.07)',
        hair2: 'rgba(255,255,255,0.13)',
      },
      fontFamily: {
        sans: ['Inter', 'ui-sans-serif', 'system-ui', 'sans-serif'],
        // Numbers are set in the same face as everything else, just tabular.
        mono: ['Inter', 'ui-sans-serif', 'system-ui', 'sans-serif'],
      },
      borderRadius: {
        xl2: '1.25rem',
      },
      boxShadow: {
        lift: '0 16px 48px -16px rgba(0,0,0,0.7)',
        glow: '0 0 0 1px rgba(255,255,255,0.14)',
      },
      keyframes: {
        shimmer: { '100%': { transform: 'translateX(100%)' } },
        ping2: { '0%': { transform: 'scale(1)', opacity: '0.7' }, '100%': { transform: 'scale(2.6)', opacity: '0' } },
        drift: {
          '0%,100%': { transform: 'translate(0,0) scale(1)' },
          '50%': { transform: 'translate(6%,-4%) scale(1.08)' },
        },
      },
      animation: {
        shimmer: 'shimmer 1.6s infinite',
        ping2: 'ping2 1.8s cubic-bezier(0,0,0.2,1) infinite',
        drift: 'drift 9s ease-in-out infinite',
      },
    },
  },
  plugins: [],
}
