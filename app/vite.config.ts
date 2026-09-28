import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// Puerto fijo para `tauri dev`. En el build final no hay servidor: Tauri incrusta `dist/`.
export default defineConfig({
  plugins: [react()],
  clearScreen: false,
  server: { port: 1420, strictPort: true },
  build: {
    target: 'es2022',
    // Sin source maps en ningún build (docs/10-proteccion-del-codigo-y-build.md).
    sourcemap: false,
  },
  test: { environment: 'jsdom' },
})
