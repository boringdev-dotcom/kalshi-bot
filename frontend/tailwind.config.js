/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        ink: {
          950: '#090b10',
          900: '#10131a',
          800: '#161a23',
          700: '#1d222d',
          600: '#2a303d',
        },
        mint: '#3ddc97',
        coral: '#ff6b6b',
        gold: '#f5b74e',
        peri: '#8b9cff',
        mute: '#8d96a8',
        dim: '#5d6577',
      },
      borderColor: {
        hair: 'rgba(255,255,255,0.06)',
        hair2: 'rgba(255,255,255,0.1)',
      },
      fontFamily: {
        sans: ['Inter', 'ui-sans-serif', 'system-ui', 'sans-serif'],
        mono: ['"JetBrains Mono"', 'ui-monospace', 'SFMono-Regular', 'monospace'],
      },
      borderRadius: {
        xl2: '1.125rem',
      },
      boxShadow: {
        lift: '0 12px 40px -12px rgba(0,0,0,0.6)',
        glow: '0 0 0 1px rgba(139,156,255,0.35), 0 8px 40px -8px rgba(139,156,255,0.25)',
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
