# Hoja de estilos del instalador y peticiones de imágenes

**Estado: pedido escrito (2026-11-11, `INS-57`); ninguna imagen entregada todavía.** El frontal del juego ya
aplica la marca de Tarkor (`UX-40`); el asistente la adopta en `INS-56` (pendiente: hoy su CSS no tiene aún los
tokens `gold-*`). Este documento dice **qué imágenes necesita el instalador**, cuáles están ya pedidas en el generador y solo se colocan aquí, y cuáles son peticiones nuevas, con
su medida, su prompt y cómo se dan por buenas. Sigue el formato de las peticiones de Tarkor para `gimg` y no repite
su hoja: la resume y dice qué cambia para el instalador. Colocarlas es `INS-58` del [plan](05-plan-de-trabajo.md).

## 0. Fuente

| Repo | Commit | Rama | Rutas leídas |
|---|---|---|---|
| `galivelop-image-generator` (GVIG) | `db9c364` (2026-11-11) | `main` | `docs/marcas/tarkor/hoja.md` (la hoja de estilos de Tarkor), `docs/marcas/tarkor/peticiones.md` (piezas `#1`…`#17` y `E1`…`E18`), `docs/marcas/tarkor/logos/`, `docs/propuestas/tarkor/diseno-interfaz-2026-11-10.md`, `examples/tarkor/orders/` |
| `World-Maker-Fantasy` (el juego) | `c858a150` | `claude/marca-interfaz` | `docs/producto/diseno-interfaz-marca.md` (`UX-40`), `frontend/src/index.css` |
| Este repo | `87fdd08` | `claude/installer-docs-review-09e7vs` | [`11-diseno-del-frontal.md`](11-diseno-del-frontal.md), `app/src/estilos.css`, `app/src-tauri/tauri.conf.json`, `app/src-tauri/icons/`, `app/src-tauri/windows/installer.nsi` |

Si la hoja de Tarkor y este documento se contradicen, **manda la hoja**: aquí se corrige. Los otros dos repos se
leen; desde este nunca se modifican.

## 1. La estética, aplicada al instalador

**La madera sostiene, el oro remata.** Proporción 60/30/10: madera o noche, hierro y piedra, oro. El oro, como
mucho un 10 % de la pieza, y el más claro (`gold-100`), un 5 %. Una sola luz, rasante, desde arriba a la izquierda;
sin sombras arrojadas, halos ni neblina. Sin morado ni violeta, sin luna ni disco de sol, sin personas, caras, manos
ni criaturas, sin pólvora, sin letras pintadas, sin interfaz falsa, sin `#000` ni `#fff`.

El instalador vive en tres sitios, y cada uno tiene su fondo:

| Territorio | Qué es | Fondo | Piezas |
|---|---|---|---|
| **Dentro del asistente** | La ventana de 1100 × 720 (mínimo 900 × 600): riel, panel, barra inferior | Madera y hierro, como dentro del juego (decidido el 2026-11-11, `INS-56`) | `#2`, `#3`, `#5`, `#9`, `#17`, `E7`, `I4` |
| **La ventana al mundo** | La portada de «Bienvenida» y de «Listo»: una imagen enmarcada dentro del panel de madera | Noche índigo, con filete de oro por CSS | `I3` |
| **Fuera del asistente** | El instalador de Windows (NSIS), el icono en el escritorio, la biblioteca de Steam en la Deck, la página del repo | Noche índigo `night-950` → `night-900` con el cinturón de polvo; sin luna | `E14`, `I1`, `I2`, `I5`, `I6`, `E4`, `E5`, `E3` |

### Paleta para las imágenes

| Rol en la imagen | Token | Hex |
|---|---|---|
| Noche, arriba | `night-950` | `#0f1428` |
| Noche, cuerpo | `night-900` | `#1a2140` |
| Cinturón de polvo | `accent-500`, `accent-300` | `#4aa8d8`, `#a8d8f0` |
| Roca y siluetas | `iron-950` | `#0e0b08` |
| Hierro forjado | `iron-900` | `#171310` |
| Rejilla grabada del hierro | `accent2-600` | `#52626f` |
| Madera de fondo | `wood-950` | `#1b130c` |
| Tablones | — | `#332415`, `#46311d` |
| Tierra del camino | — | `#241a10` |
| Oro tallado | `gold-500` | `#b8862b` |
| Pátina del oro | `gold-700` | `#7a5a1e` |
| Filo gastado del oro | `gold-300` | `#f2c45a` |
| Piedra del emblema | `stone-700` | `#3a342d` |
| Estados (gema) | `accent-500`, `cost-500`, `danger-500` | `#4aa8d8`, `#f59e0b`, `#ef4444` |

## 2. Cómo pedirlas

Reglas de la hoja de Tarkor (§4, §6, §9 y §12, con la revisión del 2026-11-11), que valen igual aquí:

- **Ningún modelo pinta el emblema, el logo ni «TARKOR».** Llegan por composición desde los SVG de
  `docs/marcas/tarkor/logos/` de GVIG (`tarkor-emblema.svg`, `tarkor-emblema-simple.svg`, `tarkor-lockup-v.svg`,
  `tarkor-lockup-h.svg`). El prompt no los nombra.
- **Sin prompt negativo y sin negaciones.** Lo que no debe salir **no se nombra, ni negado** («no stars» pintó una
  estrella; «reserved for an emblem» pintó un emblema). La única negación admitida es el «no haze» de los bloques.
  Palabras que no entran en un prompt: `moon`, `sun`, `star`, `stars`, `emblem`, `logo`, `title`, `text`,
  `letters`, `sign`, `caption`, `watermark`, `glowing`, `flare`, `purple`, `violet`, `like`, `human`, `man`,
  `woman`, `people`, `castle`, nombres propios, y `no`, `not`, `without`, `never`, `none`, `nothing`.
- **La zona libre se describe como lo que es**, con su fracción desde el borde: «The upper third, from the top edge
  downward, is plain calm sky in #1a2140, even and empty».
- **En las piezas que reciben el logo, el logo es lo más claro de la pieza.** Oro pintado, un 10 % como mucho.
- **Medidas:** múltiplos de 64 y hasta 1 048 576 píxeles por imagen. `cfg` 1.0, `euler`.
- **Modelo:** `zimage-turbo-q6` a 8 pasos para la entrega; FLUX.2 klein solo para bocetos (`draft`). De 2 a 3
  semillas por pieza; los recuentos (seis cuñas, cuatro puntas) no los garantiza ningún modelo.
- **Recorte con croma:** las piezas sueltas cierran el prompt con la frase de croma de la hoja (verde `#00ff00`) y
  se recortan con `gimg matte`. De las peticiones nuevas de este documento, ninguna lo necesita.

**Bloque común** (materia: madera, hierro, oro; va delante del prompt de la pieza):

> Epic fantasy game asset. Materials: aged dark wood planks with raised grain in #332415 and #46311d, dark forged
> iron in #171310, old carved gold in #b8862b with dark patina #7a5a1e in the recesses and bright worn edges in
> #f2c45a, dark cracked stone in #3a342d. Warm raking light from the upper left, deep cool shadows in every groove.
> A thin dark bronze outline separates gold from background. Physically plausible materials, crisp edges, high
> contrast, no haze.

**Bloque de noche** (escenas; va en lugar del común, y el material se nombra una sola vez, donde está):

> Epic fantasy matte painting, physically plausible, crisp edges, high contrast, clear air, no haze. Deep indigo
> blue night sky #1a2140, slightly green-leaning, near black #0f1428 at the top. A slanted belt of pale shimmering
> stardust in #4aa8d8 and #a8d8f0 crosses the sky and is the only light in it.

**Cómo llega cada imagen aquí.** `gimg` no escribe en otros repos y este repo no escribe en GVIG. El pedido es este
documento: GVIG lo lee (como leyó `11` para su fila `#17`), genera, y deja la entrega en su carpeta
`examples/tarkor/entrega/`, que no se versiona. La copia a este repo la hace la usuaria o una sesión de este repo con
los archivos delante, en la tarea `INS-58`.

**Dónde se guardan aquí:**

| Carpeta | Qué |
|---|---|
| `app/src-tauri/icons/` | Los siete archivos del icono (`E14`) |
| `app/src-tauri/windows/` | `lateral.bmp` (`I1`) y `cabecera.bmp` (`I2`), junto a `installer.nsi` |
| `app/src/imagenes/` (nueva) | Lo que carga el asistente: portada, hierro del riel, estados, barra, `emblema-simple.svg` |
| `app/src-tauri/steam/` (nueva; ruta a confirmar en `INS-51`) | Las imágenes de biblioteca de la Deck |

**Peso.** Lo que carga el asistente va dentro del ejecutable: fotos y texturas en WebP (calidad 85), piezas con
transparencia en PNG. **Tope: 1 MB entre todas.** La política de contenido del asistente (`img-src 'self' data:`)
ya las admite si se importan desde el código; nada se carga de la red.

## 3. Recursos

### Bloque A — Ya pedido en GVIG: aquí solo se coloca

No se vuelven a pedir. La columna «Estado» es el de GVIG a `db9c364`.

| Pieza | Qué es | Dónde va en el instalador | Estado |
|---|---|---|---|
| **`E14`** Icono de aplicación | El emblema sobre un disco `night-950` que llena el marco; de 64 px para abajo, `tarkor-emblema-simple.svg` rasterizado | `app/src-tauri/icons/`: `fuente.png` (1024), `icon.png` (512), el de 256 (`128x128` con el sufijo `@2x`), `128x128.png`, `64x64.png`, `32x32.png`, `icon.ico` (16, 24, 32, 48, 64 y 256). Sustituye al rombo azul. También es el icono del instalador y del desinstalador de Windows (`I5`) | Prioridad alta; sin pedido escrito. El fondo está en duda (§6, duda 1) |
| **`#17`** Estados de las comprobaciones (4) | Una estrella de oro con una gema: hecho (azul), aviso (ámbar), error (rojo); en curso, una rosa de los vientos. PNG de 64² y 32² | Pantalla 6 «Comprobación» y filas de «Descarga» y «Reparar», a 20 px; pantalla «El motor se ha detenido», a 64 px. `app/src/imagenes/estado-*.png` | Sin pedido escrito. Legible a 20 px en gris |
| **`E7`** Barra de progreso | Pista y relleno de 1024 × 32; la cabeza es la estrella de `#9` | `.pista` y `.relleno` de la descarga (`estilos.css` l.90-91). El medidor de memoria de la pantalla 4 sigue en CSS: es un dato, con sus marcas | Pista y relleno válidos en la primera ronda (q357 y q359); sin entregar |
| **`#9`** Separador con estrella | Filete de oro que se desvanece, con una estrella en el centro, 1024 × 64 | `.filete` (l.60), bajo el título de cada paso | Pedido en el bloque B de GVIG |
| **`#2`** Tablón de panel | Textura de 1024², en mosaico, al 50 % | Fondo de `.principal` (l.49-53) y de `.caja` | Pedido |
| **`#3`** Madera de fondo | Textura casi negra de 1024² | Fondo de la ventana, tras el panel | Pedido |
| **`#5`** Banda de hierro y oro | Banda horizontal de 1024 × 256, mosaico en horizontal | **`.barra`** (l.65), la barra inferior fija. GVIG la apunta al riel, pero el riel es vertical: ver `I4` | Pedido |
| **`E13`** Botón en tres estados | Placa de madera con cerco de hierro, 128 × 48 | `.btn` y `.btn.pri`. Hasta que exista, el botón sigue en CSS | Prioridad media |
| **`E4`** Cápsula | 1024 × 576 con el centro libre para el logo | Cápsula horizontal de la biblioteca de Steam en la Deck: recorte a 1024 × 478 y de ahí a 920 × 430 | Rechazada en la primera ronda (q352, q353); se rehace |
| **`E5`** Fondo ancho | La escena de `E2` sin la banda de madera, 3840 × 1240 | Fondo de la ficha en la biblioteca de Steam de la Deck (basta a 1920 × 620) | Prioridad baja en GVIG: **para la Deck sube a media** |
| **`E3`** Imagen social | 1280 × 640 con el logo | Vista previa del repo en GitHub (la página de descargas) | Se rehace |
| Logos en SVG | `tarkor-emblema-simple.svg`, `tarkor-lockup-v.svg`, `tarkor-lockup-h.svg` | El emblema simple, a 40 px, sobre «TARKOR» en el riel; los lockups, en `I1`, `I6` y el logo de la biblioteca de Steam (el vertical sobre transparente, 1280 × 720) | Existen |

«TARKOR» en el riel es texto, y con `INS-56` pasa a `.title-gold`: no hace falta el wordmark en SVG dentro del
asistente. `E6` (pantalla de carga) es del juego, que se carga dentro de la ventana; el asistente no la usa.

### Bloque B — El instalador de Windows (NSIS)

La plantilla `app/src-tauri/windows/installer.nsi` ya tiene los huecos; falta darles imagen en
`bundle.windows.nsis` de `tauri.conf.json`. Hoy salen los dibujos por defecto de NSIS.

| Id | Recurso | Medidas | Perfil | Dónde va | Prompt (tras el bloque de noche) | Notas |
|---|---|---|---|---|---|---|
| **I1** | **Lateral del instalador** (páginas de bienvenida y de final) | 704 × 1344 generado → 164 × 314 y 328 × 628, BMP de 24 bits | `lateral` 704 × 1344 (**perfil nuevo**; si no, `portrait` 896 × 1152 recortado al centro a 602 × 1152) | `sidebarImage` → `windows/lateral.bmp` | Tall upright view. The belt of stardust rises from the lower left to the upper right across the middle of the frame. Low jagged dark rock spires in #0e0b08 stand along the bottom. Under them, across the bottom tenth, a band of dark forged iron #171310 with one thin line of old gold #b8862b on its top edge. The upper third, from the top edge downward, is plain calm sky in #1a2140, even and empty. | Prioridad alta. `tarkor-lockup-v.svg` en el tercio superior, por composición, a 120 px de ancho en la versión de 164. Sin alfa: `magick lateral.png -resize 164x314! -type TrueColor BMP3:lateral.bmp`. La de 328 × 628 es para pantallas al 150 %: cuál se ve mejor se decide en `INS-52` |
| **I2** | **Cabecera del instalador** (resto de páginas, y la del desinstalador) | 150 × 57 y 300 × 114, BMP de 24 bits | **No se genera**: composición | `headerImage` y `uninstallerHeaderImage` → `windows/cabecera.bmp` | — | Prioridad alta. Fondo liso `night-950` `#0f1428`, `tarkor-emblema-simple.svg` centrado a 41 px de alto y una línea de 1 px `gold-700` en el borde inferior. Sin escena: a 57 px de alto no se lee |
| **I5** | **Icono del instalador y del desinstalador** | `.ico` con 16, 24, 32, 48, 64 y 256 | **No se genera**: es `E14` | `installerIcon` y `uninstallerIcon` → `icons/icon.ico` | — | El mismo icono que la aplicación: quien instala reconoce luego el acceso directo. Las claves del desinstalador se comprueban con la versión de `@tauri-apps/cli` al implementarlo |

### Bloque C — El asistente

| Id | Recurso | Medidas | Perfil | Dónde va | Prompt | Notas |
|---|---|---|---|---|---|---|
| **I3** | **Portada del asistente** («Bienvenida» y «Listo») | 1536 × 512 generado → 1536 × 384 (recorte central) en WebP; se muestra a 870 × 218 px con `object-fit: cover` | `cabecera` 1536 × 512 | Banda sobre el título en la pantalla 1 y sobre el resumen en la 7; `app/src/imagenes/portada.webp` | *(tras el bloque de noche)* Wide view along a packed earth road in #241a10 that runs from the bottom centre to a long dark timber palisade on a low hill, its closed gate in the middle of the frame, plain dark banners hanging on its posts, jagged dark rock spires in #0e0b08 on both sides. The gate has dark forged iron fittings #171310 and one thin line of old gold #b8862b across its lintel. The upper half is calm sky crossed by the belt of stardust. All the detail sits in the middle band of the height; the top fifth and the bottom fifth are quiet and even. | Prioridad media. **Sin logo**: el riel ya dice «TARKOR» al lado. Marco por CSS (borde `gold-900`, radio 10 px). Ningún texto va encima. Con la ventana al mínimo (panel de 670 px) se recortan los lados: lo importante, en el centro. Mientras no exista, la pantalla sigue como está |
| **I4** | **Hierro del riel** | 1024 × 1024 WebP, mosaico en las dos direcciones | `textura` 1024 × 1024 | Fondo de `.riel` (l.31-33), 230 px de ancho; `app/src/imagenes/riel-hierro.webp` | *(tras el bloque común)* Seamless tileable texture of dark forged iron seen straight on, colour #171310 with a faint engraved grid of fine lines in #52626f, matte metal with subtle scratches and a few hammer marks, even exposure across the whole image, flat, edge to edge, top view. | Prioridad baja. Es `#5` sin las tiras de oro: el filo de oro del riel lo pone el CSS. Luminancia media por debajo de 40 sobre 255: encima va texto. Si la madera o el oro del bloque común se cuelan, se repite sin el bloque. Hasta que exista, el riel sigue con su degradado |

### Bloque D — La Steam Deck: «juego ajeno a Steam»

En la Deck, Tarkor se añade a Steam como juego ajeno (`INS-51`). Sin imágenes propias, la biblioteca enseña un
rectángulo gris con el nombre. Steam admite cinco imágenes por juego; cuatro salen de piezas que ya existen o están
pedidas, y una es nueva.

| Id | Recurso | Medidas | Perfil | De dónde sale | Prompt (tras el bloque de noche) | Notas |
|---|---|---|---|---|---|---|
| **I6** | **Cápsula vertical de biblioteca** | 896 × 1152 generado → 768 × 1152 (recorte central) → 600 × 900 PNG | `portrait` 896 × 1152 | **Petición nueva** | Tall upright view. The belt of stardust rises from the lower left to the upper right through the lower half of the frame. Along the bottom quarter, a long dark timber palisade on a low hill between jagged dark rock spires in #0e0b08, with one thin line of old gold #b8862b across the lintel of its gate. The upper half, from the top edge downward, is plain calm sky in #1a2140, even and empty. | Prioridad media. `tarkor-lockup-v.svg` en la mitad superior, por composición. Tiene que leerse a 200 px de ancho, que es como se ve en la rejilla de la Deck. Si una semilla de `I1` convence, se prueba antes su recorte a 704 × 1056 |
| — | Cápsula horizontal | 920 × 430 PNG | — | `E4`, recortada | — | El logo, por composición, como en `E4` |
| — | Fondo de la ficha | 1920 × 620 PNG | — | `E5` | — | Sin logo: Steam lo superpone |
| — | Logo | 1280 × 720 PNG con transparencia | — | `tarkor-lockup-v.svg` rasterizado | — | No se genera |
| — | Icono | 256 × 256 PNG | — | `E14` | — | No se genera |

## 4. Lo que no se pide, y por qué

- **El emblema, el logo y «TARKOR» generados.** Los pinta mal cualquier modelo; salen de los SVG.
- **Iconos de 64 px o menos generados.** A ese tamaño, el emblema simple en SVG, rasterizado.
- **Pictogramas de los cuatro perfiles** (Mínimo, Ligero, Equilibrado, Máximo). Pedirían un recuento (una a cuatro
  gemas) que el modelo no garantiza, y el nombre con sus etiquetas ya los distingue.
- **Ilustraciones en las pantallas 2 a 6.** Son pantallas que explican y piden permiso: una imagen compite con el
  texto que hay que leer antes de pulsar (principio 2 de [`11`](11-diseno-del-frontal.md)).
- **Números del riel, bordes, filetes lisos y el medidor de memoria.** CSS: cambian con el estado o con un dato.
- **Pantalla de arranque.** No hay: mientras carga la ventana se ve su color de fondo (`wood-950`), que se fija en
  la configuración de la ventana.
- **Icono de pestaña, cursor, fondo de imagen de disco de macOS.** Tauri no enseña el primero; el cursor lo
  descartó la hoja de Tarkor; no hay versión de macOS.
- **Capturas del juego para la página del repo.** Son capturas, no generaciones; GVIG tiene su plantilla (`E12`).

## 5. De dónde sale cada propuesta

Contraste con las referencias de diseño del proyecto. Están citadas de cómo son esos productos, sin volver a
abrirlos en esta sesión: lo que dependa de una versión concreta se comprueba al implementarlo.

| Propuesta | Referencia | Qué se toma |
|---|---|---|
| Lateral y cabecera de marca en el instalador de Windows (`I1`, `I2`) | **Steam** | Su instalador de Windows enseña la marca en la columna lateral de la bienvenida y del final, y un distintivo pequeño en el resto de páginas |
| Cabecera solo con el emblema, sin escena (`I2`); mismo icono para instalar y para abrir (`I5`) | **Instalador de Ollama** | No decora: el icono y el nombre, y el mismo icono en el acceso directo |
| Portada en la bienvenida con una sola acción debajo (`I3`) | **Asistente de LM Studio**, **Ollama** | La primera pantalla es una imagen de marca y un botón |
| La misma portada en «Listo», sobre el botón **Jugar** (`I3`) | **Steam**, **Heroic** | La ficha del juego: el arte arriba y «Jugar» debajo |
| Sin imagen en «Descarga»: barra, cifras y texto (`E7`) | **Steam**, **Heroic**, **itch.io** | Las pantallas de descarga son datos; itch.io deja la carátula en pequeño |
| Un mismo pictograma con la gema en cuatro colores para los estados (`#17`) | **Heroic**, **Steam** | Un glifo por estado, siempre en el mismo sitio de la fila |
| Juego de imágenes para la biblioteca de la Deck (`I6`, `E4`, `E5`) | **Steam**, **Heroic** | Steam define las cinco imágenes; Heroic, al añadir un juego a Steam, las copia él mismo en vez de pedírselas al jugador |
| Imagen social del repo (`E3`) | **itch.io** | La carátula que acompaña al enlace cuando se comparte |

## 6. Dudas para la usuaria

1. **Fondo del icono (`E14`).** Las peticiones de GVIG dicen «disco `night-950`»; su hoja (§9), «emblema simple
   sobre madera 950». Recomendado: **noche**, porque el icono vive fuera del juego (escritorio, barra de tareas,
   biblioteca) y esa es la regla de la marca. Hay que corregirlo en GVIG, no aquí.
2. **La portada (`I3`) mete una noche dentro del asistente**, que se decidió de madera. La hoja de Tarkor solo deja
   dos noches dentro del juego (`E6` y el cielo `#6`), y la propuesta de marca del 2026-11-10 nombra «la portada del
   instalador» entre las piezas de noche. Recomendado: sí, enmarcada, y solo en «Bienvenida» y «Listo».
3. **Cómo llega el pedido a GVIG.** Desde aquí no se toca ese repo. Lo natural es una sesión allí que lea este
   documento y añada un bloque «Instalador» (`I1`, `I3`, `I4`, `I6`) y el perfil `lateral`.
4. **Quién copia la entrega.** La carpeta `entrega/` de GVIG no se sube: los archivos solo están en el equipo que
   generó. O los copia la usuaria a este repo, o la sesión de `INS-58` se abre en ese equipo.

## 7. Orden de trabajo y cómo se da por buena cada pieza

1. **`E14`** (icono): quita el rombo azul de todo. Con él salen `I5` e `I2`, que no se generan.
2. **`I1`** (lateral): con `I2` e `I5`, el instalador de Windows queda completo.
3. **`#17`** y **`E7`**: las dos piezas que el asistente enseña en cada instalación.
4. **`I3`** (portada), si la duda 2 se resuelve que sí.
5. **`I6`**, `E4` y `E5`, antes de `INS-51`.
6. **`I4`**, `#2`, `#3`, `#5`, `#9`, `E13`: texturas y adornos; el CSS de hoy vale mientras tanto.

Una pieza se da por buena con el **veredicto de la usuaria** y con esto:

- 60/30/10 a ojo, oro pintado hasta un 10 %, y el logo, donde va, lo más claro de la pieza.
- Sin letras, figuras, luna ni morado. Zona libre lisa de verdad.
- Texto sobre textura con contraste de 4,5:1 o más. Texturas repetidas 4 × 4 sin costura.
- Pictogramas legibles a 20 px y en gris. `I6`, legible a 200 px de ancho.
- `I1` e `I2`: BMP de 24 bits, sin alfa, en su medida exacta.
- Entre todas las del asistente, 1 MB como mucho.

**No se da por probado con tests** (`INS-58` lo deja pendiente de `INS-8`, `INS-51` e `INS-52`): cómo se ven el
lateral y la cabecera en un Windows al 100 % y al 150 %; el icono en la barra de tareas clara y oscura; las imágenes
en la biblioteca de la Deck.
