// PROVISIONAL (fase 0): descarga y comprobación simuladas para poder recorrer el asistente entero.
// Se sustituyen por comandos reales de Tauri en la fase 0.5 (Ollama + /api/pull) y 4.2
// (comprobaciones de docs/07). Nada de este fichero debe llegar a una release.

import { useEffect, useState } from 'react'

/** Tamaños aproximados de docs/03; en la fase 0.5 vendrán del progreso real de `ollama pull`. */
const TAMANO_GB: Record<string, number> = {
  'qwen2.5:7b': 4.7,
  'qwen2.5:3b': 1.9,
  'qwen2.5:1.5b-instruct': 1,
  'qwen3.5:4b': 3,
  'nomic-embed-text': 0.3,
}

export interface Elemento {
  id: string
  gb: number
  hecho: number
}

export function elementosDescarga(modelos: string[], conGpuDedicada: boolean): Elemento[] {
  return [
    { id: 'motor', gb: conGpuDedicada ? 1.4 : 0.05, hecho: 0 },
    ...modelos.map((m) => ({ id: m, gb: TAMANO_GB[m] ?? 1, hecho: 0 })),
  ]
}

export function useDescargaSimulada(inicial: Elemento[], pausada: boolean) {
  const [elementos, setElementos] = useState(inicial)
  useEffect(() => {
    if (pausada) return
    const id = setInterval(() => {
      setElementos((prev) => {
        const i = prev.findIndex((e) => e.hecho < e.gb)
        if (i < 0) return prev
        return prev.map((e, j) => (j === i ? { ...e, hecho: Math.min(e.gb, e.hecho + Math.max(0.08, e.gb / 12)) } : e))
      })
    }, 180)
    return () => clearInterval(id)
  }, [pausada])
  return elementos
}

export type EstadoComprobacion = 'pendiente' | 'curso' | 'ok' | 'fallo'

export function useComprobacionSimulada(total: number) {
  const [estados, setEstados] = useState<EstadoComprobacion[]>(() => Array(total).fill('pendiente'))
  useEffect(() => {
    let temporizador: ReturnType<typeof setTimeout> | undefined
    const marcar = (k: number, estado: EstadoComprobacion) => setEstados((e) => e.map((s, j) => (j === k ? estado : s)))
    const siguiente = (k: number) => {
      if (k >= total) return
      marcar(k, 'curso')
      temporizador = setTimeout(() => { marcar(k, 'ok'); siguiente(k + 1) }, k === total - 1 ? 1200 : 400)
    }
    setEstados(Array(total).fill('pendiente'))
    siguiente(0)
    return () => clearTimeout(temporizador)
  }, [total])
  return estados
}
