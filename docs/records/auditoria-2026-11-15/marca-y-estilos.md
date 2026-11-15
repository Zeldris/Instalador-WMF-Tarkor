# Auditoría 2026-11-15: marca y estilos del front

Subagente `sonnet`, solo lectura, sobre `bdb36af`; contraste calculado con los hex reales, sin capturas. Sin verificar
todavía en la sesión principal. Base: `app/src/estilos.css` (único CSS), `app/src/*.tsx`, `app/src-tauri/icons/`,
docs 11 y 13, y `frontend/src/index.css` del juego.

## Media

1. **La marca de docs 11/13 no está aplicada** (INS-56 abierta): faltan `gold-*`, `stone-*`, `night-*`,
   `crystal-deep`; «TARKOR» no va en oro (`.marca`, `estilos.css:38`); `h1` en Cinzel 600 y no 700 (`:57`); el filete
   (`:60`) y el foco usan el azul `accent`, que el doc 11 reserva para estados. El `index.css` del juego en `main`
   todavía no tiene `gold`/`night`. Mientras, `.filete` y `.pasos li.actual` podrían pasar a oro.
2. **Contraste por debajo de 4,5:1**:
   | Par | Ratio | Sitio |
   |---|---|---|
   | `.btn.pri` `#fff` sobre `accent-600` | 3,92 | `:69` |
   | Ídem hover sobre `accent-500` | 2,66 | `:70` |
   | Número del paso actual, `wood-100` sobre `accent-600` | 3,12 | `:46` |
   | Pasos pendientes, `wood-400` sobre `wood-800` | 4,14 | `:41` |
   | `.escala`, `wood-500` sobre `wood-800` | 2,35 | `:96` |
   | `.riel .pie` e icono pendiente, `wood-500` sobre `iron-800` | 2,91 | `:47`, `:148` |

   Propuesta: `.btn.pri` con fondo `#2a7099` (~5:1) o texto `iron-900` sobre `accent-500` (~6,9:1); hover aclarando el
   borde; `.escala`, `.pie` y pendientes a `wood-300`.
3. **Sin modo claro** (`color-scheme: dark` fijo): coherente con el juego; declararlo en doc 11 como decisión.
4. **Barras de progreso sin semántica** (`pantallasIa.tsx:151,167`, `componentes.tsx:77`): falta
   `role="progressbar"` con `aria-valuenow/min/max` y `aria-label`.
5. **Foco recortado** en el control segmentado: `.seg { overflow: hidden }` (`:128`) con `outline-offset: 2px`
   (`:72`). Propuesta: `.seg button:focus-visible { outline-offset: -2px }`.
6. **Bordes de controles a 1,59:1** (`.btn`, `.seg`: `wood-600` sobre `wood-800`, `:67`, `:128`); WCAG 1.4.11 pide
   3:1. Propuesta: `wood-400` (4,1:1).

## Baja

7. Valores sueltos: `#fff` (`:69`, `:151`, contra la regla del doc 13), `rgba(...)` (`:52`); radios 4–12 px y 999,
   tamaños de letra 11–28 px y espaciados 6–38 px sin escala. Propuesta: tokens `--r-*`, `--t-*`, `--sp-*`, `--on-accent`.
8. Estilos en línea que duplican clases: `componentes.tsx:343` (ya está `.tarjeta-caja .aviso`), `:414` (ya está
   `pre.licencia`), `App.tsx:118` (error `position: fixed` que tapa la barra inferior), `componentes.tsx:298` y
   `pantallas.tsx:47` (`marginTop`).
9. Faltan `--accent2-500/600` (la rejilla de hierro del doc 13 usa `accent2-600`): con INS-56.
10. El spinner con `prefers-reduced-motion` queda estático y su estado solo se nota por el borde: añadir texto o
    `aria-label` «en curso».
11. Rombos vacíos `wood-600` sobre `wood-900` a 1,82:1 (`:123`); `aria-label` lo cubre; `wood-500` se vería mejor.
12. Letra de 11 px (`.etiqueta`, `.escala`, `.ficha dt`, `.marca small`, `.marca-perfil span`) y objetivos táctiles
    pequeños (`.seg button` ~32 px, `.enlace` ~20 px): mínimo 12 px y 36–40 px pensando en la Steam Deck.

## Coherencia entre pantallas

- Tres formas de error: `.error` con `role="alert"` (casi todas), `pantallas.tsx:103` sin `role`, y el flotante de
  `App.tsx:118`.
- Carga: texto `…` con `role="status"` o spinner solo en comprobaciones; sin componente común.
- «Reintentar / Reintentando… / Reintentar ahora» repetidos en `textos.ts:127,151,251`: un objeto común.
- `aria-live="polite"` y `role="status"` mezclados: unificar.

## Recursos

- Fuentes: se empaquetan los subsets cyrillic/greek/vietnamese de Inter y cada peso en woff y woff2 (más de 60
  archivos en `app/dist/assets`). Importar solo `latin` y `latin-ext` en woff2 ahorra unos 200 KB.
- Licencias de Cinzel e Inter (OFL-1.1) declaradas en `app/src/licencias/generadas/terceros.json`.
- Iconos provisionales y ligeros; imágenes pendientes de INS-58.

## Bien

Tokens `wood/iron/accent/moss/danger/cost` idénticos al juego; foco visible global; fuentes locales; contraste alto
en el texto principal (`wood-100` sobre `wood-800` 11,9:1); `prefers-reduced-motion`; `role="alert"`/`status`,
`aria-pressed`, `aria-current` y `aria-expanded` bien usados; tono del doc 11 respetado.
