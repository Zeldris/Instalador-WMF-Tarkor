const numero = new Intl.NumberFormat('es-ES', { maximumFractionDigits: 1 })

/** "10,5" — cifras con un decimal como mucho, en formato español. */
export const fmt = (n: number) => numero.format(n)

/** Megas a gigas redondeando al entero ("16" para 16 095 MB). */
export const gbDeMb = (mb: number) => numero.format(Math.round(mb / 1024))
