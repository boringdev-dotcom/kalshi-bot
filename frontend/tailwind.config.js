/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        // Dark theme colors - calmer palette
        'bg-primary': '#0a0a12',
        'bg-secondary': '#12121c',
        'bg-tertiary': '#1a1a28',
        'bg-panel': '#0f0f18',
        'border-primary': '#2a2a3e',
        'border-secondary': '#3a3a50',
        'border-subtle': '#1e1e2a', // Subtle borders for less visual noise
        'text-primary': '#e0e0e8',
        'text-secondary': '#a0a0b0',
        'text-muted': '#606070',
        'accent-blue': '#00d4ff',
        'accent-purple': '#7b2cbf',
        'accent-green': '#00c853',
        'accent-red': '#ff1744',
        'accent-yellow': '#ffab00',
        'accent-orange': '#ff6d00',
      },
      fontFamily: {
        mono: ['JetBrains Mono', 'SF Mono', 'Monaco', 'monospace'],
        sans: ['Inter', 'SF Pro Display', '-apple-system', 'BlinkMacSystemFont', 'sans-serif'],
      },
    },
  },
  plugins: [],
}
