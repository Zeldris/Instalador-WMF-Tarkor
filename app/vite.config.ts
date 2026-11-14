import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import { existsSync } from 'node:fs'
import { fileURLToPath } from 'node:url'

// INS-47: el build de producción no sale sin las licencias de terceros que genera `herramientas/licencias-terceros.mjs`
// (`npm run build` la corre antes); en dev y en vitest el archivo es opcional.
const TERCEROS = fileURLToPath(new URL('./src/licencias/generadas/terceros.json', import.meta.url))

// Puerto fijo para `tauri dev`. En el build final no hay servidor: Tauri incrusta `dist/`.
export default defineConfig(({ command }) => {
  if (command === 'build' && !existsSync(TERCEROS)) {
    throw new Error('Falta src/licencias/generadas/terceros.json: las licencias de terceros no se generaron. '
      + 'Corre `node herramientas/licencias-terceros.mjs` (o `npm run build`, que lo hace antes) y reintenta.')
  }
  return {
    plugins: [react()],
    clearScreen: false,
    server: { port: 1420, strictPort: true },
    build: {
      target: 'es2022',
      // Sin source maps en ningún build (docs/10-proteccion-del-codigo-y-build.md).
      sourcemap: false,
    },
    test: { environment: 'jsdom' },
  }
})
