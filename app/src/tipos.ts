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
  /** Descarga × margen de disco: lo que hay que tener libre en la carpeta de la IA. */
  necesitaDiscoGb: number
}

export interface Evaluacion {
  memoriaParaIaGb: number | null
  /** Espacio libre en la carpeta de la IA; null si no se pudo medir. */
  discoLibreGb: number | null
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
  /** Carpeta elegida por la usuaria para la IA (el destino, sin «Tarkor IA»); null = la de por defecto. */
  carpetaIa: string | null
}

export interface Rutas {
  datos: string
  ia: string
  registros: string
}

export interface Catalogo {
  motor: { version: string; paquetes: Record<string, { archivo: string; descargaGb: number }> }
  reglas: { reservaMinimaGb: number; reservaProporcion: number; memoriaJuegoGb: number; proporcionVramUtil: number; margenComodoGb: number; margenDisco: number }
  modelos: Record<string, { descargaGb: number; licencia: string; piensa?: boolean }>
  perfiles: Perfil[]
}

export interface InfoMotor {
  version: string
  instalado: boolean
  enMarcha: boolean
  descargaGb: number
  modelosGb: Record<string, number>
}

export type ProgresoMotor =
  | { fase: 'descargando'; hecho: number; total: number }
  | { fase: 'verificando' }
  | { fase: 'extrayendo' }
  | { fase: 'listo' }

export interface ProgresoModelo {
  modelo: string
  estado: string
  hecho: number
  total: number
}

export type Comprobacion = { resultado: 'ok'; detalle: string } | { resultado: 'omitida'; motivo: string }

export const cabe =(p: PerfilEvaluado) => p.cabeEnMemoria && p.cabeEnDisco

/** Una tarjeta pide confirmar si el perfil no cabe en memoria (solo con análisis). */
export const pideConfirmar = (e: Evaluacion, p: PerfilEvaluado) => e.memoriaParaIaGb !== null && !p.cabeEnMemoria
/** Hay que impedir la descarga: no cabe en disco o falta la confirmación. */
export const bloqueado = (e: Evaluacion, p: PerfilEvaluado, confirmado: boolean) => !p.cabeEnDisco || (pideConfirmar(e, p) && !confirmado)
