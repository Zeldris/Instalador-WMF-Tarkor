// INS-47: licencias de terceros generadas en el build (docs/11, «Licencias de terceros»).
//
// Junta las dependencias que entran en la app (crates de Rust con cargo-about; paquetes de npm de producción con
// package-lock.json y node_modules) y escribe:
//   - src/licencias/generadas/terceros.json: lo que enseña la pantalla de licencias (no se versiona);
//   - dist-licencias/THIRD-PARTY-NOTICES.txt: el mismo contenido en texto plano, para publicarlo con cada versión
//     (INS-46; tampoco se versiona).
// Uso: `node herramientas/licencias-terceros.mjs` desde app/ (lo corre `npm run build` antes de compilar).
// La parte pura (agrupar, deduplicar, ordenar, dar formato) se exporta y la prueba `licencias-terceros.test.mjs`;
// el resto es entrada y salida.

import { spawnSync } from 'node:child_process'
import { existsSync, mkdirSync, readFileSync, readdirSync, writeFileSync } from 'node:fs'
import { dirname, join, resolve } from 'node:path'
import { fileURLToPath, pathToFileURL } from 'node:url'

export const VERSION_CARGO_ABOUT = '0.9.3'
export const ORDEN_INSTALAR = `cargo install cargo-about --locked --features cli --version ${VERSION_CARGO_ABOUT}`

// ---------- Parte pura ----------

/** Compara cadenas sin depender del idioma del sistema (el orden tiene que ser el mismo en todas las máquinas). */
export const comparar = (a, b) => (a < b ? -1 : a > b ? 1 : 0)

/**
 * La expresión SPDX en una forma estable: espacios colapsados y, si es plana (solo OR o solo AND, sin paréntesis),
 * con los términos ordenados, para que `MIT OR Apache-2.0` y `Apache-2.0 OR MIT` sean el mismo grupo.
 */
export function normalizarExpresion(expr) {
  const e = (expr ?? '').trim().replace(/\s+/g, ' ')
  if (!e) return 'Desconocida'
  if (e.includes('(')) return e
  for (const op of [' OR ', ' AND ']) {
    if (e.includes(op) && !e.includes(op === ' OR ' ? ' AND ' : ' OR ')) return e.split(op).sort(comparar).join(op)
  }
  return e
}

/** Los ids SPDX sueltos de una expresión (sin operadores ni paréntesis; `X WITH Y` queda como un solo id). */
export function idsDeExpresion(expr) {
  return (expr ?? '').replace(/[()]/g, ' ').split(/\s+(?:OR|AND)\s+/).map((s) => s.trim()).filter(Boolean)
}

/** Un texto de licencia sin sangrías de fin de línea ni líneas en blanco sobrantes, para comparar y guardar. */
export function limpiarTexto(texto) {
  return texto.replace(/\r\n?/g, '\n').split('\n').map((l) => l.replace(/\s+$/, '')).join('\n').replace(/^\n+|\n+$/g, '')
}

/**
 * Agrupa por licencia y deduplica textos idénticos.
 * `entradas`: `{ nombre, version, ecosistema: 'rust' | 'npm', licencia, textos: string[] }`.
 * Devuelve `{ grupos: [{ licencia, paquetes: [{ nombre, version, ecosistema }], textos: [{ texto, paquetes: number[] }] }] }`,
 * donde `paquetes` de cada texto son índices de `paquetes` del grupo. Todo en orden alfabético estable.
 */
export function agrupar(entradas) {
  const porLicencia = new Map()
  for (const e of entradas) {
    const licencia = normalizarExpresion(e.licencia)
    if (!porLicencia.has(licencia)) porLicencia.set(licencia, [])
    porLicencia.get(licencia).push(e)
  }
  const grupos = [...porLicencia].sort(([a], [b]) => comparar(a, b)).map(([licencia, lista]) => {
    // Un mismo paquete (nombre, versión, ecosistema) puede llegar dos veces (p. ej. dos destinos): una sola.
    const unicos = new Map()
    for (const e of lista) unicos.set(`${e.ecosistema}\0${e.nombre}\0${e.version}`, e)
    const ordenados = [...unicos.values()].sort((a, b) =>
      comparar(a.ecosistema, b.ecosistema) || comparar(a.nombre, b.nombre) || comparar(a.version, b.version))
    const paquetes = ordenados.map(({ nombre, version, ecosistema }) => ({ nombre, version, ecosistema }))
    const porTexto = new Map()
    ordenados.forEach((e, i) => {
      for (const t of new Set(e.textos.map(limpiarTexto).filter(Boolean))) {
        if (!porTexto.has(t)) porTexto.set(t, [])
        porTexto.get(t).push(i)
      }
    })
    const textos = [...porTexto].sort(([a], [b]) => comparar(a, b)).map(([texto, idx]) => ({ texto, paquetes: idx }))
    return { licencia, paquetes, textos }
  })
  return { grupos }
}

/** Entradas de Rust a partir de la salida JSON de `cargo about generate --format json`. */
export function entradasDeCargoAbout(salida) {
  const porCrate = new Map()
  for (const lic of salida.licenses) {
    for (const u of lic.used_by) {
      const c = u.crate
      if (!c.source) continue // los miembros del propio workspace (tarkor, tarkor-nucleo) no son de terceros
      const clave = `${c.name}\0${c.version}`
      if (!porCrate.has(clave)) porCrate.set(clave, { nombre: c.name, version: c.version, ecosistema: 'rust', licencia: c.license || lic.id, textos: [] })
      porCrate.get(clave).textos.push(lic.text)
    }
  }
  return [...porCrate.values()]
}

/** Paquetes de producción de un `package-lock.json` (v2/v3): `{ nombre, version, ruta, licencia, opcional }`. */
export function paquetesDeProduccion(lock) {
  const salida = []
  for (const [ruta, p] of Object.entries(lock.packages ?? {})) {
    if (!ruta || p.dev || p.link) continue
    const nombre = ruta.slice(ruta.lastIndexOf('node_modules/') + 'node_modules/'.length)
    salida.push({ nombre, version: p.version, ruta, licencia: p.license, opcional: Boolean(p.optional) })
  }
  return salida
}

/** ¿Es este archivo uno de licencia con texto (no solo la etiqueta SPDX de `LICENSE.spdx`)? */
export const esArchivoDeLicencia = (nombre) => /^(licen[sc]e|copying)([-_.].*)?$/i.test(nombre) && !/\.spdx$/i.test(nombre)

/**
 * Los textos de respaldo de un paquete npm sin archivo de licencia propio: el texto estándar de cada id de su
 * licencia que ya traiga alguna crate (`textosPorId`: id SPDX -> texto). Devuelve [] si no hay ninguno.
 */
export function textosDeRespaldo(licencia, textosPorId) {
  return idsDeExpresion(licencia).map((id) => textosPorId.get(id)).filter(Boolean)
}

/** Mapa id SPDX -> primer texto (el de menor orden, para que sea estable) de la salida de cargo-about. */
export function textosPorId(salida) {
  const m = new Map()
  for (const l of [...salida.licenses].sort((a, b) => comparar(a.text, b.text))) if (!m.has(l.id)) m.set(l.id, l.text)
  return m
}

/** El texto plano de `THIRD-PARTY-NOTICES.txt`. */
export function aTextoPlano(datos) {
  const raya = '='.repeat(78)
  const partes = ['Licencias de terceros de Tarkor', '', `Paquetes: ${datos.grupos.reduce((n, g) => n + g.paquetes.length, 0)} · Licencias: ${datos.grupos.length}`, '']
  for (const g of datos.grupos) {
    partes.push(raya, `${g.licencia} (${g.paquetes.length} ${g.paquetes.length === 1 ? 'paquete' : 'paquetes'})`, raya, '')
    for (const p of g.paquetes) partes.push(`  ${p.nombre} ${p.version} (${p.ecosistema})`)
    for (const t of g.textos) {
      partes.push('', '-'.repeat(78), `Texto usado por: ${t.paquetes.map((i) => g.paquetes[i].nombre).join(', ')}`, '-'.repeat(78), '', t.texto)
    }
    partes.push('')
  }
  return partes.join('\n')
}

// ---------- Entrada y salida ----------

const AQUI = dirname(fileURLToPath(import.meta.url))
const APP = resolve(AQUI, '..')

function fallar(mensaje) {
  console.error(`licencias-terceros: ${mensaje}`)
  process.exit(1)
}

function correrCargoAbout() {
  const version = spawnSync('cargo', ['about', '--version'], { cwd: APP, encoding: 'utf8' })
  if (version.error || version.status !== 0) {
    fallar(`falta cargo-about. Instálalo con:\n  ${ORDEN_INSTALAR}`)
  }
  const r = spawnSync('cargo', ['about', 'generate', '--workspace', '--locked', '--format', 'json'], {
    cwd: APP, encoding: 'utf8', maxBuffer: 1 << 30,
  })
  if (r.status !== 0) {
    process.stderr.write(r.stderr ?? '')
    fallar('cargo-about falló (arriba, el motivo; una licencia no aceptada se añade a `accepted` de app/about.toml solo tras revisarla).')
  }
  return JSON.parse(r.stdout)
}

function entradasDeNpm(porId) {
  const lock = JSON.parse(readFileSync(join(APP, 'package-lock.json'), 'utf8'))
  // Un paquete opcional que no se instala en esta plataforma no entra en la app: se salta.
  return paquetesDeProduccion(lock).filter((p) => !(p.opcional && !existsSync(join(APP, p.ruta)))).map((p) => {
    const dir = join(APP, p.ruta)
    if (!existsSync(dir)) fallar(`falta ${p.ruta}: corre \`npm ci\` antes.`)
    let licencia = p.licencia
    if (!licencia) licencia = JSON.parse(readFileSync(join(dir, 'package.json'), 'utf8')).license
    if (!licencia) fallar(`el paquete npm ${p.nombre}@${p.version} no declara licencia.`)
    const textos = readdirSync(dir).filter(esArchivoDeLicencia).sort().map((f) => readFileSync(join(dir, f), 'utf8'))
    if (textos.length === 0) {
      const respaldo = textosDeRespaldo(licencia, porId)
      if (respaldo.length === 0) fallar(`el paquete npm ${p.nombre}@${p.version} (${licencia}) no trae archivo de licencia y no hay texto estándar de respaldo.`)
      console.warn(`licencias-terceros: ${p.nombre}@${p.version} no trae archivo de licencia; se usa el texto estándar de ${licencia}.`)
      textos.push(...respaldo)
    }
    return { nombre: p.nombre, version: p.version, ecosistema: 'npm', licencia, textos }
  })
}

function main() {
  const cargo = correrCargoAbout()
  const datos = agrupar([...entradasDeCargoAbout(cargo), ...entradasDeNpm(textosPorId(cargo))])
  const json = join(APP, 'src', 'licencias', 'generadas', 'terceros.json')
  const txt = join(APP, 'dist-licencias', 'THIRD-PARTY-NOTICES.txt')
  mkdirSync(dirname(json), { recursive: true })
  mkdirSync(dirname(txt), { recursive: true })
  writeFileSync(json, JSON.stringify(datos) + '\n')
  writeFileSync(txt, aTextoPlano(datos))
  const paquetes = datos.grupos.reduce((n, g) => n + g.paquetes.length, 0)
  console.log(`licencias-terceros: ${datos.grupos.length} licencias, ${paquetes} paquetes -> ${json} y ${txt}`)
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) main()
