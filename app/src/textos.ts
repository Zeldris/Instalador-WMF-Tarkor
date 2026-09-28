// Todo el texto visible del asistente, en un único sitio para revisarlo de una vez
// (docs/11-diseno-del-frontal.md, "Implementación").

import { rangoDescarga } from './catalogo'

const rango = rangoDescarga()

export const pasos = ['Bienvenida', 'Qué se instala', 'Tu equipo', 'Perfil', 'Descarga', 'Comprobación', 'Listo']

export const comun = {
  marca: 'TARKOR',
  subtitulo: 'Preparación del primer arranque',
  pie: 'Todo se guarda en tu equipo',
  atras: 'Atrás',
  continuar: 'Continuar',
}

export const bienvenida = {
  titulo: 'Bienvenido a Tarkor',
  lead: 'Antes de jugar vamos a preparar el motor de IA que narra tus partidas. Se ejecuta entero en tu equipo, así que primero hay que ajustarlo a lo que tu equipo puede mover.',
  pasos: [
    ['Te contamos qué se instala', 'y qué no hace Tarkor nunca.'],
    ['Revisamos tu equipo', 'si nos das permiso, para recomendarte un perfil.'],
    ['Descargamos lo necesario:', `entre ${rango} GB según el perfil.`],
    ['Comprobamos que todo funciona', 'con una narración de prueba.'],
  ],
  duracion: 'Tardarás unos minutos, más lo que tarde la descarga. Si cierras a medias, continuarás donde lo dejaste.',
  contenido: 'Contiene violencia de fantasía. Recomendado a partir de 16 años.',
  accion: 'Empezar',
}

export const queSeInstala = {
  titulo: 'Qué se instala',
  lead: 'Léelo con calma. Nada se descarga hasta el paso 5 y siempre te diremos el tamaño antes.',
  seInstala: 'Se instalará',
  items: [
    ['El motor de IA', '(Ollama, de código abierto). Entre 50 MB y 1,5 GB según tu gráfica.'],
    ['Los modelos de lenguaje', `del perfil que elijas: entre ${rango} GB.`],
    ['La base de datos de tus partidas,', 'que empieza ocupando unos pocos MB.'],
  ],
  donde: 'Dónde:',
  nunca: 'Tarkor nunca',
  nuncaItems: [
    'Envía tu partida a ningún sitio.',
    'Te pide una cuenta ni un correo.',
    'Recoge estadísticas de uso.',
    'Se queda funcionando al cerrarlo ni arranca con el sistema.',
    'Usa la cámara, el micrófono, tu ubicación ni tus contactos.',
  ],
  red: 'Conexión a internet: solo para estas descargas, desde las fuentes oficiales de Ollama y de cada modelo.',
  acepto: 'He leído lo que se va a instalar y acepto la licencia de uso y las licencias de terceros.',
  accion: 'Aceptar y continuar',
}

export const tuEquipo = {
  tituloPermiso: '¿Podemos revisar tu equipo?',
  leadPermiso: 'Así te recomendamos el perfil de IA que mejor le va, y te mostramos hasta dónde puedes llegar sin forzarlo.',
  consultaremos: 'Lo que consultaremos',
  items: ['Memoria RAM total y libre.', 'Procesador: modelo y número de núcleos.', 'Tarjeta gráfica y su memoria.', 'Espacio libre en el disco.', 'Sistema operativo.'],
  privacidad: 'Se usa solo para recomendarte un perfil. No sale de tu equipo y no se envía a nadie.',
  analizar: 'Analizar mi equipo',
  analizando: 'Analizando…',
  manual: 'Prefiero elegir a mano',
  titulo: 'Tu equipo',
  lead: 'Esto es lo que hemos encontrado.',
  memoria: 'Memoria',
  compartida: 'compartida',
  grafica: 'Gráfica',
  sinGrafica: 'No detectada',
  procesador: 'Procesador',
  disco: 'Disco libre',
  sistema: 'Sistema',
  puedes: (gb: string, perfil: string) => `Puedes dedicar a la IA unos ${gb} GB. Te recomendamos el perfil ${perfil}.`,
  insuficienteTitulo: 'Tu equipo va muy justo para la IA de Tarkor.',
  insuficiente: (ram: string, perfil: string) => `Con ${ram} GB de memoria no cabe ni el perfil ${perfil} sin quitarle memoria al sistema. Puedes probarlo igualmente: cierra otros programas mientras juegas y ten en cuenta que puede ir lento o cerrarse.`,
  integrada: 'Tu gráfica comparte memoria con el sistema, así que hemos calculado solo con la RAM.',
  reanalizar: 'Volver a analizar',
  error: 'No hemos podido analizar tu equipo. Puedes elegir el perfil a mano.',
}

export const perfil = {
  titulo: 'Elige cuánto dedicarle',
  lead: 'Cuanta más memoria le dediques, mejor narra. Por encima del máximo seguro tu equipo puede ir lento o cerrar el juego.',
  leadManual: 'Sin analizar tu equipo no sabemos cuánto aguanta. Si dudas, empieza por Ligero: podrás subirlo después.',
  medidor: (gb: string) => `Tu equipo puede dedicar unos ${gb} GB a la IA sin quedarse corto.`,
  recomendado: 'Recomendado',
  maximoSeguro: 'Máximo seguro',
  supera: 'Supera tu equipo',
  sinDisco: 'No cabe en el disco',
  experimental: 'Experimental',
  calidadExplicada: 'Cada perfil usa modelos de IA de distinto tamaño: cuanto más grande, mejor narra, pero más memoria necesita. Todos permiten jugar la partida completa.',
  memoria: 'Memoria',
  descarga: 'Descarga',
  velocidad: 'Velocidad',
  narracion: 'Narración',
  aviso: 'Este perfil necesita más de lo que tu equipo puede dedicar. Puede dejar el equipo lento o cerrar el juego a mitad de partida.',
  usoCpu: 'Uso del procesador',
  moderado: 'Moderado',
  alto: 'Alto',
  usoModerado: (n: number, t: number) => `Usa ${n} de ${t} hilos. Tu equipo sigue fluido mientras narra.`,
  usoAlto: (n: number, t: number) => `Usa ${n} de ${t} hilos. Narra más rápido, pero el equipo va más cargado.`,
  noRecomendados: 'Mostrar perfiles no recomendados',
  detalles: 'Ver detalles técnicos',
  colPerfil: 'Perfil', colNarrador: 'Narrador', colSugerir: 'Sugerir', colCargados: 'Modelos cargados a la vez',
  detallesPie: 'Todos usan el mismo cronista y el mismo modelo de memoria del mundo.',
  pie: 'Podrás cambiarlo cuando quieras en Ajustes → Rendimiento de la IA.',
  accion: (gb: string) => `Descargar ${gb} GB`,
}

export const descarga = {
  titulo: 'Descargando',
  lead: (perfil: string) => `Perfil ${perfil}. Puedes pausar y seguir más tarde; lo ya descargado se conserva.`,
  total: 'Total',
  quedan: (min: number) => `quedan unos ${min} min`,
  motor: 'Motor de IA',
  estados: { cola: 'En cola', bajando: 'Descargando', pausa: 'En pausa', listo: 'Listo' },
  verificado: 'Descargado de las fuentes oficiales y verificado al terminar cada archivo.',
  pausar: 'Pausar',
  reanudar: 'Reanudar',
  accion: 'Comprobar la instalación',
  nombreModelo: (m: string): string => ({
    'qwen2.5:7b': 'Narrador',
    'qwen2.5:3b': 'Narrador',
    'qwen2.5:1.5b-instruct': 'Cronista',
    'qwen3.5:4b': 'Sugerencias',
    'nomic-embed-text': 'Memoria del mundo',
  })[m] ?? m,
}

export const comprobacion = {
  titulo: 'Comprobación',
  lead: 'Probamos cada pieza por separado para que, si algo falla, sepas exactamente qué.',
  pasos: [
    ['Carpeta de datos', 'Se puede escribir en la carpeta de datos.'],
    ['Base de datos de partidas', 'Preparada y al día.'],
    ['Motor del juego', 'Arranca y responde.'],
    ['Datos del mundo', 'Personajes, lugares, objetos y lore del mundo cargados.'],
    ['Motor de IA', 'En marcha.'],
    ['Modelos', 'Todos presentes y verificados.'],
    ['Narración de prueba', ''],
  ],
  comprobando: 'Comprobando…',
}

export const listo = {
  titulo: 'Todo preparado',
  lead: 'Tarkor está listo para jugar.',
  perfil: 'Perfil',
  memoria: 'Memoria de la IA',
  espacio: 'Espacio usado',
  partidas: 'Tus partidas',
  pie: 'Puedes cambiar el perfil o volver a analizar tu equipo en Ajustes → Rendimiento de la IA.',
  accion: 'Jugar',
}

export const juego = {
  titulo: 'Aquí se abrirá el juego',
  lead: 'El asistente está completo. En esta fase del desarrollo el juego todavía no va dentro de la app (fase 4 del plan).',
  ajustes: 'Ajustes → Rendimiento de la IA',
  repetir: 'Repetir el asistente',
}

export const ajustes = {
  titulo: 'Rendimiento de la IA',
  actual: (perfil: string, mem: string, disco: string) => `Perfil actual: ${perfil} · usa ${mem} GB de memoria · los modelos ocupan ${disco} GB en disco.`,
  reanalizar: 'Volver a analizar mi equipo',
  liberar: (perfil: string, gb: string) => `Al cambiar a ${perfil} podrás borrar modelos que ya no usarás y liberar ${gb} GB.`,
  actualBoton: 'Perfil actual',
  cambiar: 'Cambiar de perfil',
  cambiarDescargar: (gb: string) => `Cambiar y descargar ${gb} GB`,
  volver: 'Volver',
}

export const errores = {
  guardar: 'No se pudo guardar la configuración en la carpeta de datos. Comprueba que hay espacio libre.',
}
