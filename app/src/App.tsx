import { useCallback, useEffect, useRef, useState } from 'react'
import { api } from './api'
import { configInicial } from './ejemplo'
import { errores } from './textos'
import type { Config, Evaluacion, Rutas } from './tipos'
import { Ajustes, Bienvenida, Comprobacion, Descarga, ElegirPerfil, Juego, Listo, QueSeInstala, TuEquipo } from './pantallas'

type Vista = 'asistente' | 'juego' | 'ajustes'

export default function App() {
  const [config, setConfig] = useState<Config | null>(null)
  const [rutas, setRutas] = useState<Rutas | null>(null)
  const [evaluacion, setEvaluacion] = useState<Evaluacion | null>(null)
  const [vista, setVista] = useState<Vista>('asistente')
  const [error, setError] = useState<string | null>(null)
  const ultima = useRef<Config | null>(null)

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

  const ir = useCallback((paso: number) => actualizar({ pasoAsistente: Math.min(7, Math.max(1, paso)) }), [actualizar])

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

  const aviso = error && <div className="error" role="alert" style={{ position: 'fixed', bottom: 16, left: 16, right: 16 }}>{error}</div>

  if (vista === 'juego') {
    return <>{aviso}<Juego abrirAjustes={() => setVista('ajustes')} repetir={() => { setVista('asistente'); actualizar({ ...configInicial(), pasoAsistente: 1 }); setEvaluacion(null) }} /></>
  }
  if (vista === 'ajustes' && evaluacion) {
    return <>{aviso}<Ajustes config={config} evaluacion={evaluacion} actualizar={actualizar} reanalizar={analizar} volver={() => setVista('juego')} /></>
  }

  // Sin evaluación no se puede pasar del paso 3.
  const paso = !evaluacion ? Math.min(config.pasoAsistente, 3) : config.pasoAsistente
  const nav = { ir }
  let pantalla
  switch (paso) {
    case 1: pantalla = <Bienvenida {...nav} />; break
    case 2: pantalla = <QueSeInstala {...nav} config={config} rutas={rutas} actualizar={actualizar} />; break
    case 3: pantalla = <TuEquipo {...nav} config={config} evaluacion={evaluacion} analizar={analizar} elegirAMano={elegirAMano} />; break
    case 4: pantalla = <ElegirPerfil {...nav} config={config} evaluacion={evaluacion!} actualizar={actualizar} />; break
    case 5: pantalla = <Descarga {...nav} config={config} evaluacion={evaluacion!} actualizar={actualizar} />; break
    case 6: pantalla = <Comprobacion {...nav} />; break
    default: pantalla = <Listo config={config} evaluacion={evaluacion!} rutas={rutas} jugar={() => { actualizar({ asistenteCompletado: true }); setVista('juego') }} />
  }
  return <>{aviso}{pantalla}</>
}
