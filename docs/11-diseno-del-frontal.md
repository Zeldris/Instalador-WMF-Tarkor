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
  - `Supera tu equipo` (danger) en los que no caben en memoria: se pueden elegir, pero al
    hacerlo la tarjeta muestra el aviso en `cost` ("Puede dejar tu equipo lento o cerrar el
    juego") y pide confirmación en la propia tarjeta. Sin interruptor aparte (LM Studio estima si
    un modelo cabe, avisa y deja cargarlo; decidido el 2026-10-25, `INS-14`).
- **Espacio en disco** en cada tarjeta: "Necesita X GB · libres Y GB". Si no cabe, la línea va en
  `danger` con el enlace "Cambiar carpeta", y el botón de descarga se deshabilita hasta que quepa
  (itch.io y Heroic muestran necesario frente a disponible; aquí se bloquea el inicio porque la
  descarga fallaría a medias).
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
- Si se pierde la conexión: la descarga se pausa sola, la fila pasa a "Esperando conexión" y se
  reanuda al volver la red, con reintentos cada vez más espaciados (Heroic: autopausa y reanuda).
  Los reintentos van a los 5, 10, 20, 40 y luego cada 60 s (el contador vuelve a 5 s en cuanto llega
  progreso), con una cuenta atrás y dos botones: «Pausar» (cancela el reintento) y «Reintentar ahora».
  Solo cuenta como falta de red lo que se arregla solo (sin DNS, conexión cortada, tiempo agotado):
  un cortafuegos o proxy que bloquea el registro, o un disco lleno, siguen siendo un error con «Reintentar».
- Encima de las filas, la carpeta de destino con "Cambiar carpeta" mientras no haya empezado
  (LM Studio y Ollama permiten cambiar la carpeta de modelos; en la Deck, para la tarjeta SD).

### 6. Comprobación

Lista de las 7 comprobaciones de [`07`](07-flujo-de-instalacion.md) con un icono de estado cada
una (pendiente, en curso, correcto, fallo). La última, "Narración de prueba", muestra la frase
generada y la velocidad medida ("unas 9 palabras por segundo"), sacada de `eval_count /
eval_duration`. Por debajo de 3 palabras/s se sugiere un perfil más ligero. Es la única prueba de
velocidad: no hay botón aparte (LM Studio muestra la velocidad en cada respuesta).

En caso de fallo, la fila se expande con la explicación, **Reintentar**, "Ver detalles" y
**Copiar informe**. Si el fallo es de memoria, se ofrece "Probar un perfil más ligero" que vuelve
al paso 4. Si falla el motor de IA o un modelo, también **Reparar** (ver Ajustes).

### 7. Listo

- "Todo preparado". Resumen: perfil elegido, espacio usado, dónde están tus partidas.
- Acción: **Jugar** → abre el juego (pantalla de inicio actual del frontend).

### Ajustes → Rendimiento de la IA

Accesible desde el menú del juego. Mismo estilo.

- Perfil actual, memoria que usa, espacio que ocupan los modelos.
- **Dónde corre la IA** (`/api/ps` de Ollama, refrescado cada 5 s mientras Ajustes está abierto): una frase y la
  memoria que ocupa de verdad: "La IA usa la gráfica al 100 %", "Repartida: 60 % en la gráfica y 40 % en el
  procesador (va más lenta)" o "La IA va en el procesador"; sin nada cargado, "Se carga al narrar el primer turno".
  El porcentaje es el de todos los modelos cargados juntos, pesados por su tamaño. Sale de `ollama ps` ("100% GPU",
  "48%/52% CPU/GPU"), dicho en palabras de jugador (decisión de la usuaria, 2026-10-25).
- "Volver a analizar mi equipo".
- Las tres tarjetas del paso 4 para cambiar de perfil; si el cambio implica descargar, muestra el
  tamaño en el botón ("Cambiar y descargar 2,7 GB"). Al cambiar, descarga lo que falte con su progreso y se puede
  pausar; el perfil de antes sigue activo hasta que termina, y entonces se guarda el nuevo y se reinicia el motor
  (Steam descarga al elegir y no toca lo instalado hasta tener lo nuevo). Después, si sobran modelos, "Borrar
  modelos que ya no uso (X GB)", solo con el motor propio: los de un Ollama externo no se tocan (la "Desinstalar"
  de la ficha de Steam).
- Uso del procesador.
- **Carpeta de los modelos**: la ruta, su espacio y "Mover…", que copia el motor y los modelos a la
  nueva carpeta, comprueba y borra la vieja (LM Studio, "My Models"; Ollama, `OLLAMA_MODELS`).
- **Reparar**: vuelve a comprobar la suma de cada archivo del motor (el "Verificar archivos" de Steam; las
  sumas quedan en su marca `.completo` al instalarlo) y lo reinstala si alguna no casa, sin quitar el de antes
  hasta tener el nuevo listo; luego suma cada capa de `blobs/` (su nombre es su suma), borra las dañadas y pide
  de nuevo los modelos del perfil: `/api/pull` solo baja lo que falta (el "healing" de itch.io). Ollama no
  vuelve a sumar las capas que ya tiene, por eso las suma Tarkor. Se puede cancelar, dice por dónde va y no
  coincide con «Mover a otra carpeta»; si falla, el motor vuelve a arrancar con lo que hubiera.
- "Copiar informe del sistema" para pedir ayuda.

### Copiar informe

En Ajustes y en "El motor se ha detenido" (el "Copy diagnostics" de Heroic). **Copiar informe** lo deja en el
portapapeles con el plugin de portapapeles de Tauri (el del navegador no es fiable en WebKitGTK); "Ver detalles"
despliega el mismo texto antes. Lleva: versión de la app, sistema, equipo analizado, perfil y uso del procesador,
ajustes de Ollama del perfil, origen del catálogo, estado del motor (versión, en marcha, último motivo de parada),
lo que dice `/api/ps` y las últimas 200 líneas de `motor-ia.log`. La carpeta personal se cambia por `~` y la carpeta de la IA sale como `<carpeta de la IA>`. Nunca sale
del equipo si el jugador no lo pega él mismo (`08`).

### Error: el motor se ha detenido

Un hilo de Rust vigila los procesos cada 2 s, cargue lo que cargue la ventana, y avisa al frontal con un evento; la
pantalla es una ruta del asistente, como Ajustes, para que con el juego cargado (`INS-41`) se pueda navegar a ella
(decisión de la usuaria, 2026-10-25). Pantalla superpuesta (sobre el juego) cuando un sidecar se cae dos veces seguidas:

- "El motor del juego se ha detenido" / "El motor de IA se ha detenido".
- Qué significa para la partida: "Tu partida está guardada hasta el último turno completado".
- Acciones: **Reintentar**, "Copiar informe", "Cambiar a un perfil más ligero" (solo si el motor de
  IA se detuvo por falta de memoria: lo dicen las últimas líneas de su registro, y lleva a Ajustes con el perfil de
  menos memoria siguiente ya elegido).

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
