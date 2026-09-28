// Datos de ejemplo para abrir el asistente en un navegador normal y para los tests. Equipo tipo
// Steam Deck; la evaluación es la que devuelve `nucleo` para ese equipo (ver el test
// `deck_16gb_maximo_justo_recomienda_equilibrado` en nucleo/src/perfiles.rs).

import type { Api } from './api'
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

const base = { cronista: 'qwen2.5:1.5b-instruct', embeddings: 'nomic-embed-text' }
const perfiles = (cabeMaximo: boolean): PerfilEvaluado[] => [
  { ...base, id: 'ligero', nombre: 'Ligero', memoriaGb: 3.5, descargaGb: 3.3, velocidad: 3, calidad: 1, narrador: 'qwen2.5:3b', sugerencias: base.cronista, maxModelosCargados: 1, keepAlive: '2m', cabeEnMemoria: true, cabeEnDisco: true },
  { ...base, id: 'equilibrado', nombre: 'Equilibrado', memoriaGb: 7, descargaGb: 6, velocidad: 2, calidad: 2, narrador: 'qwen2.5:7b', sugerencias: base.cronista, maxModelosCargados: 2, keepAlive: '5m', cabeEnMemoria: true, cabeEnDisco: true },
  { ...base, id: 'maximo', nombre: 'Máximo', memoriaGb: 10.5, descargaGb: 9, velocidad: 2, calidad: 3, narrador: 'qwen2.5:7b', sugerencias: 'qwen3.5:4b', maxModelosCargados: 4, keepAlive: '5m', cabeEnMemoria: cabeMaximo, cabeEnDisco: true },
]

export const evaluacionEjemplo: Evaluacion = {
  memoriaParaIaGb: 11,
  perfiles: perfiles(true),
  maximoSeguro: 'maximo',
  recomendado: 'equilibrado',
  equipoInsuficiente: false,
}

export const evaluacionManual: Evaluacion = {
  memoriaParaIaGb: null,
  perfiles: perfiles(true),
  maximoSeguro: null,
  recomendado: 'ligero',
  equipoInsuficiente: false,
}

let guardada = configInicial()

export const ejemplo: Api = {
  rutas: async () => ({ datos: '~/.local/share/tarkor', ia: '~/.local/share/tarkor/ia', registros: '~/.local/state/tarkor/registros' }),
  cargarConfig: async () => structuredClone(guardada),
  guardarConfig: async (c) => { guardada = structuredClone(c) },
  analizarEquipo: async () => equipoEjemplo,
  evaluarPerfiles: async (equipo) => (equipo ? evaluacionEjemplo : evaluacionManual),
}
