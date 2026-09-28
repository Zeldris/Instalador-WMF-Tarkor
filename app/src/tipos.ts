// Espejo de los tipos serializados por `nucleo/` (serde, camelCase). Si cambia un struct de Rust,
// cambia aquí también.

/** Id de un perfil del catálogo (catalogo/catalogo.json). */
export type PerfilId = string
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
  /** Qué resultado esperar, en palabras de jugador. */
  resultado: string
  /** 1-4 */
  calidad: number
  /** 1-4 */
  velocidad: number
  memoriaGb: number
  narrador: string
  cronista: string
  sugerencias: string
  embeddings: string
  maxModelosCargados: number
  keepAlive: string
  experimental?: boolean
}

export interface PerfilEvaluado extends Perfil {
  descargaGb: number
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

export interface Catalogo {
  reglas: { reservaMinimaGb: number; reservaProporcion: number; memoriaJuegoGb: number; proporcionVramUtil: number; margenComodoGb: number; margenDisco: number }
  modelos: Record<string, { descargaGb: number; licencia: string; piensa?: boolean }>
  perfiles: Perfil[]
}

export const cabe = (p: PerfilEvaluado) => p.cabeEnMemoria && p.cabeEnDisco
