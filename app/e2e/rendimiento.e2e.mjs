// Prueba de punta a punta de Ajustes → Rendimiento de la IA y de la pantalla «El motor de IA se ha
// detenido» (INS-43, docs/11), sobre la app instalada de verdad (Linux).
//
// A diferencia de asistente.e2e.mjs, aquí el motor es el PROPIO de la app, no un Ollama externo: con
// TARKOR_OLLAMA_URL no habría reinicio automático, ni modelos sobrantes, ni pantalla de motor
// detenido. El script prepara la carpeta de datos (config.json con el asistente parado en la elección de
// perfil (Mínimo) y el equipo ya analizado, y un `bin/ollama` que es el Ollama falso en modo `serve`, ver ollama-falso.mjs), abre la
// app y comprueba, por este orden:
//   0. (el final del asistente, para arrancar el motor y dejar un modelo cargado)
//   1. Ajustes dice dónde corre la IA (modelo cargado a medias en la gráfica: «Repartida: …»).
//   2. Cambiar a otro perfil enseña el progreso y, al acabar, el perfil nuevo (y se guarda). Con FALSO_CORTES_PULL, la
//      primera descarga se corta como sin internet y Ajustes enseña «Esperando conexión» y sigue sola.
//   3. Sobran modelos: «Borrar modelos que ya no uso (X GB)» y al pulsarlo desaparece (y se borran).
//   4. «Ver detalles» del informe enseña `~` en vez de la carpeta personal y sin el nombre de usuario.
//   5. Matar el motor dos veces agota el reinicio automático: sale «El motor de IA se ha detenido».
//   6. Reintentar con el motor sin poder arrancar se queda con el error; con el motor disponible
//      otra vez, vuelve a Ajustes.
//   7. «Borrar datos del juego» (INS-45): «Borrar» desactivado sin casillas; con «partidas» marcada, para el
//      motor, borra las partidas y la configuración, deja la IA y enseña la pantalla final.
//
// Uso (ver app/README.md): TARKOR_DATOS y HOME de la app deben ser los del entorno con que se lanzó
// tauri-driver, y TARKOR_OLLAMA_URL no debe estar puesta.
//   node e2e/rendimiento.e2e.mjs /usr/bin/tarkor /tmp/capturas
//
// Sin dependencias: habla el protocolo WebDriver por HTTP directamente (los ayudantes son los de
// asistente.e2e.mjs, copiados para que cada prueba se lea sola).

import { execSync } from 'node:child_process'
import { chmodSync, existsSync, mkdirSync, readFileSync, rmSync, writeFileSync } from 'node:fs'
import { basename, dirname, join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const [app = '/usr/bin/tarkor', capturas = 'e2e-capturas'] = process.argv.slice(2)
const datos = process.env.TARKOR_DATOS
const casa = process.env.HOME ?? ''
if (!datos) throw new Error('Falta TARKOR_DATOS (la misma carpeta con la que se lanzó tauri-driver)')
if (process.env.TARKOR_OLLAMA_URL) throw new Error('Con TARKOR_OLLAMA_URL el motor es externo: no hay reinicio, sobrantes ni pantalla de motor detenido. Quítala.')
const usuario = basename(casa)
if (usuario.length < 4) throw new Error(`HOME (${casa}) debe acabar en un nombre de usuario reconocible (4 letras o más) para comprobar que el informe no lo cuenta`)
const DRIVER = process.env.WEBDRIVER_URL ?? 'http://127.0.0.1:4444'
mkdirSync(capturas, { recursive: true })

const aqui = dirname(fileURLToPath(import.meta.url))
const guion = resolve(aqui, 'ollama-falso.mjs')
const ia = join(datos, 'ia')
const modelos = join(ia, 'modelos')
const marca = join(datos, 'no-arrancar') // si existe, el «ollama» falso se cierra al arrancar

const ELEM = 'element-6066-11e4-a52e-4f735466cecf'
let sesion

async function wd(metodo, ruta, cuerpo) {
  const r = await fetch(`${DRIVER}${ruta}`, {
    method: metodo,
    headers: { 'content-type': 'application/json' },
    body: cuerpo === undefined ? undefined : JSON.stringify(cuerpo),
  })
  const json = await r.json()
  if (!r.ok) throw new Error(`${metodo} ${ruta}: ${JSON.stringify(json.value ?? json)}`)
  return json.value
}
const s = (ruta) => `/session/${sesion}${ruta}`
const esperar = (ms) => new Promise((ok) => setTimeout(ok, ms))

async function abrir() {
  const v = await wd('POST', '/session', { capabilities: { alwaysMatch: { 'tauri:options': { application: app } } } })
  sesion = v.sessionId
}
const cerrar = () => wd('DELETE', `/session/${sesion}`)

async function buscar(xpath, timeoutMs = 15000) {
  const fin = Date.now() + timeoutMs
  for (;;) {
    try {
      return (await wd('POST', s('/element'), { using: 'xpath', value: xpath }))[ELEM]
    } catch (e) {
      if (Date.now() > fin) throw new Error(`No aparece ${xpath}`, { cause: e })
      await esperar(200)
    }
  }
}
/** Espera a que NO exista el elemento. */
async function desaparece(xpath, timeoutMs = 15000) {
  const fin = Date.now() + timeoutMs
  for (;;) {
    try { await wd('POST', s('/element'), { using: 'xpath', value: xpath }) } catch { return }
    if (Date.now() > fin) throw new Error(`Sigue ahí ${xpath}`)
    await esperar(200)
  }
}
const boton = (t) => `//button[starts-with(normalize-space(), ${JSON.stringify(t)})]`
const titulo = (t) => `//h1[normalize-space()=${JSON.stringify(t)}]`
async function pulsar(xpath, timeoutMs = 15000) {
  const id = await buscar(xpath, timeoutMs)
  const fin = Date.now() + timeoutMs
  while (await wd('GET', s(`/element/${id}/property/disabled`))) {
    if (Date.now() > fin) throw new Error(`${xpath} sigue deshabilitado`)
    await esperar(200)
  }
  await wd('POST', s(`/element/${id}/click`), {})
}
const pantalla = () => wd('POST', s('/execute/sync'), { script: 'return document.body.innerText', args: [] })
/** Espera a que el texto de la pantalla case con la expresión y lo devuelve. */
async function veTexto(re, timeoutMs = 15000) {
  const fin = Date.now() + timeoutMs
  for (;;) {
    const t = await pantalla()
    if (re.test(t)) return t
    if (Date.now() > fin) throw new Error(`No se ve ${re} en la pantalla:\n${t}`)
    await esperar(150)
  }
}

let n = 0
async function captura(nombre) {
  const base = join(capturas, `r${String(++n).padStart(2, '0')}-${nombre}`)
  writeFileSync(`${base}.png`, Buffer.from(await wd('GET', s('/screenshot')), 'base64'))
  writeFileSync(`${base}.txt`, await pantalla().catch(() => ''))
}
function comprobar(cond, mensaje) {
  if (!cond) throw new Error(`Falla: ${mensaje}`)
  console.log(`  ✓ ${mensaje}`)
}

/** Deja la carpeta de datos como la de alguien que ya hizo el asistente con el perfil Mínimo. */
function preparar() {
  // Nunca se borra nada: una carpeta con datos de verdad no se pisa.
  if (existsSync(join(datos, 'config.json'))) throw new Error(`${datos} ya tiene un config.json: usa una carpeta nueva (mktemp -d)`)
  const version = JSON.parse(readFileSync(join(aqui, '..', 'catalogo', 'catalogo.json'), 'utf8')).motor.version
  const motor = join(ia, 'motor', version)
  mkdirSync(join(motor, 'bin'), { recursive: true })
  mkdirSync(modelos, { recursive: true })
  const ejecutable = join(motor, 'bin', 'ollama')
  writeFileSync(ejecutable, `#!/bin/sh
if [ -e "${marca}" ]; then echo "el motor falso no puede arrancar (marca no-arrancar)" >&2; exit 1; fi
FALSO_PASO_MS=500 exec "${process.execPath}" "${guion}" serve
`)
  chmodSync(ejecutable, 0o755)
  writeFileSync(join(motor, '.completo'), '')
  // Los modelos del Mínimo, uno cargado, y un `qwen2.5:7b` que quedó de un perfil de antes.
  writeFileSync(join(modelos, 'falso.json'), JSON.stringify({ modelos: ['qwen2.5:1.5b-instruct', 'nomic-embed-text:latest', 'qwen2.5:7b'], cargado: null }))
  writeFileSync(join(datos, 'config.json'), JSON.stringify({
    version: 1,
    consentimientoAceptado: true,
    permisoAnalisis: true,
    equipo: {
      ramTotalMb: 32768, ramLibreMb: 24000, cpuModelo: 'CPU de prueba', nucleos: 8, hilos: 16, discoLibreMb: 400000, sistema: 'Linux',
      gpus: [{ nombre: 'GPU de prueba', fabricante: 'nvidia', vramMb: 12288, integrada: false }],
    },
    perfil: 'minimo',
    pasoAsistente: 4,
  }))
}
const leerConfig = () => JSON.parse(readFileSync(join(datos, 'config.json'), 'utf8'))
const leerModelos = () => JSON.parse(readFileSync(join(modelos, 'falso.json'), 'utf8')).modelos
const pidsMotor = () => {
  try { return execSync('pgrep -f "[o]llama-falso.mjs serve"', { encoding: 'utf8' }).split('\n').filter(Boolean).map(Number) } catch { return [] }
}
/** Mata el motor falso y espera a que desaparezca; devuelve el pid que mató. */
async function matarMotor() {
  const [pid] = pidsMotor()
  if (!pid) throw new Error('No hay motor falso en marcha que matar')
  process.kill(pid, 'SIGKILL')
  return pid
}
async function esperaOtroMotor(distintoDe, timeoutMs = 20000) {
  const fin = Date.now() + timeoutMs
  for (;;) {
    const otro = pidsMotor().find((p) => p !== distintoDe)
    if (otro) return otro
    if (Date.now() > fin) throw new Error('El motor no se reinició solo tras matarlo la primera vez')
    await esperar(200)
  }
}

async function recorrido() {
  preparar()
  await abrir()
  console.log('Ajustes → Rendimiento de la IA, con el motor propio')
  // La app no arranca el motor sola al abrirse con el asistente completado (llegará con INS-41):
  // se hace el final del asistente, que lo instala (ya está), lo arranca y descarga los modelos del
  // Mínimo con el Ollama falso. La comprobación de la narración deja un modelo cargado.
  await buscar(titulo('Elige cuánto dedicarle'))
  await pulsar(boton('Descargar'))
  await pulsar(boton('Comprobar la instalación'), 120000)
  await buscar(titulo('Comprobación'))
  await veTexto(/niebla/, 60000)
  await pulsar(boton('Continuar'))
  await buscar(titulo('Todo preparado'))
  await pulsar(boton('Jugar'))
  await buscar(titulo('Aquí se abrirá el juego'), 30000)
  await veTexto(/El narrador está listo/, 60000)
  await pulsar(boton('Ajustes'))
  await buscar(titulo('Rendimiento de la IA'))

  // 1. Dónde corre la IA.
  const dondeCorre = await veTexto(/Repartida: 60 % gráfica, 40 % procesador \(va más lenta\)/, 30000)
  comprobar(/Repartida: 60 % gráfica, 40 % procesador/.test(dondeCorre) && /ocupa [\d.,]+ GB/.test(dondeCorre), '1. Ajustes dice «Repartida: 60 % gráfica, 40 % procesador» y la memoria que ocupa')
  await captura('donde-corre')

  // 2. Cambiar de perfil: progreso y perfil nuevo.
  await pulsar(`//button[.//span[@class="nombre"][normalize-space()="Ligero"]]`)
  await pulsar(boton('Cambiar y descargar'))
  if (Number(process.env.FALSO_CORTES_PULL ?? 0) > 0) {
    // El Ollama falso corta la primera descarga como sin internet: Ajustes espera y reintenta sola (INS-42, trozo C).
    const espera = await veTexto(/Esperando conexión · Reintentando en \d+ s\./, 30000)
    comprobar(/Esperando conexión/.test(espera), '2. sin red, el cambio de perfil espera y reintenta solo («Esperando conexión · Reintentando en N s»)')
    await captura('cambiando-esperando')
  }
  const progreso = await veTexto(/Descargando lo que falta de qwen3\.5:2b \(\d+ %\)/, 30000)
  comprobar(progreso.includes('qwen3.5:2b'), '2. el cambio enseña el progreso de la descarga (qwen3.5:2b)')
  await captura('cambiando')
  await veTexto(/Perfil actual: Ligero/, 60000)
  comprobar(true, '2. al acabar, Ajustes muestra el perfil nuevo (Ligero)')
  comprobar(leerConfig().perfil === 'ligero', '2. config.json guarda el perfil ligero')
  comprobar(leerModelos().includes('qwen3.5:2b'), '2. el motor tiene el modelo nuevo')
  await veTexto(/Repartida: 60 %/, 30000)
  comprobar(true, '2. tras reiniciar el motor con el perfil nuevo, Ajustes vuelve a decir dónde corre la IA')

  // 3. Modelos sobrantes.
  const borrar = await veTexto(/Borrar modelos que ya no uso \(4[.,]7 GB\)/, 15000)
  comprobar(/Borrar modelos que ya no uso \(4[.,]7 GB\)/.test(borrar), '3. sale «Borrar modelos que ya no uso (4,7 GB)» (el qwen2.5:7b de antes)')
  await captura('sobrantes')
  await pulsar(boton('Borrar modelos que ya no uso'))
  await desaparece(boton('Borrar modelos que ya no uso'), 15000)
  comprobar(!leerModelos().includes('qwen2.5:7b'), '3. al pulsarlo desaparece el botón y el motor ya no tiene qwen2.5:7b')
  comprobar(['qwen3.5:2b', 'qwen2.5:1.5b-instruct', 'nomic-embed-text:latest'].every((m) => leerModelos().includes(m)), '3. los modelos del perfil siguen ahí')

  // 4. Informe anónimo.
  await pulsar(boton('Ver detalles'))
  const informe = await texto('//pre[@aria-label="Copiar informe"]', 15000)
  await captura('informe')
  comprobar(informe.includes('HOME:~'), '4. «Ver detalles» enseña `~` en vez de la carpeta personal (HOME:~)')
  comprobar(!informe.includes(casa) && !informe.includes(usuario), `4. el informe no lleva la carpeta personal ni el nombre de usuario («${usuario}»)`)
  const registro = readFileSync(join(datos, 'registros', 'motor-ia.log'), 'utf8')
  comprobar(registro.includes(casa), '4. (control) el registro del motor sí lleva la carpeta personal: el informe la quita de verdad')

  // 5. Matar el motor dos veces.
  const primero = await matarMotor()
  const segundo = await esperaOtroMotor(primero)
  comprobar(segundo !== primero, '5. tras matar el motor, la app lo reinicia sola (reinicio automático)')
  process.kill(segundo, 'SIGKILL')
  await buscar(titulo('El motor de IA se ha detenido'), 30000)
  await captura('motor-detenido')
  comprobar(pidsMotor().length === 0, '5. a la segunda caída no hay más reinicios y sale «El motor de IA se ha detenido»')
  comprobar((await pantalla()).includes('Tu partida está guardada hasta el último turno completado'), '5. la pantalla dice que la partida está guardada')

  // 6. Reintentar.
  writeFileSync(marca, '')
  await pulsar(boton('Reintentar'))
  const error = await texto('//div[@role="alert"]', 30000)
  comprobar(error.includes('se cerró al arrancar'), `6. Reintentar sin poder arrancar el motor se queda con el error real: "${error.slice(0, 70)}…"`)
  await buscar(titulo('El motor de IA se ha detenido'))
  await captura('reintento-fallido')
  rmSync(marca)
  await pulsar(boton('Reintentar'))
  await buscar(titulo('Rendimiento de la IA'), 30000)
  await desaparece(titulo('El motor de IA se ha detenido'))
  await veTexto(/Repartida: 60 %/, 30000)
  comprobar(pidsMotor().length === 1, '6. Reintentar con el motor disponible vuelve a Ajustes, con el motor en marcha y dónde corre la IA')
  await captura('reintentado')

  // 7. Borrar datos del juego (INS-45): solo las partidas; la IA se queda.
  mkdirSync(join(datos, 'partidas'), { recursive: true })
  writeFileSync(join(datos, 'partidas', 'uno.sav'), 'x')
  await pulsar(boton('Borrar datos del juego'))
  await buscar('//*[@role="dialog"]')
  const botonBorrar = '//button[normalize-space()="Borrar"]'
  const aBorrar = await buscar(botonBorrar)
  comprobar(await wd('GET', s(`/element/${aBorrar}/property/disabled`)) === true, '7. «Borrar» está desactivado mientras no se marque nada')
  await captura('borrar-dialogo')
  await pulsar('//label[contains(., "Borrar también mis partidas guardadas")]')
  await pulsar(botonBorrar)
  await veTexto(/Datos borrados\. Ya puedes borrar el archivo \.AppImage/)
  await buscar(boton('Cerrar Tarkor'))
  await captura('borrar-final')
  comprobar(pidsMotor().length === 0, '7. al borrar se para el motor')
  comprobar(!existsSync(join(datos, 'partidas')) && !existsSync(join(datos, 'config.json')), '7. se borraron las partidas y la configuración (el siguiente arranque empieza el asistente)')
  comprobar(existsSync(join(ia, 'modelos')), '7. la IA se queda, porque su casilla no estaba marcada')
  await cerrar()
}

async function texto(xpath, timeoutMs) {
  return wd('GET', s(`/element/${await buscar(xpath, timeoutMs)}/text`))
}

try {
  await recorrido()
  console.log(`Todo correcto. Capturas en ${capturas}`)
} catch (e) {
  console.error(e)
  if (sesion) {
    await captura('fallo').catch(() => {})
    await cerrar().catch(() => {})
  }
  process.exit(1)
} finally {
  if (existsSync(marca)) rmSync(marca)
}
