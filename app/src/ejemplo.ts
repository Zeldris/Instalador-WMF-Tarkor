// Datos de ejemplo para abrir el asistente en un navegador normal y para los tests. Equipo tipo
// Steam Deck. Usa el mismo catálogo que la app (catalogo/catalogo.json) y reproduce el cálculo de
// nucleo/src/perfiles.rs solo para este modo sin Tauri; la fuente de verdad es la de Rust, cubierta
// por sus tests (p. ej. `deck_16gb_maximo_justo_recomienda_equilibrado`).

import type { Api } from './api'
import catalogoJson from '../catalogo/catalogo.json'
import type { Catalogo, Config, Equipo, Evaluacion, PerfilEvaluado } from './tipos'

const catalogo = catalogoJson as Catalogo

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
    const descargaGb = [...new Set([p.narrador, p.cronista, p.sugerencias, p.embeddings])]
      .reduce((a, m) => a + (catalogo.modelos[m]?.descargaGb ?? 0), 0)
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

export const ejemplo: Api = {
  rutas: async () => ({ datos: '~/.local/share/tarkor', ia: '~/.local/share/tarkor/ia', registros: '~/.local/state/tarkor/registros' }),
  cargarConfig: async () => structuredClone(guardada),
  guardarConfig: async (c) => { guardada = structuredClone(c) },
  analizarEquipo: async () => equipoEjemplo,
  evaluarPerfiles: async (equipo) => evaluarEjemplo(equipo),
}
