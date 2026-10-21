# Motores: de dónde sale cada campo del registro

Qué campo de la respuesta de cada motor rellena cada campo `gen_ai.*`/`app.*` de `docs/ia/opt-ai-registro.md`.
`(?)` = **no verificado** contra la documentación del motor (comprobar antes de fiarse). `app.duration_ms` y
`app.ttft_ms` los mide siempre el cliente. Un motor sin el campo lo deja ausente (no `null`).

| Campo del registro | Ollama `/api/generate` | Ollama `/api/embed` | llama.cpp server | LM Studio y vLLM (OpenAI-compatible) |
|---|---|---|---|---|
| `gen_ai.usage.input_tokens` | `prompt_eval_count` | `prompt_eval_count` | `timings.prompt_n` o `tokens_evaluated` (?) | `usage.prompt_tokens` |
| `gen_ai.usage.output_tokens` | `eval_count` | no aplica | `timings.predicted_n` o `tokens_predicted` (?) | `usage.completion_tokens` |
| `gen_ai.response.finish_reason` | `done_reason` | no aplica | `stop_type` (?) | `choices[0].finish_reason` |
| `app.load_ms` | `load_duration` (ns, /1e6) | `load_duration` (ns) | no hay: el modelo se carga al arrancar (se omite) | no hay por llamada (?) |
| `app.prefill_ms` | `prompt_eval_duration` (ns) | no aplica | `timings.prompt_ms` | no hay (?) |
| `app.decode_ms` | `eval_duration` (ns) | no aplica | `timings.predicted_ms` | no hay (?) |
| duración total del motor | `total_duration` (ns) | `total_duration` (ns) | suma de `timings` (?) | no hay: se usa la del cliente |
| `app.ttft_ms` | cliente, en streaming | no aplica | cliente, en streaming | cliente, en streaming |
| `app.num_ctx` (pedido) | `options.num_ctx` | `options.num_ctx` (?) | `-c` al arrancar (?) | `--max-model-len` en vLLM (?) |
| `gen_ai.request.max_tokens` | `options.num_predict` | no aplica | `n_predict` | `max_tokens` |
| `app.keep_alive` | `keep_alive` (petición) | `keep_alive` | no aplica (siempre cargado) | LM Studio: TTL del modelo (?); vLLM: no aplica |
| Caché de prompt reutilizada | no se expone (?) | no aplica | `timings.cache_n` (?) | `usage.prompt_tokens_details.cached_tokens` (vLLM, ?) |

Notas:

- Ollama devuelve las duraciones en **nanosegundos**; el registro, en milisegundos.
- `app.truncated` se calcula en el cliente: `input_tokens` ≥ `num_ctx`.
- Ajustes del paso 3 (flash attention, KV cache `q8_0`, paralelismo): en Ollama son variables de entorno del servidor
  (`OLLAMA_FLASH_ATTENTION`, `OLLAMA_KV_CACHE_TYPE`, `OLLAMA_NUM_PARALLEL`, `OLLAMA_MAX_LOADED_MODELS`; nombres a
  confirmar en su documentación, `(?)`); en llama.cpp, flags del servidor (`-fa`, `--cache-type-k/-v`, `-np`, `(?)`).
- En Ollama, `keep_alive` y `num_ctx` son **del modelo cargado**, no de la llamada (`QA-170`): una llamada con otro
  `num_ctx` recarga el runner y la última que llega fija cuánto sigue cargado. Al proponer o tocar uno, se buscan
  todas las llamadas a ese modelo (`grep -rn "ollamaModel<X>" backend/src`) y se alinean con una constante
  compartida (como `CTX_CRONISTA` en `narrador.ts`). Así se encontró que el respaldo de `narrar` recargaba el cronista
  de `clasificar` (`QA-168`).
- Un motor nuevo se añade con una columna aquí y su traducción en el cliente del proyecto.
