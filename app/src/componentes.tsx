import { useEffect, useRef, useState } from 'react'
import type { ReactNode } from 'react'
import { api, ErrorIa } from './api'
import { textoEspera, useEsperaRed } from './esperaRed'
import { comun, pasos, perfil as t, reparar as tr } from './textos'
import * as tx from './textos'
import type { Evaluacion, InfoBorrado, PerfilId, ProgresoModelo, ProgresoMotor, Reparacion, UsoCpu } from './tipos'
import { pideConfirmar } from './tipos'
import { fmt } from './formato'

export function Marco({ paso, titulo, lead, barra, children }: {
  paso: number
  titulo: string
  lead?: string
  barra: ReactNode
  children: ReactNode
}) {
  return (
    <div className="ventana">
      <aside className="riel">
        <div className="marca">{comun.marca}<small>{comun.subtitulo}</small></div>
        <ol className="pasos">
          {pasos.map((nombre, i) => {
            const n = i + 1
            const clase = n < paso ? 'hecho' : n === paso ? 'actual' : ''
            return (
              <li key={nombre} className={clase} aria-current={n === paso ? 'step' : undefined}>
                <span className="n">{n < paso ? '✓' : n}</span><span className="t">{nombre}</span>
              </li>
            )
          })}
        </ol>
        <div className="pie">{comun.pie}</div>
      </aside>
      <Pagina titulo={titulo} lead={lead} barra={barra}>{children}</Pagina>
    </div>
  )
}

/** Panel de madera con título, contenido y barra inferior. Sin riel: Ajustes y el juego. */
export function Pagina({ titulo, lead, barra, sola, children }: {
  titulo: string
  lead?: string
  barra: ReactNode
  sola?: boolean
  children: ReactNode
}) {
  return (
    <section className={`principal${sola ? ' sola' : ''}`}>
      <div className="contenido">
        <h1>{titulo}</h1>
        {lead && <p className="lead">{lead}</p>}
        <div className="filete" />
        {children}
      </div>
      <div className="barra">{barra}</div>
    </section>
  )
}

function Rombos({ n }: { n: number }) {
  return <span className="rombos" aria-label={`${n} de 4`}>{'◆'.repeat(n)}<i>{'◆'.repeat(4 - n)}</i></span>
}

/** Barra de memoria disponible para la IA con la marca de cada perfil (docs/11, pantalla 4). */
export function Medidor({ evaluacion }: { evaluacion: Evaluacion }) {
  const disponible = evaluacion.memoriaParaIaGb
  if (disponible === null) return null
  // La escala llega al perfil más exigente (o a lo disponible, si es más), redondeada a par para
  // que la marca central sea un número entero.
  const mayor = Math.max(disponible, ...evaluacion.perfiles.map((p) => p.memoriaGb))
  const tope = Math.ceil(mayor / 2) * 2
  const pct = (v: number) => `${Math.min(100, (v / tope) * 100)}%`
  return (
    <div className="medidor">
      <p>{t.medidor(fmt(disponible))}</p>
      <div className="pista" role="img" aria-label={t.medidor(fmt(disponible))}>
        <div className="relleno" style={{ width: pct(disponible) }} />
        {evaluacion.perfiles.map((p) => (
          <div key={p.id} className={`marca-perfil${p.memoriaGb > disponible ? ' fuera' : ''}`} style={{ left: pct(p.memoriaGb) }}>
            <span>{p.nombre}</span>
          </div>
        ))}
      </div>
      <div className="escala mono"><span>0 GB</span><span>{tope / 2} GB</span><span>{tope} GB</span></div>
    </div>
  )
}

export function Tarjetas({ evaluacion, seleccionado, onSeleccionar, confirmado, onConfirmar, onCambiarCarpeta, moviendo, desactivado = false }: {
  evaluacion: Evaluacion
  seleccionado: PerfilId | null
  onSeleccionar: (id: PerfilId) => void
  confirmado: boolean
  onConfirmar: (si: boolean) => void
  onCambiarCarpeta: () => void
  moviendo: boolean
  /** Algo más está usando el motor (p. ej. Reparar): no se cambia de perfil ni de carpeta. */
  desactivado?: boolean
}) {
  const analizado = evaluacion.memoriaParaIaGb !== null
  const libre = evaluacion.discoLibreGb
  return (
    <div className="tarjetas">
      {evaluacion.perfiles.map((p) => {
        const sel = seleccionado === p.id
        return (
          <div key={p.id} className="tarjeta-caja">
            <button
              type="button"
              className={`tarjeta${sel ? ' sel' : ''}`}
              aria-pressed={sel}
              disabled={desactivado}
              onClick={() => onSeleccionar(p.id)}
            >
              <span className="nombre">{p.nombre}</span>
              <span className="etiquetas">
                {analizado && evaluacion.recomendado === p.id && <span className="etiqueta rec">{t.recomendado}</span>}
                {analizado && evaluacion.maximoSeguro === p.id && <span className="etiqueta max">{t.maximoSeguro}</span>}
                {analizado && !p.cabeEnMemoria && <span className="etiqueta fuera">{t.supera}</span>}
                {analizado && p.cabeEnMemoria && !p.cabeEnDisco && <span className="etiqueta fuera">{t.sinDisco}</span>}
                {p.experimental && <span className="etiqueta exp">{t.experimental}</span>}
              </span>
              <span className="resultado">{p.resultado}</span>
              <dl>
                <dt>{t.memoria}</dt><dd>{fmt(p.memoriaGb)} GB</dd>
                <dt>{t.descarga}</dt><dd>{fmt(p.descargaGb)} GB</dd>
                <dt>{t.velocidad}</dt><dd><Rombos n={p.velocidad} /></dd>
                <dt>{t.narracion}</dt><dd><Rombos n={p.calidad} /></dd>
              </dl>
            </button>
            {sel && pideConfirmar(evaluacion, p) && (
              <div className="aviso">
                <span>{t.aviso}</span>
                <label className="interruptor">
                  <input type="checkbox" checked={confirmado} onChange={(e) => onConfirmar(e.target.checked)} /> {t.confirmar}
                </label>
              </div>
            )}
            {libre !== null && (
              <p className={`espacio peq${p.cabeEnDisco ? ' tenue' : ' sin'}`}>
                <span><span className="nw">{t.necesita(fmt(p.necesitaDiscoGb))}</span> · <span className="nw">{t.libres(fmt(libre))}</span></span>
                {!p.cabeEnDisco && <button type="button" className="enlace" disabled={moviendo || desactivado} onClick={onCambiarCarpeta}>{t.cambiarCarpeta}</button>}
              </p>
            )}
          </div>
        )
      })}
    </div>
  )
}

/** Estado de «elegir carpeta y mover»: «Moviendo…» y el error, para mostrarlos donde convenga. */
export function useMoverCarpeta(cambiar: () => Promise<void>) {
  const [moviendo, setMoviendo] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const mover = async () => {
    setMoviendo(true)
    setError(null)
    // El núcleo explica qué pasó y qué hacer (otra carpeta, poco espacio); se enseña tal cual.
    try { await cambiar() } catch (e) { setError(typeof e === 'string' && e ? e : t.errorCarpeta) } finally { setMoviendo(false) }
  }
  return { moviendo, error, mover }
}

export function CarpetaIa({ ruta, accion, moviendo, error, onMover, desactivado = false }: { ruta: string; accion: string; moviendo: boolean; error: string | null; onMover: () => void; desactivado?: boolean }) {
  return (
    <div className="carpeta">
      <div className="fila">
        <span className="tenue">{t.carpeta}</span> <span className="ruta">{ruta}</span>
        <button type="button" className="enlace" disabled={moviendo || desactivado} onClick={onMover}>{moviendo ? t.moviendo : accion}</button>
      </div>
      {error && <div className="error" role="alert">{error}</div>}
    </div>
  )
}

const pc = (hecho: number, total: number) => (total ? Math.round((hecho / total) * 100) : 0)

function textoMotor(p: ProgresoMotor) {
  return p.fase === 'descargando' ? tr.motor.descargando(pc(p.hecho, p.total)) : tr.motor[p.fase]
}

export function textoModelo(p: ProgresoModelo) {
  if (p.estado === 'verificando') return tr.comprobandoModelos(pc(p.hecho, p.total))
  return p.total > 0 && p.hecho < p.total ? tr.descargandoModelo(p.modelo, pc(p.hecho, p.total)) : tr.pidiendoModelo(p.modelo)
}

/**
 * «Reparar» (`INS-49`): el botón, lo que está haciendo y cómo acabó. `alTerminar` solo se llama si salió bien.
 * Si se pierde la red (`ErrorIa.red`, `INS-42`) espera y repite la reparación sola, como la Descarga.
 */
export function Reparar({ alTerminar, alReparar, desactivado = false }: {
  alTerminar?: (r: Reparacion) => void
  /** Avisa de que está (o ya no) reparando, esperando la red incluida: el padre bloquea lo que usa el mismo motor. */
  alReparar?: (reparando: boolean) => void
  desactivado?: boolean
}) {
  const [reparando, setReparando] = useState(false)
  const [estado, setEstado] = useState('')
  const [error, setError] = useState<string | null>(null)
  const cancelando = useRef(false)
  const espera = useEsperaRed()
  useEffect(() => { alReparar?.(reparando) }, [alReparar, reparando])
  useEffect(() => () => alReparar?.(false), [alReparar])
  const empezar = async () => {
    cancelando.current = false
    espera.cancelar()
    setReparando(true)
    setError(null)
    setEstado(tr.motor.verificando)
    let esperaPuesta = false
    try {
      const r = await api.reparar(
        (p) => {
          if (p.fase === 'descargando') espera.progreso('motor', p.hecho)
          setEstado(textoMotor(p))
        },
        (p) => {
          // «verificando» cuenta capas comprobadas en disco (sin modelo), no bytes bajados: no es progreso de red.
          if (p.estado !== 'success' && p.estado !== 'verificando') espera.progreso(p.modelo, p.hecho)
          setEstado(textoModelo(p))
        },
      )
      const partes = [...(r.motorReinstalado ? [tr.motorReinstalado] : []), ...(r.capasRepuestas > 0 ? [tr.capas(r.capasRepuestas)] : [])]
      setEstado(partes.length ? tr.hecho(partes) : tr.enOrden)
      alTerminar?.(r)
    } catch (e) {
      if (cancelando.current) setEstado(tr.cancelado)
      else if (e instanceof ErrorIa && e.red) {
        setEstado('')
        esperaPuesta = true
        espera.programar(() => void empezar())
      } else {
        setEstado('')
        setError(String(e))
      }
    } finally {
      // Con la espera puesta, `reparando` lo quita el reintento (que vuelve a ponerlo) o «Cancelar».
      if (!esperaPuesta) setReparando(false)
    }
  }
  const cancelar = () => {
    if (espera.segundos !== null) {
      // No hay reparación en curso: basta con cancelar el reintento programado.
      espera.cancelar()
      setReparando(false)
      setEstado(tr.cancelado)
      return
    }
    cancelando.current = true
    void api.cancelarDescargas()
  }
  return (
    <div className="reparar">
      <div className="fila">
        <button type="button" className="btn" disabled={reparando || desactivado} onClick={empezar}>{reparando ? tr.reparando : tr.boton}</button>
        {reparando && <button type="button" className="btn" onClick={cancelar}>{tr.cancelar}</button>}
        {espera.segundos !== null && <button type="button" className="btn" onClick={espera.reintentarAhora}>{tx.descarga.reintentarAhora}</button>}
        {espera.segundos !== null
          ? <span className="peq tenue" role="status">{textoEspera(espera.segundos)}</span>
          : <span className="peq tenue" aria-live="polite">{estado || tr.explicacion}</span>}
      </div>
      {error && <div className="error" role="alert">{error}</div>}
    </div>
  )
}

export function ControlUsoCpu({ uso, hilos, onCambiar, desactivado = false }: { uso: UsoCpu; hilos: number; onCambiar: (u: UsoCpu) => void; desactivado?: boolean }) {
  const moderado = Math.max(1, Math.floor(hilos / 2))
  const alto = Math.max(1, hilos - 1)
  return (
    <div className="fila">
      <span>{t.usoCpu}</span>
      <div className="seg" role="group" aria-label={t.usoCpu}>
        <button type="button" aria-pressed={uso === 'moderado'} disabled={desactivado} onClick={() => onCambiar('moderado')}>{t.moderado}</button>
        <button type="button" aria-pressed={uso === 'alto'} disabled={desactivado} onClick={() => onCambiar('alto')}>{t.alto}</button>
      </div>
      <span className="peq tenue">{uso === 'moderado' ? t.usoModerado(moderado, hilos) : t.usoAlto(alto, hilos)}</span>
    </div>
  )
}

export function DetallesTecnicos({ evaluacion }: { evaluacion: Evaluacion }) {
  return (
    <details>
      <summary>{t.detalles}</summary>
      <div className="tabla">
        <table>
          <thead><tr><th>{t.colPerfil}</th><th>{t.colNarrador}</th><th>{t.colSugerir}</th><th>{t.colCargados}</th></tr></thead>
          <tbody>
            {evaluacion.perfiles.map((p) => (
              <tr key={p.id}><td>{p.nombre}</td><td className="mono">{p.narrador}</td><td className="mono">{p.sugerencias}</td><td>{p.maxModelosCargados}</td></tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="peq tenue" style={{ marginTop: 6 }}>{t.detallesPie}</p>
    </details>
  )
}

/**
 * «Borrar datos del juego» (`INS-45`, solo Linux): botón y diálogo con las dos casillas sin marcar.
 * «Borrar» espera a que haya una marcada. `alBorrar` se llama cuando ya está todo borrado.
 */
export function BorrarDatos({ desactivado, alBorrar, alOcupar }: { desactivado: boolean; alBorrar: () => void; alOcupar?: (ocupado: boolean) => void }) {
  const t = tx.borrarDatos
  const [abierto, setAbierto] = useState(false)
  const [info, setInfo] = useState<InfoBorrado | null>(null)
  const [partidas, setPartidas] = useState(false)
  const [ia, setIa] = useState(false)
  const [borrando, setBorrando] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const abrir = () => {
    setPartidas(false)
    setIa(false)
    setError(null)
    setAbierto(true)
    void api.infoBorrado().then(setInfo, () => setInfo({ rutaIa: '', tamano: '' }))
  }
  const borrar = async () => {
    setError(null)
    setBorrando(true)
    alOcupar?.(true)
    try {
      await api.borrarDatos(partidas, ia)
      alBorrar()
    } catch (e) {
      setError(String(e))
    } finally {
      setBorrando(false)
      alOcupar?.(false)
    }
  }
  return (
    <div>
      <div className="fila">
        <button type="button" className="btn" disabled={desactivado || abierto} onClick={abrir}>{t.boton}</button>
      </div>
      {abierto && (
        <div className="aviso" role="dialog" aria-label={t.titulo} style={{ marginTop: 12, display: 'flex', flexDirection: 'column', gap: 10 }}>
          <strong>{t.titulo}</strong>
          <span>{t.lead}</span>
          <label className="casilla"><input type="checkbox" checked={partidas} disabled={borrando} onChange={(e) => setPartidas(e.target.checked)} /><span>{t.partidas}</span></label>
          <label className="casilla"><input type="checkbox" checked={ia} disabled={borrando} onChange={(e) => setIa(e.target.checked)} /><span>{t.ia(info?.tamano ?? '')}</span></label>
          {error && <div className="error" role="alert">{error}</div>}
          <div className="fila">
            <button type="button" className="btn pri" disabled={borrando || (!partidas && !ia)} onClick={() => void borrar()}>{borrando ? t.borrando : t.borrar}</button>
            <button type="button" className="btn" disabled={borrando} onClick={() => setAbierto(false)}>{t.cancelar}</button>
          </div>
        </div>
      )}
    </div>
  )
}

/** «Copiar informe» y «Ver detalles» (docs/11): copia con el portapapeles de Tauri; si falla, deja el texto desplegado para copiarlo a mano. */
export function CopiarInforme() {
  const [texto, setTexto] = useState<string | null>(null)
  const [visible, setVisible] = useState(false)
  const [copiado, setCopiado] = useState(false)
  const [ocupado, setOcupado] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [cargando, setCargando] = useState(false)
  // El informe cambia (motor parado, memoria): se pide de nuevo cada vez, y mientras llega se ve «cargando».
  const obtener = async (): Promise<string> => {
    setCargando(true)
    try {
      const x = await api.informe()
      setTexto(x)
      return x
    } finally {
      setCargando(false)
    }
  }
  const copiar = async () => {
    setOcupado(true)
    setError(null)
    setCopiado(false)
    let dado: string
    try {
      dado = await obtener()
    } catch {
      setError(tx.informe.errorInforme)
      setOcupado(false)
      return
    }
    try {
      await api.copiar(dado)
      setCopiado(true)
    } catch {
      setVisible(true)
      setError(tx.informe.errorCopiar)
    }
    setOcupado(false)
  }
  const detalles = async () => {
    if (visible) { setVisible(false); return }
    setError(null)
    setVisible(true)
    try { await obtener() } catch { setVisible(false); setError(tx.informe.errorInforme) }
  }
  return (
    <div>
      <div className="fila">
        <button type="button" className="btn" disabled={ocupado} onClick={() => void copiar()}>{tx.informe.copiar}</button>
        <button type="button" className="btn" aria-expanded={visible} onClick={() => void detalles()}>{visible ? tx.informe.ocultarDetalles : tx.informe.verDetalles}</button>
        {copiado && <span className="peq tenue" role="status">{tx.informe.copiado}</span>}
      </div>
      {error && <div className="error" role="alert">{error}</div>}
      {cargando && <p className="peq tenue" role="status">{tx.informe.cargando}</p>}
      {visible && !cargando && texto !== null && <pre className="peq" tabIndex={0} aria-label={tx.informe.copiar} style={{ whiteSpace: 'pre-wrap', userSelect: 'text', maxHeight: 240, overflow: 'auto' }}>{texto}</pre>}
    </div>
  )
}
