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
  /** Carpeta de la IA elegida (`<elegida>/Tarkor IA`, la guarda el núcleo); null = la de por defecto. */
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

/** Resultado de «Reparar» (`INS-49`). */
export interface Reparacion {
  motorReinstalado: boolean
  /** Capas de modelos dañadas o que faltaban, vueltas a descargar. */
  capasRepuestas: number
  modelos: string[]
}

/** Dónde corre la IA ahora (`uso_ia`, `/api/ps`): `porcentajeGpu` es `null` si no hay nada cargado. */
export interface UsoIa {
  porcentajeGpu: number | null
  memoriaMb: number
}

/** Un modelo del Ollama propio que no es del perfil actual (`modelos_sobrantes`). */
export interface Sobrante {
  modelo: string
  gb: number
}

/** Aviso de motor detenido: evento `motor-detenido` y comando `motor_detenido`. */
export interface MotorDetenido {
  motivo: string
  /** El registro del motor habla de falta de memoria: se ofrece un perfil más ligero. */
  sinMemoria: boolean
}

export type Comprobacion = { resultado: 'ok'; detalle: string } | { resultado: 'omitida'; motivo: string }

/** Una tarjeta pide confirmar si el perfil no cabe en memoria (solo con análisis). */
export const pideConfirmar = (e: Evaluacion, p: PerfilEvaluado) => e.memoriaParaIaGb !== null && !p.cabeEnMemoria
/** Hay que impedir la descarga: no cabe en disco o falta la confirmación. */
export const bloqueado = (e: Evaluacion, p: PerfilEvaluado, confirmado: boolean) => !p.cabeEnDisco || (pideConfirmar(e, p) && !confirmado)

/**
 * El perfil de la evaluación con ese id; si no está (un perfil guardado que ya no existe, o `null`) cuenta como el
 * recomendado, y si tampoco, el primero. Sin `!`: una evaluación sin perfiles es un fallo del núcleo y lo dice.
 */
export function perfilDe(evaluacion: Evaluacion, id: PerfilId | null | undefined): PerfilEvaluado {
  const perfil = evaluacion.perfiles.find((p) => p.id === id)
    ?? evaluacion.perfiles.find((p) => p.id === evaluacion.recomendado)
    ?? evaluacion.perfiles[0]
  if (!perfil) throw new Error('La evaluación no trae ningún perfil')
  return perfil
}

/** El perfil de menos memoria justo por debajo del actual (por `memoriaGb`, sin experimentales ni los que no caben en disco); null si ya es el más ligero. */
export function perfilMasLigero(perfiles: { id: PerfilId; memoriaGb: number; experimental?: boolean; cabeEnDisco?: boolean }[], actual: PerfilId | null): PerfilId | null {
  const ref = perfiles.find((p) => p.id === actual)
  if (!ref) return null
  const menores = perfiles.filter((p) => !p.experimental && p.cabeEnDisco !== false && p.memoriaGb < ref.memoriaGb).sort((a, b) => b.memoriaGb - a.memoriaGb)
  return menores[0]?.id ?? null
}
