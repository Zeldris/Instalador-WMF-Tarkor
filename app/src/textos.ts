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
    ['El motor de IA', '(Ollama, de código abierto): unos 1,4 GB.'],
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
  aviso: 'Puede dejar tu equipo lento o cerrar el juego a mitad de partida.',
  confirmar: 'Usar este perfil igualmente',
  necesita: (gb: string) => `Necesita ${gb} GB`,
  libres: (gb: string) => `libres ${gb} GB`,
  cambiarCarpeta: 'Cambiar carpeta',
  carpeta: 'Carpeta de la IA',
  moviendo: 'Moviendo…',
  errorCarpeta: 'No se pudo cambiar la carpeta.',
  usoCpu: 'Uso del procesador',
  moderado: 'Moderado',
  alto: 'Alto',
  usoModerado: (n: number, t: number) => `Usa ${n} de ${t} hilos. Tu equipo sigue fluido mientras narra.`,
  usoAlto: (n: number, t: number) => `Usa ${n} de ${t} hilos. Narra más rápido, pero el equipo va más cargado.`,
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
  estados: { cola: 'En cola', bajando: 'Descargando', pausa: 'En pausa', esperando: 'Esperando conexión', verificando: 'Verificando', extrayendo: 'Preparando', detenida: 'Detenida', listo: 'Listo' },
  verificado: 'Descargado de las fuentes oficiales y verificado al terminar cada archivo.',
  pausar: 'Pausar',
  reanudar: 'Reanudar',
  accion: 'Comprobar la instalación',
  reintentar: 'Reintentar',
  reintentarAhora: 'Reintentar ahora',
  /** Aviso de la espera por falta de red (docs/11 §5); `segundos` es la cuenta atrás hasta el siguiente reintento. */
  sinRed: 'Sin conexión. La descarga seguirá sola cuando vuelva la red; lo descargado se conserva.',
  reintentandoEn: (segundos: number) => `Reintentando en ${segundos} s.`,
  /** Para qué sirve cada modelo; un mismo modelo puede cumplir varios papeles (perfil Mínimo). */
  papeles: { narrador: 'Narrador', cronista: 'Cronista', sugerencias: 'Sugerencias', embeddings: 'Memoria del mundo' },
}

export const comprobacion = {
  titulo: 'Comprobación',
  lead: 'Probamos cada pieza por separado para que, si algo falla, sepas exactamente qué.',
  pasos: [
    { id: 'datos', nombre: 'Carpeta de datos' },
    { id: 'basedatos', nombre: 'Base de datos de partidas' },
    { id: 'juego', nombre: 'Motor del juego' },
    { id: 'mundo', nombre: 'Datos del mundo' },
    { id: 'motor', nombre: 'Motor de IA' },
    { id: 'modelos', nombre: 'Modelos' },
    { id: 'narracion', nombre: 'Narración de prueba' },
  ],
  comprobando: 'Comprobando…',
  velocidad: (palabras: number, segundos: number) =>
    `Tu equipo narra a unas ${palabras} palabras por segundo: una narración típica tardará unos ${segundos} segundos.`,
  reintentar: 'Reintentar',
  masLigero: 'Probar un perfil más ligero',
  lenta: 'Tu equipo narra despacio con este perfil: uno más ligero responderá antes',
  copiar: 'Copiar informe',
  copiado: 'Informe copiado',
}

export const reparar = {
  boton: 'Reparar',
  reparando: 'Reparando…',
  cancelar: 'Cancelar',
  cancelado: 'Reparación cancelada. Lo ya comprobado sigue en su sitio; puedes volver a empezarla cuando quieras.',
  explicacion: 'Comprueba el motor de IA y los modelos archivo por archivo y vuelve a descargar solo lo que falte o esté dañado.',
  motor: { verificando: 'Comprobando el motor de IA…', descargando: (pc: number) => `Volviendo a descargar el motor de IA (${pc} %)…`, extrayendo: 'Preparando el motor de IA…', listo: 'Motor de IA comprobado.' },
  comprobandoModelos: (pc: number) => `Comprobando los archivos de los modelos (${pc} %)…`,
  descargandoModelo: (m: string, pc: number) => `Descargando lo que falta de ${m} (${pc} %)…`,
  pidiendoModelo: (m: string) => `Revisando ${m} con el servidor de modelos…`,
  enOrden: 'Todo estaba en orden: el motor de IA y los modelos están completos.',
  motorReinstalado: 'se ha vuelto a instalar el motor de IA',
  capas: (n: number) => (n === 1 ? 'se ha vuelto a descargar 1 archivo de los modelos' : `se han vuelto a descargar ${n} archivos de los modelos`),
  hecho: (partes: string[]) => `Reparado: ${partes.join(' y ')}.`,
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
  preparando: 'Preparando el narrador…',
  listo: 'El narrador está listo',
  noCalento: (motivo: string) => `No se pudo preparar el narrador: el primer turno tardará más. (${motivo})`,
  masLigero: 'Cambiar a un perfil más ligero',
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
  carpeta: 'Carpeta de la IA',
  moverCarpeta: 'Mover a otra carpeta',
  pausar: 'Pausar',
  cambiando: 'Cambiando de perfil…',
  /** Principio del mensaje con que el núcleo informa de una pausa (`Error::Cancelado`, app/nucleo). */
  prefijoCancelacion: 'Descarga cancelada',
  pausado: 'Cambio pausado. Lo descargado se conserva y sigue el perfil de antes.',
  borrar: (gb: string) => `Borrar modelos que ya no uso (${gb} GB)`,
  borrando: 'Borrando…',
  dondeCorre: {
    gpu: 'La IA usa la gráfica al 100 %',
    repartida: (gpu: number) => `Repartida: ${gpu} % gráfica, ${100 - gpu} % procesador (va más lenta)`,
    cpu: 'La IA va en el procesador',
    nada: 'Se carga al narrar el primer turno',
    memoria: (gb: string) => `ocupa ${gb} GB`,
  },
}

/** «Borrar datos del juego» (Linux, `INS-45`; docs/07, «Desinstalación»). */
export const borrarDatos = {
  boton: 'Borrar datos del juego',
  titulo: 'Borrar datos del juego',
  lead: 'Tarkor se cerrará al terminar. Marca lo que quieres borrar; los registros se borran siempre.',
  partidas: 'Borrar también mis partidas guardadas',
  ia: (tamano: string) => (tamano ? `Borrar también el motor de IA y los modelos (${tamano})` : 'Borrar también el motor de IA y los modelos'),
  borrar: 'Borrar',
  borrando: 'Borrando…',
  cancelar: 'Cancelar',
  finalTitulo: 'Datos borrados',
  finalTexto: 'Datos borrados. Ya puedes borrar el archivo .AppImage o desinstalar el paquete .deb.',
  cerrar: 'Cerrar Tarkor',
}

export const informe = {
  copiar: 'Copiar informe',
  copiado: 'Copiado',
  verDetalles: 'Ver detalles',
  ocultarDetalles: 'Ocultar detalles',
  cargando: 'Preparando el informe…',
  errorCopiar: 'No se pudo copiar solo: selecciona el texto de abajo y cópialo a mano.',
  errorInforme: 'No se pudo preparar el informe.',
}

export const motorDetenido = {
  titulo: 'El motor de IA se ha detenido',
  lead: 'Tu partida está guardada hasta el último turno completado.',
  reintentar: 'Reintentar',
  reintentando: 'Reintentando…',
  masLigero: 'Cambiar a un perfil más ligero',
  sinMemoria: 'Parece que se quedó sin memoria.',
}

export const licencias = {
  titulo: 'Licencias y avisos',
  lead: 'Lo que Tarkor descarga y usa, con su licencia. Los textos completos van dentro de la app: se leen sin conexión.',
  abrir: 'Leer las licencias',
  abrirAjustes: 'Licencias',
  volver: 'Volver',
  builtWithLlama: 'Built with Llama',
  /** `perfiles`: nombres visibles de los perfiles del catálogo cargado que usan un modelo con licencia Llama. */
  builtWithLlamaLead: (perfiles: string[]) =>
    perfiles.length === 0 ? 'Algunos modelos de Tarkor son Llama 3.1, de Meta.'
      : perfiles.length === 1 ? `El perfil ${perfiles[0]} usa Llama 3.1, de Meta.`
        : `Los perfiles ${perfiles.slice(0, -1).join(', ')} y ${perfiles[perfiles.length - 1]} usan Llama 3.1, de Meta.`,
  motor: 'Motor de IA',
  motorNombre: 'Ollama',
  modelos: 'Modelos de lenguaje',
  /** Nombre visible de cada licencia del catálogo (`licencia` de `catalogo.json`). */
  nombres: {
    'Llama-3.1-Community': 'Llama 3.1 Community License',
    'Apache-2.0': 'Apache License 2.0',
    MIT: 'Licencia MIT',
  } as Record<string, string>,
  avisoLlama: 'Llama 3.1 is licensed under the Llama 3.1 Community License, Copyright © Meta Platforms, Inc. All Rights Reserved.',
  politica: 'Política de uso aceptable de Llama 3.1:',
  politicaUrl: 'https://llama.meta.com/llama3_1/use-policy',
  copiarEnlace: 'Copiar enlace',
  copiado: 'Copiado',
  errorCopiar: 'No se pudo copiar. Selecciona el enlace y cópialo a mano.',
  textoCompleto: (licencia: string) => `Texto completo de la ${licencia}`,
  fuentes: 'Los modelos y el motor se descargan de sus fuentes oficiales; sus licencias pueden cambiar entre versiones.',
}

export const errores = {
  guardar: 'No se pudo guardar la configuración en la carpeta de datos. Comprueba que hay espacio libre.',
}

/** La frase de «dónde corre la IA» según el porcentaje en la gráfica (`null` = nada cargado). */
export function fraseUso(porcentajeGpu: number | null): string {
  const d = ajustes.dondeCorre
  if (porcentajeGpu === null) return d.nada
  const gpu = Math.min(100, Math.max(0, Math.round(porcentajeGpu)))
  return gpu >= 100 ? d.gpu : gpu <= 0 ? d.cpu : d.repartida(gpu)
}
