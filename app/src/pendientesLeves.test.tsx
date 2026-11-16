// INS-68: pendientes leves del frontal (lista de modelos, fila de fallo de la Comprobación, «Copiar informe», ejemplo sin perfiles).
import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import App from './App'
import { catalogo, descargaGb, modelosDe } from './catalogo'
import { CopiarInforme } from './componentes'
import { configInicial, ejemplo, equipoEjemplo, evaluarEjemplo, TEXTO_INFORME } from './ejemplo'

afterEach(async () => {
  cleanup()
  vi.restoreAllMocks()
  await ejemplo.guardarConfig(configInicial())
})

describe('modelosDe (INS-68)', () => {
  it('da los modelos distintos de cada perfil, y la descarga suma cada uno una vez', () => {
    for (const p of catalogo.perfiles) {
      const modelos = modelosDe(p)
      expect(new Set(modelos).size).toBe(modelos.length)
      expect(modelos).toContain(p.narrador)
      expect(modelos).toContain(p.embeddings)
      expect(descargaGb(p)).toBeCloseTo(modelos.reduce((a, m) => a + catalogo.modelos[m].descargaGb, 0))
    }
    expect(modelosDe({ ...catalogo.perfiles[0], narrador: 'a', cronista: 'a', sugerencias: 'a', embeddings: 'b' })).toEqual(['a', 'b'])
  })
})

describe('fila de fallo de la Comprobación (INS-68)', () => {
  const conFallo = async (perfil: string) => {
    vi.spyOn(ejemplo, 'comprobar').mockImplementation(async (id) => {
      if (id === 'motor') throw 'El motor no responde.'
      return { resultado: 'ok', detalle: 'Correcto.' }
    })
    await ejemplo.guardarConfig({ ...configInicial(), consentimientoAceptado: true, permisoAnalisis: true, equipo: await ejemplo.analizarEquipo(), perfil, pasoAsistente: 6 })
    render(<App />)
    await screen.findByText('El motor no responde.', {}, { timeout: 3000 })
  }

  it('sin un perfil más ligero, no ofrece «Probar un perfil más ligero»', async () => {
    await conFallo('minimo')
    expect(screen.getByRole('button', { name: 'Reintentar' })).toBeTruthy()
    expect(screen.queryByRole('button', { name: 'Probar un perfil más ligero' })).toBeNull()
  })

  it('con uno, lo ofrece y deja elegido el perfil más ligero, no el actual', async () => {
    await conFallo('equilibrado')
    fireEvent.click(screen.getByRole('button', { name: 'Probar un perfil más ligero' }))
    expect((await screen.findByRole('button', { name: /^Ligero/ })).getAttribute('aria-pressed')).toBe('true')
    expect((await ejemplo.cargarConfig()).perfil).toBe('ligero')
  })
})

describe('CopiarInforme (INS-68)', () => {
  it('pide el informe cada vez, y «Copiar» no oculta el texto desplegado mientras carga', async () => {
    let n = 0
    const informe = vi.spyOn(ejemplo, 'informe').mockImplementation(async () => {
      n++
      await new Promise((ok) => setTimeout(ok, 80))
      return `${TEXTO_INFORME} #${n}`
    })
    render(<CopiarInforme />)
    fireEvent.click(screen.getByRole('button', { name: 'Ver detalles' }))
    expect(await screen.findByText(/#1$/)).toBeTruthy()
    expect(informe).toHaveBeenCalledTimes(1)
    fireEvent.click(screen.getByRole('button', { name: 'Copiar informe' }))
    // Mientras llega el informe nuevo, el texto anterior sigue a la vista.
    expect(screen.getByText(/#1$/)).toBeTruthy()
    expect(await screen.findByText(/#2$/)).toBeTruthy()
    expect(informe).toHaveBeenCalledTimes(2)
    fireEvent.click(await screen.findByRole('button', { name: 'Copiar informe' }))
    expect(await screen.findByText(/#3$/)).toBeTruthy()
    expect(informe).toHaveBeenCalledTimes(3)
  })
})

describe('ejemplo sin perfiles (INS-68)', () => {
  it('evaluar con el catálogo sin perfiles no se cae', () => {
    const antes = catalogo.perfiles
    ;(catalogo as { perfiles: typeof antes }).perfiles = []
    try {
      expect(evaluarEjemplo(equipoEjemplo).perfiles).toEqual([])
      expect(evaluarEjemplo(null).perfiles).toEqual([])
    } finally {
      ;(catalogo as { perfiles: typeof antes }).perfiles = antes
    }
  })
})
