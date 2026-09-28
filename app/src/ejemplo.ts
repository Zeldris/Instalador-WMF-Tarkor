// Datos de ejemplo para abrir el asistente en un navegador normal y para los tests. Equipo tipo
// Steam Deck. Usa el mismo catálogo que la app (catalogo/catalogo.json) y reproduce el cálculo de
// nucleo/src/perfiles.rs solo para este modo sin Tauri; la fuente de verdad es la de Rust, cubierta
// por sus tests (p. ej. `deck_16gb_maximo_justo_recomienda_equilibrado`).

import type { Api } from './api'
import { catalogo, descargaGb as descargaDe } from './catalogo'
import type { Config, Equipo, Evaluacion, PerfilEvaluado } from './tipos'

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

export function evaluarEjemplo(equipo: Equipo | null): Evaluacion {
  const r = catalogo.reglas
  const ram = equipo ? equipo.ramTotalMb / 1024 : 0
  const paraIa = equipo ? Math.max(0, ram - Math.max(r.reservaMinimaGb, ram * r.reservaProporcion) - r.memoriaJuegoGb) : null
  const disco = equipo ? equipo.discoLibreMb / 1024 : null
  const perfiles: PerfilEvaluado[] = catalogo.perfiles.map((p) => {
    const descargaGb = descargaDe(p)
    return {
      ...p,
      descargaGb,
      cabeEnMemoria: paraIa === null || p.memoriaGb <= paraIa,
      cabeEnDisco: disco === null || descargaGb * r.margenDisco <= disco,
    }
  })
  const masLigero = perfiles.find((p) => !p.experimental)!.id
  if (paraIa === null) return { memoriaParaIaGb: null, perfiles, maximoSeguro: null, recomendado: masLigero, equipoInsuficiente: false }
  const caben = perfiles.filter((p) => p.cabeEnMemoria && p.cabeEnDisco && !p.experimental)
  const ultimo = caben.at(-1)
  let recomendado = ultimo?.id ?? masLigero
  if (ultimo && caben.length > 1 && paraIa - ultimo.memoriaGb < r.margenComodoGb) recomendado = caben.at(-2)!.id
  return { memoriaParaIaGb: paraIa, perfiles, maximoSeguro: ultimo?.id ?? null, recomendado, equipoInsuficiente: !ultimo }
}

let guardada = configInicial()
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
  rutas: async () => ({ datos: '~/.local/share/tarkor', ia: '~/.local/share/tarkor/ia', registros: '~/.local/state/tarkor/registros' }),
  cargarConfig: async () => structuredClone(guardada),
  guardarConfig: async (c) => { guardada = structuredClone(c) },
  analizarEquipo: async () => equipoEjemplo,
  evaluarPerfiles: async (equipo) => evaluarEjemplo(equipo),
  estadoMotor: async () => ({
    version: catalogo.motor.version,
    instalado: false,
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
  },
  iniciarMotor: async () => {},
  descargarModelos: async (progreso) => {
    cancelado = false
    const perfil = catalogo.perfiles.find((p) => p.id === guardada.perfil) ?? catalogo.perfiles[0]
    const modelos = [...new Set([perfil.narrador, perfil.cronista, perfil.sugerencias, perfil.embeddings])]
    for (const modelo of modelos) {
      const total = (catalogo.modelos[modelo]?.descargaGb ?? 1) * 1024 ** 3
      await simular(total, 8, (hecho) => progreso({ modelo, estado: 'pulling', hecho, total }))
      progreso({ modelo, estado: 'success', hecho: total, total })
    }
    return modelos
  },
  cancelarDescargas: async () => { cancelado = true },
  comprobar: async (id) => {
    await pausa(150)
    if (['basedatos', 'juego', 'mundo'].includes(id)) return { resultado: 'omitida', motivo: 'Llega con el juego empaquetado (fase 4).' }
    if (id === 'narracion') {
      return { resultado: 'ok', detalle: JSON.stringify({ texto: 'La niebla del estrecho se abre un instante y deja ver, al otro lado, las hogueras de Berig.', tokensPorSegundo: 12 }) }
    }
    return { resultado: 'ok', detalle: 'Correcto (ejemplo).' }
  },
}
