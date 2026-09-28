import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'
import App from './App'
import { ejemplo, configInicial } from './ejemplo'

afterEach(async () => {
  cleanup()
  await ejemplo.guardarConfig(configInicial())
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

    // Ultra no cabe en la Deck: deshabilitado salvo que se pidan los no recomendados.
    expect(await boton(/^Ultra/)).toHaveProperty('disabled', true)
    expect(screen.getByText('Experimental')).toBeTruthy()
  })

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

  it('guarda el progreso para continuar donde se quedó', async () => {
    await hastaElPermiso()
    const guardada = await ejemplo.cargarConfig()
    expect(guardada.consentimientoAceptado).toBe(true)
    expect(guardada.pasoAsistente).toBe(3)
  })
})
