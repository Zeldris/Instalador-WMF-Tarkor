# App de escritorio de Tarkor

Envoltorio Tauri v2 del juego: asistente de primer arranque, análisis del equipo, perfiles de IA y
(más adelante) gestión de los procesos del backend y de Ollama. Diseño en
[`../docs/11-diseno-del-frontal.md`](../docs/11-diseno-del-frontal.md); plan en
[`../docs/05-plan-de-trabajo.md`](../docs/05-plan-de-trabajo.md).

## Estructura

| Carpeta | Qué hay |
|---|---|
| `nucleo/` | Rust sin interfaz: detección de equipo (`equipo.rs`), perfiles y máximo seguro (`perfiles.rs`), `config.json` y carpetas (`config.rs`), cliente de Ollama y uso de la gráfica (`ollama.rs`), vigilancia de procesos (`procesos.rs`) y texto de «Copiar informe» (`informe.rs`). Con tests. |
| `src-tauri/` | App de Tauri: expone el núcleo al asistente como comandos (también `uso_ia`, `cambiar_perfil`, `modelos_sobrantes`, `borrar_modelos`, `informe`, `motor_detenido` y `reintentar_motor`, y el evento `motor-detenido` que emite un hilo que vigila el motor cada 2 s) y el plugin de portapapeles. |
| `src/` | Asistente en React. Textos en `textos.ts`; tipos espejo de Rust en `tipos.ts`. |

`src/simulacion.ts` simula la descarga y la comprobación hasta `INS-5`: no debe llegar a una
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

Un test nuevo del núcleo vive en el `mod tests` del mismo archivo que el arreglo, así que
`rojo-sin-arreglo.sh` se llevaría también el test: se comprueba a mano, quitando solo la lógica del arreglo,
viendo fallar el test con su motivo y devolviéndola.

## Prueba de punta a punta (Linux)

Recorre el asistente en la app instalada pulsando los botones por su texto, guarda una captura de
cada pantalla, comprueba `config.json` y vuelve a abrir la app para ver que no repite el asistente.

```sh
sudo apt install webkit2gtk-driver xvfb   # driver WebDriver de WebKit y pantalla virtual
cargo install tauri-driver --locked
npm run tauri build
sudo dpkg -i target/release/bundle/deb/Tarkor_*_amd64.deb
export TARKOR_DATOS=$(mktemp -d)
# Con un Ollama falso (e2e/ollama-falso.mjs) para recorrer el asistente sin descargar modelos:
export TARKOR_OLLAMA_URL=http://127.0.0.1:11499
xvfb-run -a sh -c 'node e2e/ollama-falso.mjs 11499 & F=$!; tauri-driver & D=$!; trap "kill $D $F" EXIT; sleep 2; node e2e/asistente.e2e.mjs /usr/bin/tarkor capturas'
```

Sin `TARKOR_OLLAMA_URL` la app instala y arranca el motor real (1,4 GB). En una red que bloquea
el registro de modelos, `E2E_ESPERA_ERROR_RED=1` comprueba que el error se explica y se puede
reintentar.

### Ajustes → Rendimiento de la IA y motor detenido (`INS-43`)

`e2e/rendimiento.e2e.mjs` usa el motor **propio** de la app, no uno externo (con `TARKOR_OLLAMA_URL` no hay
reinicio automático, ni modelos sobrantes, ni pantalla de motor detenido): prepara una carpeta de datos nueva
con un `bin/ollama` que es `e2e/ollama-falso.mjs serve`, acaba el asistente con el perfil Mínimo y comprueba
dónde corre la IA, el cambio de perfil con su progreso, el borrado de sobrantes, el informe sin la carpeta
personal, dos caídas del motor y «Reintentar». `HOME` debe acabar en un nombre de usuario de 4 letras o más
(con él comprueba que el informe no lo cuenta) y `TARKOR_OLLAMA_URL` no debe estar puesta. Usa el binario
que se acaba de compilar (`npx tauri build --no-bundle` → `target/release/tarkor`) o el instalado.

```sh
export HOME=$(mktemp -d)/lucianita TARKOR_DATOS=$(mktemp -d); mkdir -p $HOME; unset TARKOR_OLLAMA_URL
xvfb-run -a sh -c 'tauri-driver & D=$!; trap "kill $D" EXIT; sleep 2; node e2e/rendimiento.e2e.mjs target/release/tarkor capturas'
```

## Motor de IA sin el asistente

```sh
cargo run --release -p tarkor-nucleo --example motor minimo   # o ligero, equilibrado...
```

Instala el motor real, lo arranca con los ajustes del perfil para este equipo, descarga los
modelos y hace la narración de prueba mostrando los tokens por segundo. Pensado para medir en la
Steam Deck o en un Windows (`INS-8`).
