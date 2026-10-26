// Pantallas 5 (Descarga) y 6 (Comprobación): trabajan con el motor de IA de verdad
// (docs/07 y docs/11). En el navegador y en los tests, `api` las simula.

import { useCallback, useEffect, useRef, useState } from 'react'
import { api, ErrorIa } from './api'
import { Marco, Reparar } from './componentes'
import * as tx from './textos'
import type { Config, Evaluacion, ProgresoMotor } from './tipos'
import { perfilDe } from './tipos'
import { fmt } from './formato'

type EstadoFila = 'cola' | 'bajando' | 'verificando' | 'extrayendo' | 'listo'
interface Fila {
  id: string
  nombre: string
  gb: number
  /** 0..1 */
  parte: number
  estado: EstadoFila
}

/** Segundos de espera entre reintentos por falta de red (docs/11 §5): 5, 10, 20, 40 y luego 60 como tope. */
export const ESPERAS_RED_S: readonly number[] = [5, 10, 20, 40, 60]

interface Props {
  /** Esperas entre reintentos por falta de red, en segundos; la última se repite. Solo los tests la cambian. */
  esperas?: readonly number[]
  ir: (paso: number) => void
  config: Config
  evaluacion: Evaluacion
  actualizar: (c: Partial<Config>) => void
}

export function Descarga({ ir, config, evaluacion, actualizar, esperas = ESPERAS_RED_S }: Props) {
  const t = tx.descarga
  const p = perfilDe(evaluacion, config.perfil)
  const [filas, setFilas] = useState<Fila[] | null>(null)
  const [fase, setFase] = useState<'trabajando' | 'esperando' | 'pausada' | 'error' | 'fin'>('trabajando')
  const [error, setError] = useState<string | null>(null)
  const [intento, setIntento] = useState(0)
  const pausando = useRef(false)
  // Reintento programado por falta de red: cuándo salta (para la cuenta atrás), su temporizador y cuántas veces seguidas ha fallado.
  const [reintentoEn, setReintentoEn] = useState<number | null>(null)
  const [ahora, setAhora] = useState(() => Date.now())
  const temporizador = useRef<ReturnType<typeof setTimeout> | null>(null)
  const fallosRed = useRef(0)
  const quitarTemporizador = () => {
    if (temporizador.current !== null) clearTimeout(temporizador.current)
    temporizador.current = null
    setReintentoEn(null)
  }
  const inicio = useRef({ t: 0, gb: 0 })
  const papeles = [['narrador', p.narrador], ['cronista', p.cronista], ['sugerencias', p.sugerencias], ['embeddings', p.embeddings]] as const
  const nombreDe = (m: string) => {
    const suyos = papeles.filter(([, modelo]) => modelo === m).map(([papel]) => t.papeles[papel])
    return suyos.length > 1 ? `${suyos.slice(0, -1).join(', ')} y ${suyos.at(-1)!.toLowerCase()}` : (suyos[0] ?? m)
  }

  const cambiar = useCallback((id: string, cambio: Partial<Fila>) => {
    setFilas((fs) => fs && fs.map((f) => (f.id === id ? { ...f, ...cambio } : f)))
  }, [])

  useEffect(() => {
    let vivo = true
    pausando.current = false
    setFase('trabajando')
    setError(null)
    setReintentoEn(null)
    void (async () => {
      try {
        const info = await api.estadoMotor()
        const modelos = [...new Set([p.narrador, p.cronista, p.sugerencias, p.embeddings])]
        setFilas((previas) => {
          const antes = new Map((previas ?? []).map((f) => [f.id, f]))
          return [
            { id: 'motor', nombre: t.motor, gb: info.descargaGb, parte: info.instalado ? 1 : 0, estado: info.instalado ? 'listo' : 'cola' },
            ...modelos.map((m): Fila => antes.get(m) ?? { id: m, nombre: nombreDe(m), gb: info.modelosGb[m] ?? 0, parte: 0, estado: 'cola' }),
          ]
        })
        inicio.current = { t: Date.now(), gb: 0 }
        if (!info.instalado) {
          await api.instalarMotor((pm: ProgresoMotor) => {
            if (!vivo) return
            if (pm.fase === 'descargando' && pm.hecho > 0) fallosRed.current = 0
            if (pm.fase === 'descargando') cambiar('motor', { estado: 'bajando', parte: pm.total ? pm.hecho / pm.total : 0 })
            else if (pm.fase === 'listo') cambiar('motor', { estado: 'listo', parte: 1 })
            else cambiar('motor', { estado: pm.fase, parte: 1 })
          })
        }
        cambiar('motor', { estado: 'listo', parte: 1 })
        await api.iniciarMotor()
        const bajados = await api.descargarModelos((pm) => {
          if (!vivo) return
          if (pm.hecho > 0) fallosRed.current = 0
          const listo = pm.estado === 'success'
          cambiar(pm.modelo, { estado: listo ? 'listo' : 'bajando', parte: listo ? 1 : pm.total ? pm.hecho / pm.total : 0 })
        })
        if (!vivo) return
        actualizar({ modelosDescargados: bajados })
        setFase('fin')
      } catch (e) {
        if (!vivo) return
        if (pausando.current) setFase('pausada')
        else if (e instanceof ErrorIa && e.red) {
          // Sin internet: la descarga espera y vuelve a intentarlo sola, cada vez más espaciada.
          const segundos = esperas[Math.min(fallosRed.current, esperas.length - 1)]
          fallosRed.current++
          setFase('esperando')
          setReintentoEn(Date.now() + segundos * 1000)
          setAhora(Date.now())
          temporizador.current = setTimeout(() => { temporizador.current = null; setIntento((n) => n + 1) }, segundos * 1000)
        } else {
          setError(String(e))
          setFase('error')
        }
      }
    })()
    return () => {
      vivo = false
      if (temporizador.current !== null) clearTimeout(temporizador.current)
      temporizador.current = null
    }
    // Se relanza al reanudar o reintentar.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [intento])

  // Cuenta atrás de la espera: un tic por segundo mientras haya un reintento programado.
  useEffect(() => {
    if (reintentoEn === null) return
    const id = setInterval(() => setAhora(Date.now()), 1000)
    return () => clearInterval(id)
  }, [reintentoEn])

  const pausar = () => {
    if (fase === 'esperando') {
      // No hay descarga en curso: basta con cancelar el reintento programado.
      quitarTemporizador()
      setFase('pausada')
      return
    }
    pausando.current = true
    void api.cancelarDescargas()
  }
  const reintentarAhora = () => {
    quitarTemporizador()
    setIntento((n) => n + 1)
  }
  const reanudar = () => {
    fallosRed.current = 0
    setIntento((n) => n + 1)
  }

  const total = (filas ?? []).reduce((a, f) => a + f.gb, 0)
  const hecho = (filas ?? []).reduce((a, f) => a + f.gb * f.parte, 0)
  const segundos = (Date.now() - inicio.current.t) / 1000
  const velocidad = segundos > 3 ? hecho / segundos : 0
  const quedan = velocidad > 0 ? Math.max(1, Math.ceil((total - hecho) / velocidad / 60)) : null

  const barra = (
    <>
      <button type="button" className="btn" onClick={() => { pausar(); ir(4) }}>{tx.comun.atras}</button>
      <span className="hueco" />
      {fase === 'fin' && <button type="button" className="btn pri" onClick={() => ir(6)}>{t.accion}</button>}
      {(fase === 'trabajando' || fase === 'esperando') && <button type="button" className="btn" onClick={pausar}>{t.pausar}</button>}
      {fase === 'esperando' && <button type="button" className="btn pri" onClick={reintentarAhora}>{t.reintentarAhora}</button>}
      {(fase === 'pausada' || fase === 'error') && (
        <button type="button" className="btn pri" onClick={reanudar}>{fase === 'error' ? t.reintentar : t.reanudar}</button>
      )}
    </>
  )

  return (
    <Marco paso={5} titulo={t.titulo} lead={t.lead(p.nombre)} barra={barra}>
      <div className="descargas">
        <div className="descarga">
          <b>{t.total}</b>
          <span className="mono peq">{fmt(hecho)} / {fmt(total)} GB{fase === 'trabajando' && quedan ? ` · ${t.quedan(quedan)}` : ''}</span>
          <div className="progreso"><div style={{ width: `${total ? (hecho / total) * 100 : 0}%` }} /></div>
        </div>
        <div className="filete" />
        {(filas ?? []).map((f) => {
          const ok = f.estado === 'listo'
          const estado = ok ? t.estados.listo
            : fase === 'esperando' && (f.parte > 0 || f.estado === 'bajando') ? t.estados.esperando
            : fase === 'pausada' && f.parte > 0 ? t.estados.pausa
            : fase === 'error' && f.estado === 'bajando' ? t.estados.detenida
            : f.estado === 'verificando' ? t.estados.verificando
            : f.estado === 'extrayendo' ? t.estados.extrayendo
            : f.estado === 'bajando' ? t.estados.bajando : t.estados.cola
          return (
            <div key={f.id} className={`descarga${ok ? ' ok' : ''}`}>
              <span>{f.nombre} {f.gb > 0 && <span className="peq tenue mono">{fmt(f.gb)} GB</span>}</span>
              <span className="estado">{estado}</span>
              <div className="progreso"><div style={{ width: `${f.parte * 100}%` }} /></div>
            </div>
          )
        })}
      </div>
      {fase === 'esperando' && (
        <div className="aviso" role="status">
          {t.sinRed}{reintentoEn !== null && ` ${t.reintentandoEn(Math.max(0, Math.ceil((reintentoEn - ahora) / 1000)))}`}
        </div>
      )}
      {error && <div className="error" role="alert">{error}</div>}
      <p className="peq tenue">{t.verificado}</p>
    </Marco>
  )
}

type EstadoComp = 'pendiente' | 'curso' | 'ok' | 'omitida' | 'fallo'

export function Comprobacion({ ir }: { ir: (paso: number) => void }) {
  const t = tx.comprobacion
  const [estados, setEstados] = useState<EstadoComp[]>(() => t.pasos.map(() => 'pendiente'))
  const [detalles, setDetalles] = useState<string[]>(() => t.pasos.map(() => ''))
  // Cada reintento es una ronda nueva, aunque empiece en el mismo paso que la anterior.
  const [ronda, setRonda] = useState({ desde: 0, n: 0 })
  const [copiado, setCopiado] = useState('')

  useEffect(() => {
    let vivo = true
    void (async () => {
      for (let i = ronda.desde; i < t.pasos.length; i++) {
        if (!vivo) return
        setEstados((e) => e.map((s, j) => (j === i ? 'curso' : s)))
        try {
          const r = await api.comprobar(t.pasos[i].id)
          if (!vivo) return
          setEstados((e) => e.map((s, j) => (j === i ? (r.resultado === 'ok' ? 'ok' : 'omitida') : s)))
          setDetalles((d) => d.map((s, j) => (j === i ? (r.resultado === 'ok' ? r.detalle : r.motivo) : s)))
        } catch (e) {
          if (!vivo) return
          setEstados((es) => es.map((s, j) => (j === i ? 'fallo' : s)))
          setDetalles((d) => d.map((s, j) => (j === i ? String(e) : s)))
          return
        }
      }
    })()
    return () => { vivo = false }
  }, [ronda, t.pasos])

  const fallo = estados.indexOf('fallo')
  const todo = estados.every((s) => s === 'ok' || s === 'omitida')
  const reintentar = () => {
    setEstados((e) => e.map((s, j) => (j >= fallo ? 'pendiente' : s)))
    setRonda((r) => ({ desde: fallo, n: r.n + 1 }))
  }
  const copiar = () => {
    const informe = t.pasos.map((p, i) => `${p.nombre}: ${estados[i]} ${detalles[i]}`).join('\n')
    navigator.clipboard?.writeText(informe).then(() => setCopiado(t.copiado), () => setCopiado(informe))
  }

  return (
    <Marco paso={6} titulo={t.titulo} lead={t.lead}
      barra={<><button type="button" className="btn" onClick={() => ir(5)}>{tx.comun.atras}</button><span className="hueco" />
        <button type="button" className="btn pri" disabled={!todo} onClick={() => ir(7)}>{todo ? tx.comun.continuar : t.comprobando}</button></>}>
      <ol className="comprobaciones">
        {t.pasos.map((paso, i) => (
          <li key={paso.id}>
            <div className="cab">
              <span className={`icono ${estados[i]}`}>{estados[i] === 'ok' ? '✓' : estados[i] === 'fallo' ? '!' : estados[i] === 'omitida' ? '–' : ''}</span>
              <span>{paso.nombre}</span>
            </div>
            <Detalle estado={estados[i]} id={paso.id} detalle={detalles[i]} />
            {estados[i] === 'fallo' && (
              <div className="fila">
                <button type="button" className="btn pri" onClick={reintentar}>{t.reintentar}</button>
                <button type="button" className="btn" onClick={() => ir(4)}>{t.masLigero}</button>
                <button type="button" className="btn" onClick={copiar}>{t.copiar}</button>
                <span className="peq tenue" aria-live="polite">{copiado}</span>
              </div>
            )}
            {estados[i] === 'fallo' && (paso.id === 'motor' || paso.id === 'modelos') && <Reparar alTerminar={reintentar} />}
          </li>
        ))}
      </ol>
    </Marco>
  )
}

function Detalle({ estado, id, detalle }: { estado: EstadoComp; id: string; detalle: string }) {
  const t = tx.comprobacion
  if (estado === 'fallo') return <div className="error" role="alert">{detalle}</div>
  if (estado === 'omitida') return <p className="peq tenue">{detalle}</p>
  if (estado !== 'ok') return null
  if (id !== 'narracion') return <p className="peq tenue">{detalle}</p>
  const { texto, tokensPorSegundo } = JSON.parse(detalle) as { texto: string; tokensPorSegundo: number }
  // En castellano una palabra son ~1,4 tokens de Qwen: palabras/s ≈ tokens/s × 0,7.
  const palabras = Math.max(1, Math.round(tokensPorSegundo * 0.7))
  return (
    <>
      <p className="cita">«{texto}»</p>
      <p className="peq tenue">{t.velocidad(palabras, Math.round(150 / palabras))}</p>
    </>
  )
}
