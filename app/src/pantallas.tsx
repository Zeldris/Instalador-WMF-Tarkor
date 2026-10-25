// Pantallas del asistente de primer arranque (docs/11-diseno-del-frontal.md).

import { useEffect, useRef, useState } from 'react'
import { api } from './api'
import { CarpetaIa, CopiarInforme, ControlUsoCpu, DetallesTecnicos, Marco, Medidor, Pagina, Reparar, Tarjetas, textoModelo, useMoverCarpeta } from './componentes'
import * as tx from './textos'
import type { Config, Equipo, Evaluacion, PerfilId, Rutas, Sobrante, UsoIa } from './tipos'
import { bloqueado } from './tipos'
import { fmt, gbDeMb } from './formato'

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

export function ElegirPerfil({ ir, config, evaluacion, rutas, cambiarCarpeta, actualizar }: Nav & {
  config: Config
  evaluacion: Evaluacion
  rutas: Rutas | null
  cambiarCarpeta: () => Promise<void>
  actualizar: (c: Partial<Config>) => void
}) {
  const t = tx.perfil
  const [confirmado, setConfirmado] = useState(false)
  const carpeta = useMoverCarpeta(cambiarCarpeta)
  const manual = evaluacion.memoriaParaIaGb === null
  const elegido = config.perfil ?? evaluacion.recomendado
  const p = evaluacion.perfiles.find((x) => x.id === elegido)!
  const hilos = config.equipo?.hilos ?? 4
  return (
    <Marco paso={4} titulo={t.titulo} lead={manual ? t.leadManual : t.lead}
      barra={<><Atras ir={ir} paso={4} /><span className="hueco" />
        <button type="button" className="btn pri" disabled={bloqueado(evaluacion, p, confirmado)} onClick={() => { actualizar({ perfil: elegido }); ir(5) }}>{t.accion(fmt(p.descargaGb))}</button></>}>
      <Medidor evaluacion={evaluacion} />
      <p className="peq tenue">{t.calidadExplicada}</p>
      <Tarjetas evaluacion={evaluacion} seleccionado={elegido} confirmado={confirmado} onConfirmar={setConfirmado}
        onCambiarCarpeta={carpeta.mover} moviendo={carpeta.moviendo}
        onSeleccionar={(id: PerfilId) => { setConfirmado(false); actualizar({ perfil: id }) }} />
      {rutas && <CarpetaIa ruta={rutas.ia} accion={t.cambiarCarpeta} moviendo={carpeta.moviendo} error={carpeta.error} onMover={carpeta.mover} />}
      <ControlUsoCpu uso={config.usoCpu} hilos={hilos} onCambiar={(usoCpu) => actualizar({ usoCpu })} />
      <div className="fila"><DetallesTecnicos evaluacion={evaluacion} /></div>
      <p className="peq tenue">{t.pie}</p>
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

const REFRESCO_USO_MS = 5000

/** Dónde corre la IA y la memoria que ocupa, refrescado cada 5 s mientras Ajustes está abierto. Si falla, no se muestra nada. */
function DondeCorre() {
  const [uso, setUso] = useState<UsoIa | null>(null)
  useEffect(() => {
    let vivo = true
    const leer = () => { api.usoIa().then((u) => { if (vivo) setUso(u) }, () => { if (vivo) setUso(null) }) }
    leer()
    const id = setInterval(leer, REFRESCO_USO_MS)
    return () => { vivo = false; clearInterval(id) }
  }, [])
  if (!uso) return null
  const d = tx.ajustes.dondeCorre
  return (
    <p className="peq" aria-live="polite">
      {tx.fraseUso(uso.porcentajeGpu)}{uso.porcentajeGpu !== null && uso.memoriaMb > 0 && <span className="tenue"> · {d.memoria(fmt(uso.memoriaMb / 1024))}</span>}
    </p>
  )
}

/** «Cambiar y descargar» (`INS-43`): llama a `cambiar_perfil`, que da el progreso y devuelve el `Config` guardado. */
function useCambiarPerfil(reemplazarConfig: (c: Config) => void) {
  const [cambiando, setCambiando] = useState(false)
  const [estado, setEstado] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [borrando, setBorrando] = useState(false)
  const [sobrantes, setSobrantes] = useState<Sobrante[]>([])
  const pausando = useRef(false)
  const cambiar = async (perfil: PerfilId) => {
    pausando.current = false
    setCambiando(true)
    setError(null)
    setEstado(tx.ajustes.cambiando)
    try {
      reemplazarConfig(await api.cambiarPerfil(perfil, (p) => setEstado(textoModelo(p))))
      setEstado('')
      // Con un Ollama externo el núcleo devuelve una lista vacía: sus modelos no se tocan.
      setSobrantes(await api.modelosSobrantes().catch(() => []))
    } catch (e) {
      if (pausando.current && String(e).startsWith(tx.ajustes.prefijoCancelacion)) setEstado(tx.ajustes.pausado)
      else { setEstado(''); setError(String(e)) }
    } finally {
      setCambiando(false)
    }
  }
  const pausar = () => { pausando.current = true; void api.cancelarDescargas() }
  const borrar = async () => {
    setError(null)
    setBorrando(true)
    try {
      await api.borrarModelos(sobrantes.map((s) => s.modelo))
      setSobrantes([])
    } catch (e) {
      setError(String(e))
    } finally {
      setBorrando(false)
    }
  }
  return { cambiando, borrando, estado, error, sobrantes, cambiar, pausar, borrar }
}

export function Ajustes({ perfilInicial, config, evaluacion, rutas, cambiarCarpeta, actualizar, reemplazarConfig, reanalizar, alCambiar, volver }: {
  /** Perfil ya elegido al abrir (desde «Cambiar a un perfil más ligero»). */
  perfilInicial?: PerfilId
  config: Config
  evaluacion: Evaluacion
  rutas: Rutas | null
  cambiarCarpeta: () => Promise<void>
  actualizar: (c: Partial<Config>) => void
  /** Sustituye el estado entero por el `Config` que ya guardó el núcleo (si no, un guardado posterior volvería al perfil viejo). */
  reemplazarConfig: (c: Config) => void
  reanalizar: () => Promise<void>
  /** Avisa a la app de que está (o ya no) cambiando de perfil: mientras, no se tapa Ajustes con la pantalla del motor. */
  alCambiar?: (cambiando: boolean) => void
  volver: () => void
}) {
  const t = tx.ajustes
  const [elegido, setElegido] = useState<PerfilId>(perfilInicial ?? config.perfil ?? evaluacion.recomendado)
  const [confirmado, setConfirmado] = useState(false)
  const carpeta = useMoverCarpeta(cambiarCarpeta)
  const cambio = useCambiarPerfil(reemplazarConfig)
  useEffect(() => { alCambiar?.(cambio.cambiando) }, [alCambiar, cambio.cambiando])
  useEffect(() => () => alCambiar?.(false), [alCambiar])
  const actual = evaluacion.perfiles.find((x) => x.id === (config.perfil ?? evaluacion.recomendado))!
  // Un id que no está en la evaluación (un perfil que ya no existe) no deja nada preseleccionado.
  const nuevo = evaluacion.perfiles.find((x) => x.id === elegido)
  const extra = nuevo ? Math.max(0, nuevo.descargaGb - actual.descargaGb) : 0
  return (
    <div className="ventana">
      <Pagina sola titulo={t.titulo} lead={t.actual(actual.nombre, fmt(actual.memoriaGb), fmt(actual.descargaGb))}
        barra={<><button type="button" className="btn" disabled={cambio.cambiando} onClick={volver}>{t.volver}</button>
          <button type="button" className="btn" disabled={cambio.cambiando} onClick={reanalizar}>{t.reanalizar}</button><span className="hueco" />
          {cambio.cambiando && <button type="button" className="btn" onClick={cambio.pausar}>{t.pausar}</button>}
          <button type="button" className="btn pri" disabled={cambio.cambiando || !nuevo || nuevo.id === actual.id || bloqueado(evaluacion, nuevo, confirmado)} onClick={() => nuevo && void cambio.cambiar(nuevo.id)}>
            {nuevo?.id === actual.id ? t.actualBoton : extra > 0 ? t.cambiarDescargar(fmt(extra)) : t.cambiar}
          </button></>}>
        <DondeCorre />
        <Medidor evaluacion={evaluacion} />
        {cambio.estado && <p className="peq tenue" aria-live="polite">{cambio.estado}</p>}
        {cambio.error && <div className="error" role="alert">{cambio.error}</div>}
        {cambio.sobrantes.length > 0 && (
          <div className="fila">
            <button type="button" className="btn" disabled={cambio.borrando || cambio.cambiando} onClick={() => void cambio.borrar()}>{cambio.borrando ? t.borrando : t.borrar(fmt(cambio.sobrantes.reduce((a, s) => a + s.gb, 0)))}</button>
          </div>
        )}
        <Tarjetas evaluacion={evaluacion} seleccionado={elegido} confirmado={confirmado} onConfirmar={setConfirmado}
          onCambiarCarpeta={carpeta.mover} moviendo={carpeta.moviendo}
          onSeleccionar={(id) => { setConfirmado(false); setElegido(id) }} />
        {rutas && <CarpetaIa ruta={rutas.ia} accion={t.moverCarpeta} moviendo={carpeta.moviendo} error={carpeta.error} onMover={carpeta.mover} desactivado={cambio.cambiando} />}
        <ControlUsoCpu uso={config.usoCpu} hilos={config.equipo?.hilos ?? 4} onCambiar={(usoCpu) => actualizar({ usoCpu })} desactivado={cambio.cambiando} />
        <Reparar alTerminar={(r) => actualizar({ modelosDescargados: r.modelos })} desactivado={cambio.cambiando} />
        <CopiarInforme />
        {nuevo && nuevo.descargaGb < actual.descargaGb && <p className="peq tenue">{t.liberar(nuevo.nombre, fmt(actual.descargaGb - nuevo.descargaGb))}</p>}
      </Pagina>
    </div>
  )
}
