# Empaquetado con Tauri

**Estado: ABIERTO.** La elección de Tauri sobre Electron ya está decidida (ver
[`01-arquitectura-general.md`](01-arquitectura-general.md)), pero el detalle de cómo se empaqueta
el backend como sidecar, cómo se firma el instalador y cómo se genera build por plataforma no está
resuelto todavía.

## Por qué Tauri y no Electron

Tauri usa el webview del sistema operativo (WebView2 en Windows, WKWebView en macOS, WebKitGTK en
Linux) en vez de empaquetar un Chromium completo como hace Electron — el instalador resultante pesa
bastante menos. Ya decidido en la investigación original (`docs/20-instalador-distribuible.md` del
repo del juego, 2026-08-20); no hay motivo conocido para reabrir esta elección.

## El backend como sidecar

Tauri soporta arrancar un binario externo ("sidecar") junto con la propia app, y pararlo cuando la
app se cierra. El backend Node de Tarkor se arrancaría así — hablando por `localhost` con el
frontend, exactamente como hoy en desarrollo (el frontend ya lee `VITE_API_URL` con fallback a
`localhost:3001`, no necesita cambios).

Preguntas abiertas:

- **¿Cómo se empaqueta el backend Node como binario?** Node no es un binario nativo por sí mismo —
  hace falta algo como `pkg`, `nexe`, o el propio runtime de Node embebido junto con el código.
  Investigar qué opción encaja mejor con Tauri y con las dependencias reales del backend (Prisma
  Client, en concreto, suele requerir pasos especiales para empaquetarse bien porque genera código
  nativo según la plataforma).
- **Prisma Client y el motor de query nativo**: Prisma genera un binario de motor de query
  específico por plataforma (`libquery_engine`). Hay que asegurarse de que el binario correcto para
  cada plataforma de destino (Windows/macOS/Linux) viaja dentro del paquete del sidecar.
- **Puerto del backend**: hoy fijo en `3001` vía `.env`. En un instalador, ¿se mantiene fijo (riesgo
  de colisión si el jugador tiene otra cosa en ese puerto) o el sidecar elige un puerto libre y se
  lo comunica al frontend de alguna forma al arrancar?
- **Ciclo de vida**: qué pasa si el sidecar crashea a mitad de partida — ¿Tauri lo reinicia solo,
  o hay que implementar ese comportamiento? ¿Cómo se le informa al jugador si el backend no
  responde?

## Build por plataforma

- **Windows**: `.exe`/`.msi`. Investigar el mecanismo estándar de Tauri para cada uno y cuál encaja
  mejor con el flujo de consentimiento/validación descrito en
  [`07-flujo-de-instalacion.md`](07-flujo-de-instalacion.md).
- **macOS**: `.dmg`. Apple exige firma de código (notarización) para que la app no dé aviso de
  "desarrollador no identificado" — esto normalmente cuesta una cuenta de desarrollador de Apple de
  pago. A decidir si se acepta el aviso en una primera versión gratuita del proyecto, o se paga la
  cuenta.
- **Linux**: `.AppImage` (mencionado en la investigación original) u otros formatos que Tauri
  soporte (`.deb`, `.rpm`). Steam Deck/SteamOS (la máquina de desarrollo real de Álvaro) corre
  Linux — probar el instalador ahí es un paso obligatorio antes de dar el trabajo por terminado
  (ver [`05-plan-de-trabajo.md`](05-plan-de-trabajo.md), último paso).

## Firma de código

Relacionado con [`07-flujo-de-instalacion.md`](07-flujo-de-instalacion.md): firmar el instalador
evita avisos de "editor desconocido"/"origen no identificado" en Windows y macOS, pero tiene un
coste (certificados de pago, cuenta de desarrollador de Apple). Sin decidir si se firma desde la
primera versión o se acepta el aviso al principio, dado que el proyecto es gratuito.

## Qué falta antes de implementar

- Elegir y probar el mecanismo de empaquetado del backend Node como binario/sidecar.
- Confirmar que Prisma Client con SQLite (tras la migración de
  [`02-migracion-postgres-a-sqlite.md`](02-migracion-postgres-a-sqlite.md)) empaqueta limpio en las
  tres plataformas.
- Decidir el manejo de puerto (fijo vs. dinámico) del sidecar.
- Decidir la estrategia de firma de código por plataforma.
- Primera build de prueba real (aunque sea sin todo el contenido final) para validar que el patrón
  sidecar funciona en la práctica antes de invertir en el resto del plan.
