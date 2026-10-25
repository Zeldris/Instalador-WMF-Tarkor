import { describe, expect, it } from 'vitest'
import { fraseUso } from './textos'

describe('fraseUso', () => {
  it('sin nada cargado dice que se carga al narrar', () => {
    expect(fraseUso(null)).toBe('Se carga al narrar el primer turno')
  })
  it('todo en la gráfica, todo en el procesador y repartida', () => {
    expect(fraseUso(100)).toBe('La IA usa la gráfica al 100 %')
    expect(fraseUso(0)).toBe('La IA va en el procesador')
    expect(fraseUso(60)).toBe('Repartida: 60 % gráfica, 40 % procesador (va más lenta)')
  })
  it('redondea y acota: 99,6 % es 100 y -3 es 0', () => {
    expect(fraseUso(99.6)).toBe('La IA usa la gráfica al 100 %')
    expect(fraseUso(-3)).toBe('La IA va en el procesador')
    expect(fraseUso(59.6)).toBe('Repartida: 60 % gráfica, 40 % procesador (va más lenta)')
  })
})
