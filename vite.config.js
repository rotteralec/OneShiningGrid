import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Minimal Vite config for One Shining Grid. The OneShiningGrid.jsx lives in
// the repo root (alongside the data files) so we point Vite at it via
// src/main.jsx. Files under public/ get served at "/" — that's where
// player_index.json and daily_grid.json land.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    open: true,
  },
});
