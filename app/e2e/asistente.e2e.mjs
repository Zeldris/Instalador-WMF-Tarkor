// Prueba de punta a punta del asistente sobre la app instalada de verdad (Linux).
//
// Recorre las 7 pantallas pulsando los botones por su texto, como un jugador, guarda una captura
// de cada paso y comprueba lo que queda en config.json. Luego vuelve a abrir la app para ver que
// recuerda que el asistente ya se completó.
//
// Uso (ver app/README.md):
//   TARKOR_DATOS=/tmp/datos tauri-driver &          # necesita WebKitWebDriver (webkit2gtk-driver)
//   node e2e/asistente.e2e.mjs /usr/bin/tarkor /tmp/capturas
//
// Sin dependencias: habla el protocolo WebDriver por HTTP directamente.

import { mkdirSync, readFileSync, writeFileSync } from 'node:fs'
import { join } from 'node:path'

const [app = '/usr/bin/tarkor', capturas = 'e2e-capturas'] = process.argv.slice(2)
const datos = process.env.TARKOR_DATOS
if (!datos) throw new Error('Falta TARKOR_DATOS (la misma carpeta con la que se lanzó tauri-driver)')
const DRIVER = process.env.WEBDRIVER_URL ?? 'http://127.0.0.1:4444'
mkdirSync(capturas, { recursive: true })

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

/** Espera a que exista un elemento (XPath) y lo devuelve. */
async function buscar(xpath, timeoutMs = 15000) {
  const fin = Date.now() + timeoutMs
  for (;;) {
    try {
      const v = await wd('POST', s('/element'), { using: 'xpath', value: xpath })
      return v[ELEM]
    } catch (e) {
      if (Date.now() > fin) throw new Error(`No aparece ${xpath}`, { cause: e })
      await esperar(200)
    }
  }
}

const boton = (texto) => `//button[starts-with(normalize-space(), ${JSON.stringify(texto)})]`
const titulo = (texto) => `//h1[normalize-space()=${JSON.stringify(texto)}]`
const conTexto = (texto) => `//*[contains(normalize-space(text()), ${JSON.stringify(texto)})]`

async function pulsar(texto, timeoutMs) {
  const id = await buscar(boton(texto), timeoutMs)
  // Un botón deshabilitado se ignora: se espera a que se habilite.
  const fin = Date.now() + (timeoutMs ?? 15000)
  while (await wd('GET', s(`/element/${id}/property/disabled`))) {
    if (Date.now() > fin) throw new Error(`"${texto}" sigue deshabilitado`)
    await esperar(200)
  }
  await wd('POST', s(`/element/${id}/click`), {})
}

async function texto(xpath, timeoutMs) {
  return wd('GET', s(`/element/${await buscar(xpath, timeoutMs)}/text`))
}

let n = 0
async function captura(nombre) {
  const png = await wd('GET', s('/screenshot'))
  writeFileSync(join(capturas, `${String(++n).padStart(2, '0')}-${nombre}.png`), Buffer.from(png, 'base64'))
}

function comprobar(cond, mensaje) {
  if (!cond) throw new Error(`Falla: ${mensaje}`)
  console.log(`  ✓ ${mensaje}`)
}

const leerConfig = () => JSON.parse(readFileSync(join(datos, 'config.json'), 'utf8'))

async function recorrido() {
  await abrir()
  console.log('Primer arranque')

  await buscar(titulo('Bienvenido a Tarkor'))
  await captura('bienvenida')
  await pulsar('Empezar')

  await buscar(titulo('Qué se instala'))
  const aceptar = await buscar(boton('Aceptar y continuar'))
  comprobar(await wd('GET', s(`/element/${aceptar}/property/disabled`)), 'no se puede continuar sin marcar la casilla')
  await captura('que-se-instala')
  await wd('POST', s(`/element/${await buscar('//input[@id="acepto"]')}/click`), {})
  await pulsar('Aceptar y continuar')

  await buscar(titulo('¿Podemos revisar tu equipo?'))
  await captura('permiso')
  await pulsar('Analizar mi equipo')
  await buscar(titulo('Tu equipo'))
  const recomendacion = await texto(conTexto('Te recomendamos el perfil'))
  comprobar(/Te recomendamos el perfil \S+/.test(recomendacion), `análisis real del equipo: "${recomendacion}"`)
  await captura('tu-equipo')
  await pulsar('Continuar')

  await buscar(titulo('Elige cuánto dedicarle'))
  const seleccionada = await texto('//button[@aria-pressed="true"]//span[@class="nombre"]')
  comprobar(recomendacion.includes(seleccionada), `el perfil recomendado (${seleccionada}) viene seleccionado`)
  await captura('perfil')
  await pulsar('Descargar')

  await buscar(titulo('Descargando'))
  await captura('descarga')
  if (process.env.E2E_ESPERA_ERROR_RED) {
    // Motor real en una red que bloquea el registro de modelos: el motor se instala y arranca,
    // y la descarga del modelo muestra un error explicado con opción de reintentar.
    const error = await texto('//div[@role="alert"]', 600000)
    comprobar(error.startsWith('La red de este equipo no deja descargar'), `error de red explicado: "${error.slice(0, 70)}…"`)
    await buscar(boton('Reintentar'))
    await captura('error-red')
    await cerrar()
    return
  }
  await pulsar('Comprobar la instalación', 600000)

  await buscar(titulo('Comprobación'))
  const narracion = await texto('//p[@class="cita"]', 120000)
  comprobar(narracion.includes('niebla'), `narración de prueba: ${narracion}`)
  comprobar(/palabras por segundo/.test(await texto(conTexto('palabras por segundo'))), 'velocidad medida')
  await captura('comprobacion')
  await pulsar('Continuar')

  await buscar(titulo('Todo preparado'))
  await captura('listo')
  await pulsar('Jugar')
  await buscar(titulo('Aquí se abrirá el juego'))

  const c = leerConfig()
  comprobar(c.asistenteCompletado === true, 'config.json: asistente completado')
  comprobar(c.consentimientoAceptado === true && c.permisoAnalisis === true, 'config.json: consentimiento y permiso guardados')
  comprobar(c.equipo && c.equipo.ramTotalMb > 0, `config.json: equipo detectado (${Math.round(c.equipo.ramTotalMb / 1024)} GB)`)
  comprobar(typeof c.perfil === 'string' && c.modelosDescargados.length > 0, `config.json: perfil ${c.perfil} y modelos ${c.modelosDescargados.join(', ')}`)

  await pulsar('Ajustes')
  await buscar(titulo('Rendimiento de la IA'))
  await captura('ajustes')
  await cerrar()

  console.log('Segundo arranque')
  await abrir()
  await buscar(titulo('Aquí se abrirá el juego'))
  comprobar(true, 'recuerda que el asistente ya se completó y no lo repite')
  await cerrar()
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
}
