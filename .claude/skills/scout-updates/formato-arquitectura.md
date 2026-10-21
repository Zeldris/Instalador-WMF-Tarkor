# Formato de `arquitectura.md`

Inventario del proyecto al estilo de un SBOM/ML-BOM ([CycloneDX](https://cyclonedx.org/capabilities/mlbom/)), en
Markdown legible. Lo escribe y lo mantiene `scout-updates`; la usuaria puede editarlo (sobre todo las restricciones).

```markdown
# Arquitectura · <proyecto>

Mantenida por `scout-updates`. Cada sección lleva su sello; para contrastar: `contrastar.py`.

## Restricciones

- Hardware mínimo: <máquina>, <memoria total>, <memoria libre para la IA>.
- <local o nube>, <idioma>, <presupuesto>, <licencias admitidas>.

## Modelos de IA
<!-- sello: 2026-10-20 · 78667dc · backend/.env.example, backend/src/config/env.ts -->

| Componente | Versión | Uso | Dónde se configura |
|---|---|---|---|
| narrador | `modelo:etiqueta` (base, cuantización, tamaño) | narrar turnos | `env.ts` `OLLAMA_MODEL_NARRADOR` |

banco · narrador: casos `docs/scout/banco/narrador.jsonl`, rúbrica `docs/scout/banco/narrador-rubrica.md`
```

- **Secciones**, por tipo, solo las que tenga el proyecto: `Modelos de IA`, `Dependencias`, `Runtimes`,
  `Infraestructura y CI`, `Servicios externos`, `Planificados`. Su título es el nombre del foco
  (`/scout-updates runtimes`).
- **`Planificados`**: componentes diseñados y sin implementar. El sello lleva los documentos de diseño, y la sección
  dice qué restricciones les aplican si no son las generales (p. ej. corren con la aplicación cerrada).
- **`Restricciones`** no lleva sello ni se contrasta: la escribe la usuaria (paso 0) y es el filtro del paso 4.
- **Sello**, en la línea siguiente al título: `<!-- sello: AAAA-MM-DD · <commit corto> · ruta, ruta -->`. Las rutas
  son los archivos de donde sale la sección, relativas a la raíz. Al contrastar sin cambios, solo cambia la fecha; al
  reescribir, fecha y commit (`git rev-parse --short HEAD`).
- **Componente**: qué es, versión exacta (o el rango del manifiesto), para qué se usa en el proyecto y todos los
  sitios donde se fija (una migración los toca todos).
- **Dependencias**: las directas que importan (marco, ORM, cliente de IA, test); el resto se resume con su número y
  su lockfile. Las vulnerabilidades no se apuntan aquí: son del momento, las da la búsqueda.
- **`banco · <componente>`** (opcional, solo modelos generativos): dónde están los casos y la rúbrica del banco de
  calidad ([`banco-calidad.md`](banco-calidad.md)).
