// Empaqueta el backend del juego para el instalador (docs/10, camino A; fase 0.6 de docs/05):
//
//   1. esbuild junta todo el backend en un solo fichero CommonJS, minificado y sin source maps.
//   2. bytenode lo compila a bytecode de V8 (`servidor.jsc`): el código fuente no viaja.
//   3. Se copia el runtime de Node con el que se compiló (el bytecode va atado a esa versión) y
//      el cliente de Prisma, que no se compila (es una librería de terceros con binario nativo).
//
// Uso:  node herramientas/empaquetar-backend.mjs <carpeta backend del juego> <salida>
// Requisitos: `npm ci` y `npx prisma generate` hechos en el backend; esbuild y bytenode
// instalados (`npm i --no-save esbuild bytenode` en la carpeta del backend vale).
//
// Este script vive en el repo público: no contiene código del juego, solo lo transforma.

import { cpSync, existsSync, mkdirSync, readdirSync, readFileSync, rmSync, statSync, writeFileSync } from 'node:fs'
import { createRequire } from 'node:module'
import { dirname, join, relative, resolve } from 'node:path'
import { execFileSync } from 'node:child_process'

const [backendArg, salidaArg] = process.argv.slice(2)
if (!backendArg || !salidaArg) {
  console.error('Uso: node herramientas/empaquetar-backend.mjs <backend> <salida>')
  process.exit(1)
}
const backend = resolve(backendArg)
const salida = resolve(salidaArg)
const requerir = createRequire(join(backend, 'package.json'))
const esbuild = requerir('esbuild')

rmSync(salida, { recursive: true, force: true })
mkdirSync(salida, { recursive: true })

// El backend es ESM con `await` de primer nivel en server.ts; bytenode necesita CommonJS.
// Este plugin envuelve el cuerpo de server.ts en una función asíncrona y cambia cada
// `import.meta.dirname` por la carpeta equivalente dentro del paquete (la raíz del paquete hace
// de carpeta del backend: ahí van uploads/ y Modelfile).
const adaptar = {
  name: 'adaptar-a-cjs',
  setup(build) {
    build.onLoad({ filter: /\.ts$/ }, (args) => {
      let codigo = readFileSync(args.path, 'utf8')
      const dir = relative(backend, dirname(args.path)).replaceAll('\\', '/')
      codigo = codigo.replaceAll('import.meta.dirname', `__tarkorDir(${JSON.stringify(dir)})`)
      if (args.path === join(backend, 'src', 'server.ts')) {
        const lineas = codigo.split('\n')
        const imports = lineas.filter((l) => /^import\s/.test(l))
        const cuerpo = lineas.filter((l) => !/^import\s/.test(l))
        codigo = `${imports.join('\n')}\n(async () => {\n${cuerpo.join('\n')}\n})().catch((e) => { console.error(e); process.exit(1) })\n`
      }
      return { contents: codigo, loader: 'ts' }
    })
  },
}

console.log('1/4 esbuild: un solo fichero minificado…')
await esbuild.build({
  entryPoints: [join(backend, 'src', 'server.ts')],
  bundle: true,
  platform: 'node',
  target: 'node22',
  format: 'cjs',
  minify: true,
  sourcemap: false,
  legalComments: 'none',
  // Prisma genera código y un binario nativo por plataforma: va aparte, sin compilar.
  external: ['@prisma/client', '.prisma/client'],
  banner: {
    js: `const __tarkorDir = (d) => require('path').join(process.env.TARKOR_BACKEND_RAIZ || __dirname, d);`,
  },
  outfile: join(salida, 'servidor.cjs'),
  plugins: [adaptar],
  logLevel: 'warning',
})

console.log('2/4 bytenode: compilando a bytecode de V8…')
execFileSync(process.execPath, ['-e', `require(${JSON.stringify(requerir.resolve('bytenode'))}).compileFile({ filename: ${JSON.stringify(join(salida, 'servidor.cjs'))}, output: ${JSON.stringify(join(salida, 'servidor.jsc'))} })`])
rmSync(join(salida, 'servidor.cjs'))

console.log('3/4 cargador…')
await esbuild.build({
  stdin: { contents: `require('bytenode'); require('./servidor.jsc');`, resolveDir: backend, loader: 'js' },
  bundle: true,
  platform: 'node',
  target: 'node22',
  format: 'cjs',
  minify: true,
  // bytenode solo usa `electron` si se ejecuta dentro de Electron; aquí nunca.
  external: ['./servidor.jsc', 'electron'],
  outfile: join(salida, 'arrancar.cjs'),
  logLevel: 'warning',
})

console.log('4/4 runtime de Node y cliente de Prisma…')
const nodeDestino = join(salida, process.platform === 'win32' ? 'node.exe' : 'node')
cpSync(process.execPath, nodeDestino)
for (const dep of ['@prisma/client', '.prisma/client']) {
  cpSync(join(backend, 'node_modules', dep), join(salida, 'node_modules', dep), { recursive: true })
}
// El runtime de Prisma trae variantes para otras bases de datos, edge y navegador: solo hace
// falta `library.js` (Node con el motor nativo). Reduce ~70 MB.
const runtime = join(salida, 'node_modules', '@prisma', 'client', 'runtime')
for (const f of readdirSync(runtime)) {
  if (!/^library\.(js|d\.ts)$/.test(f)) rmSync(join(runtime, f), { recursive: true, force: true })
}
if (existsSync(join(backend, 'Modelfile'))) cpSync(join(backend, 'Modelfile'), join(salida, 'Modelfile'))
writeFileSync(join(salida, 'VERSION-NODE'), process.version + '\n')

const mb = (f) => (statSync(f).size / 1024 ** 2).toFixed(1)
console.log(`Listo en ${salida}`)
console.log(`  servidor.jsc ${mb(join(salida, 'servidor.jsc'))} MB · node ${mb(nodeDestino)} MB (${process.version})`)
