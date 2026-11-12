import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { catalogo } from './catalogo'
import { ejemplo, fijarErrorCopiar, textoCopiado } from './ejemplo'
import { LICENCIA_LLAMA, Licencias, LicenciasDeTerceros, modelosPorLicencia, textosLicencia } from './pantallaLicencias'
import type { LicenciasTerceros } from './tipos'
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
    expect(textosLicencia[LICENCIA_LLAMA]).toContain('LLAMA 3.1 COMMUNITY LICENSE AGREEMENT')
    expect(textosLicencia['Apache-2.0']).toContain('Apache License')
    expect(textosLicencia.MIT).toContain('Copyright (c) Ollama')
  })

  it('agrupa todos los modelos del catálogo por licencia, sin repetir ninguno', () => {
    const listados = modelosPorLicencia(catalogo).flatMap(([, ms]) => ms)
    expect(listados.sort()).toEqual(Object.keys(catalogo.modelos).sort())
    expect(modelosPorLicencia(catalogo).find(([l]) => l === LICENCIA_LLAMA)?.[1]).toEqual(['llama3.1:8b'])
  })

  it('muestra «Built with Llama», el aviso de Meta y la política de uso, y copia su enlace', async () => {
    const volver = vi.fn()
    render(<Licencias volver={volver} />)
    expect(await screen.findByRole('heading', { name: 'Built with Llama' })).toBeTruthy()
    expect(screen.getByText('Los perfiles Equilibrado y Máximo usan Llama 3.1, de Meta.')).toBeTruthy()
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
    fireEvent.click(await screen.findByRole('button', { name: 'Copiar enlace' }))
    expect((await screen.findByRole('alert')).textContent).toBe(t.errorCopiar)
    expect(screen.queryByText('Copiado')).toBeNull()
  })

  it('usa el catálogo que cargó el núcleo, no el incrustado', async () => {
    const ajeno = structuredClone(catalogo)
    ajeno.modelos['llama3.1:8b'].licencia = 'Apache-2.0'
    const espia = vi.spyOn(ejemplo, 'catalogo').mockResolvedValue(ajeno)
    render(<Licencias volver={() => {}} />)
    await screen.findByText('Texto completo de la Apache License 2.0')
    expect(screen.queryByRole('heading', { name: 'Built with Llama' })).toBeNull()
    espia.mockRestore()
  })

  it('cada licencia tiene su texto completo desplegable', async () => {
    render(<Licencias volver={() => {}} />)
    await screen.findByText('Texto completo de la Llama 3.1 Community License')
    for (const nombre of ['Licencia MIT', 'Llama 3.1 Community License', 'Apache License 2.0']) {
      expect(screen.getByText(`Texto completo de la ${nombre}`)).toBeTruthy()
    }
  })
})

describe('Licencias de terceros', () => {
  const datos: LicenciasTerceros = {
    grupos: [
      {
        licencia: 'MIT',
        paquetes: [
          { nombre: 'react', version: '19.3.0', ecosistema: 'npm' },
          { nombre: 'serde', version: '1.0.0', ecosistema: 'rust' },
          { nombre: 'tokio', version: '1.2.3', ecosistema: 'rust' },
        ],
        textos: [
          { texto: 'MIT Copyright (c) Meta', paquetes: [0] },
          { texto: 'MIT Copyright (c) Serde y Tokio', paquetes: [1, 2] },
        ],
      },
      { licencia: 'Zlib', paquetes: [{ nombre: 'adler32', version: '1.0.0', ecosistema: 'rust' }], textos: [{ texto: 'Texto Zlib', paquetes: [0] }] },
    ],
  }

  it('agrupa por licencia y dice cuántos paquetes usa cada una', () => {
    render(<LicenciasDeTerceros datos={datos} />)
    expect(screen.getByRole('heading', { name: t.terceros })).toBeTruthy()
    expect(screen.getByText(t.tercerosResumen(3))).toBeTruthy()
    expect(screen.getByText(t.tercerosResumen(1))).toBeTruthy()
    expect(screen.getByText('MIT')).toBeTruthy()
    expect(screen.getByText('Zlib')).toBeTruthy()
    // Cerrados, no pintan sus paquetes ni sus textos.
    expect(screen.queryByText('react 19.3.0')).toBeNull()
  })

  it('al desplegar un grupo enseña sus paquetes con versión y cada texto una vez, con quién lo usa', () => {
    render(<LicenciasDeTerceros datos={datos} />)
    const grupo = screen.getByText('MIT').closest('details') as HTMLDetailsElement
    grupo.open = true
    fireEvent(grupo, new Event('toggle'))
    expect(screen.getByText('react 19.3.0')).toBeTruthy()
    expect(screen.getByText('serde 1.0.0')).toBeTruthy()
    expect(screen.getByText('tokio 1.2.3')).toBeTruthy()
    expect(screen.getByText('MIT Copyright (c) Meta')).toBeTruthy()
    expect(screen.getByText('MIT Copyright (c) Serde y Tokio').tagName).toBe('PRE')
    expect(screen.getByText(`${t.tercerosUsadoPor(2)}: serde, tokio`)).toBeTruthy()
    // El otro grupo sigue cerrado.
    expect(screen.queryByText('Texto Zlib')).toBeNull()
  })

  it('sin datos dice en una línea que no se generaron, y no enseña grupos', () => {
    render(<LicenciasDeTerceros datos={null} />)
    expect(screen.getByText(t.tercerosSin)).toBeTruthy()
    expect(document.querySelector('details')).toBeNull()
  })

  it('la página de licencias incluye la sección (sin el archivo generado, la línea discreta)', async () => {
    render(<Licencias volver={() => {}} />)
    expect(await screen.findByRole('heading', { name: t.terceros })).toBeTruthy()
  })
})
