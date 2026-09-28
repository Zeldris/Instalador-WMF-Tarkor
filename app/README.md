# App de escritorio de Tarkor

Envoltorio Tauri v2 del juego: asistente de primer arranque, análisis del equipo, perfiles de IA y
(más adelante) gestión de los procesos del backend y de Ollama. Diseño en
[`../docs/11-diseno-del-frontal.md`](../docs/11-diseno-del-frontal.md); plan en
[`../docs/05-plan-de-trabajo.md`](../docs/05-plan-de-trabajo.md).

## Estructura

| Carpeta | Qué hay |
|---|---|
| `nucleo/` | Rust sin interfaz: detección de equipo (`equipo.rs`), perfiles y máximo seguro (`perfiles.rs`), `config.json` y carpetas (`config.rs`). Con tests. |
| `src-tauri/` | App de Tauri: expone el núcleo al asistente como comandos. |
| `src/` | Asistente en React. Textos en `textos.ts`; tipos espejo de Rust en `tipos.ts`. |

`src/simulacion.ts` simula la descarga y la comprobación hasta la fase 0.5: no debe llegar a una
release.

## Requisitos

- Node 22 y Rust estable.
- Linux: `libwebkit2gtk-4.1-dev libgtk-3-dev librsvg2-dev libayatana-appindicator3-dev libxdo-dev libssl-dev`.
- Windows: WebView2 (viene con Windows 10/11).

## Comandos

```sh
npm install
npm run dev                      # solo el asistente, en el navegador, con un equipo de ejemplo
npm run tauri dev                # la app real, con detección de equipo de verdad
npm test                         # tests del asistente
cargo test -p tarkor-nucleo      # tests del núcleo
cargo run -p tarkor-nucleo --example analizar   # qué detectaría en este equipo (útil en la Steam Deck)
npm run tauri build              # instaladores (.exe en Windows; .AppImage y .deb en Linux)
```

`TARKOR_DATOS=/ruta` cambia la carpeta de datos (para pruebas sin tocar la real).

## Prueba de punta a punta (Linux)

Recorre el asistente en la app instalada pulsando los botones por su texto, guarda una captura de
cada pantalla, comprueba `config.json` y vuelve a abrir la app para ver que no repite el asistente.

```sh
sudo apt install webkit2gtk-driver xvfb   # driver WebDriver de WebKit y pantalla virtual
cargo install tauri-driver --locked
npm run tauri build
sudo dpkg -i target/release/bundle/deb/Tarkor_*_amd64.deb
export TARKOR_DATOS=$(mktemp -d)
xvfb-run -a sh -c 'tauri-driver & D=$!; trap "kill $D" EXIT; sleep 2; node e2e/asistente.e2e.mjs /usr/bin/tarkor capturas'
```
