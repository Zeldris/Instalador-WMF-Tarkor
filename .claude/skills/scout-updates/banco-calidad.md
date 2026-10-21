# Banco de calidad por pares

Compara modelos generativos con los **prompts reales** del proyecto, a ciegas y por pares, como hace
[EQ-Bench Creative Writing v3](https://eqbench.com/creative_writing.html). Mide calidad; la latencia es de otra
herramienta (en este repositorio, `opt-ai`) y no se mezcla.

## Casos

- 10-15 situaciones reales y variadas (no 15 de la misma), una línea JSONL cada una:
  `{"id", "system", "prompt", "contexto", "opciones": {"temperature", "num_ctx", "max_tokens"}}`.
- `system` y `prompt` son **los que recibe el modelo en el proyecto**, sin recortar: un prompt de juguete mide otra
  cosa. `contexto` es lo que ve el juez (la petición o la acción y lo anterior, en pocas líneas): la captura no lo
  sabe, así que se escribe a mano al elegir los casos; sin él, el juez solo ve la cola del prompt.
- Quita antes datos personales (nombres reales, identificadores, texto libre de usuarios).
- La ruta va en `arquitectura.md` (`banco · <componente>`), con la **rúbrica**: 4-6 criterios del proyecto (p. ej.
  coherencia con lo anterior, naturalidad en el idioma, fidelidad al mundo, ajuste de longitud, sin repeticiones).

## Pasada

```bash
B=.claude/skills/scout-updates/banco.py
python3 $B generar casos.jsonl --modelo <actual> --salida s-actual.jsonl     # también el modelo actual
python3 $B generar casos.jsonl --modelo <candidato> --salida s-cand.jsonl   # uno por candidato
python3 $B pares s-*.jsonl --casos casos.jsonl --salida pares.jsonl --clave clave.json
python3 $B juzgar pares.jsonl --juez <modelo> --rubrica rubrica.md --salida veredictos.jsonl
python3 $B resumen pares.jsonl clave.json veredictos.jsonl
```

- `--api openai --url <url>` para motores OpenAI-compatibles (llama.cpp, LM Studio, vLLM).
- Los candidatos, con la **misma configuración** que tendrían en el proyecto (`num_ctx`, temperatura). Si el proyecto
  es local y no hay motor a mano, una API con el mismo modelo sirve para la calidad (a mayor precisión que la
  cuantización local: dilo en el informe); memoria y latencia se miden después en el hardware mínimo. Una salida con `error` no entra en pares: se informa.
- Las salidas, pares y veredictos van a una carpeta temporal, no al repositorio.

## Juez

- **El agente, por defecto** (el que ejecuta la skill: Claude Code, u otro): lee `pares.jsonl` (nunca `clave.json`
  hasta el resumen) y escribe `veredictos.jsonl`, una línea por par: `{"par", "ganador": "X"|"Y"|"empate", "motivo"}`,
  aplicando la rúbrica. No depende de nada instalado. Con muchos pares, en un subagente para no llenar el contexto.
- **Un modelo con `banco.py juzgar`**, si la usuaria lo pide para ahorrar tokens: el más capaz disponible, distinto de
  los candidatos (un modelo tiende a preferirse a sí mismo). Su debilidad se dice en el informe y se calibra: el
  agente juzga 5-6 pares y se comparan.
- Cada caso se juzga **en los dos órdenes**, por el sesgo de posición de los jueces LLM
  ([arXiv 2406.07791](https://arxiv.org/abs/2406.07791)); si el ganador cambia al girarlo, cuenta como empate.

## Lectura del resumen

- **tasa**: victorias / jugadas (empate = 0,5). Con 10-15 casos, una diferencia menor de ~0,15 es ruido: dilo.
- **consistencia al girar** baja (< 0,6) o **gana X** lejos de 0,5 (> 0,65 o < 0,35): el juez es poco fiable;
  el resultado se informa como especulativo y se propone otro juez o que juzgue el agente.
- **Todas las cifras del informe y los fallos típicos de cada modelo salen de `resumen --detalle`**: cara a cara,
  puntos por caso y los motivos de los pares que pierde cada modelo, con el mismo conteo que la tasa. Un recuento
  propio cuenta distinto (el par que cambia al girarlo) y no cuadra con el ranking.
- Lee 2-3 pares de los que gana y pierde cada modelo antes de recomendar: la cifra no dice **por qué**.

## Decisión

Por la diferencia de tasa del candidato con el actual en el cara a cara:

- **gana por más de ~0,15**: se recomienda adoptarlo.
- **dentro del ruido** (menos de ~0,15 en cualquier sentido): deciden la memoria y la latencia, medidas en el hardware
  mínimo.
- **pierde por más de ~0,15**: se recomienda rechazarlo. Si una causa ajena al modelo pesa en el resultado (p. ej. el
  prompt), el motivo de `propuestas.md` dice qué cambio la quita, y la condición para reabrir es quedar **dentro del
  ruido** tras ese cambio.
