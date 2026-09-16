# Ollama y los modelos de IA

**Estado: ABIERTO.** Este es el hueco más grande del plan — el documento original
(`docs/20-instalador-distribuible.md` del repo del juego) no lo resuelve. Aquí se deja planteado el
problema y las alternativas reales conocidas, para decidir en una sesión futura.

## El problema

Hoy, en desarrollo, Ollama es un requisito previo que el desarrollador instala y gestiona a mano:

| Uso | Modelo | Cómo se obtiene hoy |
|---|---|---|
| Narrador (narración principal) | `tarkor-narrador` (`FROM qwen2.5:7b`) | `ollama pull qwen2.5:7b` + `ollama create tarkor-narrador -f Modelfile` |
| Cronista (clasificación de acciones) | `qwen2.5:1.5b-instruct` | `ollama pull qwen2.5:1.5b-instruct` |
| Sugerencias ("Sugerir" bajo demanda) | `qwen3.5:4b` | `ollama pull qwen3.5:4b` |
| Embeddings (RAG de lore) | `nomic-embed-text` | `ollama pull nomic-embed-text` |

Cuatro modelos, varios GB de descarga en total, y un paso de construcción propio (`Modelfile`) para
el narrador. Un jugador final no es un desarrollador — no se le puede pedir que abra una terminal,
instale Ollama, y ejecute cuatro `ollama pull` más un `ollama create`.

Además, el `Modelfile` es un artefacto del propio proyecto (vive en `backend/`) — si cambia en el
futuro, `tarkor-narrador` hay que reconstruirlo con el mismo comando `ollama create`. Eso también
tiene que resolverse de alguna forma para el instalador (¿se reconstruye en el primer arranque?
¿se empaqueta ya construido?).

## Por qué esto no es opcional

El narrador es el corazón del juego — sin un modelo corriendo, Tarkor no puede generar ni una sola
narración. A diferencia de la generación de prompts de imagen (que sí puede quitarse del instalador
sin más, ver `06-inventario-exclusiones.md`), Ollama y sus modelos tienen que estar presentes y
funcionando para que el juego sea jugable en absoluto.

## Alternativas a valorar (ninguna decidida todavía)

### A. El instalador gestiona Ollama por el jugador

El instalador comprueba si Ollama está instalado; si no, guía al jugador a instalarlo (enlazando al
instalador oficial de Ollama para su sistema operativo) o lo descarga él mismo como parte del propio
proceso de instalación. En el primer arranque de la app, hace `pull` de los 4 modelos con una barra
de progreso visible — puede tardar varios minutos y pesar varios GB, así que el jugador necesita
saber que está pasando.

Preguntas abiertas de este camino:
- ¿Se puede embeber el instalador oficial de Ollama dentro del propio paquete de Tarkor, o solo se
  puede enlazar/descargar en el momento? (Depende de la licencia/distribución de Ollama — sin
  investigar todavía.)
- ¿Qué pasa si el jugador ya tiene Ollama instalado por otro motivo (otra app, otro proyecto)? ¿El
  instalador debe detectarlo y reutilizarlo, o siempre gestiona su propia instancia?
- El `Modelfile` de `tarkor-narrador`: ¿se ejecuta `ollama create` en el primer arranque del jugador
  (necesita el `Modelfile` empaquetado y el modelo base `qwen2.5:7b` ya descargado), o hay alguna
  forma de distribuir el modelo ya construido sin pasar por ese paso?

### B. Ollama queda fuera del instalador, requisito previo manual

El instalador solo empaqueta Tarkor en sí. Se documenta claramente (en el propio flujo de
instalación, o en un README que se le muestra al jugador) que debe instalar Ollama y los 4 modelos
por su cuenta antes de poder jugar — básicamente el mismo `docs/15-instalacion.md` § 6 del repo del
juego, pero dirigido a un jugador en vez de a un desarrollador.

Más simple de implementar, pero contradice bastante el objetivo original del instalador ("que cargue
como una app", sin pasos manuales) — un jugador normal probablemente no sepa qué es Ollama ni cómo
instalarlo desde una terminal.

### C. Modelos más pequeños / cuantizados para reducir la descarga

Sin investigar todavía si existen variantes más ligeras de los 4 modelos actuales que mantengan
calidad de narración aceptable, para reducir el tamaño total de la descarga del primer arranque.
Relacionado pero independiente de la decisión A/B de arriba — aplicaría en cualquiera de los dos
caminos.

## Qué falta antes de decidir

- Investigar de verdad las opciones de distribución de Ollama (licencia, si se puede embeber un
  instalador de terceros, tamaño real de cada modelo descargado).
- Decidir si el paso de `ollama create tarkor-narrador` se hace en el primer arranque del jugador o
  se resuelve de otra forma.
- Probar tiempos reales de descarga/arranque en una máquina "limpia" (sin Ollama previo) para saber
  si la experiencia del primer arranque es aceptable o hay que replantear el enfoque.
