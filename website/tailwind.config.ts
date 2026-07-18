import type { Config } from "tailwindcss";

// DESIGN SYSTEM tokens (see README.md) - navy ink / seal gold / data teal / parchment
// / muted / muted-red, matching the "Every signal. Every loss. On the record." brand.
const config: Config = {
  content: ["./app/**/*.{ts,tsx}", "./components/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        ink: "#0a0e27",
        gold: "#d4af37",
        teal: "#2ec4b6",
        parchment: "#e8e2d0",
        muted: "#8a94ad",
        loss: "#d47a6a",
      },
      fontFamily: {
        serif: ["Georgia", "Cambria", "Times New Roman", "Times", "serif"],
        sans: [
          "system-ui",
          "-apple-system",
          "Segoe UI",
          "Roboto",
          "Helvetica Neue",
          "Arial",
          "sans-serif",
        ],
      },
    },
  },
  plugins: [],
};

export default config;
