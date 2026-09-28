// Espejo de los tipos serializados por `nucleo/` (serde, camelCase). Si cambia un struct de Rust,
// cambia aquí también.

export type PerfilId = 'ligero' | 'equilibrado' | 'maximo'
export type UsoCpu = 'moderado' | 'alto'

export interface Gpu {
  nombre: string
  fabricante: 'nvidia' | 'amd' | 'intel' | 'otro'
  vramMb: number | null
  integrada: boolean
}

export interface Equipo {
  ramTotalMb: number
  ramLibreMb: number
  cpuModelo: string
  nucleos: number
  hilos: number
  gpus: Gpu[]
  discoLibreMb: number
  sistema: string
}

export interface Perfil {
  id: PerfilId
  nombre: string
  memoriaGb: number
  descargaGb: number
  velocidad: number
  calidad: number
  narrador: string
  cronista: string
  sugerencias: string
  embeddings: string
  maxModelosCargados: number
  keepAlive: string
}

export interface PerfilEvaluado extends Perfil {
  cabeEnMemoria: boolean
  cabeEnDisco: boolean
}

export interface Evaluacion {
  memoriaParaIaGb: number | null
  perfiles: PerfilEvaluado[]
  maximoSeguro: PerfilId | null
  recomendado: PerfilId
  equipoInsuficiente: boolean
}

export interface Config {
  version: number
  consentimientoAceptado: boolean
  permisoAnalisis: boolean | null
  equipo: Equipo | null
  perfil: PerfilId | null
  usoCpu: UsoCpu
  modelosDescargados: string[]
  pasoAsistente: number
  asistenteCompletado: boolean
}

export interface Rutas {
  datos: string
  ia: string
  registros: string
}

export const cabe = (p: PerfilEvaluado) => p.cabeEnMemoria && p.cabeEnDisco
