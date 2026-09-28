# Diseño del frontal

**Estado: propuesta de diseño (2026-09-28), lista para implementar.** Pantallas del asistente de
primer arranque, de Ajustes → Rendimiento de la IA y de los errores del motor. El instalador NSIS de
Windows usa sus pantallas estándar (ver [`07-flujo-de-instalacion.md`](07-flujo-de-instalacion.md));
todo lo de aquí es la parte propia, dentro de la app.

Prototipo navegable: [`diseno/prototipo-asistente.html`](../diseno/prototipo-asistente.html)
(se abre en cualquier navegador; los datos del equipo son de ejemplo y se pueden cambiar arriba).

## Principios

1. **Parece Tarkor desde el primer segundo.** Mismo sistema visual que el juego: tokens de
   `frontend/src/index.css` (madera `wood-*`, hierro `iron-*`, acento azul `accent-*` de Helek
   Sirik, `moss` para éxito, `danger` para fallo, `cost` para avisos), Cinzel para títulos, Inter
   para texto, `Cascadia Code`/monoespaciada para cifras. Paneles `.plank-panel`, riel `.iron-band`,
   separadores `.accent-hairline`.
2. **Todo se explica antes de hacerse.** Cada pantalla dice qué va a pasar y cuánto ocupa o tarda
   antes del botón que lo hace.
3. **El jugador decide.** Nada preseleccionado que implique consentimiento; cada descarga tiene su
   botón.
4. **Lenguaje de jugador.** "Motor de IA", no "Ollama sidecar"; "memoria", no "RAM" en los títulos
   (RAM aparece como dato). Los nombres técnicos van en "Ver detalles".
5. **Sin callejones sin salida.** Todo error dice qué falló, qué hacer, y ofrece reintentar y copiar
   el informe.

## Estructura de la ventana

Ventana de 1100 × 720 (mínimo 900 × 600). A la izquierda un riel de hierro con los 7 pasos (la
secuencia es real: el orden importa y el jugador ve dónde está); a la derecha un panel de madera
con el contenido y una barra inferior fija con "Atrás" y la acción principal.

```
┌──────────────┬───────────────────────────────────────────────┐
│  TARKOR      │  Título del paso (Cinzel)                     │
│              │  Texto de una o dos frases                    │
│  1 Bienvenida│  ───────────── accent-hairline ─────────────  │
│  2 Qué se    │                                               │
│    instala   │  Contenido del paso                           │
│  3 Tu equipo │                                               │
│  4 Perfil    │                                               │
│  5 Descarga  │                                               │
│  6 Compro-   │                                               │
│    bación    │                                               │
│  7 Listo     ├───────────────────────────────────────────────┤
│              │  [Atrás]                    [Acción principal]│
└──────────────┴───────────────────────────────────────────────┘
```

Pasos completados en `moss`, paso actual en `accent`, futuros en `wood-400`.

## Pantallas

### 1. Bienvenida

- Título: "Bienvenido a Tarkor".
- Texto: qué va a pasar en 4 frases (preparar el motor de IA para tu equipo, descargar lo
  necesario, comprobar que todo funciona, jugar) y cuánto tarda: "Unos minutos, más el tiempo de
  descarga (1,3-9,4 GB según tu equipo)". El rango se calcula del catálogo (`12`).
- Nota de contenido: "Contiene violencia de fantasía. Recomendado a partir de 16 años."
- Acción: **Empezar**.

### 2. Qué se instala y qué no se hace

Dos columnas:

- **Se instalará:** el motor de IA (Ollama, código abierto), los modelos de lenguaje que elijas
  en el paso 4 (1,3-9,4 GB), la base de datos de tus partidas. Dónde: la ruta real de la carpeta de
  datos, con botón "Cambiar" (solo mientras no haya nada descargado).
- **Tarkor nunca:** envía tu partida a ningún sitio · pide cuenta ni correo · recoge estadísticas
  de uso · arranca solo con el sistema · usa cámara, micrófono, ubicación o contactos.
- **Conexión a internet:** solo para estas descargas, desde sus fuentes oficiales.

Casilla **sin marcar**: "He leído lo que se va a instalar y acepto la licencia de uso". Enlace
"Leer la licencia y las licencias de terceros". Acción **Aceptar y continuar**, deshabilitada hasta
marcar la casilla.

### 3. Tu equipo (permiso de análisis)

- Título: "¿Podemos revisar tu equipo?"
- Lista de lo que se consulta: memoria RAM, procesador, tarjeta gráfica y su memoria, espacio libre
  en disco, sistema operativo.
- "Se usa solo para recomendarte un perfil. No sale de tu equipo y no se envía a nadie."
- Acciones: **Analizar mi equipo** (principal) · "Prefiero elegir a mano" (secundaria).
- Tras analizar (menos de un segundo), la misma pantalla muestra una ficha del equipo detectado
  antes de pasar al 4.

### 4. Elige cuánto dedicarle

La pantalla central del asistente.

- **Medidor de memoria** arriba: una barra con la memoria disponible para la IA según el cálculo
  de [`09`](09-deteccion-de-equipo-y-perfiles.md), con marcas donde cae cada perfil y la línea
  "máximo seguro". Texto: "Tu equipo puede dedicar unos 11 GB a la IA sin quedarse corto".
- **Tres tarjetas de perfil** (Ligero / Equilibrado / Máximo), mismas medidas y mismo orden de
  datos en cada una: memoria que usa, descarga, velocidad y calidad de narración (con 1-3
  marcas), y una etiqueta de estado:
  - `Recomendado` (accent) en el preseleccionado.
  - `Máximo seguro` en el más alto que cabe.
  - `Supera tu equipo` (danger) en los que no caben: deshabilitados.
- Interruptor "Mostrar perfiles no recomendados": habilita los que no caben, con aviso en `cost`
  ("Puede dejar tu equipo lento o cerrar el juego") y confirmación en la propia tarjeta.
- **Uso del procesador:** control segmentado Moderado / Alto con una frase de efecto.
- "Ver detalles técnicos" desplegable: modelos exactos de cada perfil.
- Pie: "Podrás cambiarlo cuando quieras en Ajustes → Rendimiento de la IA".
- Acción: **Descargar X GB**.
- Si se eligió "a mano" en el paso 3: sin medidor ni etiquetas de máximo; Ligero preseleccionado y
  aviso de que un perfil alto puede no caber.

### 5. Descarga

- Una fila por elemento (Motor de IA, cada modelo): nombre de jugador + tamaño + barra + estado
  (en cola, descargando, verificando, listo).
- Barra total arriba con tiempo estimado restante.
- Acciones: **Pausar / Reanudar**; "Cancelar" pide confirmación en la propia pantalla (nunca un
  diálogo del sistema) y avisa de que lo descargado se conserva para continuar.
- Si se pierde la conexión: la fila afectada pasa a "Esperando conexión" y se reintenta sola.

### 6. Comprobación

Lista de las 7 comprobaciones de [`07`](07-flujo-de-instalacion.md) con un icono de estado cada
una (pendiente, en curso, correcto, fallo). La última, "Narración de prueba", muestra la frase
generada y la velocidad medida ("unas 9 palabras por segundo").

En caso de fallo, la fila se expande con la explicación, **Reintentar**, "Ver detalles" y
**Copiar informe**. Si el fallo es de memoria, se ofrece "Probar un perfil más ligero" que vuelve
al paso 4.

### 7. Listo

- "Todo preparado". Resumen: perfil elegido, espacio usado, dónde están tus partidas.
- Acción: **Jugar** → abre el juego (pantalla de inicio actual del frontend).

### Ajustes → Rendimiento de la IA

Accesible desde el menú del juego. Mismo estilo.

- Perfil actual, memoria que usa, espacio que ocupan los modelos.
- "Volver a analizar mi equipo".
- Las tres tarjetas del paso 4 para cambiar de perfil; si el cambio implica descargar, muestra el
  tamaño en el botón ("Cambiar y descargar 2,7 GB"); si sobran modelos, "Borrar modelos que ya no
  uso (X GB)".
- Uso del procesador.
- "Copiar informe del sistema" para pedir ayuda.

### Error: el motor se ha detenido

Pantalla superpuesta (sobre el juego) cuando un sidecar se cae dos veces seguidas:

- "El motor del juego se ha detenido" / "El motor de IA se ha detenido".
- Qué significa para la partida: "Tu partida está guardada hasta el último turno completado".
- Acciones: **Reintentar**, "Copiar informe", "Cambiar a un perfil más ligero" (solo si el motor de
  IA se detuvo por falta de memoria).

## Implementación

- El asistente es una pequeña app de React + Vite dentro de este repositorio (`app/asistente/`),
  compilada aparte e incluida en la app de Tauri junto al build del juego.
- Al abrir la app, Tauri lee `config.json`: si `asistenteCompletado` no es `true`, abre el asistente;
  si lo es, arranca los sidecars y abre el juego.
- Reutiliza los tokens de `frontend/src/index.css` (copiados o importados en el build) para no
  duplicar decisiones de diseño.
- Ajustes → Rendimiento de la IA vive también en el asistente (ruta propia), y el juego solo
  necesita un enlace a ella en su menú.
- Todo el texto del asistente en un único fichero de textos, para revisarlo de una vez.
