# Fuentes por tipo de componente

Las que se consultan primero en el paso 3, por tipo. Una afirmación se cita a la fuente que la **posee** (la del
proyecto o el organismo que la publica), con la fecha de consulta; un blog o un agregador solo para encontrar la
primaria. Los rankings son ruido para un uso concreto: orientan, el banco decide.

| Tipo | Fuente | Para qué |
|---|---|---|
| Runtimes | [endoflife.date](https://endoflife.date/docs/api/v1/) (`/api/v1/products/<producto>/`, en beta) y la página oficial de versiones del runtime | fin de soporte y versión LTS actual |
| Imágenes de contenedor | página de la imagen oficial (Docker Hub, etiquetas) | etiqueta actual de la misma familia |
| Dependencias | registro del ecosistema (npm, PyPI, crates.io, pkg.go.dev) y el CHANGELOG o las releases del proyecto | versión actual, cambios incompatibles |
| Vulnerabilidades | [OSV](https://osv.dev) (`osv-scanner scan --lockfile <lock>`, si está instalado: [lockfiles admitidos](https://google.github.io/osv-scanner-v1/supported-languages-and-lockfiles/)) | avisos de las versiones en uso |
| Salud de una dependencia | [OpenSSF Scorecard](https://github.com/ossf/scorecard) | mantenimiento, para elegir entre candidatos |
| Qué manifiestos existen | [Renovate managers](https://docs.renovatebot.com/modules/manager/) | ecosistemas que `inventario.py` aún no lee |
| Acciones de CI | releases del repositorio de la acción; avisos de deprecación de GitHub (runners, Node de las acciones) | versión mayor actual |
| Modelos locales | ficha del modelo (Hugging Face: licencia, idiomas, contexto), la biblioteca del motor (Ollama: etiquetas y tamaños; [`/api/show`](https://docs.ollama.com/api/tags.md) para los instalados) | tamaño, cuantizaciones, idiomas |
| Calidad de modelos de escritura | [EQ-Bench Creative Writing v3](https://eqbench.com/creative_writing.html) y la tabla de la ficha del modelo | candidatos que probar en el banco |
| Riesgos de IA | [OWASP LLM Top 10](https://genai.owasp.org/llm-top-10/) | inyección de prompt, salida insegura, cadena de suministro de modelos |
| Anillos del informe | [Thoughtworks Tech Radar](https://www.thoughtworks.com/radar) | qué significa Adoptar, Probar, Evaluar, Retirar |

## Huecos

- Ninguna fuente fiable dice **cómo escribe un modelo en español** narrativo: los rankings de escritura creativa
  son en inglés. Para eso está el banco con los casos del proyecto.
- La **memoria real** de un modelo en el hardware mínimo no sale de la ficha (depende de `num_ctx`, cuantización de
  la caché y motor): el tamaño en disco solo descarta los que no caben ni de lejos; el resto se mide.
- La API de endoflife.date está en beta: si falla, la página oficial de versiones del runtime.
