import type { Config } from "tailwindcss";

const config: Config = {
  content: ["./src/**/*.{js,ts,jsx,tsx,mdx}"],
  theme: {
    extend: {
      colors: {
        surface: { DEFAULT: "#18181b", 2: "#1f1f23", 3: "#27272a" },
        border: { DEFAULT: "#3f3f46", subtle: "#27272a" },
        accent: { DEFAULT: "#f59e0b", hover: "#d97706", muted: "#92400e" },
        success: "#22c55e",
        warning: "#f59e0b",
        danger: "#ef4444",
        info: "#3b82f6",
      },
      fontFamily: {
        sans: ["var(--font-inter)", "system-ui", "sans-serif"],
        mono: ["var(--font-mono)", "monospace"],
      },
      animation: {
        "fade-in": "fadeIn 0.2s ease",
        "slide-up": "slideUp 0.3s ease",
        "pulse-slow": "pulse 3s infinite",
      },
      keyframes: {
        fadeIn: { from: { opacity: "0" }, to: { opacity: "1" } },
        slideUp: { from: { transform: "translateY(8px)", opacity: "0" }, to: { transform: "translateY(0)", opacity: "1" } },
      },
      backdropBlur: {
        "3xl": "64px",
      },
    },
  },
  plugins: [],
};
export default config;
