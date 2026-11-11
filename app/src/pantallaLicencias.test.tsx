import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { catalogo } from './catalogo'
import { fijarErrorCopiar, textoCopiado } from './ejemplo'
import { Licencias, modelosPorLicencia, textosLicencia } from './pantallaLicencias'
import { licencias as t } from './textos'

afterEach(() => {
  cleanup()
  fijarErrorCopiar(null)
})

describe('Licencias y avisos', () => {
  it('cada licencia del catálogo tiene nombre visible y texto completo', () => {
    // Un modelo nuevo con otra licencia no sale sin su texto (docs/08: la licencia se incluye completa).
    for (const m of Object.values(catalogo.modelos)) {
      expect(t.nombres[m.licencia], m.licencia).toBeTruthy()
      expect(textosLicencia[m.licencia]?.length, m.licencia).toBeGreaterThan(500)
    }
    expect(textosLicencia['Llama-3.1-Community']).toContain('LLAMA 3.1 COMMUNITY LICENSE AGREEMENT')
    expect(textosLicencia['Apache-2.0']).toContain('Apache License')
    expect(textosLicencia.MIT).toContain('Copyright (c) Ollama')
  })

  it('agrupa todos los modelos del catálogo por licencia, sin repetir ninguno', () => {
    const listados = modelosPorLicencia().flatMap(([, ms]) => ms)
    expect(listados.sort()).toEqual(Object.keys(catalogo.modelos).sort())
    expect(modelosPorLicencia().find(([l]) => l === 'Llama-3.1-Community')?.[1]).toEqual(['llama3.1:8b'])
  })

  it('muestra «Built with Llama», el aviso de Meta y la política de uso, y copia su enlace', async () => {
    const volver = vi.fn()
    render(<Licencias volver={volver} />)
    expect(screen.getByRole('heading', { name: 'Built with Llama' })).toBeTruthy()
    expect(screen.getByText(t.avisoLlama)).toBeTruthy()
    expect(t.avisoLlama).toBe('Llama 3.1 is licensed under the Llama 3.1 Community License, Copyright © Meta Platforms, Inc. All Rights Reserved.')
    expect(screen.getByText('https://llama.meta.com/llama3_1/use-policy')).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: 'Copiar enlace' }))
    expect(await screen.findByText('Copiado')).toBeTruthy()
    expect(textoCopiado()).toBe('https://llama.meta.com/llama3_1/use-policy')
    fireEvent.click(screen.getByRole('button', { name: 'Volver' }))
    expect(volver).toHaveBeenCalledOnce()
  })

  it('si no se puede copiar el enlace, dice que se copie a mano', async () => {
    fijarErrorCopiar('portapapeles no disponible')
    render(<Licencias volver={() => {}} />)
    fireEvent.click(screen.getByRole('button', { name: 'Copiar enlace' }))
    expect((await screen.findByRole('alert')).textContent).toBe(t.errorCopiar)
    expect(screen.queryByText('Copiado')).toBeNull()
  })

  it('cada licencia tiene su texto completo desplegable', () => {
    render(<Licencias volver={() => {}} />)
    for (const nombre of ['Licencia MIT', 'Llama 3.1 Community License', 'Apache License 2.0']) {
      expect(screen.getByText(`Texto completo de la ${nombre}`)).toBeTruthy()
    }
  })
})
