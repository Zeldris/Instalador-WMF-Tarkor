import { useRef, useState } from 'react'
import type { ReactNode } from 'react'
import { api } from './api'
import { comun, pasos, perfil as t, reparar as tr } from './textos'
import type { Evaluacion, PerfilId, ProgresoModelo, ProgresoMotor, Reparacion, UsoCpu } from './tipos'
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

export function Tarjetas({ evaluacion, seleccionado, onSeleccionar, confirmado, onConfirmar, onCambiarCarpeta, moviendo }: {
  evaluacion: Evaluacion
  seleccionado: PerfilId | null
  onSeleccionar: (id: PerfilId) => void
  confirmado: boolean
  onConfirmar: (si: boolean) => void
  onCambiarCarpeta: () => void
  moviendo: boolean
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
                {!p.cabeEnDisco && <button type="button" className="enlace" disabled={moviendo} onClick={onCambiarCarpeta}>{t.cambiarCarpeta}</button>}
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

export function CarpetaIa({ ruta, accion, moviendo, error, onMover }: { ruta: string; accion: string; moviendo: boolean; error: string | null; onMover: () => void }) {
  return (
    <div className="carpeta">
      <div className="fila">
        <span className="tenue">{t.carpeta}</span> <span className="ruta">{ruta}</span>
        <button type="button" className="enlace" disabled={moviendo} onClick={onMover}>{moviendo ? t.moviendo : accion}</button>
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

/** «Reparar» (`INS-49`): el botón, lo que está haciendo y cómo acabó. `alTerminar` solo se llama si salió bien. */
export function Reparar({ alTerminar }: { alTerminar?: (r: Reparacion) => void }) {
  const [reparando, setReparando] = useState(false)
  const [estado, setEstado] = useState('')
  const [error, setError] = useState<string | null>(null)
  const cancelando = useRef(false)
  const empezar = async () => {
    cancelando.current = false
    setReparando(true)
    setError(null)
    setEstado(tr.motor.verificando)
    try {
      const r = await api.reparar((p) => setEstado(textoMotor(p)), (p) => setEstado(textoModelo(p)))
      const partes = [...(r.motorReinstalado ? [tr.motorReinstalado] : []), ...(r.capasRepuestas > 0 ? [tr.capas(r.capasRepuestas)] : [])]
      setEstado(partes.length ? tr.hecho(partes) : tr.enOrden)
      alTerminar?.(r)
    } catch (e) {
      if (cancelando.current) setEstado(tr.cancelado)
      else {
        setEstado('')
        setError(String(e))
      }
    } finally {
      setReparando(false)
    }
  }
  return (
    <div className="reparar">
      <div className="fila">
        <button type="button" className="btn" disabled={reparando} onClick={empezar}>{reparando ? tr.reparando : tr.boton}</button>
        {reparando && <button type="button" className="btn" onClick={() => { cancelando.current = true; void api.cancelarDescargas() }}>{tr.cancelar}</button>}
        <span className="peq tenue" aria-live="polite">{estado || tr.explicacion}</span>
      </div>
      {error && <div className="error" role="alert">{error}</div>}
    </div>
  )
}

export function ControlUsoCpu({ uso, hilos, onCambiar }: { uso: UsoCpu; hilos: number; onCambiar: (u: UsoCpu) => void }) {
  const moderado = Math.max(1, Math.floor(hilos / 2))
  const alto = Math.max(1, hilos - 1)
  return (
    <div className="fila">
      <span>{t.usoCpu}</span>
      <div className="seg" role="group" aria-label={t.usoCpu}>
        <button type="button" aria-pressed={uso === 'moderado'} onClick={() => onCambiar('moderado')}>{t.moderado}</button>
        <button type="button" aria-pressed={uso === 'alto'} onClick={() => onCambiar('alto')}>{t.alto}</button>
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
