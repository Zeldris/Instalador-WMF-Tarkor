// Datos de ejemplo para abrir el asistente en un navegador normal y para los tests. Equipo tipo
// Steam Deck. Usa el mismo catálogo que la app (catalogo/catalogo.json) y reproduce el cálculo de
// nucleo/src/perfiles.rs solo para este modo sin Tauri; la fuente de verdad es la de Rust, cubierta
// por sus tests (p. ej. `deck_16gb_maximo_justo_recomienda_equilibrado`).

import type { Api } from './api'
import { catalogo, descargaGb as descargaDe } from './catalogo'
import { ErrorIa } from './tipos'
import type { Config, Equipo, Evaluacion, MotorDetenido, PerfilEvaluado, ProgresoModelo, Sobrante, UsoIa } from './tipos'

export const configInicial = (): Config => ({
  version: 1,
  consentimientoAceptado: false,
  permisoAnalisis: null,
  equipo: null,
  perfil: null,
  usoCpu: 'moderado',
  modelosDescargados: [],
  pasoAsistente: 1,
  asistenteCompletado: false,
  carpetaIa: null,
})

export const equipoEjemplo: Equipo = {
  ramTotalMb: 16384,
  ramLibreMb: 12800,
  cpuModelo: 'AMD Custom APU 0405',
  nucleos: 4,
  hilos: 8,
  gpus: [{ nombre: 'AMD 163f', fabricante: 'amd', vramMb: null, integrada: true }],
  discoLibreMb: 184320,
  sistema: 'Linux (SteamOS 3.7)',
}

const rutasPorDefecto = () => ({ datos: '~/.local/share/tarkor', ia: '~/.local/share/tarkor/ia', registros: '~/.local/state/tarkor/registros' })
/** Disco libre de la carpeta de IA simulada: el del equipo de ejemplo, y mucho en la carpeta que se «elige». */
const DISCO_CARPETA_ELEGIDA_GB = 500
let discoLibreIaGb = equipoEjemplo.discoLibreMb / 1024
let rutasEjemplo = rutasPorDefecto()
/** Para los tests: fija el disco libre de la carpeta de IA actual. */
export const fijarDiscoLibreIa = (gb: number) => { discoLibreIaGb = gb }
/** Para los tests: vuelve a la carpeta y el disco por defecto. */
export const reiniciarCarpetaIa = () => { discoLibreIaGb = equipoEjemplo.discoLibreMb / 1024; rutasEjemplo = rutasPorDefecto(); errorCarpetaIa = null }
let errorCarpetaIa: string | null = null
/** Para los tests: el siguiente cambio de carpeta falla con este mensaje, como lo daría el núcleo. */
export const fijarErrorCarpetaIa = (mensaje: string) => { errorCarpetaIa = mensaje }
/** Simula una capa dañada: la comprobación «Modelos» falla hasta que se repara. */
let modelosDanados = false
export const fijarModelosDanados = (danados: boolean) => { modelosDanados = danados }

export function evaluarEjemplo(equipo: Equipo | null): Evaluacion {
  const r = catalogo.reglas
  const ram = equipo ? equipo.ramTotalMb / 1024 : 0
  const paraIa = equipo ? Math.max(0, ram - Math.max(r.reservaMinimaGb, ram * r.reservaProporcion) - r.memoriaJuegoGb) : null
  const disco = discoLibreIaGb
  const perfiles: PerfilEvaluado[] = catalogo.perfiles.map((p) => {
    const descargaGb = descargaDe(p)
    const necesitaDiscoGb = descargaGb * r.margenDisco
    return {
      ...p,
      descargaGb,
      cabeEnMemoria: paraIa === null || p.memoriaGb <= paraIa,
      cabeEnDisco: necesitaDiscoGb <= disco,
      necesitaDiscoGb,
    }
  })
  const masLigero = (perfiles.find((p) => !p.experimental) ?? perfiles[0]).id
  if (paraIa === null) return { memoriaParaIaGb: null, discoLibreGb: disco, perfiles, maximoSeguro: null, recomendado: masLigero, equipoInsuficiente: false }
  const caben = perfiles.filter((p) => p.cabeEnMemoria && p.cabeEnDisco && !p.experimental)
  const ultimo = caben.at(-1)
  let recomendado = ultimo?.id ?? masLigero
  if (ultimo && caben.length > 1 && paraIa - ultimo.memoriaGb < r.margenComodoGb) recomendado = caben.at(-2)!.id
  return { memoriaParaIaGb: paraIa, discoLibreGb: disco, perfiles, maximoSeguro: ultimo?.id ?? null, recomendado, equipoInsuficiente: !ultimo }
}

let guardada = configInicial()
let sobrantes: Sobrante[] = []
let usoSimulado: UsoIa | Error = { porcentajeGpu: 100, memoriaMb: 5400 }
/** Para los tests: lo que dirá `usoIa` (un `Error` hace que falle, como con el motor parado). */
export const fijarUsoIa = (uso: UsoIa | Error) => { usoSimulado = uso }
/** Para los tests: vuelve al estado de ejemplo de los modelos sobrantes y del uso. */
let errorCambioPerfil: string | null = null
/** Para los tests: el siguiente cambio de perfil falla con este mensaje, sin tocar el perfil guardado. */
export const fijarErrorCambioPerfil = (mensaje: string) => { errorCambioPerfil = mensaje }
let retardoCambioPerfil = 0
/** Para los tests: el cambio de perfil tarda esto (ms) antes de acabar o de fallar. */
export const fijarRetardoCambioPerfil = (ms: number) => { retardoCambioPerfil = ms }
let sinRedRestantes = 0
let sinRedCortes = 0
let sinRedAntes: ProgresoModelo[] | ((corte: number) => ProgresoModelo[]) | null = null
/** El motor simulado se «instala» una vez, como el real: un reintento de la Descarga ya no lo repite. */
let motorInstalado = false
/** Para los tests: las `n` siguientes llamadas a `descargarModelos` fallan por falta de red (un `ErrorIa` con `red`), como el núcleo. */
export const fijarSinRed = (n: number, antes: typeof sinRedAntes = null) => { sinRedRestantes = n; sinRedCortes = 0; sinRedAntes = antes }
export const reiniciarModelos = () => { sinRedRestantes = 0; sinRedCortes = 0; sinRedAntes = null; motorInstalado = false; errorCambioPerfil = null; retardoCambioPerfil = 0; sobrantes = []; usoSimulado = { porcentajeGpu: 100, memoriaMb: 5400 } }
const modelosDe = (id: string | null) => {
  const perfil = catalogo.perfiles.find((p) => p.id === id) ?? catalogo.perfiles[0]
  return [...new Set([perfil.narrador, perfil.cronista, perfil.sugerencias, perfil.embeddings])]
}
let avisoMotor: MotorDetenido | null = null
let errorReintento: string | null = null
let errorCopiar: string | null = null
let copiado: string | null = null
const oyentes = new Set<(a: MotorDetenido) => void>()
/** Para los tests: el aviso que devolverá `motorDetenido` (null = ninguno). */
export const fijarMotorDetenido = (aviso: MotorDetenido | null) => { avisoMotor = aviso }
/** Para los tests: como el evento `motor-detenido` de Rust: guarda el aviso y avisa a quien escuche. */
export const emitirMotorDetenido = (aviso: MotorDetenido) => { avisoMotor = aviso; oyentes.forEach((f) => f(aviso)) }
/** Para los tests: el siguiente `reintentarMotor` falla con este mensaje. */
export const fijarErrorReintento = (mensaje: string | null) => { errorReintento = mensaje }
/** Para los tests: `copiar` falla con este mensaje (null = funciona). */
export const fijarErrorCopiar = (mensaje: string | null) => { errorCopiar = mensaje }
/** Para los tests: lo último que se copió al portapapeles simulado. */
export const textoCopiado = () => copiado
/** Para los tests: cuántos oyentes de `motor-detenido` siguen activos. */
export const oyentesMotor = () => oyentes.size
export const TEXTO_INFORME = 'Tarkor (informe de ejemplo)\nSistema: Linux\nMotor: en marcha'
export const reiniciarMotorDetenido = () => { avisoMotor = null; errorReintento = null; errorCopiar = null; copiado = null; oyentes.clear() }
let cancelado = false
const pausa = (ms: number) => new Promise((ok) => setTimeout(ok, ms))

/** Descarga simulada en `pasos` avisos; se detiene si se cancela. */
async function simular(total: number, pasos: number, aviso: (hecho: number) => void) {
  for (let i = 1; i <= pasos; i++) {
    if (cancelado) throw new Error('Descarga cancelada. Lo descargado se conserva para continuar.')
    await pausa(60)
    aviso(Math.round((total * i) / pasos))
  }
}

export const ejemplo: Api = {
  rutas: async () => ({ ...rutasEjemplo }),
  cargarConfig: async () => structuredClone(guardada),
  guardarConfig: async (c) => { guardada = structuredClone(c) },
  analizarEquipo: async () => equipoEjemplo,
  evaluarPerfiles: async (equipo) => evaluarEjemplo(equipo),
  estadoMotor: async () => ({
    version: catalogo.motor.version,
    instalado: motorInstalado,
    enMarcha: false,
    descargaGb: catalogo.motor.paquetes.linux.descargaGb,
    modelosGb: Object.fromEntries(Object.entries(catalogo.modelos).map(([k, v]) => [k, v.descargaGb])),
  }),
  instalarMotor: async (progreso) => {
    cancelado = false
    const total = catalogo.motor.paquetes.linux.descargaGb * 1024 ** 3
    await simular(total, 10, (hecho) => progreso({ fase: 'descargando', hecho, total }))
    progreso({ fase: 'verificando' })
    progreso({ fase: 'extrayendo' })
    progreso({ fase: 'listo' })
    motorInstalado = true
  },
  iniciarMotor: async () => {},
  descargarModelos: async (progreso) => {
    cancelado = false
    const perfil = catalogo.perfiles.find((p) => p.id === guardada.perfil) ?? catalogo.perfiles[0]
    const modelos = [...new Set([perfil.narrador, perfil.cronista, perfil.sugerencias, perfil.embeddings])]
    if (sinRedRestantes > 0) {
      sinRedRestantes--
      // Como Ollama: empieza por el manifiesto (sin bytes) y ahí se corta. Con `antes`, informa de eso en cada corte
      // (`corte` cuenta desde 0): un modelo que ya estaba en disco, o los bytes que ya tenía al reanudar.
      progreso({ modelo: modelos[0], estado: 'pulling manifest', hecho: 0, total: 0 })
      const extra = typeof sinRedAntes === 'function' ? sinRedAntes(sinRedCortes) : (sinRedAntes ?? [])
      sinRedCortes++
      extra.forEach(progreso)
      await pausa(30)
      throw new ErrorIa('No se pudo conectar con el servidor de modelos. Comprueba tu conexión a internet y vuelve a intentarlo; lo ya descargado se conserva.', true)
    }
    for (const modelo of modelos) {
      const total = (catalogo.modelos[modelo]?.descargaGb ?? 1) * 1024 ** 3
      await simular(total, 8, (hecho) => progreso({ modelo, estado: 'pulling', hecho, total }))
      progreso({ modelo, estado: 'success', hecho: total, total })
    }
    return modelos
  },
  cancelarDescargas: async () => { cancelado = true },
  reparar: async (motor, progreso) => {
    cancelado = false
    motor({ fase: 'verificando' })
    await pausa(60)
    if (cancelado) throw new Error('Reparación cancelada. Lo ya comprobado sigue en su sitio.')
    motor({ fase: 'listo' })
    const perfil = catalogo.perfiles.find((p) => p.id === guardada.perfil) ?? catalogo.perfiles[0]
    const modelos = [...new Set([perfil.narrador, perfil.cronista, perfil.sugerencias, perfil.embeddings])]
    modelos.forEach((_, i) => progreso({ modelo: '', estado: 'verificando', hecho: i, total: modelos.length }))
    const capasRepuestas = modelosDanados ? 1 : 0
    if (modelosDanados) {
      const total = 1024 ** 3
      await simular(total, 4, (hecho) => progreso({ modelo: modelos[0], estado: 'pulling', hecho, total }))
      modelosDanados = false
    }
    return { motorReinstalado: false, capasRepuestas, modelos }
  },
  elegirCarpeta: async () => '/mnt/tarjeta-sd',
  cambiarCarpetaIa: async (destino) => {
    await pausa(60)
    if (errorCarpetaIa) throw errorCarpetaIa
    discoLibreIaGb = DISCO_CARPETA_ELEGIDA_GB
    rutasEjemplo = { ...rutasEjemplo, ia: `${destino}/Tarkor IA` }
    return { ...rutasEjemplo }
  },
  usoIa: async () => {
    if (usoSimulado instanceof Error) throw usoSimulado.message
    return { ...usoSimulado }
  },
  cambiarPerfil: async (perfil, progreso) => {
    cancelado = false
    if (retardoCambioPerfil) await pausa(retardoCambioPerfil)
    if (errorCambioPerfil) throw errorCambioPerfil
    const antes = modelosDe(guardada.perfil)
    const nuevos = modelosDe(perfil)
    const faltan = nuevos.filter((m) => !guardada.modelosDescargados.includes(m))
    for (const modelo of faltan) {
      const total = (catalogo.modelos[modelo]?.descargaGb ?? 1) * 1024 ** 3
      await simular(total, 8, (hecho) => progreso({ modelo, estado: 'pulling', hecho, total }))
      progreso({ modelo, estado: 'success', hecho: total, total })
    }
    guardada = { ...guardada, perfil, modelosDescargados: nuevos }
    sobrantes = antes.filter((m) => !nuevos.includes(m)).map((modelo) => ({ modelo, gb: catalogo.modelos[modelo]?.descargaGb ?? 1 }))
    return structuredClone(guardada)
  },
  modelosSobrantes: async () => sobrantes.map((s) => ({ ...s })),
  borrarModelos: async (modelos) => { sobrantes = sobrantes.filter((s) => !modelos.includes(s.modelo)) },
  informe: async () => TEXTO_INFORME,
  motorDetenido: async () => (avisoMotor ? { ...avisoMotor } : null),
  reintentarMotor: async () => {
    await pausa(30)
    if (errorReintento) throw errorReintento
    avisoMotor = null
  },
  alMotorDetenido: async (cb) => {
    oyentes.add(cb)
    return () => { oyentes.delete(cb) }
  },
  copiar: async (texto) => {
    if (errorCopiar) throw errorCopiar
    copiado = texto
  },
  comprobar: async (id) => {
    await pausa(150)
    if (['basedatos', 'juego', 'mundo'].includes(id)) return { resultado: 'omitida', motivo: 'Llega con el juego empaquetado (fase 4).' }
    if (id === 'modelos' && modelosDanados) throw 'Faltan modelos: qwen2.5:7b. Vuelve al paso de descarga.'
    if (id === 'narracion') {
      return { resultado: 'ok', detalle: JSON.stringify({ texto: 'La niebla del estrecho se abre un instante y deja ver, al otro lado, las hogueras de Berig.', tokensPorSegundo: 12 }) }
    }
    return { resultado: 'ok', detalle: 'Correcto (ejemplo).' }
  },
}
