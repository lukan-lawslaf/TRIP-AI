/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      fontFamily: {
        sans: ['Geist', 'sans-serif'],
        display: ['Special Elite', 'serif'],
        inter: ['Inter', 'sans-serif'],
        serifdisplay: ['Instrument Serif', 'serif'],
        figtree: ['Figtree', 'sans-serif'],
      },
      colors: {
        wandor: {
          dark: '#0a0a0a',
          text: '#1a1a1a',
          muted: '#767676',
          prompt: '#905831',
        },
        ink: {
          DEFAULT: '#2A4A5A',
          deep: '#202A36',
        },
      },
      screens: {
        mobile: { max: '809.98px' },
      },
    },
  },
  plugins: [],
}
