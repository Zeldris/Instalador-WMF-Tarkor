// Acceso a los comandos de Tauri (src-tauri/src/lib.rs). Fuera de Tauri (`npm run dev` en un
// navegador normal) usa un equipo de ejemplo para poder trabajar el diseño sin compilar Rust.

import { invoke } from '@tauri-apps/api/core'
import type { Config, Equipo, Evaluacion, Rutas } from './tipos'
import { ejemplo } from './ejemplo'

export const enTauri = typeof window !== 'undefined' && '__TAURI_INTERNALS__' in window

export interface Api {
  rutas(): Promise<Rutas>
  cargarConfig(): Promise<Config>
  guardarConfig(config: Config): Promise<void>
  analizarEquipo(): Promise<Equipo>
  evaluarPerfiles(equipo: Equipo | null): Promise<Evaluacion>
}

const tauri: Api = {
  rutas: () => invoke('rutas'),
  cargarConfig: () => invoke('cargar_config'),
  guardarConfig: (config) => invoke('guardar_config', { config }),
  analizarEquipo: () => invoke('analizar_equipo'),
  evaluarPerfiles: (equipo) => invoke('evaluar_perfiles', { equipo }),
}

export const api: Api = enTauri ? tauri : ejemplo
