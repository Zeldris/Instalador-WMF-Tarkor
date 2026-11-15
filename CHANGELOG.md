# Registro de cambios

Los cambios de cada versión del instalador de Tarkor. El formato sigue
[Keep a Changelog](https://keepachangelog.com/es-ES/1.1.0/) y las versiones, [SemVer](https://semver.org/lang/es/).
Cada PR a `main` apunta lo suyo en `[Unreleased]`; al cerrar una versión del
[roadmap](docs/05-plan-de-trabajo.md), `python3 tools/dev/version.py publicar X.Y.Z` la pasa a su sección con fecha,
y el tag `vX.Y.Z` crea el release con esas notas (`.github/workflows/release.yml`).

## [Unreleased]

### Añadido

- Una sola versión del instalador en `app/src-tauri/tauri.conf.json`; `tools/dev/version.py` la copia a
  `package.json`, `package-lock.json`, `Cargo.toml` y `Cargo.lock`, y el check comprueba que coinciden (FLU-10).
- Este registro de cambios y el release de GitHub por tag `vX.Y.Z`, de momento sin binarios (FLU-10).
- Auditoría de requisitos del juego con diez propuestas de tareas (FLU-9).

### Seguridad

- Dependencias del núcleo y la app al día frente a los avisos de RustSec: `rustls`, `rustls-webpki`, raíces de
  certificados, `tokio`, `rustix`; `zip` 2 → 9 y `ruzstd` 0.8 → 0.9 en la extracción del motor (INS-64).
- Dependabot semanal (npm, cargo y acciones) y job `auditoria` en el CI con `cargo audit` y `npm audit` (INS-64).

### Cambiado

- Accesibilidad del asistente (INS-66): contraste de al menos 4,5:1 en el botón principal y los textos tenues, bordes de controles visibles, barras de progreso y medidor de memoria con `role="progressbar"`, foco del control segmentado sin recortar y letra mínima de 12 px.
- Fuentes del asistente: solo los subconjuntos `latin` y `latin-ext` de Cinzel e Inter en woff2 (`app/src/fuentes.css`):
  de 54 archivos y 1,5 MB a 12 y 260 KB (INS-67).
- El plan de trabajo pasa a ser un roadmap por versiones (`0.1` a `1.0`), que lee `roadmap.py` (FLU-10).

## [0.1.0] - 2026-11-14

Primera versión: todo lo fusionado en `main` hasta `9fce3d1` (fases 0, 1 y 4 del plan anterior). Sin release con
binarios todavía.

### Añadido

- Asistente de primer arranque (Tauri v2, React y TypeScript) con los tokens visuales del juego (INS-1).
- Detección de equipo y perfiles de IA, incluidos Mínimo y Ligero, y perfiles por encima del máximo seguro con aviso
  (INS-2, INS-13, INS-14).
- Catálogo de modelos y ajustes de Ollama por equipo; Ollama portable con descarga fijada por SHA256 y modelos con
  progreso (INS-3b, INS-5).
- Gestor de procesos auxiliares con puerto libre, comprobación de salud y un reinicio automático (INS-4).
- Descargas reales de punta a punta con autopausa por red y calentamiento del narrador (INS-42).
- Ajustes → Rendimiento de la IA y pantalla de motor detenido (INS-43).
- Carpeta del motor y los modelos elegible y movible; «Reparar» (INS-48, INS-49).
- Instalador NSIS en castellano por usuario, AppImage y `.deb`, y «Borrar datos del juego» (INS-44, INS-45, INS-59).
- Pantalla «Licencias de terceros» generada en el build (INS-47).
- Hoja de estilos del instalador con sus peticiones de imágenes (INS-57).
- Flujo de trabajo Galivelop-workflow v0.6.0 (FLU-1, FLU-3…FLU-9).

[Unreleased]: https://github.com/zeldris/instalador-wmf-tarkor/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/zeldris/instalador-wmf-tarkor/releases/tag/v0.1.0
