# Per-call log

One JSON object per line, in the file the project's log switch names; with the switch off, nothing is written.
Field names follow the OpenTelemetry GenAI vocabulary (`gen_ai.*`, status "Development" when this was written:
check it before relying on it); project-specific ones carry the `app.` prefix. Absent fields are omitted, never
`null`. `scripts/medir.py` reads this format.

| Field | Type | Meaning |
|---|---|---|
| `ts` | ISO 8601 UTC | End of the call |
| `gen_ai.operation.name` | `text_completion`, `chat`, `embeddings`, `retrieval` | Kind of call |
| `gen_ai.provider.name` | text | Engine: `ollama`, `llama.cpp`, `lmstudio`, `vllm` |
| `gen_ai.request.model` | text | Model asked for |
| `gen_ai.request.max_tokens` | integer | Max output tokens (`num_predict` or equivalent) |
| `gen_ai.usage.input_tokens` | integer | Prompt tokens |
| `gen_ai.usage.output_tokens` | integer | Generated tokens |
| `gen_ai.response.finish_reason` | text | `stop`, `length`, `error`... |
| `app.task` | text | The project's task name (a warm-up task is excluded from the analysis) |
| `app.machine_profile` | text | Machine profile; unset becomes `unknown` and `medir.py` warns |
| `app.num_ctx` | integer | Context length asked for, or the loaded model's effective one |
| `app.turn` | text | Id shared by the calls of one user-facing step; `medir.py` adds a per-turn table (needs `ts` and `app.duration_ms`) |
| `app.event` | text | A marker line with no call; `medir.py` ignores it |
| `app.keep_alive` | text | How long the model stays loaded |
| `app.duration_ms` | number | Whole call, measured by the client |
| `app.load_ms` | number | Model load time (above the cold threshold = cold start) |
| `app.prefill_ms` | number | Prompt reading |
| `app.decode_ms` | number | Generation |
| `app.ttft_ms` | number | Time to first token (streaming only) |
| `app.truncated` | boolean | Prompt was cut: `input_tokens` >= `num_ctx`, or prompt characters / 4 > `num_ctx` |
| `app.error` | text | Message if the call failed |
| `app.rag.query` | text | Retrieval query (`retrieval` only) |
| `app.rag.k` | integer | Chunks asked for |
| `app.rag.results` | list of `{id, score}` | Chunks returned, in order |
| `app.rag.embed_ms`, `app.rag.search_ms` | number | Query embedding and search time |

**Privacy:** `app.rag.query` stores what users typed and `app.error` can quote prompt fragments. The log is not
shared or pasted without cleaning it first.

## Quality cases

One line per case in the project's case file: `{"id": "...", "question": "...", "expected": ["<chunk id or
source>", ...], "origin": "<finding id or seed>", "cause": "absent|not_retrieved|ignored|null", "must_pass": true}`.
Use chunk ids that survive a reindex (a title or a source path, not a database id). The evaluation command prints,
per case, the rank of the first expected chunk, and overall recall@k and MRR. `must_pass` makes a miss in the
top-k exit non-zero.
