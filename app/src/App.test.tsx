import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { act } from 'react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import App from './App'
import { ErrorIa, perfilDe, perfilMasLigero } from './tipos'
import { catalogo } from './catalogo'
import { Reparar } from './componentes'
import { Ajustes, ElegirPerfil, Listo } from './pantallas'
import { Descarga } from './pantallasIa'
import { ejemplo, configInicial, evaluarEjemplo, equipoEjemplo, fijarDiscoLibreIa, fijarErrorCambioPerfil, fijarRetardoCambioPerfil, fijarErrorCarpetaIa, fijarModelosDanados, fijarSinRed, fijarUsoIa, reiniciarCarpetaIa, reiniciarModelos, emitirMotorDetenido, fijarCalentar, arranquesDelMotor, fijarTokensPorSegundo, fijarErrorCopiar, fijarErrorReintento, fijarMotorDetenido, oyentesMotor, reiniciarMotorDetenido, textoCopiado, TEXTO_INFORME } from './ejemplo'

afterEach(async () => {
  cleanup()
  vi.restoreAllMocks()
  await ejemplo.guardarConfig(configInicial())
  reiniciarCarpetaIa()
  fijarModelosDanados(false)
  reiniciarModelos()
  reiniciarMotorDetenido()
})

const boton = (nombre: string | RegExp, timeout = 1000) => screen.findByRole('button', { name: nombre }, { timeout })

async function hastaElPermiso() {
  render(<App />)
  fireEvent.click(await boton('Empezar'))
  const aceptar = await boton('Aceptar y continuar')
  expect(aceptar).toHaveProperty('disabled', true)
  fireEvent.click(screen.getByRole('checkbox'))
  expect(aceptar).toHaveProperty('disabled', false)
  fireEvent.click(aceptar)
  await screen.findByText('¿Podemos revisar tu equipo?')
}

async function hastaElPerfil() {
  await hastaElPermiso()
  fireEvent.click(await boton('Analizar mi equipo'))
  await screen.findByText(/Te recomendamos el perfil/, {}, { timeout: 2000 })
  fireEvent.click(await boton('Continuar'))
  await boton(/^Equilibrado/)
}

describe('asistente de primer arranque', () => {
  it('con análisis recomienda el perfil calculado y marca el máximo seguro', async () => {
    await hastaElPermiso()
    fireEvent.click(await boton('Analizar mi equipo'))
    await screen.findByText(/Te recomendamos el perfil Equilibrado/)
    fireEvent.click(await boton('Continuar'))

    const equilibrado = await boton(/^Equilibrado/)
    expect(equilibrado.getAttribute('aria-pressed')).toBe('true')
    expect(screen.getByText('Máximo seguro')).toBeTruthy()
    expect(screen.getByText(/Tu equipo puede dedicar unos 11 GB/)).toBeTruthy()
    expect(await boton('Descargar 6,2 GB')).toBeTruthy()

    // Con el narrador `llama3.1:8b`, Máximo (11,5 GB) ya no cabe en la Deck: se elige con aviso.
    fireEvent.click(await boton(/^Máximo/))
    expect(await boton('Descargar 9,6 GB')).toBeTruthy()
    expect(screen.getByText(/Puede dejar tu equipo lento/)).toBeTruthy()

    // Ultra tampoco cabe, pero se puede elegir: tras el aviso hay que confirmar.
    expect(screen.getByText('Experimental')).toBeTruthy()
    expect(screen.queryByRole('checkbox', { name: /Mostrar perfiles no recomendados/ })).toBeNull()
  })

  it('un perfil que no cabe en memoria se elige, avisa y pide confirmar en su tarjeta', async () => {
    await hastaElPerfil()
    expect(screen.queryByText(/Puede dejar tu equipo lento/)).toBeNull()
    const ultra = await boton(/^Ultra/)
    expect(ultra).toHaveProperty('disabled', false)
    fireEvent.click(ultra)
    expect(ultra.getAttribute('aria-pressed')).toBe('true')
    expect(screen.getByText(/Puede dejar tu equipo lento/)).toBeTruthy()
    const descargar = await boton(/^Descargar/)
    expect(descargar).toHaveProperty('disabled', true)
    fireEvent.click(screen.getByRole('checkbox', { name: 'Usar este perfil igualmente' }))
    expect(descargar).toHaveProperty('disabled', false)

    // La confirmación se pierde al cambiar de tarjeta.
    fireEvent.click(await boton(/^Equilibrado/))
    expect(screen.queryByText(/Puede dejar tu equipo lento/)).toBeNull()
    expect(screen.queryByRole('checkbox', { name: 'Usar este perfil igualmente' })).toBeNull()
    fireEvent.click(await boton(/^Ultra/))
    expect(screen.getByRole('checkbox', { name: 'Usar este perfil igualmente' })).toHaveProperty('checked', false)
    expect(await boton(/^Descargar/)).toHaveProperty('disabled', true)
  })

  it('cada tarjeta dice cuánto necesita y cuánto queda libre', async () => {
    await hastaElPerfil()
    const lineas = [...document.querySelectorAll('.espacio')].map((n) => n.textContent)
    expect(lineas).toHaveLength(5)
    lineas.forEach((l) => expect(l).toMatch(/^Necesita .* GB · libres 180 GB$/))
  })

  it('sin disco para el perfil elegido se bloquea la descarga hasta cambiar de carpeta', async () => {
    // Equilibrado cabe en memoria pero necesita 6,2 × 1,1 GB de disco.
    fijarDiscoLibreIa(6)
    await hastaElPerfil()
    fireEvent.click(await boton(/^Equilibrado/))
    const sin = await screen.findAllByText(/libres 6 GB/)
    expect(sin.some((n) => n.closest('.espacio')?.classList.contains('sin'))).toBe(true)
    expect(await boton(/^Descargar/)).toHaveProperty('disabled', true)

    const carpeta = document.querySelector('.carpeta') as HTMLElement
    expect(within(carpeta).getByText(/ia$/)).toBeTruthy()
    fireEvent.click(within(carpeta).getByRole('button', { name: 'Cambiar carpeta' }))
    await waitFor(() => expect(within(carpeta).getByText('/mnt/tarjeta-sd/Tarkor IA')).toBeTruthy())
    await waitFor(() => expect(screen.getAllByText(/libres 500 GB/).length).toBeGreaterThan(0))
    expect(await boton(/^Descargar/)).toHaveProperty('disabled', false)
    expect((await ejemplo.cargarConfig()).carpetaIa).toBe('/mnt/tarjeta-sd/Tarkor IA')
  })

  it('si no se puede cambiar la carpeta, dice por qué', async () => {
    const motivo = 'La carpeta /mnt/tarjeta-sd/Tarkor IA ya existe y no está vacía. Elige otra.'
    fijarErrorCarpetaIa(motivo)
    await hastaElPerfil()
    const carpeta = document.querySelector('.carpeta') as HTMLElement
    fireEvent.click(within(carpeta).getByRole('button', { name: 'Cambiar carpeta' }))
    expect((await within(carpeta).findByRole('alert')).textContent).toBe(motivo)
  })

  it('en Ajustes se puede mover la carpeta de la IA, y repetir el asistente no la olvida', async () => {
    await hastaElPerfil()
    fireEvent.click(await boton(/^Descargar/))
    fireEvent.click(await boton('Comprobar la instalación', 10000))
    await screen.findByText(/palabras por segundo/, {}, { timeout: 5000 })
    fireEvent.click(await boton('Continuar'))
    fireEvent.click(await boton('Jugar'))
    fireEvent.click(await boton(/Ajustes/))
    await screen.findByText('Rendimiento de la IA')
    const carpeta = document.querySelector('.carpeta') as HTMLElement
    fireEvent.click(within(carpeta).getByRole('button', { name: 'Mover a otra carpeta' }))
    await waitFor(() => expect(within(carpeta).getByText('/mnt/tarjeta-sd/Tarkor IA')).toBeTruthy())

    fireEvent.click(await boton('Volver'))
    fireEvent.click(await boton('Repetir el asistente'))
    await boton('Empezar')
    await waitFor(async () => expect((await ejemplo.cargarConfig()).pasoAsistente).toBe(1))
    expect((await ejemplo.cargarConfig()).carpetaIa).toBe('/mnt/tarjeta-sd/Tarkor IA')
  }, 20000)

  it('cada perfil explica qué resultado esperar', async () => {
    await hastaElPermiso()
    fireEvent.click(await boton('Analizar mi equipo'))
    fireEvent.click(await boton('Continuar'))
    expect(await screen.findByText(/Para probar Tarkor en casi cualquier equipo/)).toBeTruthy()
    expect(screen.getByText(/La experiencia para la que se diseñó Tarkor/)).toBeTruthy()
  })

  it('eligiendo a mano no hay medidor y parte del perfil más ligero', async () => {
    await hastaElPermiso()
    fireEvent.click(await boton('Prefiero elegir a mano'))
    const minimo = await boton(/^Mínimo/)
    expect(minimo.getAttribute('aria-pressed')).toBe('true')
    expect(screen.queryByText(/Tu equipo puede dedicar/)).toBeNull()
    expect(screen.queryByText('Recomendado')).toBeNull()
  })

  it('descarga, comprueba y termina', async () => {
    await hastaElPermiso()
    fireEvent.click(await boton('Analizar mi equipo'))
    fireEvent.click(await boton('Continuar'))
    fireEvent.click(await boton(/^Descargar/))

    // Mínimo usa el mismo modelo para tres papeles; Equilibrado, el cronista para sugerir.
    expect(await screen.findByText('Cronista y sugerencias')).toBeTruthy()
    fireEvent.click(await boton('Comprobar la instalación', 10000))

    expect(await screen.findByText(/palabras por segundo/, {}, { timeout: 5000 })).toBeTruthy()
    expect(screen.getAllByText(/Llega con el juego empaquetado/)).toHaveLength(3)
    fireEvent.click(await boton('Continuar'))
    await screen.findByText('Todo preparado')
    expect((await ejemplo.cargarConfig()).modelosDescargados).toEqual(['llama3.1:8b', 'qwen2.5:1.5b-instruct', 'nomic-embed-text'])
  }, 20000)

  it('si falla un modelo en la comprobación, Reparar lo repone y la comprobación sigue', async () => {
    await hastaElPerfil()
    fireEvent.click(await boton(/^Descargar/))
    fijarModelosDanados(true)
    fireEvent.click(await boton('Comprobar la instalación', 10000))
    expect((await screen.findByRole('alert', {}, { timeout: 3000 })).textContent).toMatch(/^Faltan modelos/)
    // Sin reparar, la capa seguiría dañada y «Modelos» volvería a fallar al relanzar.
    fireEvent.click(await boton('Reparar'))
    expect(await screen.findByText(/palabras por segundo/, {}, { timeout: 5000 })).toBeTruthy()
    expect(screen.queryByRole('alert')).toBeNull()
  }, 20000)

  it('Reintentar vuelve a comprobar aunque falle otra vez el mismo paso', async () => {
    await hastaElPerfil()
    fireEvent.click(await boton(/^Descargar/))
    fijarModelosDanados(true)
    fireEvent.click(await boton('Comprobar la instalación', 10000))
    const fallo = async () => expect((await screen.findByRole('alert', {}, { timeout: 3000 })).textContent).toMatch(/^Faltan modelos/)
    await fallo()
    fireEvent.click(await boton('Reintentar'))
    await fallo()
    fireEvent.click(await boton('Reintentar'))
    await fallo()
  }, 20000)

  it('una reparación se puede cancelar', async () => {
    await hastaElPerfil()
    fireEvent.click(await boton(/^Descargar/))
    fijarModelosDanados(true)
    fireEvent.click(await boton('Comprobar la instalación', 10000))
    await screen.findByRole('alert', {}, { timeout: 3000 })
    fireEvent.click(await boton('Reparar'))
    fireEvent.click(await boton('Cancelar'))
    expect(await screen.findByText(/^Reparación cancelada/, {}, { timeout: 3000 })).toBeTruthy()
    expect(await boton('Reparar')).toHaveProperty('disabled', false)
  }, 20000)

  it('en Ajustes, Reparar dice si todo estaba en orden', async () => {
    await hastaElPerfil()
    fireEvent.click(await boton(/^Descargar/))
    fireEvent.click(await boton('Comprobar la instalación', 10000))
    await screen.findByText(/palabras por segundo/, {}, { timeout: 5000 })
    fireEvent.click(await boton('Continuar'))
    fireEvent.click(await boton('Jugar'))
    fireEvent.click(await boton(/Ajustes/))
    fireEvent.click(await boton('Reparar'))
    expect(await screen.findByText(/^Todo estaba en orden/, {}, { timeout: 3000 })).toBeTruthy()
  }, 20000)

  async function hastaAjustes() {
    await hastaElPerfil()
    fireEvent.click(await boton(/^Descargar/))
    fireEvent.click(await boton('Comprobar la instalación', 10000))
    await screen.findByText(/palabras por segundo/, {}, { timeout: 5000 })
    fireEvent.click(await boton('Continuar'))
    fireEvent.click(await boton('Jugar'))
    fireEvent.click(await boton(/Ajustes/))
  }

  it('las licencias se leen desde el paso 2, y Volver deja la casilla como estaba', async () => {
    render(<App />)
    fireEvent.click(await boton('Empezar'))
    fireEvent.click(screen.getByRole('checkbox'))
    fireEvent.click(await boton('Leer las licencias'))
    expect(await screen.findByRole('heading', { name: 'Built with Llama' })).toBeTruthy()
    fireEvent.click(await boton('Volver'))
    expect(screen.getByRole('checkbox')).toHaveProperty('checked', true)
    expect(await boton('Aceptar y continuar')).toHaveProperty('disabled', false)
  })

  it('las licencias se leen desde Ajustes, y Volver deja Ajustes como estaba', async () => {
    await hastaAjustes()
    fireEvent.click(await boton('Licencias'))
    expect(await screen.findByRole('heading', { name: 'Licencias y avisos' })).toBeTruthy()
    fireEvent.click(await boton('Volver'))
    expect(await boton('Reparar')).toBeTruthy()
  }, 30000)

  it('Licencias no desmonta Ajustes: el resultado de Reparar y «Copiado» siguen al Volver', async () => {
    await hastaAjustes()
    fireEvent.click(await boton('Reparar'))
    expect(await screen.findByText(/^Todo estaba en orden/, {}, { timeout: 3000 })).toBeTruthy()
    fireEvent.click(await boton('Copiar informe'))
    expect(await screen.findByText('Copiado')).toBeTruthy()
    fireEvent.click(await boton('Licencias'))
    expect(await screen.findByRole('heading', { name: 'Licencias y avisos' })).toBeTruthy()
    fireEvent.click(await boton('Volver'))
    expect(screen.getByText(/^Todo estaba en orden/)).toBeTruthy()
    expect(screen.getByText('Copiado')).toBeTruthy()
  }, 30000)

  it('en Ajustes dice dónde corre la IA, y si no responde la pantalla sigue', async () => {
    await hastaAjustes()
    expect(await screen.findByText(/La IA usa la gráfica al 100 %/)).toBeTruthy()
    cleanup()
    fijarUsoIa(new Error('El motor no está en marcha'))
    render(<App />)
    fireEvent.click(await boton(/Ajustes/))
    expect(await boton('Reparar')).toBeTruthy()
    expect(screen.queryByText(/La IA/)).toBeNull()
  }, 30000)

  it('cambiar de perfil adopta el Config devuelto, ofrece borrar lo que sobra y lo borra', async () => {
    await hastaAjustes()
    fireEvent.click(await boton(/^Ligero/))
    fireEvent.click(await boton(/^Cambiar/))
    fireEvent.click(await boton(/^Borrar modelos que ya no uso/, 5000))
    await waitFor(() => expect(screen.queryByRole('button', { name: /^Borrar modelos que ya no uso/ })).toBeNull())
    expect((await ejemplo.cargarConfig()).perfil).toBe('ligero')
    expect(await ejemplo.modelosSobrantes()).toEqual([])
    // Un guardado posterior no puede devolver el perfil viejo: sin `reemplazarConfig`, `actualizar` lo pisaba.
    fireEvent.click(screen.getByRole('button', { name: 'Alto' }))
    await waitFor(async () => expect((await ejemplo.cargarConfig()).usoCpu).toBe('alto'))
    expect((await ejemplo.cargarConfig()).perfil).toBe('ligero')
    expect(screen.getByText(/^Perfil actual: Ligero/)).toBeTruthy()
  }, 30000)

  it('en Ajustes, un perfil inicial que no está en la evaluación no rompe la pantalla ni preselecciona nada', async () => {
    const evaluacion = evaluarEjemplo(equipoEjemplo)
    render(<Ajustes perfilInicial={'no-existe' as never} config={configInicial()} evaluacion={evaluacion} rutas={null} cambiarCarpeta={async () => {}}
      actualizar={() => {}} reemplazarConfig={() => {}} reanalizar={async () => {}} volver={() => {}} />)
    expect(await boton('Reparar')).toBeTruthy()
    expect(screen.getAllByRole('button').filter((b) => b.getAttribute('aria-pressed') === 'true' && /Ligero|Equilibrado|Alto|Mínimo/.test(b.textContent ?? ''))).toHaveLength(0)
    expect(screen.getByRole('button', { name: /^Cambiar/ })).toHaveProperty('disabled', true)
  })

  it('en Ajustes, un perfil guardado que ya no está en la evaluación cuenta como el recomendado', async () => {
    const evaluacion = evaluarEjemplo(equipoEjemplo)
    const recomendado = evaluacion.perfiles.find((x) => x.id === evaluacion.recomendado)!
    render(<Ajustes config={{ ...configInicial(), perfil: 'no-existe' as never }} evaluacion={evaluacion} rutas={null} cambiarCarpeta={async () => {}}
      actualizar={() => {}} reemplazarConfig={() => {}} reanalizar={async () => {}} volver={() => {}} />)
    expect(await boton('Reparar')).toBeTruthy()
    expect(screen.getByText(new RegExp(`^Perfil actual: ${recomendado.nombre}`))).toBeTruthy()
  })

  describe('un perfil guardado que ya no está en la evaluación (INS-43)', () => {
    const huerfana = () => ({ ...configInicial(), perfil: 'no-existe' as never })
    const recomendadoDe = (e: ReturnType<typeof evaluarEjemplo>) => e.perfiles.find((x) => x.id === e.recomendado)!

    it('perfilDe devuelve el perfil pedido, y si no está (o es null) el recomendado, y si tampoco el primero', () => {
      const e = evaluarEjemplo(equipoEjemplo)
      expect(perfilDe(e, 'ligero').id).toBe('ligero')
      expect(perfilDe(e, 'no-existe').id).toBe(e.recomendado)
      expect(perfilDe(e, null).id).toBe(e.recomendado)
      expect(perfilDe(e, undefined).id).toBe(e.recomendado)
      expect(perfilDe({ ...e, recomendado: 'tampoco' }, 'no-existe')).toBe(e.perfiles[0])
      expect(() => perfilDe({ ...e, perfiles: [] }, 'ligero')).toThrow('La evaluación no trae ningún perfil')
    })

    it('Descarga no se cae y descarga el perfil recomendado', async () => {
      const e = evaluarEjemplo(equipoEjemplo)
      render(<Descarga ir={() => {}} config={huerfana()} evaluacion={e} actualizar={() => {}} />)
      expect(await screen.findByText(new RegExp(`^Perfil ${recomendadoDe(e).nombre}\\.`))).toBeTruthy()
    })

    it('Perfil no se cae, marca el recomendado y guarda el recomendado, no el id que no existe', async () => {
      const e = evaluarEjemplo(equipoEjemplo)
      const guardados: unknown[] = []
      render(<ElegirPerfil ir={() => {}} config={huerfana()} evaluacion={e} rutas={null} cambiarCarpeta={async () => {}}
        actualizar={(c) => guardados.push(c.perfil)} />)
      const tarjeta = await boton(new RegExp(`^${recomendadoDe(e).nombre}`))
      expect(tarjeta.getAttribute('aria-pressed')).toBe('true')
      fireEvent.click(await boton(/^Descargar/))
      expect(guardados).toEqual([e.recomendado])
    })

    it('Listo no se cae y enseña el perfil recomendado', () => {
      const e = evaluarEjemplo(equipoEjemplo)
      render(<Listo config={huerfana()} evaluacion={e} rutas={null} jugar={() => {}} />)
      expect(screen.getByText(recomendadoDe(e).nombre)).toBeTruthy()
    })
  })

  it('durante un cambio de perfil, el control de CPU, Reparar y la carpeta están desactivados', async () => {
    await hastaAjustes()
    fijarRetardoCambioPerfil(300)
    fireEvent.click(await boton(/^Ligero/))
    fireEvent.click(await boton(/^Cambiar/))
    await boton('Pausar')
    expect(screen.getByRole('button', { name: 'Alto' })).toHaveProperty('disabled', true)
    expect(screen.getByRole('button', { name: 'Moderado' })).toHaveProperty('disabled', true)
    expect(screen.getByRole('button', { name: 'Reparar' })).toHaveProperty('disabled', true)
    expect(screen.getByRole('button', { name: /Mover/ })).toHaveProperty('disabled', true)
    await boton(/^Borrar modelos que ya no uso/, 5000)
    expect(screen.getByRole('button', { name: 'Alto' })).toHaveProperty('disabled', false)
  }, 30000)

  it('si cambiar de perfil falla, muestra el error y sigue el perfil de antes', async () => {
    await hastaAjustes()
    const antes = (await ejemplo.cargarConfig()).perfil
    fijarErrorCambioPerfil('El motor de IA no arranca con el perfil nuevo (x); sigue el perfil de antes.')
    fireEvent.click(await boton(/^Ligero/))
    fireEvent.click(await boton(/^Cambiar/))
    expect((await screen.findByRole('alert')).textContent).toContain('sigue el perfil de antes')
    expect((await ejemplo.cargarConfig()).perfil).toBe(antes)
  }, 30000)

  describe('motor detenido', () => {
    const aviso = { motivo: 'El motor de IA se detuvo: out of memory', sinMemoria: true }
    const conAsistenteHecho = async () => {
      await ejemplo.guardarConfig({ ...configInicial(), consentimientoAceptado: true, permisoAnalisis: true, equipo: await ejemplo.analizarEquipo(), perfil: 'equilibrado', pasoAsistente: 7, asistenteCompletado: true })
    }

    it('perfilMasLigero elige el de memoria justo por debajo, sin experimentales, y null con el más ligero', () => {
      const ids = catalogo.perfiles.map((p) => p.id)
      expect(perfilMasLigero(catalogo.perfiles, 'equilibrado')).toBe('ligero')
      expect(perfilMasLigero(catalogo.perfiles, 'ligero')).toBe('minimo')
      expect(perfilMasLigero(catalogo.perfiles, ids[0])).toBeNull()
      expect(perfilMasLigero(catalogo.perfiles, null)).toBeNull()
      const mezcla = [{ id: 'a', memoriaGb: 1 }, { id: 'x', memoriaGb: 2, experimental: true }, { id: 'b', memoriaGb: 3 }] as never
      expect(perfilMasLigero(mezcla, 'b' as never)).toBe('a')
    })

    it('al montar, si hay un aviso pendiente, sale la pantalla con el motivo', async () => {
      await conAsistenteHecho()
      fijarMotorDetenido(aviso)
      render(<App />)
      expect(await screen.findByText('El motor de IA se ha detenido')).toBeTruthy()
      expect(screen.getByText(aviso.motivo)).toBeTruthy()
    })

    it('el evento abre la pantalla y la escucha se limpia al desmontar', async () => {
      await conAsistenteHecho()
      const { unmount } = render(<App />)
      await boton(/Ajustes/, 3000)
      expect(oyentesMotor()).toBe(1)
      emitirMotorDetenido(aviso)
      expect(await screen.findByText('El motor de IA se ha detenido')).toBeTruthy()
      unmount()
      expect(oyentesMotor()).toBe(0)
    })

    it('Reintentar con éxito vuelve a donde estaba', async () => {
      await conAsistenteHecho()
      fijarMotorDetenido(aviso)
      render(<App />)
      fireEvent.click(await boton('Reintentar'))
      await waitFor(() => expect(screen.queryByText('El motor de IA se ha detenido')).toBeNull())
      expect(await boton(/Ajustes/)).toBeTruthy()
    })

    it('Reintentar con fallo se queda y muestra el error real', async () => {
      await conAsistenteHecho()
      fijarMotorDetenido(aviso)
      fijarErrorReintento('El motor de IA no arranca: falta memoria')
      render(<App />)
      fireEvent.click(await boton('Reintentar'))
      expect((await screen.findByRole('alert')).textContent).toBe('El motor de IA no arranca: falta memoria')
      expect(screen.getByText('El motor de IA se ha detenido')).toBeTruthy()
      expect(await boton('Reintentar')).toHaveProperty('disabled', false)
    })

    it('«Cambiar a un perfil más ligero» lleva a Ajustes con el siguiente perfil elegido, y no sale sin falta de memoria', async () => {
      await conAsistenteHecho()
      fijarMotorDetenido({ ...aviso, sinMemoria: false })
      render(<App />)
      await screen.findByText('El motor de IA se ha detenido')
      expect(screen.queryByRole('button', { name: 'Cambiar a un perfil más ligero' })).toBeNull()
      cleanup()
      fijarMotorDetenido(aviso)
      render(<App />)
      fireEvent.click(await boton('Cambiar a un perfil más ligero'))
      expect((await boton(/^Ligero/)).getAttribute('aria-pressed')).toBe('true')
    })

    it('un aviso en el asistente: Reintentar con éxito sigue en el asistente, y Volver de Ajustes (desde «más ligero») también', async () => {
      await hastaElPerfil()
      emitirMotorDetenido(aviso)
      fireEvent.click(await boton('Reintentar'))
      await waitFor(() => expect(screen.queryByText('El motor de IA se ha detenido')).toBeNull())
      expect(await boton(/^Equilibrado/)).toBeTruthy()
      emitirMotorDetenido(aviso)
      fireEvent.click(await boton('Cambiar a un perfil más ligero'))
      fireEvent.click(await boton('Volver'))
      expect(await boton(/^Equilibrado/)).toBeTruthy()
      expect(screen.queryByRole('button', { name: /Ajustes/ })).toBeNull()
    }, 30000)

    it('un aviso durante un cambio de perfil espera: Ajustes sigue y la pantalla sale al acabar', async () => {
      await conAsistenteHecho()
      render(<App />)
      fireEvent.click(await boton(/Ajustes/))
      fijarRetardoCambioPerfil(300)
      fireEvent.click(await boton(/^Ligero/))
      fireEvent.click(await boton(/^Cambiar/))
      await boton('Pausar')
      emitirMotorDetenido(aviso)
      await new Promise((ok) => setTimeout(ok, 50))
      expect(screen.queryByText('El motor de IA se ha detenido')).toBeNull()
      expect(screen.getByRole('button', { name: 'Pausar' })).toBeTruthy()
      expect(await screen.findByText('El motor de IA se ha detenido', {}, { timeout: 10000 })).toBeTruthy()
    }, 30000)

    it('un aviso durante un cambio que ya no sigue en pie no sale al acabar', async () => {
      await conAsistenteHecho()
      render(<App />)
      fireEvent.click(await boton(/Ajustes/))
      fijarRetardoCambioPerfil(300)
      fireEvent.click(await boton(/^Ligero/))
      fireEvent.click(await boton(/^Cambiar/))
      await boton('Pausar')
      emitirMotorDetenido(aviso)
      fijarMotorDetenido(null)
      await boton(/^Borrar modelos que ya no uso/, 5000)
      await new Promise((ok) => setTimeout(ok, 100))
      expect(screen.queryByText('El motor de IA se ha detenido')).toBeNull()
    }, 30000)

    it('Pausar con un error que no es de cancelación muestra el error real', async () => {
      await conAsistenteHecho()
      render(<App />)
      fireEvent.click(await boton(/Ajustes/))
      fijarRetardoCambioPerfil(300)
      fijarErrorCambioPerfil('El motor de IA no arranca con el perfil nuevo (x).')
      fireEvent.click(await boton(/^Ligero/))
      fireEvent.click(await boton(/^Cambiar/))
      fireEvent.click(await boton('Pausar'))
      expect((await screen.findByRole('alert')).textContent).toContain('no arranca con el perfil nuevo')
      expect(screen.queryByText(/Descarga en pausa|pausad/i)).toBeNull()
    }, 30000)

    it('Copiar informe copia y confirma; si copiar falla deja el texto desplegado', async () => {
      await conAsistenteHecho()
      fijarMotorDetenido(aviso)
      render(<App />)
      fireEvent.click(await boton('Copiar informe'))
      expect(await screen.findByText('Copiado')).toBeTruthy()
      expect(textoCopiado()).toBe(TEXTO_INFORME)
      cleanup()
      fijarErrorCopiar('portapapeles no disponible')
      render(<App />)
      fireEvent.click(await boton('Copiar informe'))
      expect((await screen.findByRole('alert')).textContent).toMatch(/cópialo a mano/)
      expect(screen.getByText(/Tarkor \(informe de ejemplo\)/)).toBeTruthy()
      expect(screen.queryByText('Copiado')).toBeNull()
    })
  })

  it('guarda el progreso para continuar donde se quedó', async () => {
    await hastaElPermiso()
    const guardada = await ejemplo.cargarConfig()
    expect(guardada.consentimientoAceptado).toBe(true)
    expect(guardada.pasoAsistente).toBe(3)
  })
})

/** Entra en la app con el asistente acabado y ese perfil: abre directamente la vista del juego. */
const conJuego = async (perfil: string) => {
  await ejemplo.guardarConfig({ ...configInicial(), consentimientoAceptado: true, permisoAnalisis: true, equipo: await ejemplo.analizarEquipo(), perfil: perfil as never, pasoAsistente: 7, asistenteCompletado: true })
}

describe('calentar el narrador al entrar en el juego (INS-42)', () => {
  it('con el motor parado lo arranca y luego calienta el narrador; con el motor en marcha no lo reinicia', async () => {
    await conJuego('equilibrado')
    const asegurar = vi.spyOn(ejemplo, 'asegurarMotor')
    const calentar = vi.spyOn(ejemplo, 'calentarNarrador')
    render(<App />)
    expect((await screen.findByRole('status')).textContent).toBe('Preparando el narrador…')
    expect((await screen.findByText('El narrador está listo')).getAttribute('role')).toBe('status')
    expect(asegurar).toHaveBeenCalledTimes(1)
    expect(arranquesDelMotor()).toBe(1)
    expect(calentar).toHaveBeenCalledTimes(1)
    expect(asegurar.mock.invocationCallOrder[0]).toBeLessThan(calentar.mock.invocationCallOrder[0])
    cleanup()

    calentar.mockClear()
    render(<App />)
    await screen.findByText('El narrador está listo')
    expect(arranquesDelMotor()).toBe(1)
    expect(calentar).toHaveBeenCalledTimes(1)
  })

  it('calienta una sola vez por entrada, aunque la pantalla se vuelva a pintar', async () => {
    await conJuego('equilibrado')
    const calentar = vi.spyOn(ejemplo, 'calentarNarrador')
    const { rerender } = render(<App />)
    await screen.findByText('El narrador está listo')
    rerender(<App />)
    await act(async () => { await new Promise((ok) => setTimeout(ok, 50)) })
    expect(calentar).toHaveBeenCalledTimes(1)
  })

  it('sin memoria avisa y ofrece el perfil más ligero, que lleva a Ajustes con ese perfil elegido', async () => {
    await conJuego('equilibrado')
    fijarCalentar('sinMemoria')
    render(<App />)
    const aviso = await screen.findByRole('alert')
    expect(aviso.textContent).toMatch(/se quedó sin memoria al cargar el narrador/)
    fireEvent.click(within(aviso).getByRole('button', { name: 'Cambiar a un perfil más ligero' }))
    expect((await boton(/^Ligero/)).getAttribute('aria-pressed')).toBe('true')
  })

  it('sin memoria pero ya en el perfil más ligero, solo dice el motivo, sin botón', async () => {
    await conJuego('minimo')
    fijarCalentar('sinMemoria')
    render(<App />)
    expect(await screen.findByText(/se quedó sin memoria al cargar el narrador/)).toBeTruthy()
    expect(screen.queryByRole('alert')).toBeNull()
    expect(screen.queryByRole('button', { name: 'Cambiar a un perfil más ligero' })).toBeNull()
  })

  it('cualquier otro error es una línea discreta con el motivo, sin aviso ni botón', async () => {
    await conJuego('equilibrado')
    fijarCalentar('error')
    render(<App />)
    const linea = await screen.findByText(/el motor no respondió/)
    // La frase dice qué se pierde (el primer turno tardará más) y deja el motivo del núcleo entre paréntesis.
    expect(linea.textContent).toBe('No se pudo preparar el narrador: el primer turno tardará más. (No se pudo cargar el narrador: el motor no respondió.)')
    expect(linea.className).toMatch(/tenue/)
    expect(screen.queryByRole('alert')).toBeNull()
    expect(screen.queryByRole('button', { name: 'Cambiar a un perfil más ligero' })).toBeNull()
    expect(screen.queryByText('El narrador está listo')).toBeNull()
  })

  it('si el motor no arranca, lo dice en la misma línea discreta y no calienta', async () => {
    await conJuego('equilibrado')
    vi.spyOn(ejemplo, 'asegurarMotor').mockRejectedValue('No se pudo arrancar el motor de IA.')
    const calentar = vi.spyOn(ejemplo, 'calentarNarrador')
    render(<App />)
    expect(await screen.findByText('No se pudo preparar el narrador: el primer turno tardará más. (No se pudo arrancar el motor de IA.)')).toBeTruthy()
    expect(calentar).not.toHaveBeenCalled()
  })

  it('si se sale antes de que conteste el motor, no lo arranca ni calienta', async () => {
    await conJuego('equilibrado')
    vi.spyOn(ejemplo, 'asegurarMotor').mockImplementation(async () => { await new Promise((ok) => setTimeout(ok, 60)) })
    const calentar = vi.spyOn(ejemplo, 'calentarNarrador')
    render(<App />)
    await screen.findByText('Preparando el narrador…')
    cleanup()
    await act(async () => { await new Promise((ok) => setTimeout(ok, 150)) })
    expect(calentar).not.toHaveBeenCalled()
  })

  it('al entrar no usa estadoMotor ni iniciarMotor: el arranque va entero por asegurarMotor, que va en fila en el motor', async () => {
    await conJuego('equilibrado')
    const estado = vi.spyOn(ejemplo, 'estadoMotor')
    const iniciar = vi.spyOn(ejemplo, 'iniciarMotor')
    render(<App />)
    await screen.findByText('El narrador está listo')
    expect(estado).not.toHaveBeenCalled()
    expect(iniciar).not.toHaveBeenCalled()
  })
})

describe('narración de prueba lenta (INS-42)', () => {
  const conComprobacion = async (perfil: string) => {
    await ejemplo.guardarConfig({ ...configInicial(), consentimientoAceptado: true, permisoAnalisis: true, equipo: await ejemplo.analizarEquipo(), perfil: perfil as never, pasoAsistente: 6 })
    render(<App />)
    await screen.findByText(/palabras por segundo/, {}, { timeout: 5000 })
  }
  const SUGERENCIA = 'Tu equipo narra despacio con este perfil: uno más ligero responderá antes'

  it('por debajo de 3 palabras por segundo sugiere un perfil más ligero, y el botón vuelve a elegir perfil', async () => {
    fijarTokensPorSegundo(2)
    await conComprobacion('equilibrado')
    expect(screen.getByText(SUGERENCIA)).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: 'Probar un perfil más ligero' }))
    expect((await boton(/^Equilibrado/)).getAttribute('aria-pressed')).toBe('true')
    expect(screen.getByText(/Cuanta más memoria le dediques/)).toBeTruthy()
  }, 15000)

  it('a una velocidad normal no sugiere nada', async () => {
    await conComprobacion('equilibrado')
    expect(screen.queryByText(SUGERENCIA)).toBeNull()
    expect(screen.queryByRole('button', { name: 'Probar un perfil más ligero' })).toBeNull()
  }, 15000)

  it('el umbral se mide sin redondear: 4 tokens/s son 2,8 palabras/s (se muestra «3») y aun así es lento', async () => {
    fijarTokensPorSegundo(4)
    await conComprobacion('equilibrado')
    expect(screen.getByText(/3 palabras por segundo/)).toBeTruthy()
    expect(screen.getByText(SUGERENCIA)).toBeTruthy()
  }, 15000)

  it('una medida inválida (0 tokens/s) no sugiere nada', async () => {
    fijarTokensPorSegundo(0)
    await conComprobacion('equilibrado')
    expect(screen.queryByText(SUGERENCIA)).toBeNull()
    expect(screen.queryByRole('button', { name: 'Probar un perfil más ligero' })).toBeNull()
  }, 15000)

  it('lenta pero en el perfil más ligero no sugiere nada: no hay a dónde bajar', async () => {
    fijarTokensPorSegundo(2)
    await conComprobacion('minimo')
    expect(screen.queryByText(SUGERENCIA)).toBeNull()
    expect(screen.queryByRole('button', { name: 'Probar un perfil más ligero' })).toBeNull()
  }, 15000)
})

describe('descarga sin red (INS-42)', () => {
  const e = evaluarEjemplo(equipoEjemplo)
  const config = { ...configInicial(), perfil: e.recomendado }
  /** Descarga con esperas de décimas de segundo; `llamadas` guarda cuándo se llamó a `descargarModelos`. */
  const conEsperas = (esperas: number[]) => {
    const llamadas: number[] = []
    const original = ejemplo.descargarModelos
    vi.spyOn(ejemplo, 'descargarModelos').mockImplementation((p) => { llamadas.push(Date.now()); return original(p) })
    render(<Descarga ir={() => {}} config={config} evaluacion={e} actualizar={() => {}} esperas={esperas} />)
    return llamadas
  }

  it('si se pierde la red muestra «Esperando conexión» y reanuda sola, cada vez más espaciada, hasta terminar', async () => {
    fijarSinRed(2)
    const llamadas = conEsperas([0.05, 0.4])
    expect((await screen.findAllByText('Esperando conexión', {}, { timeout: 2000 })).length).toBeGreaterThan(0)
    expect(screen.getByRole('status').textContent).toContain('La descarga seguirá sola cuando vuelva la red')
    expect(screen.queryByRole('alert')).toBeNull()
    expect(screen.getByRole('button', { name: 'Reintentar ahora' })).toBeTruthy()
    fireEvent.click(await boton('Comprobar la instalación', 10000))
    expect(llamadas).toHaveLength(3)
    // La segunda espera (0,4 s) es más larga que la primera (0,05 s).
    expect(llamadas[2] - llamadas[1]).toBeGreaterThanOrEqual(llamadas[1] - llamadas[0] + 250)
    expect(screen.queryByText('Esperando conexión')).toBeNull()
  }, 20000)

  it('Pausar durante la espera cancela el reintento programado', async () => {
    fijarSinRed(1)
    const llamadas = conEsperas([0.2])
    await screen.findAllByText('Esperando conexión', {}, { timeout: 2000 })
    fireEvent.click(screen.getByRole('button', { name: 'Pausar' }))
    expect(await boton('Reanudar')).toBeTruthy()
    expect(screen.queryByText('Esperando conexión')).toBeNull()
    await new Promise((ok) => setTimeout(ok, 500))
    expect(llamadas).toHaveLength(1)
    // Reanudar sí vuelve a intentarlo y termina.
    fireEvent.click(screen.getByRole('button', { name: 'Reanudar' }))
    await boton('Comprobar la instalación', 10000)
    expect(llamadas).toHaveLength(2)
  }, 20000)

  it('«Reintentar ahora» no espera al temporizador', async () => {
    fijarSinRed(1)
    const llamadas = conEsperas([60])
    await screen.findAllByText('Esperando conexión', {}, { timeout: 2000 })
    fireEvent.click(screen.getByRole('button', { name: 'Reintentar ahora' }))
    await boton('Comprobar la instalación', 10000)
    expect(llamadas).toHaveLength(2)
  }, 20000)

  it('un error que no es de red sigue mostrando el error y «Reintentar»', async () => {
    vi.spyOn(ejemplo, 'descargarModelos').mockRejectedValueOnce(new ErrorIa('Tu equipo se ha quedado sin memoria al cargar el modelo.', false, true))
    render(<Descarga ir={() => {}} config={config} evaluacion={e} actualizar={() => {}} esperas={[0.05]} />)
    expect((await screen.findByRole('alert', {}, { timeout: 2000 })).textContent).toBe('Tu equipo se ha quedado sin memoria al cargar el modelo.')
    expect(screen.queryByText('Esperando conexión')).toBeNull()
    expect(screen.queryByRole('status')).toBeNull()
    expect(await boton('Reintentar')).toBeTruthy()
    expect(screen.queryByRole('button', { name: 'Reintentar ahora' })).toBeNull()
  }, 20000)

  describe('la escalera de espera solo baja a 5 s con progreso real', () => {
    const modelos = catalogo.perfiles.find((p) => p.id === config.perfil)!
    const [m0, m1] = [modelos.narrador, modelos.cronista === modelos.narrador ? modelos.embeddings : modelos.cronista]
    const pulling = (modelo: string, hecho: number) => ({ modelo, estado: 'pulling', hecho, total: 1000 })
    const espera = (segundos: RegExp) => screen.findByText(new RegExp(`Reintentando en (${segundos.source}) s`), {}, { timeout: 2000 })
    /** Deja pasar la espera programada y el corte siguiente. */
    const pasar = (ms: number) => act(async () => { vi.advanceTimersByTime(ms) })
    const conRelojFalso = async (prueba: () => Promise<void>) => {
      vi.useFakeTimers({ shouldAdvanceTime: true })
      try { await prueba() } finally { vi.useRealTimers() }
    }

    it('un modelo que ya estaba en disco no cuenta: la segunda espera es de 10 s y la tercera de 20 s', () => conRelojFalso(async () => {
      fijarSinRed(3, [{ modelo: m0, estado: 'success', hecho: 1, total: 1 }])
      render(<Descarga ir={() => {}} config={config} evaluacion={e} actualizar={() => {}} />)
      await espera(/[45]/)
      await pasar(5000)
      await espera(/9|10/)
      await pasar(10000)
      await espera(/19|20/)
    }), 20000)

    it('un progreso repetido tras reintentar no cuenta: la segunda espera es de 10 s', () => conRelojFalso(async () => {
      fijarSinRed(3, [pulling(m0, 100)])
      render(<Descarga ir={() => {}} config={config} evaluacion={e} actualizar={() => {}} />)
      await espera(/[45]/)
      await pasar(5000)
      await espera(/9|10/)
      await pasar(10000)
      await espera(/19|20/)
    }), 20000)

    it('un progreso que sí crece devuelve la espera a 5 s', () => conRelojFalso(async () => {
      fijarSinRed(3, (corte) => [pulling(m1, corte < 2 ? 100 : 200)])
      render(<Descarga ir={() => {}} config={config} evaluacion={e} actualizar={() => {}} />)
      await espera(/[45]/)
      await pasar(5000)
      await espera(/9|10/)
      await pasar(10000)
      await espera(/[45]/)
    }), 20000)
  })
})

describe('autopausa por red al cambiar de perfil y al reparar (INS-42)', () => {
  const e = evaluarEjemplo(equipoEjemplo)
  const config = { ...configInicial(), perfil: e.recomendado }
  const linea = /^Esperando conexión · Reintentando en [45] s\.$/
  /** Deja pasar el tiempo del reloj falso (la espera programada). */
  const pasar = (ms: number) => act(async () => { vi.advanceTimersByTime(ms) })
  const conRelojFalso = async (prueba: () => Promise<void>) => {
    vi.useFakeTimers({ shouldAdvanceTime: true })
    try { await prueba() } finally { vi.useRealTimers() }
  }
  /** Ajustes con el perfil Ligero elegido y el cambio pedido; devuelve lo que recibió `reemplazarConfig`. */
  const cambiarALigero = async () => {
    const reemplazar = vi.fn()
    render(<Ajustes config={config} evaluacion={e} rutas={null} cambiarCarpeta={async () => {}} actualizar={() => {}}
      reemplazarConfig={reemplazar} reanalizar={async () => {}} volver={() => {}} />)
    fireEvent.click(await boton(/^Ligero/))
    fireEvent.click(await boton(/^Cambiar/))
    return reemplazar
  }

  it('cambiar de perfil con un corte de red muestra «Esperando conexión» y termina solo al reintentar', () => conRelojFalso(async () => {
    fijarSinRed(1)
    const cambiar = vi.spyOn(ejemplo, 'cambiarPerfil')
    const reemplazar = await cambiarALigero()
    const estado = await screen.findByRole('status', {}, { timeout: 3000 })
    expect(estado.textContent).toMatch(linea)
    expect(screen.queryByRole('alert')).toBeNull()
    expect(screen.getByRole('button', { name: 'Reintentar ahora' })).toBeTruthy()
    expect(screen.getByRole('button', { name: 'Pausar' })).toBeTruthy()
    // Mientras espera, el cambio sigue en marcha: no se puede cambiar otra vez ni tocar el resto.
    expect(screen.getByRole('button', { name: 'Reparar' })).toHaveProperty('disabled', true)
    expect(cambiar).toHaveBeenCalledTimes(1)
    await pasar(5000)
    await waitFor(() => expect(reemplazar).toHaveBeenCalledTimes(1), { timeout: 10000 })
    expect(cambiar).toHaveBeenCalledTimes(2)
    expect(reemplazar.mock.calls[0][0].perfil).toBe('ligero')
    expect(screen.queryByText(/Esperando conexión/)).toBeNull()
    expect(screen.queryByRole('alert')).toBeNull()
  }), 30000)

  it('«Reintentar ahora» al cambiar de perfil no espera al temporizador', () => conRelojFalso(async () => {
    fijarSinRed(1)
    const cambiar = vi.spyOn(ejemplo, 'cambiarPerfil')
    const reemplazar = await cambiarALigero()
    await screen.findByText(linea, {}, { timeout: 3000 })
    fireEvent.click(screen.getByRole('button', { name: 'Reintentar ahora' }))
    await waitFor(() => expect(reemplazar).toHaveBeenCalledTimes(1), { timeout: 10000 })
    expect(cambiar).toHaveBeenCalledTimes(2)
  }), 30000)

  it('Reparar con un corte de red muestra «Esperando conexión» y termina sola al reintentar', () => conRelojFalso(async () => {
    fijarSinRed(1)
    const reparar = vi.spyOn(ejemplo, 'reparar')
    render(<Reparar />)
    fireEvent.click(await boton('Reparar'))
    const estado = await screen.findByRole('status', {}, { timeout: 3000 })
    expect(estado.textContent).toMatch(linea)
    expect(screen.queryByRole('alert')).toBeNull()
    expect(screen.getByRole('button', { name: 'Reintentar ahora' })).toBeTruthy()
    expect(screen.getByRole('button', { name: 'Cancelar' })).toBeTruthy()
    expect(reparar).toHaveBeenCalledTimes(1)
    await pasar(5000)
    expect(await screen.findByText(/^Todo estaba en orden/, {}, { timeout: 10000 })).toBeTruthy()
    expect(reparar).toHaveBeenCalledTimes(2)
    expect(screen.queryByText(/Esperando conexión/)).toBeNull()
    expect(await boton('Reparar')).toHaveProperty('disabled', false)
  }), 30000)

  it('mientras Reparar espera la red, Volver, Volver a analizar y el uso del procesador están desactivados', () => conRelojFalso(async () => {
    fijarSinRed(1)
    render(<Ajustes config={config} evaluacion={e} rutas={null} cambiarCarpeta={async () => {}} actualizar={() => {}}
      reemplazarConfig={vi.fn()} reanalizar={async () => {}} volver={() => {}} />)
    fireEvent.click(await boton('Reparar'))
    await screen.findByText(linea, {}, { timeout: 3000 })
    expect(screen.getByRole('button', { name: 'Volver' })).toHaveProperty('disabled', true)
    expect(screen.getByRole('button', { name: 'Volver a analizar mi equipo' })).toHaveProperty('disabled', true)
    expect(screen.getByRole('button', { name: 'Alto' })).toHaveProperty('disabled', true)
    expect(screen.getByRole('button', { name: 'Moderado' })).toHaveProperty('disabled', true)
    // Al terminar la reparación se vuelve a poder salir.
    await pasar(5000)
    expect(await screen.findByText(/^Todo estaba en orden/, {}, { timeout: 10000 })).toBeTruthy()
    expect(screen.getByRole('button', { name: 'Volver' })).toHaveProperty('disabled', false)
    expect(screen.getByRole('button', { name: 'Alto' })).toHaveProperty('disabled', false)
  }), 30000)

  it('mientras Reparar espera la red en la Comprobación, Reintentar y el perfil más ligero están desactivados', async () => {
    await hastaElPerfil()
    fireEvent.click(await boton(/^Descargar/))
    fijarModelosDanados(true)
    fireEvent.click(await boton('Comprobar la instalación', 10000))
    await screen.findByRole('alert', {}, { timeout: 3000 })
    expect(await boton('Reintentar')).toHaveProperty('disabled', false)
    fijarSinRed(1)
    fireEvent.click(await boton('Reparar'))
    await screen.findByText(/^Esperando conexión/, {}, { timeout: 3000 })
    expect(screen.getByRole('button', { name: 'Reintentar' })).toHaveProperty('disabled', true)
    expect(screen.getByRole('button', { name: 'Probar un perfil más ligero' })).toHaveProperty('disabled', true)
  }, 20000)

  it('Pausar durante la espera del cambio de perfil cancela el reintento', () => conRelojFalso(async () => {
    fijarSinRed(1)
    const cambiar = vi.spyOn(ejemplo, 'cambiarPerfil')
    const reemplazar = await cambiarALigero()
    await screen.findByText(linea, {}, { timeout: 3000 })
    fireEvent.click(screen.getByRole('button', { name: 'Pausar' }))
    expect(await screen.findByText(/^Cambio pausado/)).toBeTruthy()
    expect(screen.queryByText(/Esperando conexión/)).toBeNull()
    expect(screen.queryByRole('button', { name: 'Reintentar ahora' })).toBeNull()
    expect(screen.getByRole('button', { name: /^Cambiar/ })).toHaveProperty('disabled', false)
    await pasar(70000)
    expect(cambiar).toHaveBeenCalledTimes(1)
    expect(reemplazar).not.toHaveBeenCalled()
  }), 30000)

  it('Cancelar durante la espera de Reparar cancela el reintento', () => conRelojFalso(async () => {
    fijarSinRed(1)
    const reparar = vi.spyOn(ejemplo, 'reparar')
    render(<Reparar />)
    fireEvent.click(await boton('Reparar'))
    await screen.findByText(linea, {}, { timeout: 3000 })
    fireEvent.click(screen.getByRole('button', { name: 'Cancelar' }))
    expect(await screen.findByText(/^Reparación cancelada/)).toBeTruthy()
    expect(screen.queryByText(/Esperando conexión/)).toBeNull()
    expect(screen.queryByRole('button', { name: 'Reintentar ahora' })).toBeNull()
    expect(screen.getByRole('button', { name: 'Reparar' })).toHaveProperty('disabled', false)
    await pasar(70000)
    expect(reparar).toHaveBeenCalledTimes(1)
  }), 30000)

  it('un error que no es de red al cambiar de perfil se muestra como error, sin espera', () => conRelojFalso(async () => {
    const cambiar = vi.spyOn(ejemplo, 'cambiarPerfil').mockRejectedValue(new ErrorIa('El motor de IA no arranca con el perfil nuevo (x); sigue el perfil de antes.'))
    await cambiarALigero()
    expect((await screen.findByRole('alert', {}, { timeout: 3000 })).textContent).toContain('sigue el perfil de antes')
    expect(screen.queryByRole('status')).toBeNull()
    expect(screen.queryByText(/Esperando conexión/)).toBeNull()
    expect(screen.queryByRole('button', { name: 'Reintentar ahora' })).toBeNull()
    expect(screen.getByRole('button', { name: /^Cambiar/ })).toHaveProperty('disabled', false)
    await pasar(70000)
    expect(cambiar).toHaveBeenCalledTimes(1)
  }), 30000)

  it('un error que no es de red al reparar se muestra como error, sin espera', () => conRelojFalso(async () => {
    const reparar = vi.spyOn(ejemplo, 'reparar').mockRejectedValue(new ErrorIa('No se pudo reinstalar el motor: disco lleno.'))
    render(<Reparar />)
    fireEvent.click(await boton('Reparar'))
    expect((await screen.findByRole('alert', {}, { timeout: 3000 })).textContent).toBe('No se pudo reinstalar el motor: disco lleno.')
    expect(screen.queryByText(/Esperando conexión/)).toBeNull()
    await pasar(70000)
    expect(reparar).toHaveBeenCalledTimes(1)
  }), 30000)

  it('al salir de Ajustes durante la espera no queda ningún reintento vivo', () => conRelojFalso(async () => {
    fijarSinRed(1)
    const cambiar = vi.spyOn(ejemplo, 'cambiarPerfil')
    await cambiarALigero()
    await screen.findByText(linea, {}, { timeout: 3000 })
    cleanup()
    await pasar(70000)
    expect(cambiar).toHaveBeenCalledTimes(1)
  }), 30000)

  /** Una llamada que la prueba resuelve a mano: `fallar` la hace fallar como un corte de red. */
  const llamadaEnVuelo = () => {
    let fallar: () => void = () => {}
    const promesa = new Promise<never>((_, rechazar) => { fallar = () => rechazar(new ErrorIa('Sin conexión.', true)) })
    return { promesa, fallar }
  }

  it('un corte de red que llega con Reparar ya desmontada no programa ningún reintento', () => conRelojFalso(async () => {
    const { promesa, fallar } = llamadaEnVuelo()
    const reparar = vi.spyOn(ejemplo, 'reparar').mockImplementation(() => promesa)
    render(<Reparar />)
    fireEvent.click(await boton('Reparar'))
    await waitFor(() => expect(reparar).toHaveBeenCalledTimes(1))
    cleanup()
    await act(async () => { fallar(); await promesa.catch(() => {}) })
    await pasar(70000)
    expect(reparar).toHaveBeenCalledTimes(1)
  }), 30000)

  it('un corte de red que llega con Ajustes ya desmontada no reintenta el cambio de perfil', () => conRelojFalso(async () => {
    const { promesa, fallar } = llamadaEnVuelo()
    const cambiar = vi.spyOn(ejemplo, 'cambiarPerfil').mockImplementation(() => promesa)
    await cambiarALigero()
    await waitFor(() => expect(cambiar).toHaveBeenCalledTimes(1))
    cleanup()
    await act(async () => { fallar(); await promesa.catch(() => {}) })
    await pasar(70000)
    expect(cambiar).toHaveBeenCalledTimes(1)
  }), 30000)

  it('Pausar y que la llamada falle a la vez con un corte de red deja «pausado», sin reintento', () => conRelojFalso(async () => {
    const { promesa, fallar } = llamadaEnVuelo()
    const cambiar = vi.spyOn(ejemplo, 'cambiarPerfil').mockImplementation(() => promesa)
    const reemplazar = await cambiarALigero()
    await waitFor(() => expect(cambiar).toHaveBeenCalledTimes(1))
    fireEvent.click(await boton('Pausar'))
    await act(async () => { fallar(); await promesa.catch(() => {}) })
    expect(await screen.findByText(/^Cambio pausado/)).toBeTruthy()
    expect(screen.queryByText(/Esperando conexión/)).toBeNull()
    expect(screen.queryByRole('alert')).toBeNull()
    await pasar(70000)
    expect(cambiar).toHaveBeenCalledTimes(1)
    expect(reemplazar).not.toHaveBeenCalled()
  }), 30000)

  it('mientras Reparar espera la red, Ajustes no deja cambiar de perfil ni tocar las tarjetas, y vuelve a dejar al cancelar', () => conRelojFalso(async () => {
    fijarSinRed(1)
    render(<Ajustes config={config} evaluacion={e} rutas={null} cambiarCarpeta={async () => {}} actualizar={() => {}}
      reemplazarConfig={vi.fn()} reanalizar={async () => {}} volver={() => {}} />)
    fireEvent.click(await boton(/^Ligero/))
    expect(await boton(/^Cambiar/)).toHaveProperty('disabled', false)
    fireEvent.click(await boton('Reparar'))
    await screen.findByText(linea, {}, { timeout: 3000 })
    expect(screen.getByRole('button', { name: /^Cambiar/ })).toHaveProperty('disabled', true)
    expect(screen.getByRole('button', { name: /^Ligero/ })).toHaveProperty('disabled', true)
    fireEvent.click(screen.getByRole('button', { name: 'Cancelar' }))
    await screen.findByText(/^Reparación cancelada/)
    expect(screen.getByRole('button', { name: /^Cambiar/ })).toHaveProperty('disabled', false)
    expect(screen.getByRole('button', { name: /^Ligero/ })).toHaveProperty('disabled', false)
  }), 30000)
})
