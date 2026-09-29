/** Design tokens from the UI/UX Specification §6 (BeeBot-inspired palette,
 *  adapted — accessible contrast maintained, original composition).
 *  Redesign: premium AI-assistant language — soft depth, calm surfaces,
 *  restrained motion. No new colors beyond the documented palette. */
import type { Config } from "tailwindcss";

export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        background: "#F7F8FA",
        surface: "#FFFFFF",
        primary: {
          DEFAULT: "#383DE7",
          soft: "#A4AAF4",
          subtle: "#EEF0FD",
          deep: "#2A2FB8",
        },
        ink: {
          DEFAULT: "#171B1D",
          muted: "#585F62",
          faint: "#8A9199",
        },
        line: "#DDE1E6",
        lineSoft: "#E9ECF0",
        danger: "#D93B43",
        success: "#1F8A4C",
      },
      borderRadius: {
        card: "16px",
        bubble: "18px",
        "2xl": "16px",
      },
      fontFamily: {
        sans: [
          "Inter",
          "Geist",
          "system-ui",
          "-apple-system",
          "Segoe UI",
          "Roboto",
          "sans-serif",
        ],
      },
      boxShadow: {
        card: "0 1px 2px rgba(23,27,29,0.04), 0 4px 16px rgba(23,27,29,0.05)",
        float:
          "0 2px 6px rgba(23,27,29,0.06), 0 12px 32px rgba(23,27,29,0.10), 0 0 0 1px rgba(221,225,230,0.7)",
        pop: "0 1px 2px rgba(42,47,184,0.35)",
      },
      keyframes: {
        "fade-up": {
          "0%": { opacity: "0", transform: "translateY(6px)" },
          "100%": { opacity: "1", transform: "translateY(0)" },
        },
        "dot-bounce": {
          "0%, 80%, 100%": { transform: "scale(0.7)", opacity: "0.5" },
          "40%": { transform: "scale(1)", opacity: "1" },
        },
      },
      animation: {
        "fade-up": "fade-up 260ms ease-out both",
        "dot-bounce": "dot-bounce 1.1s ease-in-out infinite",
      },
    },
  },
  plugins: [],
} satisfies Config;
