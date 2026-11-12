import { describe, expect, it } from 'vitest'
import nsi from '../src-tauri/windows/installer.nsi?raw'
import { borrarDatos } from './textos'

// Las casillas del desinstalador de Windows (`INS-44`) dicen lo mismo que «Borrar datos del juego» (`INS-45`):
// la plantilla NSIS no puede importar `textos.ts`, así que este test ata los dos sitios.
describe('casillas del desinstalador de Windows', () => {
  it('la de las partidas es la de textos.ts', () => {
    expect(nsi).toContain(`w "${borrarDatos.partidas}"`)
  })
  it('la de la IA, sin tamaño y con él ($8), es la de textos.ts', () => {
    expect(nsi).toContain(`StrCpy $9 "${borrarDatos.ia('')}"`)
    expect(nsi).toContain(`StrCpy $9 "${borrarDatos.ia('$8')}"`)
  })
})
