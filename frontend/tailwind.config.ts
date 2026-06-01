import type { Config } from "tailwindcss"

const config: Config = {
  content: [
    "./app/**/*.{js,ts,jsx,tsx,mdx}",
    "./components/**/*.{js,ts,jsx,tsx,mdx}",
  ],
  theme: {
    extend: {
      colors: {
        dark: {
          900: "#0a0a0a",
          800: "#121212",
          700: "#1a1a2e",
          600: "#16213e",
        },
        accent: {
          gold: "#d4a853",
          green: "#00c853",
        },
      },
    },
  },
  plugins: [],
}

export default config
