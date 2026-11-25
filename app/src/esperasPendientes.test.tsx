// INS-68 (trozo C2): pendientes leves de las esperas de red y del aviso de motor detenido.
import { act, cleanup, fireEvent, render, renderHook, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import App from './App'
import { catalogo, modelosDe } from './catalogo'
import { Reparar } from './componentes'
import { useEsperaRed } from './esperaRed'
import { Ajustes } from './pantallas'
import type { Reparacion } from './tipos'
import { configInicial, ejemplo, emitirMotorDetenido, equipoEjemplo, evaluarEjemplo, fijarSinRed, oyentesMotor, reiniciarCarpetaIa, reiniciarModelos, reiniciarMotorDetenido } from './ejemplo'

afterEach(async () => {
  cleanup()
  vi.restoreAllMocks()
  await ejemplo.guardarConfig(configInicial())
  reiniciarCarpetaIa()
  reiniciarModelos()
  reiniciarMotorDetenido()
})

const boton = (nombre: string | RegExp, timeout = 1000) => screen.findByRole('button', { name: nombre }, { timeout })
const e = evaluarEjemplo(equipoEjemplo)
const pasar = (ms: number) => act(async () => { vi.advanceTimersByTime(ms) })
const conRelojFalso = async (prueba: () => Promise<void>) => {
  vi.useFakeTimers({ shouldAdvanceTime: true })
  try { await prueba() } finally { vi.useRealTimers() }
}
const espera = (s: RegExp) => screen.findByText(new RegExp(`Reintentando en (${s.source}) s`), {}, { timeout: 2000 })

describe('progreso de la escalera (INS-68)', () => {
  it('un `hecho` menor que el máximo no cuenta como progreso ni vacía el máximo', () => {
    const { result } = renderHook(() => useEsperaRed())
    expect(result.current.progreso('m', 500)).toBe(true)
    expect(result.current.progreso('m', 500)).toBe(false)
    // El manifiesto del reintento no trae bytes: ni progreso ni reinicio.
    expect(result.current.progreso('m', 0)).toBe(false)
    expect(result.current.progreso('m', 200)).toBe(false)
    expect(result.current.progreso('m', 300)).toBe(false)
    expect(result.current.progreso('m', 501)).toBe(true)
    expect(result.current.progreso('otro', 100)).toBe(true)
  })

  it('tras un corte, el progreso reinicia por debajo del máximo y sube sin pasarlo: la espera sigue creciendo', () => {
    vi.useFakeTimers()
    try {
      const { result } = renderHook(() => useEsperaRed())
      const esperas: number[] = []
      const corte = () => { act(() => result.current.programar(() => {})); esperas.push(result.current.segundos ?? -1) }
      result.current.progreso('m', 1000)
      corte()
      for (const hecho of [100, 400, 900]) {
        act(() => { result.current.progreso('m', hecho) })
        act(() => { vi.advanceTimersByTime(60000) })
        corte()
      }
      expect(esperas).toEqual([5, 10, 20, 40])
    } finally { vi.useRealTimers() }
  })
})

describe('reiniciar a mano la escalera (INS-68)', () => {
  it('Reparar: tras Cancelar y volver a pulsar, la espera vuelve a 5 s', () => conRelojFalso(async () => {
    fijarSinRed(4)
    render(<Reparar />)
    fireEvent.click(await boton('Reparar'))
    await espera(/[45]/)
    await pasar(5000)
    await espera(/9|10/)
    await pasar(10000)
    await espera(/19|20/)
    await pasar(20000)
    await espera(/39|40/)
    fireEvent.click(screen.getByRole('button', { name: 'Cancelar' }))
    fijarSinRed(1)
    fireEvent.click(await boton('Reparar'))
    await espera(/[45]/)
  }), 30000)

  it('Ajustes: tras Pausar y volver a pulsar «Cambiar», la espera vuelve a 5 s', () => conRelojFalso(async () => {
    fijarSinRed(4)
    render(<Ajustes config={{ ...configInicial(), perfil: e.recomendado }} evaluacion={e} rutas={null} cambiarCarpeta={async () => {}} actualizar={() => {}}
      reemplazarConfig={() => {}} reanalizar={async () => {}} volver={() => {}} />)
    fireEvent.click(await boton(/^Ligero/))
    fireEvent.click(await boton(/^Cambiar/))
    await espera(/[45]/)
    await pasar(5000)
    await espera(/9|10/)
    await pasar(10000)
    await espera(/19|20/)
    await pasar(20000)
    await espera(/39|40/)
    fireEvent.click(screen.getByRole('button', { name: 'Pausar' }))
    fijarSinRed(1)
    fireEvent.click(await boton(/^Cambiar/))
    await espera(/[45]/)
  }), 30000)
})

describe('Reparar con un render nuevo (INS-68)', () => {
  it('el reintento tras un corte de red llama al `alTerminar` de ahora, no al del primer render', () => conRelojFalso(async () => {
    fijarSinRed(1)
    const viejo = vi.fn()
    const nuevo = vi.fn()
    const { rerender } = render(<Reparar alTerminar={viejo} />)
    fireEvent.click(await boton('Reparar'))
    await espera(/[45]/)
    rerender(<Reparar alTerminar={nuevo} />)
    await pasar(5000)
    await waitFor(() => expect(nuevo).toHaveBeenCalledTimes(1), { timeout: 5000 })
    expect(viejo).not.toHaveBeenCalled()
  }), 30000)

  it('Ajustes guarda los modelos del perfil de ahora aunque el perfil cambie durante la reparación', async () => {
    const [a, b] = [catalogo.perfiles.find((p) => p.id === 'equilibrado')!, catalogo.perfiles.find((p) => p.id === 'minimo')!]
    const delB = modelosDe(b)
    const soloA = modelosDe(a).filter((m) => !delB.includes(m))
    expect(soloA.length).toBeGreaterThan(0)
    let acabar!: (r: Reparacion) => void
    vi.spyOn(ejemplo, 'reparar').mockImplementation(() => new Promise<Reparacion>((ok) => { acabar = ok }))
    const actualizar = vi.fn()
    const props = { evaluacion: e, rutas: null, cambiarCarpeta: async () => {}, actualizar, reemplazarConfig: () => {}, reanalizar: async () => {}, volver: () => {} }
    const { rerender } = render(<Ajustes {...props} config={{ ...configInicial(), perfil: 'equilibrado', modelosDescargados: modelosDe(a) }} />)
    fireEvent.click(await boton('Reparar'))
    await waitFor(() => expect(acabar).toBeTypeOf('function'))
    rerender(<Ajustes {...props} config={{ ...configInicial(), perfil: 'minimo', modelosDescargados: delB }} />)
    await act(async () => { acabar({ motorReinstalado: false, capasRepuestas: 0, modelos: modelosDe(a) }) })
    await waitFor(() => expect(actualizar).toHaveBeenCalledTimes(1))
    const guardados = actualizar.mock.calls[0][0].modelosDescargados as string[]
    for (const m of soloA) expect(guardados).not.toContain(m)
    expect([...guardados].sort()).toEqual([...delB].sort())
  })
})

describe('aviso de motor detenido (INS-68)', () => {
  const aviso = { motivo: 'El motor de IA se detuvo: out of memory', sinMemoria: true }
  const conAsistenteHecho = () => ejemplo.analizarEquipo().then((equipo) => ejemplo.guardarConfig({ ...configInicial(), consentimientoAceptado: true, permisoAnalisis: true, equipo, perfil: 'equilibrado', pasoAsistente: 7, asistenteCompletado: true }))

  it('mientras el cambio de perfil espera la red, el aviso se ve y Ajustes sigue montado (oculto)', async () => {
    await conAsistenteHecho()
    render(<App />)
    fireEvent.click(await boton(/Ajustes/))
    fijarSinRed(1)
    fireEvent.click(await boton(/^Ligero/))
    fireEvent.click(await boton(/^Cambiar/))
    await screen.findByText(/^Esperando conexión · Reintentando en/, {}, { timeout: 3000 })
    emitirMotorDetenido(aviso)
    expect(await screen.findByText('El motor de IA se ha detenido')).toBeTruthy()
    // Ajustes sigue ahí, oculto, con su reintento en marcha.
    expect(screen.getByRole('button', { name: 'Pausar', hidden: true })).toBeTruthy()
    expect(screen.queryByRole('button', { name: 'Pausar' })).toBeNull()
  }, 30000)

  it('una lectura vieja de `motor_detenido()` no borra un aviso que llegó mientras tanto', async () => {
    await conAsistenteHecho()
    vi.spyOn(ejemplo, 'motorDetenido').mockImplementation(() => new Promise((ok) => setTimeout(() => ok(null), 300)))
    render(<App />)
    await waitFor(() => expect(oyentesMotor()).toBeGreaterThan(0))
    emitirMotorDetenido(aviso)
    expect(await screen.findByText('El motor de IA se ha detenido')).toBeTruthy()
    await new Promise((ok) => setTimeout(ok, 500))
    expect(screen.getByText('El motor de IA se ha detenido')).toBeTruthy()
  }, 30000)
})
