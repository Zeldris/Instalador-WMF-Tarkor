// Catálogo incrustado (el mismo que compila Rust). Solo para textos que se muestran antes de
// analizar el equipo, como el rango de descarga; los perfiles evaluados llegan siempre de Rust.

import catalogoJson from '../catalogo/catalogo.json'
import type { Catalogo, Perfil } from './tipos'
import { fmt } from './formato'

export const catalogo = catalogoJson as Catalogo

export function descargaGb(p: Perfil): number {
  return [...new Set([p.narrador, p.cronista, p.sugerencias, p.embeddings])]
    .reduce((a, m) => a + (catalogo.modelos[m]?.descargaGb ?? 0), 0)
}

/** "1,3 y 9,4": de la descarga más pequeña a la mayor de los perfiles no experimentales. */
export function rangoDescarga(): string {
  const tamanos = catalogo.perfiles.filter((p) => !p.experimental).map(descargaGb)
  return `${fmt(Math.min(...tamanos))} y ${fmt(Math.max(...tamanos))}`
}
