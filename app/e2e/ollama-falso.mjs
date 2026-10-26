// Ollama falso para la prueba de punta a punta: imita las rutas de la API que usa la app
// (versión, modelos, descarga con progreso por capas, generación y /api/ps), para recorrer el
// asistente sin descargar gigas ni depender del registro de modelos.
//
// Dos modos:
//  - `node e2e/ollama-falso.mjs [puerto]` → un Ollama «externo»: imprime la URL y la app lo usa con
//    TARKOR_OLLAMA_URL (todo en memoria).
//  - `node e2e/ollama-falso.mjs serve` → el motor «propio», lanzado por la app como `ollama serve`
//    (rendimiento.e2e.mjs lo instala detrás de un `bin/ollama`): escucha en OLLAMA_HOST y guarda los
//    modelos y cuál está cargado en OLLAMA_MODELS/falso.json, para sobrevivir a los reinicios.
//    `/api/delete` borra de verdad y `/api/ps` da `size` y `size_vram` (60 % en la gráfica).
//    FALSO_PASO_MS alarga el progreso de `/api/pull` (80 ms por paso por defecto).
//    FALSO_CORTES_PULL=n hace que las n primeras `/api/pull` respondan con el error de «sin internet»
//    del registro (no such host), como Ollama sin red; las siguientes, con normalidad.

import { createServer } from 'node:http'
import { mkdirSync, readFileSync, writeFileSync } from 'node:fs'
import { join } from 'node:path'

const propio = process.argv[2] === 'serve'
const [host, puertoPropio] = (process.env.OLLAMA_HOST ?? '127.0.0.1:11499').split(':')
const puerto = propio ? Number(puertoPropio) : Number(process.argv[2] ?? 11499)
const esperar = (ms) => new Promise((ok) => setTimeout(ok, ms))
const pasoMs = Number(process.env.FALSO_PASO_MS ?? 80)
let cortesPull = Number(process.env.FALSO_CORTES_PULL ?? 0)
// Tamaños en disco (bytes) parecidos a los reales; el resto, 500 MB.
const TAMANOS = { 'qwen2.5:7b': 4.7e9, 'qwen2.5:1.5b-instruct': 1.0e9, 'qwen3.5:2b': 2.7e9, 'nomic-embed-text:latest': 2.74e8 }
const tamano = (m) => TAMANOS[m] ?? 5e8

// Estado: modelos descargados (en el motor propio, en OLLAMA_MODELS/falso.json) y el que está cargado.
const archivo = propio ? join(process.env.OLLAMA_MODELS ?? '.', 'falso.json') : null
const estado = { modelos: [], cargado: null }
if (archivo) {
  try { Object.assign(estado, JSON.parse(readFileSync(archivo, 'utf8'))) } catch { /* primera vez */ }
}
const guardar = () => { if (archivo) { mkdirSync(join(archivo, '..'), { recursive: true }); writeFileSync(archivo, JSON.stringify(estado)) } }
const etiqueta = (m) => (m === 'nomic-embed-text' ? 'nomic-embed-text:latest' : m)

async function cuerpo(req) {
  let datos = ''
  for await (const trozo of req) datos += trozo
  return datos ? JSON.parse(datos) : {}
}

createServer(async (req, res) => {
  const json = (v, estado = 200) => {
    res.writeHead(estado, { 'content-type': 'application/json' })
    res.end(JSON.stringify(v))
  }
  const ruta = req.url
  if (ruta === '/api/version') return json({ version: '0.34.3-falso' })
  if (ruta === '/api/tags') return json({ models: estado.modelos.map((name) => ({ name, size: tamano(name) })) })
  if (ruta === '/api/ps') {
    // Un modelo cargado reparte su memoria: 60 % en la gráfica y el resto en el procesador.
    const m = estado.cargado
    return json({ models: m && estado.modelos.includes(m) ? [{ name: m, size: 2e9, size_vram: 1.2e9 }] : [] })
  }
  if (ruta === '/api/delete' && req.method === 'DELETE') {
    const { model } = await cuerpo(req)
    if (!estado.modelos.includes(etiqueta(model))) return json({ error: `model '${model}' not found` }, 404)
    estado.modelos = estado.modelos.filter((m) => m !== etiqueta(model))
    if (estado.cargado === etiqueta(model)) estado.cargado = null
    guardar()
    return json({})
  }
  if (ruta === '/api/pull') {
    const { model } = await cuerpo(req)
    res.writeHead(200, { 'content-type': 'application/x-ndjson' })
    res.write(JSON.stringify({ status: 'pulling manifest' }) + '\n')
    if (cortesPull > 0) {
      cortesPull--
      res.write(JSON.stringify({ error: `pull model manifest: Get "https://registry.ollama.ai/v2/library/${model.split(':')[0]}/manifests/${model.split(':')[1] ?? 'latest'}": dial tcp: lookup registry.ollama.ai: no such host` }) + '\n')
      return res.end()
    }
    for (let i = 1; i <= 5; i++) {
      await esperar(pasoMs)
      res.write(JSON.stringify({ status: `pulling ${model}`, digest: `sha256:${model}`, total: 500, completed: i * 100 }) + '\n')
    }
    res.write(JSON.stringify({ status: 'success' }) + '\n')
    if (!estado.modelos.includes(etiqueta(model))) estado.modelos.push(etiqueta(model))
    guardar()
    return res.end()
  }
  if (ruta === '/api/embed') {
    // Vector determinista de 768 dimensiones (como nomic-embed-text) a partir del texto.
    const { input } = await cuerpo(req)
    const textos = Array.isArray(input) ? input : [input]
    const vector = (t) => {
      let h = 2166136261
      return Array.from({ length: 768 }, (_, i) => {
        h = Math.imul(h ^ (t.charCodeAt(i % Math.max(1, t.length)) || 0) ^ i, 16777619)
        return ((h >>> 0) % 2000) / 1000 - 1
      })
    }
    return json({ model: 'nomic-embed-text', embeddings: textos.map((t) => vector(String(t))) })
  }
  if (ruta === '/api/generate') {
    const { model } = await cuerpo(req)
    const hay = estado.modelos.find((d) => d.startsWith(model))
    if (!hay) return json({ error: `model '${model}' not found` }, 404)
    estado.cargado = hay
    guardar()
    return json({ response: ' La niebla del estrecho se abre y deja ver las hogueras de Berig. ', eval_count: 60, eval_duration: 5e9 })
  }
  json({ error: 'ruta desconocida' }, 404)
}).listen(puerto, propio ? host : '127.0.0.1', () => {
  // Como Ollama de verdad, que vuelca su configuración (con la carpeta personal) al registro al arrancar.
  if (propio) console.log(`time=falso level=INFO source=routes.go msg="server config" env="map[HOME:${process.env.HOME} OLLAMA_HOST:${host}:${puerto} OLLAMA_MODELS:${process.env.OLLAMA_MODELS}]"`)
  else console.log(`http://127.0.0.1:${puerto}`)
})
