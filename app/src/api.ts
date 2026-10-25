// Acceso a los comandos de Tauri (src-tauri/src/lib.rs). Fuera de Tauri (`npm run dev` en un
// navegador normal, y los tests) usa un equipo de ejemplo y descargas simuladas.

import { Channel, invoke } from '@tauri-apps/api/core'
import type { Comprobacion, Config, Equipo, Evaluacion, InfoMotor, ProgresoModelo, ProgresoMotor, Reparacion, Rutas, Sobrante, UsoIa } from './tipos'
import { open } from '@tauri-apps/plugin-dialog'
import { ejemplo } from './ejemplo'

export const enTauri = typeof window !== 'undefined' && '__TAURI_INTERNALS__' in window

export interface Api {
  rutas(): Promise<Rutas>
  cargarConfig(): Promise<Config>
  guardarConfig(config: Config): Promise<void>
  analizarEquipo(): Promise<Equipo>
  evaluarPerfiles(equipo: Equipo | null): Promise<Evaluacion>
  estadoMotor(): Promise<InfoMotor>
  instalarMotor(progreso: (p: ProgresoMotor) => void): Promise<void>
  iniciarMotor(): Promise<void>
  descargarModelos(progreso: (p: ProgresoModelo) => void): Promise<string[]>
  cancelarDescargas(): Promise<void>
  /** Comprueba el motor y los modelos del perfil y repone lo que falte o esté dañado. */
  reparar(motor: (p: ProgresoMotor) => void, modelos: (p: ProgresoModelo) => void): Promise<Reparacion>
  comprobar(id: string): Promise<Comprobacion>
  /** Diálogo de carpeta del sistema; null si se cancela. */
  elegirCarpeta(): Promise<string | null>
  /** Mueve la IA a `<destino>/Tarkor IA` y devuelve las rutas nuevas. */
  cambiarCarpetaIa(destino: string): Promise<Rutas>
  /** Dónde corre la IA ahora; falla si el motor no está en marcha. */
  usoIa(): Promise<UsoIa>
  /** Descarga lo que falte del perfil nuevo (se pausa con `cancelarDescargas`) y devuelve el `Config` ya guardado. */
  cambiarPerfil(perfil: string, progreso: (p: ProgresoModelo) => void): Promise<Config>
  /** Modelos del motor propio que no son del perfil actual; vacío con un Ollama externo. */
  modelosSobrantes(): Promise<Sobrante[]>
  borrarModelos(modelos: string[]): Promise<void>
}

function canal<T>(fn: (m: T) => void): Channel<T> {
  const c = new Channel<T>()
  c.onmessage = fn
  return c
}

const tauri: Api = {
  rutas: () => invoke('rutas'),
  cargarConfig: () => invoke('cargar_config'),
  guardarConfig: (config) => invoke('guardar_config', { config }),
  analizarEquipo: () => invoke('analizar_equipo'),
  evaluarPerfiles: (equipo) => invoke('evaluar_perfiles', { equipo }),
  estadoMotor: () => invoke('estado_motor'),
  instalarMotor: (progreso) => invoke('instalar_motor', { canal: canal(progreso) }),
  iniciarMotor: () => invoke('iniciar_motor'),
  descargarModelos: (progreso) => invoke('descargar_modelos', { canal: canal(progreso) }),
  cancelarDescargas: () => invoke('cancelar_descargas'),
  reparar: (motor, modelos) => invoke('reparar', { canalMotor: canal(motor), canal: canal(modelos) }),
  comprobar: (id) => invoke('comprobar', { id }),
  elegirCarpeta: async () => {
    const r = await open({ directory: true })
    return typeof r === 'string' ? r : null
  },
  cambiarCarpetaIa: (destino) => invoke('cambiar_carpeta_ia', { destino }),
  usoIa: () => invoke('uso_ia'),
  cambiarPerfil: (perfil, progreso) => invoke('cambiar_perfil', { perfil, canal: canal(progreso) }),
  modelosSobrantes: () => invoke('modelos_sobrantes'),
  borrarModelos: (modelos) => invoke('borrar_modelos', { modelos }),
}

export const api: Api = enTauri ? tauri : ejemplo
