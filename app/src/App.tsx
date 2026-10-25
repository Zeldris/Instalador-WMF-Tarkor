import { useCallback, useEffect, useRef, useState } from 'react'
import { api } from './api'
import { configInicial } from './ejemplo'
import { errores } from './textos'
import { catalogo } from './catalogo'
import type { Config, Evaluacion, MotorDetenido, PerfilId, Rutas } from './tipos'
import { perfilMasLigero } from './tipos'
import { PantallaMotorDetenido } from './pantallaMotor'
import { Ajustes, Bienvenida, ElegirPerfil, Juego, Listo, QueSeInstala, TuEquipo } from './pantallas'
import { Comprobacion, Descarga } from './pantallasIa'

type Vista = 'asistente' | 'juego' | 'ajustes'

export default function App() {
  const [config, setConfig] = useState<Config | null>(null)
  const [rutas, setRutas] = useState<Rutas | null>(null)
  const [evaluacion, setEvaluacion] = useState<Evaluacion | null>(null)
  const [vista, setVista] = useState<Vista>('asistente')
  const [error, setError] = useState<string | null>(null)
  const [aviso, setAviso] = useState<MotorDetenido | null>(null)
  const [perfilAjustes, setPerfilAjustes] = useState<PerfilId | undefined>()
  const ultima = useRef<Config | null>(null)

  // La pantalla del motor detenido sale con el evento y, al montar, si el aviso se emitió antes de escuchar.
  useEffect(() => {
    let vivo = true
    let quitar: (() => void) | null = null
    void api.alMotorDetenido((a) => setAviso(a)).then((f) => { if (vivo) quitar = f; else f() })
    void api.motorDetenido().then((a) => { if (vivo && a) setAviso(a) }, () => {})
    return () => { vivo = false; quitar?.() }
  }, [])

  useEffect(() => {
    void (async () => {
      const c = await api.cargarConfig()
      setRutas(await api.rutas())
      if (c.permisoAnalisis !== null) setEvaluacion(await api.evaluarPerfiles(c.permisoAnalisis ? c.equipo : null))
      ultima.current = c
      setConfig(c)
      if (c.asistenteCompletado) setVista('juego')
    })()
  }, [])

  // Cada cambio se guarda en config.json al momento: si se cierra la app a medias, el asistente
  // continúa donde se quedó (docs/07).
  const actualizar = useCallback((parcial: Partial<Config>) => {
    if (!ultima.current) return
    const siguiente = { ...ultima.current, ...parcial }
    ultima.current = siguiente
    setConfig(siguiente)
    api.guardarConfig(siguiente).then(() => setError(null), () => setError(errores.guardar))
  }, [])

  // El núcleo ya guardó este `Config` (p. ej. al cambiar de perfil): se adopta tal cual, sin volver a guardarlo.
  const reemplazarConfig = useCallback((c: Config) => {
    ultima.current = c
    setConfig(c)
  }, [])

  const ir = useCallback((paso: number) => actualizar({ pasoAsistente: Math.min(7, Math.max(1, paso)) }), [actualizar])

  // Elegir carpeta, mover la IA, y volver a evaluar los perfiles con el disco de la carpeta nueva.
  const cambiarCarpeta = useCallback(async () => {
    const destino = await api.elegirCarpeta()
    if (!destino) return
    try {
      const nuevas = await api.cambiarCarpetaIa(destino)
      setRutas(nuevas)
      // El núcleo ya la guardó; se copia al estado para que el siguiente `actualizar` no la pise.
      actualizar({ carpetaIa: nuevas.ia })
    } catch (e) {
      // Puede fallar después de mover (el motor no arranca): se lee lo que guardó el núcleo.
      setRutas(await api.rutas())
      actualizar({ carpetaIa: (await api.cargarConfig()).carpetaIa })
      throw e
    }
    setEvaluacion(await api.evaluarPerfiles(ultima.current?.permisoAnalisis ? ultima.current.equipo : null))
  }, [actualizar])

  const analizar = useCallback(async () => {
    const equipo = await api.analizarEquipo()
    const ev = await api.evaluarPerfiles(equipo)
    setEvaluacion(ev)
    actualizar({ equipo, permisoAnalisis: true, perfil: ev.recomendado })
  }, [actualizar])

  const elegirAMano = useCallback(async () => {
    const ev = await api.evaluarPerfiles(null)
    setEvaluacion(ev)
    actualizar({ equipo: null, permisoAnalisis: false, perfil: ev.recomendado, pasoAsistente: 4 })
  }, [actualizar])

  if (!config) return null

  const avisoError = error && <div className="error" role="alert" style={{ position: 'fixed', bottom: 16, left: 16, right: 16 }}>{error}</div>

  if (aviso) {
    return <>{avisoError}<PantallaMotorDetenido aviso={aviso}
      masLigero={evaluacion ? perfilMasLigero(catalogo.perfiles, config.perfil) : null}
      reintentado={() => setAviso(null)}
      irAAjustes={(p) => { setPerfilAjustes(p); setAviso(null); setVista('ajustes') }} /></>
  }
  if (vista === 'juego') {
    return <>{avisoError}<Juego abrirAjustes={() => setVista('ajustes')} repetir={() => { setVista('asistente'); actualizar({ ...configInicial(), carpetaIa: config.carpetaIa, pasoAsistente: 1 }); setEvaluacion(null) }} /></>
  }
  if (vista === 'ajustes' && evaluacion) {
    return <>{avisoError}<Ajustes perfilInicial={perfilAjustes} config={config} evaluacion={evaluacion} rutas={rutas} cambiarCarpeta={cambiarCarpeta} actualizar={actualizar} reemplazarConfig={reemplazarConfig} reanalizar={analizar} volver={() => { setPerfilAjustes(undefined); setVista('juego') }} /></>
  }

  // Sin evaluación no se puede pasar del paso 3.
  const paso = !evaluacion ? Math.min(config.pasoAsistente, 3) : config.pasoAsistente
  const nav = { ir }
  let pantalla
  switch (paso) {
    case 1: pantalla = <Bienvenida {...nav} />; break
    case 2: pantalla = <QueSeInstala {...nav} config={config} rutas={rutas} actualizar={actualizar} />; break
    case 3: pantalla = <TuEquipo {...nav} config={config} evaluacion={evaluacion} analizar={analizar} elegirAMano={elegirAMano} />; break
    case 4: pantalla = <ElegirPerfil {...nav} config={config} evaluacion={evaluacion!} rutas={rutas} cambiarCarpeta={cambiarCarpeta} actualizar={actualizar} />; break
    case 5: pantalla = <Descarga {...nav} config={config} evaluacion={evaluacion!} actualizar={actualizar} />; break
    case 6: pantalla = <Comprobacion {...nav} />; break
    default: pantalla = <Listo config={config} evaluacion={evaluacion!} rutas={rutas} jugar={() => { actualizar({ asistenteCompletado: true }); setVista('juego') }} />
  }
  return <>{avisoError}{pantalla}</>
}
