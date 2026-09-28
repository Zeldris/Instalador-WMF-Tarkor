# Flujo de instalación

**Estado: decidido el reparto (2026-09-28); firma de Windows abierta.** Petición de Álvaro
(2026-09-16): explicar bien todo lo que el usuario acepta antes de instalarlo y validar después que
la instalación quedó correcta.

## Instalador y asistente de primer arranque

Los instaladores que genera Tauri (NSIS en Windows, AppImage en Linux) solo copian ficheros: no
pueden arrancar el backend, descargar modelos ni comprobar que la IA responde. Además, el AppImage
de Linux no tiene instalador. Por eso el trabajo se reparte en dos partes:

| | **Instalador** (Windows) | **Asistente de primer arranque** (Windows y Linux, dentro de la app) |
|---|---|---|
| Cuándo | Al ejecutar el `.exe` descargado | La primera vez que se abre Tarkor, y otra vez si no se completó |
| Qué hace | Copia la app, crea accesos directos, registra el desinstalador | Consentimiento, análisis del equipo, elección de perfil, descargas, validación |
| Descarga algo | No | Sí: Ollama y los modelos (con permiso explícito) |
| Pantallas | Estándar de NSIS en castellano | Diseño propio con el estilo del juego (ver [`11-diseno-del-frontal.md`](11-diseno-del-frontal.md)) |

El consentimiento importante (qué se descarga, cuánto ocupa, qué datos se tocan) vive en el
**asistente**, porque es donde de verdad se descarga algo y porque así es igual en las dos
plataformas. El instalador de Windows solo muestra un resumen corto.

## Instalador de Windows (NSIS)

1. **Bienvenida + resumen** en castellano: qué es Tarkor, que es gratuito, que en el primer arranque
   se pedirá permiso para descargar el motor de IA (3-9 GB según el equipo).
2. **Licencia y avisos** en lenguaje claro (ver [`08-legal-y-privacidad.md`](08-legal-y-privacidad.md)).
   Casilla sin marcar.
3. **Carpeta de instalación:** por defecto `%LOCALAPPDATA%\Programs\Tarkor`, modificable.
4. **Progreso** y **fin**, con la casilla "Abrir Tarkor ahora" marcada.

Sin permisos de administrador, solo para el usuario actual.

## Asistente de primer arranque

Pantallas en detalle: [`11-diseno-del-frontal.md`](11-diseno-del-frontal.md).

1. **Bienvenida** — qué va a pasar, en 4 pasos, y cuánto tardará aproximadamente.
2. **Qué se instala y qué no se hace** — consentimiento informado:
   - Qué se descarga (motor de IA Ollama + modelos), de dónde, cuánto ocupa.
   - Dónde se guarda todo (carpeta de datos, abajo).
   - Qué permisos usa: disco y red solo para estas descargas. Nada de cámara, micrófono,
     ubicación ni contactos.
   - Qué no hace: no envía la partida a ningún sitio, no pide cuenta, no tiene telemetría, no deja
     nada arrancando con el sistema.
   - Casilla sin marcar + botón "Aceptar y continuar". Enlace a "Ver todos los detalles legales".
3. **Permiso para analizar el equipo** — ver [`09-deteccion-de-equipo-y-perfiles.md`](09-deteccion-de-equipo-y-perfiles.md).
4. **Resultado y elección de perfil.**
5. **Descarga** de Ollama y de los modelos del perfil, con progreso, pausa y reanudación.
6. **Validación** (abajo).
7. **Listo** → Jugar.

Si se cierra la app a medias, al volver a abrirla el asistente continúa donde se quedó (estado en
`config.json`).

## Validación

Después de las descargas, antes de decir "todo listo", el asistente comprueba en orden:

| # | Comprobación | Cómo | Si falla, se le dice al jugador |
|---|---|---|---|
| 1 | Espacio y permisos de la carpeta de datos | Escribir y borrar un fichero de prueba | "No se puede escribir en la carpeta de datos (…). Comprueba el espacio libre." |
| 2 | Base de datos | Copiar la plantilla si no existe, aplicar migraciones | "No se pudo preparar la base de datos de partidas." |
| 3 | Motor del juego | Arrancar el backend y esperar `GET /health` | "El motor del juego no arranca." |
| 4 | Catálogo del mundo | Recuento de filas esperadas (NPCs, lugares, objetos, lore) | "Faltan datos del mundo; reinstala el juego." |
| 5 | Motor de IA | Arrancar Ollama y consultar `/api/tags` | "No se pudo iniciar el motor de IA." |
| 6 | Modelos | Cada modelo del perfil presente y con la suma esperada | "El modelo X no se descargó bien. [Reintentar descarga]" |
| 7 | Narración de prueba | Petición corta al narrador y al embeddings | "La IA no responde. Puede que el equipo se haya quedado sin memoria: prueba un perfil más ligero." |

Cada fallo muestra **qué** falló en lenguaje de jugador, un botón de reintentar esa comprobación, y
"Ver detalles" / "Copiar informe" con el registro técnico para pedir ayuda. Nunca un error genérico
ni un *stack trace* a la vista.

## Dónde vive cada cosa

| | Windows | Linux |
|---|---|---|
| App | `%LOCALAPPDATA%\Programs\Tarkor` | donde el jugador guarde el `.AppImage` (o `/usr` con el `.deb`) |
| Datos (partidas, `config.json`) | `%APPDATA%\Tarkor` | `~/.local/share/tarkor` |
| Motor de IA y modelos | `%LOCALAPPDATA%\Tarkor\ia` | `~/.local/share/tarkor/ia` |
| Registros | `%LOCALAPPDATA%\Tarkor\registros` | `~/.local/state/tarkor/registros` |

Los datos viven **fuera** de la carpeta de la app: actualizar o reinstalar nunca toca las partidas.

## Desinstalación

- **Windows:** el desinstalador de NSIS pregunta, con dos casillas **sin marcar**:
  - "Borrar también mis partidas guardadas"
  - "Borrar también el motor de IA y los modelos (X GB)"
- **Linux (AppImage):** no hay desinstalador. En Ajustes hay un botón "Borrar datos del juego"
  que ofrece lo mismo, y la página de descarga explica qué carpetas borrar a mano.

## Checklist de buenas prácticas

| Práctica | Decisión para Tarkor |
|---|---|
| Comprobar requisitos antes de instalar | En el asistente, con el análisis del equipo (`09`) |
| Elegir carpeta de instalación | Sí (Windows), con ruta por defecto por usuario |
| Detectar instalación previa y actualizar en vez de duplicar | Sí (NSIS lo hace con el mismo identificador de app) |
| No sobrescribir partidas al actualizar | Sí: datos fuera de la carpeta de la app + copia de seguridad antes de migrar |
| Desinstalador limpio que pregunte por las partidas | Sí (arriba) |
| Firma de código | **ABIERTO**, ver [`04-empaquetado-tauri.md`](04-empaquetado-tauri.md) |
| Verificación de integridad | `SHA256SUMS` en cada release; Ollama y modelos verificados al descargar |
| Sin permisos de administrador | Sí |
| Desinstalador visible en el panel del sistema | Sí (Windows) |
| Registros accesibles para pedir ayuda | Sí: "Copiar informe" en errores y en Ajustes |
| Nada en segundo plano sin avisar | Sí: nada arranca con el sistema; Ollama y el backend se paran al cerrar |
| Actualizaciones automáticas | Fuera de la v1. Se deja preparado el plugin de actualizaciones de Tauri para la v2 |
| Idioma | Castellano en instalador, asistente y juego |

## Abierto

- Firma de código en Windows (ver `04`).
