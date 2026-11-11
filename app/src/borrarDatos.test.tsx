import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'
import { BorrarDatos } from './componentes'
import { Ajustes } from './pantallas'
import { appSeHaCerrado, borrados, configInicial, equipoEjemplo, evaluarEjemplo, fijarErrorBorrado, fijarPlataforma, reiniciarBorrado } from './ejemplo'

afterEach(() => {
  cleanup()
  reiniciarBorrado()
})

const boton = (nombre: string | RegExp) => screen.findByRole('button', { name: nombre }, { timeout: 1000 })

function ajustes() {
  render(<Ajustes config={configInicial()} evaluacion={evaluarEjemplo(equipoEjemplo)} rutas={null} cambiarCarpeta={async () => {}}
    actualizar={() => {}} reemplazarConfig={() => {}} reanalizar={async () => {}} volver={() => {}} />)
}

async function abrirDialogo() {
  ajustes()
  fireEvent.click(await boton('Borrar datos del juego'))
  return screen.findByRole('dialog', { name: 'Borrar datos del juego' })
}

describe('Ajustes → Borrar datos del juego (INS-45)', () => {
  it('fuera de Linux no hay botón', async () => {
    fijarPlataforma('windows')
    ajustes()
    await boton('Reparar')
    await new Promise((r) => setTimeout(r, 50))
    expect(screen.queryByRole('button', { name: 'Borrar datos del juego' })).toBeNull()
  })

  it('el diálogo trae dos casillas sin marcar con el tamaño de la IA, y Borrar espera a que se marque una', async () => {
    await abrirDialogo()
    const partidas = screen.getByRole('checkbox', { name: 'Borrar también mis partidas guardadas' })
    const ia = await screen.findByRole('checkbox', { name: 'Borrar también el motor de IA y los modelos (9,6 GB)' })
    expect(partidas).toHaveProperty('checked', false)
    expect(ia).toHaveProperty('checked', false)
    const borrar = screen.getByRole('button', { name: 'Borrar' })
    expect(borrar).toHaveProperty('disabled', true)
    fireEvent.click(ia)
    expect(borrar).toHaveProperty('disabled', false)
    fireEvent.click(ia)
    expect(borrar).toHaveProperty('disabled', true)
  })

  it('Cancelar cierra el diálogo sin borrar', async () => {
    await abrirDialogo()
    fireEvent.click(screen.getByRole('button', { name: 'Cancelar' }))
    expect(screen.queryByRole('dialog')).toBeNull()
    expect(borrados).toEqual([])
  })

  it('Borrar llama con las casillas marcadas y enseña la pantalla final, que cierra la app', async () => {
    await abrirDialogo()
    fireEvent.click(screen.getByRole('checkbox', { name: 'Borrar también mis partidas guardadas' }))
    fireEvent.click(screen.getByRole('button', { name: 'Borrar' }))
    expect(await screen.findByText('Datos borrados. Ya puedes borrar el archivo .AppImage o desinstalar el paquete .deb.')).toBeTruthy()
    expect(borrados).toEqual([{ partidas: true, ia: false }])
    expect(screen.queryByRole('button', { name: 'Reparar' })).toBeNull()
    expect(appSeHaCerrado()).toBe(false)
    fireEvent.click(screen.getByRole('button', { name: 'Cerrar Tarkor' }))
    await new Promise((r) => setTimeout(r, 0))
    expect(appSeHaCerrado()).toBe(true)
  })

  it('con otra operación en curso, Borrar se desactiva aunque haya una casilla marcada', async () => {
    const { rerender } = render(<BorrarDatos desactivado={false} alBorrar={() => {}} />)
    fireEvent.click(await boton('Borrar datos del juego'))
    fireEvent.click(screen.getByRole('checkbox', { name: 'Borrar también mis partidas guardadas' }))
    expect(screen.getByRole('button', { name: 'Borrar' })).toHaveProperty('disabled', false)
    rerender(<BorrarDatos desactivado alBorrar={() => {}} />)
    expect(screen.getByRole('button', { name: 'Borrar' })).toHaveProperty('disabled', true)
  })

  it('si borrar falla, enseña el error y no la pantalla final', async () => {
    fijarErrorBorrado('No se pudo borrar /x: permiso denegado')
    await abrirDialogo()
    fireEvent.click(screen.getByRole('checkbox', { name: /^Borrar también el motor de IA/ }))
    fireEvent.click(screen.getByRole('button', { name: 'Borrar' }))
    expect((await screen.findByRole('alert')).textContent).toContain('permiso denegado')
    expect(screen.queryByText(/Ya puedes borrar el archivo/)).toBeNull()
    expect(screen.getByRole('button', { name: 'Borrar' })).toHaveProperty('disabled', false)
  })
})
