# Sources by component type

Consulted first in step 3. A claim is cited to the source that **owns** it (the project or body that publishes it),
with the consultation date; a blog or aggregator only helps find the primary one. Rankings are noise for a concrete
use: they orient, the project's own tests decide.

| Type | Source | For |
|---|---|---|
| Runtimes | [endoflife.date](https://endoflife.date/docs/api/v1/) (`/api/v1/products/<product>/`) and the runtime's official releases page | end of support, current LTS |
| Container images | the official image page (Docker Hub tags) | current tag of the same family |
| Dependencies | the ecosystem registry (npm, PyPI, crates.io, pkg.go.dev) and the project's CHANGELOG or releases | current version, breaking changes |
| Vulnerabilities | [OSV](https://osv.dev) (`osv-scanner scan --lockfile <lock>` if installed) and the ecosystem audit (`npm audit --json`, `cargo audit`, `pip-audit`) | advisories for the versions in use |
| Dependency health | [OpenSSF Scorecard](https://github.com/ossf/scorecard) | maintenance, to choose among candidates |
| Which manifests exist | [Renovate managers](https://docs.renovatebot.com/modules/manager/) | ecosystems `inventory.py` does not read yet |
| CI actions | the action's repository releases; GitHub deprecation notices (runners, Node of the actions) | current major version |
| Local models | the model card (licence, languages, context), the engine's library (tags and sizes) | size, quantisations, languages |
| AI risks | [OWASP LLM Top 10](https://genai.owasp.org/llm-top-10/) | prompt injection, unsafe output, model supply chain |
| Report rings | [Thoughtworks Tech Radar](https://www.thoughtworks.com/radar) | what Adopt, Trial, Assess, Hold mean |

## Gaps

- No reliable source says how a model writes in a given language or domain: public rankings are generic. The
  project's own cases decide.
- The **real memory** of a model on the minimum hardware does not come from its card (it depends on context size,
  cache quantisation and engine): disk size only discards what does not fit by far; the rest is measured.
- The endoflife.date API may be in beta: if it fails, use the runtime's official releases page.
