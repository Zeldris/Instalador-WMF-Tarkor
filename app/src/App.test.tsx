import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'
import App from './App'
import { perfilMasLigero } from './tipos'
import { catalogo } from './catalogo'
import { ejemplo, configInicial, fijarDiscoLibreIa, fijarErrorCambioPerfil, fijarRetardoCambioPerfil, fijarErrorCarpetaIa, fijarModelosDanados, fijarUsoIa, reiniciarCarpetaIa, reiniciarModelos, emitirMotorDetenido, fijarErrorCopiar, fijarErrorReintento, fijarMotorDetenido, oyentesMotor, reiniciarMotorDetenido, textoCopiado, TEXTO_INFORME } from './ejemplo'

afterEach(async () => {
  cleanup()
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
    expect(await boton('Descargar 6 GB')).toBeTruthy()

    fireEvent.click(await boton(/^Máximo/))
    expect(await boton('Descargar 9,4 GB')).toBeTruthy()

    // Ultra no cabe en la Deck, pero se puede elegir: tras el aviso hay que confirmar.
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
    fijarDiscoLibreIa(8)
    await hastaElPerfil()
    fireEvent.click(await boton(/^Máximo/))
    const sin = await screen.findAllByText(/libres 8 GB/)
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
    expect((await ejemplo.cargarConfig()).modelosDescargados).toEqual(['qwen2.5:7b', 'qwen2.5:1.5b-instruct', 'nomic-embed-text'])
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
