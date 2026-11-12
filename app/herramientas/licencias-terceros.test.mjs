// La parte pura del generador de licencias de terceros (INS-47): agrupar, deduplicar y ordenar.
import { describe, expect, it } from 'vitest'
import {
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
    const m = new Map([['MIT', 'texto MIT']])
    expect(textosDeRespaldo('MIT OR Apache-2.0', m)).toEqual(['texto MIT'])
    expect(textosDeRespaldo('ISC', m)).toEqual([])
  })

  it('el texto plano lleva cada grupo con su cuenta y sus textos', () => {
    const txt = aTextoPlano(agrupar([e('a', '1.0.0', 'MIT', ['Texto A'])]))
    expect(txt).toContain('MIT (1 paquete)')
    expect(txt).toContain('  a 1.0.0 (rust)')
    expect(txt).toContain('Texto A')
  })
})
