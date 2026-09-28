import type { ReactNode } from 'react'
import { comun, pasos, perfil as t } from './textos'
import type { Evaluacion, PerfilId, UsoCpu } from './tipos'
import { cabe } from './tipos'
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
  const tope = Math.max(12, Math.ceil(disponible))
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

export function Tarjetas({ evaluacion, seleccionado, onSeleccionar, mostrarNoRecomendados }: {
  evaluacion: Evaluacion
  seleccionado: PerfilId | null
  onSeleccionar: (id: PerfilId) => void
  mostrarNoRecomendados: boolean
}) {
  const analizado = evaluacion.memoriaParaIaGb !== null
  const elegido = evaluacion.perfiles.find((p) => p.id === seleccionado)
  return (
    <>
      <div className="tarjetas">
        {evaluacion.perfiles.map((p) => {
          const deshabilitada = !cabe(p) && !mostrarNoRecomendados
          return (
            <button
              key={p.id}
              type="button"
              className={`tarjeta${seleccionado === p.id ? ' sel' : ''}`}
              disabled={deshabilitada}
              aria-pressed={seleccionado === p.id}
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
          )
        })}
      </div>
      {analizado && elegido && !cabe(elegido) && <div className="aviso" role="alert">{t.aviso}</div>}
    </>
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
