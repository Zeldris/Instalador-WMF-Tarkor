import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'
import App from './App'
import { ejemplo, configInicial } from './ejemplo'

afterEach(async () => {
  cleanup()
  await ejemplo.guardarConfig(configInicial())
})

const boton = (nombre: string | RegExp) => screen.findByRole('button', { name: nombre })

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
    expect(await boton('Descargar 9 GB')).toBeTruthy()
  })

  it('eligiendo a mano no hay medidor y parte de Ligero', async () => {
    await hastaElPermiso()
    fireEvent.click(await boton('Prefiero elegir a mano'))
    const ligero = await boton(/^Ligero/)
    expect(ligero.getAttribute('aria-pressed')).toBe('true')
    expect(screen.queryByText(/Tu equipo puede dedicar/)).toBeNull()
    expect(screen.queryByText('Recomendado')).toBeNull()
  })

  it('guarda el progreso para continuar donde se quedó', async () => {
    await hastaElPermiso()
    const guardada = await ejemplo.cargarConfig()
    expect(guardada.consentimientoAceptado).toBe(true)
    expect(guardada.pasoAsistente).toBe(3)
  })
})
