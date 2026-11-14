// La parte pura del generador de licencias de terceros (INS-47): agrupar, deduplicar y ordenar.
import { spawnSync } from 'node:child_process'
import { describe, expect, it } from 'vitest'
import { mkdirSync, mkdtempSync, symlinkSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { pathToFileURL } from 'node:url'
import {
  aceptadasDeToml, crateHomologa, esEjecucionDirecta, licenciaAceptada, textosPorCrate,
  agrupar, aTextoPlano, entradasDeCargoAbout, esArchivoDeLicencia, idsDeExpresion, normalizarExpresion,
  paquetesDeProduccion, textosDeRespaldo,
} from './licencias-terceros.mjs'

const e = (nombre, version, licencia, textos, ecosistema = 'rust') => ({ nombre, version, ecosistema, licencia, textos })

describe('licencias-terceros', () => {
  it('normaliza expresiones planas para que el orden de los términos no cree grupos distintos', () => {
    expect(normalizarExpresion('MIT OR Apache-2.0')).toBe('Apache-2.0 OR MIT')
    expect(normalizarExpresion('Apache-2.0  OR  MIT')).toBe('Apache-2.0 OR MIT')
    expect(normalizarExpresion('(MIT OR Apache-2.0) AND Unicode-3.0')).toBe('(MIT OR Apache-2.0) AND Unicode-3.0')
    expect(normalizarExpresion('Apache-2.0 WITH LLVM-exception')).toBe('Apache-2.0 WITH LLVM-exception')
    expect(normalizarExpresion('')).toBe('Desconocida')
    expect(idsDeExpresion('(MIT OR Apache-2.0) AND Unicode-3.0')).toEqual(['MIT', 'Apache-2.0', 'Unicode-3.0'])
  })

  it('agrupa por licencia, cuenta paquetes y no repite textos idénticos', () => {
    const { grupos } = agrupar([
      e('tokio', '1.0.0', 'MIT', ['Texto A\n']),
      e('serde', '1.0.0', 'MIT', ['Texto A']),
      e('react', '19.0.0', 'MIT', ['Texto B'], 'npm'),
      e('zeta', '2.0.0', 'Zlib', ['Texto Z']),
    ])
    expect(grupos.map((g) => g.licencia)).toEqual(['MIT', 'Zlib'])
    const mit = grupos[0]
    // Orden estable: ecosistema, nombre, versión.
    expect(mit.paquetes.map((p) => p.nombre)).toEqual(['react', 'serde', 'tokio'])
    expect(mit.textos).toEqual([
      { texto: 'Texto A', paquetes: [1, 2] },
      { texto: 'Texto B', paquetes: [0] },
    ])
  })

  it('el resultado no depende del orden de entrada y un paquete repetido cuenta una vez', () => {
    const a = [e('b', '1', 'MIT OR Apache-2.0', ['x']), e('a', '1', 'Apache-2.0 OR MIT', ['y']), e('a', '1', 'Apache-2.0 OR MIT', ['y'])]
    expect(agrupar(a)).toEqual(agrupar([...a].reverse()))
    expect(agrupar(a).grupos).toHaveLength(1)
    expect(agrupar(a).grupos[0].paquetes).toHaveLength(2)
  })

  it('saca las crates de terceros de la salida de cargo-about y deja fuera las del workspace', () => {
    const crate = (name, license, source) => ({ crate: { name, version: '1.0.0', license, source } })
    const salida = {
      licenses: [
        { id: 'MIT', text: 'MIT de a', used_by: [crate('a', 'MIT OR Apache-2.0', 'registry+x'), crate('tarkor', 'MIT', null)] },
        { id: 'Apache-2.0', text: 'Apache', used_by: [crate('a', 'MIT OR Apache-2.0', 'registry+x')] },
      ],
    }
    expect(entradasDeCargoAbout(salida)).toEqual([e('a', '1.0.0', 'MIT OR Apache-2.0', ['MIT de a', 'Apache'])])
  })

  it('de package-lock.json solo toma producción y el nombre del paquete anidado', () => {
    const lock = { packages: {
      '': { name: 'app' },
      'node_modules/react': { version: '19.0.0', license: 'MIT' },
      'node_modules/@x/y': { version: '1.0.0', license: 'MIT', optional: true },
      'node_modules/react/node_modules/z': { version: '2.0.0', license: 'ISC' },
      'node_modules/vitest': { version: '5.0.0', license: 'MIT', dev: true },
    } }
    expect(paquetesDeProduccion(lock).map((p) => p.nombre)).toEqual(['react', '@x/y', 'z'])
    // Uno opcional se marca: si no está instalado en esta plataforma, el generador lo salta.
    expect(paquetesDeProduccion(lock).map((p) => p.opcional)).toEqual([false, true, false])
  })

  it('reconoce los archivos de licencia, no la etiqueta SPDX, y usa el texto estándar de respaldo', () => {
    for (const n of ['LICENSE', 'LICENCE', 'COPYING', 'LICENSE-MIT', 'license.md', 'LICENSE-APACHE-2.0']) expect(esArchivoDeLicencia(n), n).toBe(true)
    for (const n of ['LICENSE.spdx', 'package.json', 'licenses.json', 'README.md']) expect(esArchivoDeLicencia(n), n).toBe(false)
    const canonicos = new Map([['MIT', 'texto MIT canónico']])
    expect(textosDeRespaldo('x', 'MIT OR Apache-2.0', new Map(), canonicos)).toEqual(['texto MIT canónico'])
    expect(textosDeRespaldo('x', 'ISC', new Map(), canonicos)).toEqual([])
  })

  it('el respaldo de un plugin de Tauri es el texto de su crate homóloga, nunca el de una crate ajena', () => {
    expect(crateHomologa('@tauri-apps/plugin-dialog')).toBe('tauri-plugin-dialog')
    expect(crateHomologa('react')).toBeNull()
    // Con el código viejo salía el menor alfabético por id: aquí `Aaa` (código de otra crate) es menor que el texto bueno.
    const crate = (name, text) => ({ crate: { name, version: '1.0.0', license: 'MIT', source: 'registry+x' }, text })
    const entradas = entradasDeCargoAbout({ licenses: [
      { id: 'MIT', text: 'Aaa fn main() { /* código de regex_syntax */ }', used_by: [crate('regex-syntax')] },
      { id: 'MIT', text: 'MIT (c) Tauri Programme', used_by: [{ crate: { name: 'tauri-plugin-dialog', version: '2.0.0', license: 'MIT', source: 'registry+x' } }] },
    ] })
    const porCrate = textosPorCrate(entradas)
    const canonicos = new Map([['MIT', 'MIT canónico']])
    expect(textosDeRespaldo('@tauri-apps/plugin-dialog', 'MIT', porCrate, canonicos)).toEqual(['MIT (c) Tauri Programme'])
    // Sin crate homóloga: el canónico, no el texto de regex-syntax.
    expect(textosDeRespaldo('@tauri-apps/plugin-clipboard-manager', 'MIT', porCrate, canonicos)).toEqual(['MIT canónico'])
    expect(textosDeRespaldo('otro', 'MIT', porCrate, canonicos).join()).not.toContain('regex_syntax')
  })

  it('aplica a npm las licencias aceptadas de about.toml', () => {
    const acc = aceptadasDeToml('x = 1\naccepted = [\n  "MIT",\n  "OFL-1.1",\n  "Apache-2.0 WITH LLVM-exception",\n]\ntargets = ["a"]')
    expect(acc).toEqual(['MIT', 'OFL-1.1', 'Apache-2.0 WITH LLVM-exception'])
    expect(licenciaAceptada('MIT', acc)).toBe(true)
    expect(licenciaAceptada('GPL-3.0-only OR MIT', acc)).toBe(true)
    expect(licenciaAceptada('GPL-3.0-only', acc)).toBe(false)
    expect(licenciaAceptada('MIT AND GPL-3.0-only', acc)).toBe(false)
    expect(licenciaAceptada('', acc)).toBe(false)
  })

  it('el generador para con un mensaje claro si un paquete npm trae una licencia no aceptada', () => {
    const dir = mkdtempSync(join(tmpdir(), 'lt-'))
    mkdirSync(join(dir, 'herramientas'))
    mkdirSync(join(dir, 'node_modules', 'malo'), { recursive: true })
    writeFileSync(join(dir, 'about.toml'), 'accepted = ["MIT"]\n')
    writeFileSync(join(dir, 'package-lock.json'), JSON.stringify({ packages: { '': {}, 'node_modules/malo': { version: '1.0.0', license: 'GPL-3.0-only' } } }))
    const r = spawnSync(process.execPath, ['--input-type=module', '-e', `
      import { entradasDeNpmEn } from ${JSON.stringify(pathToFileURL(join(import.meta.dirname, 'licencias-terceros.mjs')).href)}
      entradasDeNpmEn(${JSON.stringify(dir)}, new Map())`], { encoding: 'utf8' })
    expect(r.status).toBe(1)
    expect(r.stderr).toContain('malo@1.0.0')
    expect(r.stderr).toContain('GPL-3.0-only')
    expect(r.stderr).toContain('no está en `accepted` de app/about.toml')
  })

  it('reconoce la ejecución directa con rutas distintas del mismo archivo', () => {
    const dir = mkdtempSync(join(tmpdir(), 'lt-'))
    const f = join(dir, 'a.mjs')
    writeFileSync(f, '')
    symlinkSync(f, join(dir, 'enlace.mjs'))
    expect(esEjecucionDirecta(pathToFileURL(f).href, join(dir, 'enlace.mjs'))).toBe(true)
    expect(esEjecucionDirecta(pathToFileURL(f).href, join(dir, 'otro.mjs'))).toBe(false)
    expect(esEjecucionDirecta(pathToFileURL(f).href, undefined)).toBe(false)
    // Windows: la unidad en mayúsculas o minúsculas.
    expect(esEjecucionDirecta(pathToFileURL(f).href, f.toUpperCase(), 'win32')).toBe(true)
    expect(esEjecucionDirecta(pathToFileURL(f).href, f.toUpperCase(), 'linux')).toBe(false)
  })

  it('el texto plano lleva cada grupo con su cuenta y sus textos', () => {
    const txt = aTextoPlano(agrupar([e('a', '1.0.0', 'MIT', ['Texto A'])]))
    expect(txt).toContain('MIT (1 paquete)')
    expect(txt).toContain('  a 1.0.0 (rust)')
    expect(txt).toContain('Texto A')
  })
})
