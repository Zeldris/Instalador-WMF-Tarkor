# Flujo de instalación

**Estado: ABIERTO.** Petición explícita de Álvaro (2026-09-16): el instalador debe explicar bien
todo lo que el usuario acepta instalar antes de instalarlo, y debe haber una fase de validación
posterior para confirmar que la instalación quedó correcta. Este documento recoge esa idea y una
checklist de prácticas habituales en instaladores bien construidos, para no pasar nada por alto.
Nada de esto está decidido en detalle todavía — es el punto de partida para diseñar el flujo real.

## Las dos fases que ya se pidieron explícitamente

### 1. Consentimiento informado, antes de instalar

Antes de que el instalador toque el disco del usuario, tiene que explicar con claridad qué va a
hacer — no una licencia genérica ilegible, sino una pantalla real que un jugador entienda:

- Qué se va a instalar y dónde (la propia app Tarkor, y — según lo que se decida en
  [`03-ollama-y-modelos-ia.md`](03-ollama-y-modelos-ia.md) — posiblemente Ollama y varios GB de
  modelos de IA).
- Cuánto espacio en disco necesita en total (app + modelos de IA + base de datos).
- Qué permisos necesita (acceso a disco para guardar partidas, acceso a red para el primer arranque
  si descarga modelos, nada más — Tarkor no necesita cámara/micrófono/ubicación/contactos).
- Qué NO hace — no envía datos de la partida a ningún sitio, no requiere cuenta ni login (ver
  [`08-legal-y-privacidad.md`](08-legal-y-privacidad.md) para el detalle completo de privacidad).
- Confirmación explícita del usuario antes de proceder — no "aceptar" pre-marcado, una acción real.

### 2. Validación post-instalación

Tras copiar los archivos, antes de decir "instalación completada", el instalador comprueba que todo
quedó funcional de verdad — no solo que los ficheros se copiaron sin error de disco. Candidatos a
validar automáticamente:

- El backend sidecar arranca y responde (equivalente a un health-check simple).
- La base de datos SQLite se crea/migra correctamente en el primer arranque.
- Ollama está accesible y los modelos necesarios responden (si Ollama es parte del instalador —
  pendiente de decidir en `03-ollama-y-modelos-ia.md`).
- El catálogo del mundo pre-sembrado se cargó bien (un recuento simple de filas esperadas, por
  ejemplo).

Si algo falla, el instalador debe decir QUÉ falló en términos que el jugador entienda ("no se pudo
conectar con el motor de IA" en vez de un stack trace), no solo "error de instalación" genérico.

## Checklist de lo que un instalador serio suele cuidar

Lista de referencia general — cada punto se marca como aplica/no aplica/pendiente de decidir para
Tarkor en concreto, para no perder ninguno de vista:

| Práctica | ¿Aplica a Tarkor? |
|---|---|
| Comprobar requisitos del sistema antes de instalar (espacio en disco, SO compatible, RAM/CPU suficiente para correr el modelo de IA local) | Sí — el modelo del narrador corre localmente, necesita recursos reales |
| Permitir elegir carpeta de instalación (no forzar una ruta) | Pendiente de decidir |
| Detectar una instalación previa y ofrecer actualizar/reinstalar en vez de duplicar | Sí, relevante desde la v1 en adelante |
| No sobrescribir datos del usuario (partidas guardadas) al actualizar | Sí — crítico, la base de datos vive fuera de la carpeta de la app |
| Desinstalador limpio que borre lo que instaló, preguntando si conservar partidas guardadas | Sí |
| Firma de código del instalable (evita avisos de "editor desconocido" en Windows/macOS) | Ver `04-empaquetado-tauri.md` |
| Checksum/verificación de integridad del propio instalador descargado | Recomendable, a decidir |
| No requerir privilegios de administrador si no hace falta (instalar solo para el usuario actual) | Probablemente sí — sin admin, más simple y más seguro |
| Registrar un desinstalador visible en el panel de aplicaciones del SO | Sí (estándar de cualquier instalador) |
| Ofrecer logs de instalación accesibles si algo falla, para poder pedir ayuda/reportar el fallo | Recomendable |
| No instalar nada en segundo plano sin que el usuario lo sepa (servicios que arrancan solos con el SO, telemetría oculta) | Tarkor no debe hacer esto — ver `08-legal-y-privacidad.md` |
| Actualizaciones: ¿el instalador también gestiona actualizar la app a futuras versiones, o cada versión nueva es un instalador aparte? | Sin decidir, fuera del alcance de la v1 probablemente |

## Preguntas abiertas

- ¿El instalador se distribuye firmado desde el principio, o se acepta el aviso de "editor
  desconocido" en una primera versión y se firma más adelante? (Firmar cuesta dinero/trámite en
  algunas plataformas — a valorar dado que el proyecto es gratuito.)
- ¿Dónde vive exactamente la carpeta de datos del usuario (partidas guardadas, base de datos
  SQLite) para que sobreviva a una desinstalación/reinstalación? Convención estándar por SO
  (`%APPDATA%` en Windows, `~/Library/Application Support` en macOS, `~/.local/share` en Linux) —
  sin decidir el detalle todavía.
- Idioma del instalador — Tarkor está en castellano, ¿el instalador también lo está siempre, o se
  localiza?
