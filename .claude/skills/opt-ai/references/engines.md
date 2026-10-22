# Engines: where each log field comes from, and the knobs

`(?)` = **not verified** against the engine's documentation: check before relying on it. `app.duration_ms` and
`app.ttft_ms` are always measured by the client. An engine without a field leaves it absent, not `null`.

| Log field | Ollama `/api/generate` | Ollama `/api/embed` | llama.cpp server | LM Studio, vLLM (OpenAI-compatible) |
|---|---|---|---|---|
| `gen_ai.usage.input_tokens` | `prompt_eval_count` | `prompt_eval_count` | `timings.prompt_n` or `tokens_evaluated` (?) | `usage.prompt_tokens` |
| `gen_ai.usage.output_tokens` | `eval_count` | n/a | `timings.predicted_n` or `tokens_predicted` (?) | `usage.completion_tokens` |
| `gen_ai.response.finish_reason` | `done_reason` | n/a | `stop_type` (?) | `choices[0].finish_reason` |
| `app.load_ms` | `load_duration` (ns, /1e6) | `load_duration` (ns) | none: model loads at start (omit) | none per call (?) |
| `app.prefill_ms` | `prompt_eval_duration` (ns) | n/a | `timings.prompt_ms` | none (?) |
| `app.decode_ms` | `eval_duration` (ns) | n/a | `timings.predicted_ms` | none (?) |
| `app.ttft_ms` | client, when streaming | n/a | client, when streaming | client, when streaming |
| `app.num_ctx` (asked) | `options.num_ctx` | `options.num_ctx` (?) | `-c` at start (?) | vLLM `--max-model-len` (?) |
| `gen_ai.request.max_tokens` | `options.num_predict` | n/a | `n_predict` | `max_tokens` |
| `app.keep_alive` | `keep_alive` (request) | `keep_alive` | n/a (always loaded) | LM Studio model TTL (?); vLLM n/a |
| Prompt cache reused | not exposed (?) | n/a | `timings.cache_n` (?) | `usage.prompt_tokens_details.cached_tokens` (vLLM, ?) |

- Ollama durations are **nanoseconds**; the log uses milliseconds.
- `app.truncated` is computed by the client: `input_tokens` >= `num_ctx`. It is only available when the call
  passes `num_ctx` or the client reads the loaded model's effective value (Ollama `/api/ps`, else `/api/show`);
  otherwise `medir.py` shows "-" for truncation, and the engine's own log is the place to look.
- A new engine is one more column here and a translation in the project's client.

## Knobs, in the order step 3 tries them

Names to confirm in the engine's documentation `(?)`.

| Knob | Ollama | llama.cpp server | Effect and trade-off |
|---|---|---|---|
| Flash attention | `OLLAMA_FLASH_ATTENTION=1` | `-fa` | Less memory and faster long prompts; needs hardware support |
| KV cache type | `OLLAMA_KV_CACHE_TYPE=q8_0` (or `q4_0`) | `--cache-type-k/-v` | About half the KV memory at `q8_0`; `q4_0` saves more and can cost quality |
| Parallel requests | `OLLAMA_NUM_PARALLEL` | `-np` | Each slot multiplies KV memory; 1 on a tight machine |
| Models loaded at once | `OLLAMA_MAX_LOADED_MODELS` | one model per server | More loaded models avoid reloads but compete for memory |
| Keep-alive | `OLLAMA_KEEP_ALIVE`, `keep_alive` | n/a | Long keeps the model warm (no cold start) and holds memory; 0 reloads every call |
| Context length | `OLLAMA_CONTEXT_LENGTH`, `options.num_ctx` | `-c` | Memory grows with it; too small silently truncates the prompt |
| Max output tokens | `options.num_predict` | `n_predict` | Caps runaway generation; too low cuts the answer (`length`) |
| Quantisation | model tag (`q4_K_M`, `q8_0`...) | GGUF file | Lower bits: less memory, faster, some quality lost; measure with the quality cases |
| GPU offload | automatic; `OLLAMA_GPU_*`/backend variables | `-ngl` | Layers on the GPU dominate speed; a silent CPU fallback is the usual cause of a sudden slowdown |
| Threads, batch | `options.num_thread`, `num_batch` | `-t`, `-b` | CPU-only tuning; leave cores for the rest of the app |
| Fixed prefix first | prompt design | prompt design | The engine reuses cached prefix tokens; put stable text before variable text |

- **Per-model, not per-call (Ollama):** `keep_alive` and `num_ctx` belong to the loaded model. A call with another
  `num_ctx` reloads the runner, and the last call to arrive sets how long the model stays loaded. When proposing
  or changing one, search every call site of that model and align them on one shared constant; a fallback path
  that uses a different value reloads the model another path just warmed.
- **Memory first:** on the minimum profile a model that does not fit evicts another and every turn pays a reload.
  Check the weights, the KV cache at the target context and the other loaded models together, not one by one.
- **Silent CPU fallback:** an engine started without its GPU environment runs on CPU and the round is not
  comparable; the profile check in step 0 exists to catch it.
