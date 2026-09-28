// Pantallas del asistente de primer arranque (docs/11-diseno-del-frontal.md).

import { useState } from 'react'
import { ControlUsoCpu, DetallesTecnicos, Marco, Medidor, Pagina, Tarjetas } from './componentes'
import * as tx from './textos'
import type { Config, Equipo, Evaluacion, PerfilId, Rutas } from './tipos'
import { fmt, gbDeMb } from './formato'
import { elementosDescarga, useComprobacionSimulada, useDescargaSimulada } from './simulacion'

interface Nav {
  ir: (paso: number) => void
}

const Atras = ({ ir, paso }: Nav & { paso: number }) => (
  <button type="button" className="btn" onClick={() => ir(paso - 1)}>{tx.comun.atras}</button>
)

export function Bienvenida({ ir }: Nav) {
  const t = tx.bienvenida
  return (
    <Marco paso={1} titulo={t.titulo} lead={t.lead}
      barra={<><span className="hueco" /><button type="button" className="btn pri" onClick={() => ir(2)}>{t.accion}</button></>}>
      <ul className="lista">
        {t.pasos.map(([a, b]) => <li key={a}><span><b>{a}</b> <span className="tenue">{b}</span></span></li>)}
      </ul>
      <p className="tenue peq">{t.duracion}</p>
      <p className="tenue peq">{t.contenido}</p>
    </Marco>
  )
}

export function QueSeInstala({ ir, config, rutas, actualizar }: Nav & { config: Config; rutas: Rutas | null; actualizar: (c: Partial<Config>) => void }) {
  const t = tx.queSeInstala
  return (
    <Marco paso={2} titulo={t.titulo} lead={t.lead}
      barra={<><Atras ir={ir} paso={2} /><span className="hueco" />
        <button type="button" className="btn pri" disabled={!config.consentimientoAceptado} onClick={() => ir(3)}>{t.accion}</button></>}>
      <div className="cols">
        <div className="caja">
          <h2>{t.seInstala}</h2>
          <ul className="lista">{t.items.map(([a, b]) => <li key={a}><span><b>{a}</b> {b}</span></li>)}</ul>
          {rutas && <p className="peq tenue" style={{ marginTop: 12 }}>{t.donde} <span className="ruta">{rutas.datos}</span></p>}
        </div>
        <div className="caja">
          <h2>{t.nunca}</h2>
          <ul className="lista no">{t.nuncaItems.map((x) => <li key={x}>{x}</li>)}</ul>
        </div>
      </div>
      <p className="tenue peq">{t.red}</p>
      <label className="casilla">
        <input id="acepto" type="checkbox" checked={config.consentimientoAceptado}
          onChange={(e) => actualizar({ consentimientoAceptado: e.target.checked })} />
        <span>{t.acepto}</span>
      </label>
    </Marco>
  )
}

export function TuEquipo({ ir, config, evaluacion, analizar, elegirAMano }: Nav & {
  config: Config
  evaluacion: Evaluacion | null
  analizar: () => Promise<void>
  elegirAMano: () => void
}) {
  const t = tx.tuEquipo
  const [analizando, setAnalizando] = useState(false)
  const [error, setError] = useState(false)
  const lanzar = async () => {
    setAnalizando(true)
    setError(false)
    try { await analizar() } catch { setError(true) } finally { setAnalizando(false) }
  }

  const e = config.permisoAnalisis ? config.equipo : null
  if (!e || !evaluacion) {
    return (
      <Marco paso={3} titulo={t.tituloPermiso} lead={t.leadPermiso}
        barra={<><Atras ir={ir} paso={3} /><span className="hueco" />
          <button type="button" className="btn" onClick={elegirAMano}>{t.manual}</button>
          <button type="button" className="btn pri" disabled={analizando} onClick={lanzar}>{analizando ? t.analizando : t.analizar}</button></>}>
        <div className="caja"><h2>{t.consultaremos}</h2><ul className="lista">{t.items.map((x) => <li key={x}>{x}</li>)}</ul></div>
        <p className="tenue">{t.privacidad}</p>
        {error && <div className="error" role="alert">{t.error}</div>}
      </Marco>
    )
  }

  const gpu = e.gpus.find((g) => !g.integrada) ?? e.gpus[0]
  const integrada = !e.gpus.some((g) => !g.integrada)
  const recomendado = evaluacion.perfiles.find((p) => p.id === evaluacion.recomendado)!
  return (
    <Marco paso={3} titulo={t.titulo} lead={t.lead}
      barra={<><button type="button" className="btn" disabled={analizando} onClick={lanzar}>{t.reanalizar}</button><span className="hueco" />
        <button type="button" className="btn pri" onClick={() => ir(4)}>{tx.comun.continuar}</button></>}>
      <FichaEquipo equipo={e} gpu={gpu} integrada={integrada} />
      {evaluacion.equipoInsuficiente
        ? <div className="error"><b>{t.insuficienteTitulo}</b><span>{t.insuficiente(gbDeMb(e.ramTotalMb), recomendado.nombre)}</span></div>
        : <p>{t.puedes(fmt(evaluacion.memoriaParaIaGb ?? 0), recomendado.nombre)}</p>}
      {integrada && <p className="peq tenue">{t.integrada}</p>}
    </Marco>
  )
}

function FichaEquipo({ equipo: e, gpu, integrada }: { equipo: Equipo; gpu: Equipo['gpus'][number] | undefined; integrada: boolean }) {
  const t = tx.tuEquipo
  return (
    <dl className="ficha">
      <div><dt>{t.memoria}</dt><dd>{gbDeMb(e.ramTotalMb)} GB {integrada && <span className="peq tenue">{t.compartida}</span>}</dd></div>
      <div><dt>{t.grafica}</dt><dd className="peq">{gpu ? `${gpu.nombre}${gpu.vramMb ? ` · ${gbDeMb(gpu.vramMb)} GB` : ''}` : t.sinGrafica}</dd></div>
      <div><dt>{t.procesador}</dt><dd className="peq">{e.cpuModelo} · {e.nucleos}/{e.hilos}</dd></div>
      <div><dt>{t.disco}</dt><dd>{gbDeMb(e.discoLibreMb)} GB</dd></div>
      <div><dt>{t.sistema}</dt><dd className="peq">{e.sistema}</dd></div>
    </dl>
  )
}

export function ElegirPerfil({ ir, config, evaluacion, actualizar }: Nav & {
  config: Config
  evaluacion: Evaluacion
  actualizar: (c: Partial<Config>) => void
}) {
  const t = tx.perfil
  const [noRec, setNoRec] = useState(false)
  const manual = evaluacion.memoriaParaIaGb === null
  const elegido = config.perfil ?? evaluacion.recomendado
  const p = evaluacion.perfiles.find((x) => x.id === elegido)!
  const hilos = config.equipo?.hilos ?? 4
  return (
    <Marco paso={4} titulo={t.titulo} lead={manual ? t.leadManual : t.lead}
      barra={<><Atras ir={ir} paso={4} /><span className="hueco" />
        <button type="button" className="btn pri" onClick={() => { actualizar({ perfil: elegido }); ir(5) }}>{t.accion(fmt(p.descargaGb))}</button></>}>
      <Medidor evaluacion={evaluacion} />
      <p className="peq tenue">{t.calidadExplicada}</p>
      <Tarjetas evaluacion={evaluacion} seleccionado={elegido} mostrarNoRecomendados={noRec || manual || evaluacion.equipoInsuficiente}
        onSeleccionar={(id: PerfilId) => actualizar({ perfil: id })} />
      <ControlUsoCpu uso={config.usoCpu} hilos={hilos} onCambiar={(usoCpu) => actualizar({ usoCpu })} />
      <div className="fila">
        {!manual && (
          <label className="interruptor">
            <input id="no-recomendados" type="checkbox" checked={noRec} onChange={(e) => setNoRec(e.target.checked)} /> {t.noRecomendados}
          </label>
        )}
        <DetallesTecnicos evaluacion={evaluacion} />
      </div>
      <p className="peq tenue">{t.pie}</p>
    </Marco>
  )
}

export function Descarga({ ir, config, evaluacion, actualizar }: Nav & {
  config: Config
  evaluacion: Evaluacion
  actualizar: (c: Partial<Config>) => void
}) {
  const t = tx.descarga
  const p = evaluacion.perfiles.find((x) => x.id === (config.perfil ?? evaluacion.recomendado))!
  const modelos = [...new Set([p.narrador, p.cronista, p.sugerencias, p.embeddings])]
  const conGpu = config.equipo?.gpus.some((g) => !g.integrada) ?? false
  const [pausada, setPausada] = useState(false)
  const elementos = useDescargaSimulada(elementosDescarga(modelos, conGpu), pausada)
  const total = elementos.reduce((a, e) => a + e.gb, 0)
  const hecho = elementos.reduce((a, e) => a + e.hecho, 0)
  const fin = elementos.every((e) => e.hecho >= e.gb)
  return (
    <Marco paso={5} titulo={t.titulo} lead={t.lead(p.nombre)}
      barra={<><Atras ir={ir} paso={5} /><span className="hueco" />
        {fin
          ? <button type="button" className="btn pri" onClick={() => { actualizar({ modelosDescargados: modelos }); ir(6) }}>{t.accion}</button>
          : <button type="button" className="btn" onClick={() => setPausada(!pausada)}>{pausada ? t.reanudar : t.pausar}</button>}</>}>
      <div className="descargas">
        <div className="descarga">
          <b>{t.total}</b>
          <span className="mono peq">{fmt(hecho)} / {fmt(total)} GB{fin ? '' : ` · ${t.quedan(Math.max(1, Math.ceil((total - hecho) / 0.025 / 60)))}`}</span>
          <div className="progreso"><div style={{ width: `${(hecho / total) * 100}%` }} /></div>
        </div>
        <div className="filete" />
        {elementos.map((e) => {
          const ok = e.hecho >= e.gb
          const estado = ok ? t.estados.listo : e.hecho > 0 ? (pausada ? t.estados.pausa : t.estados.bajando) : t.estados.cola
          return (
            <div key={e.id} className={`descarga${ok ? ' ok' : ''}`}>
              <span>{e.id === 'motor' ? t.motor : t.nombreModelo(e.id)} <span className="peq tenue mono">{fmt(e.gb)} GB</span></span>
              <span className="estado">{estado}</span>
              <div className="progreso"><div style={{ width: `${(e.hecho / e.gb) * 100}%` }} /></div>
            </div>
          )
        })}
      </div>
      <p className="peq tenue">{t.verificado}</p>
    </Marco>
  )
}

export function Comprobacion({ ir }: Nav) {
  const t = tx.comprobacion
  const estados = useComprobacionSimulada(t.pasos.length)
  const todo = estados.every((s) => s === 'ok')
  return (
    <Marco paso={6} titulo={t.titulo} lead={t.lead}
      barra={<><Atras ir={ir} paso={6} /><span className="hueco" />
        <button type="button" className="btn pri" disabled={!todo} onClick={() => ir(7)}>{todo ? tx.comun.continuar : t.comprobando}</button></>}>
      <ol className="comprobaciones">
        {t.pasos.map(([nombre, detalle], i) => (
          <li key={nombre}>
            <div className="cab">
              <span className={`icono ${estados[i]}`}>{estados[i] === 'ok' ? '✓' : estados[i] === 'fallo' ? '!' : ''}</span>
              <span>{nombre}</span>
            </div>
            {estados[i] === 'ok' && detalle && <p className="peq tenue">{detalle}</p>}
          </li>
        ))}
      </ol>
    </Marco>
  )
}

export function Listo({ config, evaluacion, rutas, jugar }: { config: Config; evaluacion: Evaluacion; rutas: Rutas | null; jugar: () => void }) {
  const t = tx.listo
  const p = evaluacion.perfiles.find((x) => x.id === (config.perfil ?? evaluacion.recomendado))!
  return (
    <Marco paso={7} titulo={t.titulo} lead={t.lead}
      barra={<><span className="hueco" /><button type="button" className="btn pri" onClick={jugar}>{t.accion}</button></>}>
      <dl className="ficha">
        <div><dt>{t.perfil}</dt><dd>{p.nombre}</dd></div>
        <div><dt>{t.memoria}</dt><dd>{fmt(p.memoriaGb)} GB</dd></div>
        <div><dt>{t.espacio}</dt><dd>{fmt(p.descargaGb)} GB</dd></div>
        {rutas && <div><dt>{t.partidas}</dt><dd className="peq">{rutas.datos}</dd></div>}
      </dl>
      <p className="tenue">{t.pie}</p>
    </Marco>
  )
}

export function Juego({ abrirAjustes, repetir }: { abrirAjustes: () => void; repetir: () => void }) {
  const t = tx.juego
  return (
    <div className="ventana">
      <Pagina sola titulo={t.titulo} lead={t.lead}
        barra={<><button type="button" className="btn" onClick={repetir}>{t.repetir}</button><span className="hueco" />
          <button type="button" className="btn pri" onClick={abrirAjustes}>{t.ajustes}</button></>}>
        <span />
      </Pagina>
    </div>
  )
}

export function Ajustes({ config, evaluacion, actualizar, reanalizar, volver }: {
  config: Config
  evaluacion: Evaluacion
  actualizar: (c: Partial<Config>) => void
  reanalizar: () => Promise<void>
  volver: () => void
}) {
  const t = tx.ajustes
  const [noRec, setNoRec] = useState(false)
  const [elegido, setElegido] = useState<PerfilId>(config.perfil ?? evaluacion.recomendado)
  const actual = evaluacion.perfiles.find((x) => x.id === (config.perfil ?? evaluacion.recomendado))!
  const nuevo = evaluacion.perfiles.find((x) => x.id === elegido)!
  const extra = Math.max(0, nuevo.descargaGb - actual.descargaGb)
  const manual = evaluacion.memoriaParaIaGb === null
  return (
    <div className="ventana">
      <Pagina sola titulo={t.titulo} lead={t.actual(actual.nombre, fmt(actual.memoriaGb), fmt(actual.descargaGb))}
        barra={<><button type="button" className="btn" onClick={volver}>{t.volver}</button>
          <button type="button" className="btn" onClick={reanalizar}>{t.reanalizar}</button><span className="hueco" />
          <button type="button" className="btn pri" disabled={nuevo.id === actual.id} onClick={() => actualizar({ perfil: nuevo.id })}>
            {nuevo.id === actual.id ? t.actualBoton : extra > 0 ? t.cambiarDescargar(fmt(extra)) : t.cambiar}
          </button></>}>
        <Medidor evaluacion={evaluacion} />
        <Tarjetas evaluacion={evaluacion} seleccionado={elegido} mostrarNoRecomendados={noRec || manual} onSeleccionar={setElegido} />
        <ControlUsoCpu uso={config.usoCpu} hilos={config.equipo?.hilos ?? 4} onCambiar={(usoCpu) => actualizar({ usoCpu })} />
        {!manual && (
          <label className="interruptor">
            <input id="no-recomendados-ajustes" type="checkbox" checked={noRec} onChange={(e) => setNoRec(e.target.checked)} /> {tx.perfil.noRecomendados}
          </label>
        )}
        {nuevo.descargaGb < actual.descargaGb && <p className="peq tenue">{t.liberar(nuevo.nombre, fmt(actual.descargaGb - nuevo.descargaGb))}</p>}
      </Pagina>
    </div>
  )
}
