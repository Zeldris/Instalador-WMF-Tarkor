# Empaquetado con Tauri

**Estado: plataformas decididas (2026-09-28); detalles técnicos a validar en la prueba de
concepto.** Tauri (v2) sobre Electron ya estaba decidido. Nuevo: la primera versión es **solo
Windows y Linux** (x86_64). macOS queda fuera de la v1.

## Por qué Tauri y no Electron

Tauri usa el webview del sistema operativo (WebView2 en Windows, WebKitGTK en Linux) en vez de
empaquetar un Chromium completo, así que el instalador pesa bastante menos. Decidido en la
investigación original (`docs/arquitectura/20-instalador-distribuible.md` del repo del juego).

## Procesos

```
Tarkor (Tauri, Rust)
 ├─ ventana (webview): asistente de primer arranque o juego
 ├─ sidecar 1: Ollama        127.0.0.1:<puerto libre>   modelos en <datos>/modelos
 └─ sidecar 2: backend Node  127.0.0.1:<puerto libre>   base de datos en <datos>/tarkor.sqlite
```

Tauri arranca los dos sidecars al abrir, los para al cerrar, y es el único que conoce los puertos.

### Puerto del backend: dinámico

Hoy es fijo (`3001`). En un equipo ajeno puede estar ocupado, así que Tauri busca un puerto libre y
se lo pasa al backend por `PORT`. Consecuencias:

- `VITE_API_URL` se fija al compilar, así que el frontend **no** puede saber el puerto de
  antemano. Cambio necesario en el juego: que `frontend/src/lib/api.ts` pida la URL al arrancar
  (a Tauri, vía `window.__TAURI__` o una variable inyectada en la página) y solo use
  `VITE_API_URL`/`localhost:3001` como respaldo fuera de Tauri. Es un cambio pequeño y aislado.
- **CORS:** el webview carga la página desde un origen propio de Tauri (`http://tauri.localhost`
  en Windows, `tauri://localhost` en Linux), no desde `localhost`. Hoy el backend acepta cualquier
  origen (`cors, { origin: true }` en `server.ts`); en la build empaquetada se restringe a esos
  orígenes.
- El backend escucha **solo en 127.0.0.1**, nunca en todas las interfaces.

### Ciclo de vida

- Tauri espera a que `GET /health` del backend responda antes de mostrar el juego.
- Si un sidecar se cae a mitad de partida: se reinicia solo **una vez**; si vuelve a caer, se
  muestra la pantalla "El motor del juego se ha detenido" (ver
  [`11-diseno-del-frontal.md`](11-diseno-del-frontal.md)) con opciones de reintentar y de ver el
  registro.
- Al cerrar la ventana se paran los dos procesos (en Windows, con un *Job Object* para que no
  queden huérfanos si Tauri muere de golpe).

### El backend como binario

Ver [`10-proteccion-del-codigo-y-build.md`](10-proteccion-del-codigo-y-build.md): runtime de Node
22 + bundle compilado a bytecode (preferido) o Bun compilado (reserva). `pkg`/`nexe` descartados.

## Build por plataforma

### Windows

- **Formato:** instalador `.exe` con **NSIS**, instalación **solo para el usuario actual**, sin
  permisos de administrador (`installMode: currentUser`). El `.msi` se descarta: está pensado para
  instalaciones de sistema.
- **WebView2:** viene de serie en Windows 10 y 11. Para equipos donde falte, se usa el
  *bootstrapper* de Tauri, que lo descarga durante la instalación.
- **Idioma del instalador:** castellano.
- **Desinstalación:** registrada en "Aplicaciones instaladas". Página propia preguntando si
  conservar partidas y modelos de IA (ver `07`).
- **Firma de código: ABIERTO.** Sin firmar, Windows muestra "Windows protegió su PC" y hay que
  pulsar "Más información → Ejecutar de todas formas". Además, un ejecutable con Node y bytecode
  dentro es propenso a falsos positivos del antivirus. Opciones:
  - Azure Trusted Signing (~10 $/mes) — comprobar si admite particulares en España.
  - Certificado de firma clásico (~200-400 €/año).
  - Sin firma en la v1, explicando el aviso en la página de descarga, y firmar más adelante.

### Linux

- **Formato principal:** `.AppImage`. Funciona en casi cualquier distro y en la Steam Deck sin root.
- **Opcional:** `.deb` para Ubuntu/Debian.
- **Compilado en Ubuntu 22.04** (glibc más antigua = compatible con más distros).
- **Sin firma de código;** se publica `SHA256SUMS`.
- **Steam Deck:** se instala en modo escritorio. Se documenta cómo añadirlo como "juego ajeno a
  Steam" para lanzarlo desde el modo juego. Probar en la Deck es obligatorio antes de dar la v1
  por terminada.

### Fuera de la v1

- macOS (evita la cuenta de desarrollador de Apple y la notarización).
- ARM (Windows ARM, Linux ARM).

## Tamaño estimado del instalador

| Pieza | Tamaño aprox. |
|---|---|
| Tauri + asistente + frontend del juego | 15-25 MB |
| Runtime de Node + backend | 40-90 MB |
| Motor de Prisma (si hace falta) | ~15 MB |
| Imágenes de la Enciclopedia (`backend/uploads/images`) | ~270 MB |
| Base de datos plantilla (catálogo + lore indexado) | a medir |
| **Instalador** | **~350-450 MB** |
| Ollama (descarga en primer arranque) | 50 MB - 1,5 GB según gráfica |
| Modelos (descarga en primer arranque) | 1,3-9,4 GB según perfil (11,3 GB el experimental), ver `12` |

Las imágenes son lo que más pesa del instalador: convertirlas a WebP con buena calidad podría
reducirlo a la mitad (a valorar).

## Qué falta antes de implementar

- Prueba de concepto: Tauri + backend sidecar + Ollama sidecar en Windows y en la Deck.
- Decidir la firma de Windows.
- Medir el tamaño real de la base de datos plantilla.
