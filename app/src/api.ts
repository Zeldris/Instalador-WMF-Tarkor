// Acceso a los comandos de Tauri (src-tauri/src/lib.rs). Fuera de Tauri (`npm run dev` en un
// navegador normal, y los tests) usa un equipo de ejemplo y descargas simuladas.

import { Channel, invoke } from '@tauri-apps/api/core'
import type { Comprobacion, Config, Equipo, Evaluacion, InfoMotor, ProgresoModelo, ProgresoMotor, Rutas } from './tipos'
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
  comprobar(id: string): Promise<Comprobacion>
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
  comprobar: (id) => invoke('comprobar', { id }),
}

export const api: Api = enTauri ? tauri : ejemplo
