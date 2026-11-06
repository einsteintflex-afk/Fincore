/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  darkMode: "class",
  theme: {
    extend: {
      colors: {
        brand: {
          50: "#ecfdf5", 100: "#d1fae5", 200: "#a7f3d0", 300: "#6ee7b7", 400: "#34d399",
          500: "#10b981", 600: "#059669", 700: "#047857", 800: "#065f46", 900: "#064e3b", 950: "#022c22",
        },
        gold: { 400: "#facc15", 500: "#eab308", 600: "#ca8a04" },
        ink: { 900: "#0b1220", 800: "#111a2e", 700: "#1b2640" },
      },
      fontFamily: { sans: ["Inter", "ui-sans-serif", "system-ui", "sans-serif"] },
      boxShadow: { card: "0 1px 2px rgba(16,24,40,.04), 0 1px 3px rgba(16,24,40,.08)" },
    },
  },
  plugins: [],
};
