# Arquitectura · recetario

Mantenida por `scout-updates`. Cada sección lleva su sello; para contrastar: `contrastar.py`.

## Restricciones

- Nube permitida; presupuesto de API bajo (≤ 20 €/mes).
- Idioma de las respuestas: español.

## Modelos de IA
<!-- sello: 2026-01-10 · abc1234 · .env.example -->

| Componente | Versión | Uso | Dónde se configura |
|---|---|---|---|
| Chat | `gpt-3.5-turbo` | sugerir recetas | `.env.example` `OPENAI_MODEL` |
| Embeddings | `text-embedding-ada-002` | búsqueda de recetas | `.env.example` `EMBEDDINGS_MODEL` |

## Runtimes
<!-- sello: 2026-01-10 · abc1234 · .nvmrc, package.json, Dockerfile -->

| Componente | Versión | Uso | Dónde se configura |
|---|---|---|---|
| Node.js | 16 | servidor | `.nvmrc`, `package.json` `engines`, `Dockerfile` |
| Python | sin fijar | scripts de datos | `requirements.txt` |
