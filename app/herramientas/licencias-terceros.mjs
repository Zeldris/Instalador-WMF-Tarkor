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
import { existsSync, mkdirSync, realpathSync, mkdtempSync, readFileSync, readdirSync, rmSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { dirname, join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

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

/** Crate de Rust homóloga de un paquete npm de los plugins de Tauri (`@tauri-apps/plugin-X` -> `tauri-plugin-X`), o null. */
export function crateHomologa(nombre) {
  const m = /^@tauri-apps\/plugin-(.+)$/.exec(nombre)
  return m ? `tauri-plugin-${m[1]}` : null
}

/**
 * Los textos de respaldo de un paquete npm sin archivo de licencia propio, por este orden: los de su crate homóloga
 * si cargo-about la trae (`textosPorCrate`: nombre de crate -> textos) y, si no, el texto canónico de cada id SPDX de
 * su licencia (`canonicos`: id -> texto, guardados en el repo). Nunca el texto de una crate no relacionada. [] si no hay.
 */
export function textosDeRespaldo(nombre, licencia, textosPorCrate, canonicos) {
  const crate = crateHomologa(nombre)
  const propios = crate ? textosPorCrate.get(crate) : null
  if (propios && propios.length > 0) return propios
  return idsDeExpresion(licencia).map((id) => canonicos.get(id)).filter(Boolean)
}

/** Mapa nombre de crate -> textos de licencia, de las entradas de `entradasDeCargoAbout`. */
export function textosPorCrate(entradas) {
  return new Map(entradas.map((e) => [e.nombre, e.textos]))
}

/** Licencias aceptadas (`accepted`) de un `about.toml`: lista de ids o expresiones SPDX. */
export function aceptadasDeToml(toml) {
  const m = /^accepted\s*=\s*\[([^\]]*)\]/m.exec(toml)
  if (!m) throw new Error('about.toml no tiene `accepted`')
  return [...m[1].matchAll(/"([^"]+)"/g)].map((x) => x[1])
}

/**
 * ¿Está aceptada esta expresión SPDX? Basta que cada término `AND` tenga alguna alternativa `OR` aceptada
 * (`Apache-2.0 WITH LLVM-exception` cuenta como un id). Sin paréntesis; con ellos, todos sus ids deben estar aceptados.
 */
export function licenciaAceptada(expr, aceptadas) {
  const ok = (id) => aceptadas.includes(id.trim())
  const e = (expr ?? '').trim()
  if (!e) return false
  if (e.includes('(')) return idsDeExpresion(e).every(ok)
  return e.split(/\s+AND\s+/).every((y) => y.split(/\s+OR\s+/).some(ok))
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

// Textos canónicos de reserva por id SPDX (en el repo, nunca el de una crate cualquiera).
const CANONICOS = { 'Apache-2.0': 'Apache-2.0.txt', MIT: 'MIT-SPDX.txt' }

function fallar(mensaje) {
  console.error(`licencias-terceros: ${mensaje}`)
  process.exit(1)
}

function correrCargoAbout() {
  const version = spawnSync('cargo', ['about', '--version'], { cwd: APP, encoding: 'utf8' })
  if (version.error || version.status !== 0) {
    fallar(`falta cargo-about. Instálalo con:\n  ${ORDEN_INSTALAR}`)
  }
  if (version.stdout.trim() !== `cargo-about ${VERSION_CARGO_ABOUT}`) {
    fallar(`cargo-about es «${version.stdout.trim()}» y el generador está fijado a ${VERSION_CARGO_ABOUT}. Instálalo con:\n  ${ORDEN_INSTALAR}`)
  }
  // A un archivo con -o, no por stdout: bajo PowerShell (el CI de Windows) cargo-about se niega a escribir en una
  // salida redirigida, por los problemas de codificación de PowerShell.
  const dir = mkdtempSync(join(tmpdir(), 'cargo-about-'))
  const salida = join(dir, 'licencias.json')
  try {
    const r = spawnSync('cargo', ['about', 'generate', '--workspace', '--locked', '--format', 'json', '-o', salida], {
      cwd: APP, encoding: 'utf8',
    })
    if (r.status !== 0 || !existsSync(salida)) {
      process.stderr.write(r.stderr ?? '')
      fallar('cargo-about falló (arriba, el motivo; una licencia no aceptada se añade a `accepted` de app/about.toml solo tras revisarla).')
    }
    return JSON.parse(readFileSync(salida, 'utf8'))
  } finally {
    rmSync(dir, { recursive: true, force: true })
  }
}

export function entradasDeNpmEn(APP, porCrate) {
  const aceptadas = aceptadasDeToml(readFileSync(join(APP, 'about.toml'), 'utf8'))
  const canonicos = new Map(Object.entries(CANONICOS).map(([id, f]) => [id, limpiarTexto(readFileSync(join(AQUI, '..', 'src', 'licencias', f), 'utf8'))]))
  const lock = JSON.parse(readFileSync(join(APP, 'package-lock.json'), 'utf8'))
  // Un paquete opcional que no se instala en esta plataforma no entra en la app: se salta.
  return paquetesDeProduccion(lock).filter((p) => !(p.opcional && !existsSync(join(APP, p.ruta)))).map((p) => {
    const dir = join(APP, p.ruta)
    if (!existsSync(dir)) fallar(`falta ${p.ruta}: corre \`npm ci\` antes.`)
    let licencia = p.licencia
    if (!licencia) licencia = JSON.parse(readFileSync(join(dir, 'package.json'), 'utf8')).license
    if (!licencia) fallar(`el paquete npm ${p.nombre}@${p.version} no declara licencia.`)
    if (!licenciaAceptada(licencia, aceptadas)) {
      fallar(`el paquete npm ${p.nombre}@${p.version} tiene la licencia «${licencia}», que no está en \`accepted\` de app/about.toml (se añade solo tras revisarla).`)
    }
    const textos = readdirSync(dir).filter(esArchivoDeLicencia).sort().map((f) => readFileSync(join(dir, f), 'utf8'))
    if (textos.length === 0) {
      const respaldo = textosDeRespaldo(p.nombre, licencia, porCrate, canonicos)
      if (respaldo.length === 0) fallar(`el paquete npm ${p.nombre}@${p.version} (${licencia}) no trae archivo de licencia y no hay texto de respaldo (ni de su crate homóloga ni canónico).`)
      console.warn(`licencias-terceros: ${p.nombre}@${p.version} no trae archivo de licencia; se usa el texto de respaldo de ${licencia}.`)
      textos.push(...respaldo)
    }
    return { nombre: p.nombre, version: p.version, ecosistema: 'npm', licencia, textos }
  })
}

function main() {
  const cargo = correrCargoAbout()
  const rust = entradasDeCargoAbout(cargo)
  const datos = agrupar([...rust, ...entradasDeNpmEn(APP, textosPorCrate(rust))])
  const json = join(APP, 'src', 'licencias', 'generadas', 'terceros.json')
  const txt = join(APP, 'dist-licencias', 'THIRD-PARTY-NOTICES.txt')
  mkdirSync(dirname(json), { recursive: true })
  mkdirSync(dirname(txt), { recursive: true })
  writeFileSync(json, JSON.stringify(datos) + '\n')
  writeFileSync(txt, aTextoPlano(datos))
  const paquetes = datos.grupos.reduce((n, g) => n + g.paquetes.length, 0)
  console.log(`licencias-terceros: ${datos.grupos.length} licencias, ${paquetes} paquetes -> ${json} y ${txt}`)
}

/** ¿Se corre este archivo directamente? Compara rutas reales (enlaces simbólicos) y, en Windows, sin distinguir mayúsculas. */
export function esEjecucionDirecta(url, argv1, plataforma = process.platform) {
  if (!argv1) return false
  const real = (p) => { try { return realpathSync(p) } catch { return resolve(p) } }
  const norm = (p) => (plataforma === 'win32' ? real(p).toLowerCase() : real(p))
  return norm(fileURLToPath(url)) === norm(argv1)
}

if (esEjecucionDirecta(import.meta.url, process.argv[1])) main()
