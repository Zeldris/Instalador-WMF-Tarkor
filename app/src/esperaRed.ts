// Autopausa por falta de red (INS-42, docs/11 §5): la Descarga, «Cambiar y descargar» de Ajustes y «Reparar»
// esperan y vuelven a intentarlo solos, cada vez más espaciados. Aquí está lo común: la escalera de esperas, el
// contador de fallos, qué cuenta como progreso, el temporizador y la cuenta atrás.

import { useCallback, useEffect, useRef, useState } from 'react'
import * as tx from './textos'

/** Segundos de espera entre reintentos por falta de red (docs/11 §5): 5, 10, 20, 40 y luego 60 como tope. */
export const ESPERAS_RED_S: readonly number[] = [5, 10, 20, 40, 60]

/** La línea de la espera fuera de la Descarga: «Esperando conexión · Reintentando en 5 s.» */
export const textoEspera = (segundos: number) => `${tx.descarga.estados.esperando} · ${tx.descarga.reintentandoEn(segundos)}`

export interface EsperaRed {
  /** Segundos que faltan para el siguiente reintento, o null si no hay ninguno programado. */
  segundos: number | null
  /**
   * Avisa de lo hecho de una pieza (el motor o cada modelo) y dice si es progreso real. Solo el progreso real devuelve
   * la espera a 5 s: un reintento repite lo ya bajado (Ollama informa `completed` con los bytes que tenía) y un modelo
   * que ya estaba en disco llega completo de golpe; ninguno de los dos cuenta.
   */
  progreso: (pieza: string, hecho: number) => boolean
  /**
   * Tras un error de red: cuenta un fallo y programa `reintentar` tras la espera que toque. Quien reintenta debe
   * llamar a `cancelar` al empezar (limpia la cuenta atrás que quedó a la vista).
   */
  programar: (reintentar: () => void) => void
  /** Reintenta ya, sin esperar al temporizador. No hace nada si no hay reintento programado. */
  reintentarAhora: () => void
  /** Quita el reintento programado y su cuenta atrás. */
  cancelar: () => void
  /** Vuelve a contar desde la espera más corta (al reanudar a mano). */
  reiniciar: () => void
}

/** `esperas` solo lo cambian los tests de la Descarga; la última se repite. */
export function useEsperaRed(esperas: readonly number[] = ESPERAS_RED_S): EsperaRed {
  const [reintentoEn, setReintentoEn] = useState<number | null>(null)
  const [ahora, setAhora] = useState(() => Date.now())
  const temporizador = useRef<ReturnType<typeof setTimeout> | null>(null)
  const pendiente = useRef<(() => void) | null>(null)
  const fallos = useRef(0)
  const maxHecho = useRef(new Map<string, number>())
  const escalera = useRef(esperas)
  escalera.current = esperas

  const parar = useCallback(() => {
    if (temporizador.current !== null) clearTimeout(temporizador.current)
    temporizador.current = null
    pendiente.current = null
  }, [])
  const cancelar = useCallback(() => {
    parar()
    setReintentoEn(null)
  }, [parar])
  const progreso = useCallback((pieza: string, hecho: number) => {
    if (hecho <= (maxHecho.current.get(pieza) ?? 0)) return false
    maxHecho.current.set(pieza, hecho)
    fallos.current = 0
    return true
  }, [])
  const programar = useCallback((reintentar: () => void) => {
    parar()
    const segundos = escalera.current[Math.min(fallos.current, escalera.current.length - 1)]
    fallos.current++
    setReintentoEn(Date.now() + segundos * 1000)
    setAhora(Date.now())
    pendiente.current = reintentar
    temporizador.current = setTimeout(() => { temporizador.current = null; pendiente.current = null; reintentar() }, segundos * 1000)
  }, [parar])
  const reintentarAhora = useCallback(() => {
    const reintentar = pendiente.current
    cancelar()
    reintentar?.()
  }, [cancelar])
  const reiniciar = useCallback(() => { fallos.current = 0 }, [])

  // Cuenta atrás: un tic por segundo mientras haya un reintento programado.
  useEffect(() => {
    if (reintentoEn === null) return
    const id = setInterval(() => setAhora(Date.now()), 1000)
    return () => clearInterval(id)
  }, [reintentoEn])
  // Al desmontar no queda ningún reintento vivo.
  useEffect(() => parar, [parar])

  const segundos = reintentoEn === null ? null : Math.max(0, Math.ceil((reintentoEn - ahora) / 1000))
  return { segundos, progreso, programar, reintentarAhora, cancelar, reiniciar }
}
