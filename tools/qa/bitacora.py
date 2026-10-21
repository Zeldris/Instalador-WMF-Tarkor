#!/usr/bin/env python3
"""Traída de Tarkor (los `QA-xx` de aquí son de su historial). En el instalador el roadmap es el plan
(`docs/05-plan-de-trabajo.md`) y una tarea se cierra con su casilla (`- [x] **INS-7** …`) o tachada.

QA-69 (retro del 2026-10-13): la bitácora tiene una fila «Tarea en curso» por rama y cada una es corta.

Las dos cuentas escribían en la misma celda: acabó con dos tareas y dos «Siguiente» que se
contradecían. Cada fila se llama «Tarea en curso · `<rama>`» y su texto no pasa de TOPE caracteres
(unas 5 líneas, `CLAUDE.md`), y no hay dos filas de la misma rama. Lo corre `.githooks/pre-push` sobre
la bitácora de cada commit que se sube (con la ruta como argumento).

QA-85 (retro del 2026-10-14): `bitacora.py --cerradas <base> <sha>` (también desde el pre-push) comprueba
que cada tarea que pasa a tachada (`~~…~~`) o marcada (`[x]`) en un roadmap entre esos dos commits sale también tachada en
«Hecho recientemente» de la bitácora del último. Se cerró `QA-63` en los roadmaps y la bitácora seguía en
«diagnosticado».

QA-115 (retro del 2026-10-19): `bitacora.py <ruta> --fecha AAAA-MM-DD` falla si la fila «Actualizado» es
anterior a esa fecha. El pre-push la pasa con la fecha de cada commit que cambia la bitácora: estuvo dos
días en 2026-10-17 con commits del 19.

QA-145 (retro del 2026-10-20): `bitacora.py --ajenas <commit> <rama> [--compartida]` falla si el commit
cambia una fila «Tarea en curso · `<otra rama>`» o una fila compartida de «Estado actual» (Ramas de
trabajo, Último commit en main, Hito…). Cada rama escribe solo en la suya (`QA-136`). «Actualizado» y
«Tests» se tocan en casi cada commit y no se vigilan. Lo corre `prepush-ramas.sh` en cada commit nuevo que
no es un merge; para un cambio compartido a propósito, `BITACORA_COMPARTIDA=1 git push`.

QA-182 (retro del 2026-10-21): `bitacora.py --en-curso <base> <sha>` avisa, sin fallar, de cada tarea `🚧` de un
roadmap que nombran los commits entre esos dos y cuya entrada no cambia: la de `QA-176` siguió diciendo «Falta:
banco del narrador» con el banco hecho en otra rama. Lo corre `prepush-ramas.sh`.
"""
import re
import subprocess
import sys
from pathlib import Path

TOPE = 600
LIBRES = {"Actualizado", "Tests"}  # filas compartidas que cada commit puede tocar (QA-145)
ROADMAPS = "docs/05-plan-de-trabajo.md"  # en Tarkor, la carpeta docs/producto/
RUTA_BITACORA = "docs/registros/traspaso.md"


ID = r"[A-Z]+-\d+[a-z]?"
RANGO = r"\s*(?:…|\.\.\.|–|—|\ba\b)\s*"
SEPARADOR = rf"(?:{RANGO}|\s*(?:,|\by\b)\s*)"


def ids_tachados(texto: str) -> set[str]:
    """Tareas cerradas en un texto: los identificadores con los que empieza cada tachado (`~~QA-80 · …~~`,
    `~~`QA-62`, `QA-64`~~`), con los rangos (`QA-77`…`QA-80`) desplegados. Un tachado seguido de «→» es
    una tarea movida a otro hito, no cerrada, y lo que se nombra dentro del título (`(ver QA-5)`) no cuenta."""
    ids: set[str] = set()
    for m in re.finditer(r"~~(.*?)~~(\s*→)?", texto):
        if m.group(2):
            continue
        tramo = re.sub(r"[*`]", "", m.group(1))
        cabeza = re.match(rf"\s*({ID}(?:{SEPARADOR}{ID})*)", tramo)
        if not cabeza:
            continue
        run = cabeza.group(1)
        ids |= set(re.findall(ID, run))
        for a, b in re.findall(rf"({ID}){RANGO}({ID})", run):
            (pa, na), (pb, nb) = a.rsplit("-", 1), b.rsplit("-", 1)
            if pa == pb and na.isdigit() and nb.isdigit() and int(na) < int(nb):
                ids |= {f"{pa}-{n}" for n in range(int(na), int(nb) + 1)}
    return ids


MARCADA = re.compile(rf"^\s*[-*]\s*\[[xX]\]\s*(?:\*\*)?`?({ID})\b", re.M)


def ids_cerrados(texto: str) -> set[str]:
    """Tareas cerradas en un roadmap: tachadas o con la casilla marcada (`- [x] **INS-7** …`, el plan del instalador)."""
    return ids_tachados(texto) | set(MARCADA.findall(texto))


def git(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], capture_output=True, text=True)


def cerradas_sin_bitacora(base: str, sha: str) -> list[str]:
    """Tareas tachadas en los roadmaps entre `base` y `sha` que no salen tachadas en «Hecho recientemente».
    Las que ya están tachadas en `origin/main` (llegan con un merge de main, `QA-72`) son de otra rama."""
    diff = git("diff", "-U0", base, sha, "--", ROADMAPS).stdout
    quitadas = "\n".join(l[1:] for l in diff.splitlines() if l.startswith("-") and not l.startswith("---"))
    puestas = "\n".join(l[1:] for l in diff.splitlines() if l.startswith("+") and not l.startswith("+++"))
    nuevas = ids_cerrados(puestas) - ids_cerrados(quitadas)
    for ruta in git("diff", "--name-only", base, sha, "--", ROADMAPS).stdout.split():
        en_main = git("show", f"origin/main:{ruta}")
        if en_main.returncode == 0:
            nuevas -= ids_cerrados(en_main.stdout)
    if not nuevas:
        return []
    r = git("show", f"{sha}:{RUTA_BITACORA}")
    bitacora = r.stdout if r.returncode == 0 else ""
    hecho = bitacora.split("## Hecho recientemente", 1)[1].split("\n## ", 1)[0] if "## Hecho recientemente" in bitacora else ""
    return sorted(nuevas - ids_tachados(hecho))


def filas_estado(texto: str) -> dict[str, list[str]]:
    """Filas «| **Clave** | texto |» de la tabla de «## Estado actual» (no de otras tablas del archivo): clave (con la
    rama en «Tarea en curso · rama») -> textos, en orden. Con una clave repetida se guardan todos, para que un
    cambio en una de las repetidas no quede oculto por la otra."""
    seccion = texto.split("## Estado actual", 1)[1].split("\n## ", 1)[0] if "## Estado actual" in texto else ""
    filas: dict[str, list[str]] = {}
    for l in seccion.splitlines():
        m = re.match(r"\|\s*\*\*(.+?)\*\*\s*\|(.*)\|\s*$", l)
        if m:
            filas.setdefault(m.group(1).replace("`", "").strip(), []).append(m.group(2).strip())
    return filas


def filas_ajenas(antes: str, despues: str, rama: str) -> list[str]:
    """Claves de las filas que cambian entre `antes` y `despues` y no son de `rama` ni de las LIBRES."""
    a, d = filas_estado(antes), filas_estado(despues)
    propia = f"Tarea en curso · {rama}"
    return [k for k in sorted(a.keys() | d.keys())
            if a.get(k) != d.get(k) and k != propia and k not in LIBRES]


ENTRADA = re.compile(rf"[-|]\s*(?:\[([ xX])\]\s*)?(~~)?\s*(?:\*\*)?`?({ID})\b")


def entradas(texto: str) -> dict[str, str]:
    """Entradas de un roadmap: id -> su texto, desde la línea que la abre (`- **QA-1 · …`, `| REI-53 | …`,
    `- [ ] **INS-7** …`) hasta la siguiente sin sangría. Las tachadas (cerradas o movidas) y las marcadas no se guardan."""
    res: dict[str, str] = {}
    actual = None
    for l in texto.splitlines():
        if l[:1] in (" ", "\t") and actual:
            res[actual] += "\n" + l
            continue
        m = ENTRADA.match(l)
        actual = m.group(3) if m and not m.group(2) and (m.group(1) or ' ') == ' ' else None
        if actual:
            res[actual] = l
    return res


def en_curso_sin_tocar(base: str, sha: str) -> list[str]:
    """Tareas `🚧` que nombran los commits de `base..sha` (sin merges) y cuya entrada en los roadmaps no cambia."""
    nombradas = set(re.findall(ID, git("log", "--no-merges", "--format=%B", f"{base}..{sha}").stdout))
    if not nombradas:
        return []
    antes: dict[str, set[str]] = {}
    despues: dict[str, set[str]] = {}
    for ruta in (r for r in git("ls-tree", "--name-only", sha, ROADMAPS).stdout.split() if r.endswith(".md")):
        for commit, destino in ((base, antes), (sha, despues)):
            r = git("show", f"{commit}:{ruta}")
            for i, t in (entradas(r.stdout) if r.returncode == 0 else {}).items():
                destino.setdefault(i, set()).add(t)
    return sorted(i for i in nombradas if any("🚧" in t for t in despues.get(i, ())) and despues[i] == antes.get(i))


def contenido(commit: str) -> str:
    r = git("show", f"{commit}:{RUTA_BITACORA}")
    return r.stdout if r.returncode == 0 else ""


if sys.argv[1:2] == ["--ajenas"]:
    resto = [a for a in sys.argv[2:] if a != "--compartida"]
    if len(resto) != 2:
        sys.exit("Uso: python3 tools/qa/bitacora.py --ajenas <commit> <rama> [--compartida]")
    if "--compartida" in sys.argv[2:]:
        sys.exit(0)
    commit, rama = resto
    padre = git("rev-parse", "--verify", "-q", f"{commit}^").stdout.strip()
    ajenas = filas_ajenas(contenido(padre) if padre else "", contenido(commit), rama)
    for k in ajenas:
        print(f"bitácora: el commit cambia la fila «{k}», que no es de {rama}; cada rama escribe solo en su fila "
              "«Tarea en curso» (QA-136). Si es a propósito (cerrar un PR, fila compartida), "
              "sube con `BITACORA_COMPARTIDA=1 git push` o corre bitacora.py con --compartida")
    sys.exit(1 if ajenas else 0)

if sys.argv[1:2] == ["--en-curso"]:
    if len(sys.argv) != 4:
        sys.exit("Uso: python3 tools/qa/bitacora.py --en-curso <commit base> <commit>")
    for t in en_curso_sin_tocar(sys.argv[2], sys.argv[3]):
        print(f"aviso: los commits nombran {t}, en curso (🚧), y su entrada del roadmap no cambia; si avanzó o queda "
              "algo distinto pendiente, apúntalo ahí (QA-182)")
    sys.exit(0)

if sys.argv[1:2] == ["--cerradas"]:
    if len(sys.argv) != 4:
        sys.exit("Uso: python3 tools/qa/bitacora.py --cerradas <commit base> <commit>")
    faltan = cerradas_sin_bitacora(sys.argv[2], sys.argv[3])
    for t in faltan:
        print(f"bitácora: {t} se tacha en el roadmap; apúntala tachada en «Hecho recientemente» de la bitácora")
    sys.exit(1 if faltan else 0)

args = sys.argv[1:]
fecha = None
if "--fecha" in args:
    i = args.index("--fecha")
    if i + 1 >= len(args) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", args[i + 1]):
        sys.exit("Uso: python3 tools/qa/bitacora.py [<ruta>] [--fecha AAAA-MM-DD]")
    fecha = args[i + 1]
    del args[i:i + 2]
BITACORA = Path(args[0]) if args else Path(__file__).resolve().parents[2] / RUTA_BITACORA

fallos = []
lineas = BITACORA.read_text(encoding="utf-8").splitlines()
if fecha:
    # Tolera espacios, negrita o código en la celda; sin la fila no hay fecha que comprobar, y eso también es un fallo.
    actualizado = next((m.group(1) for l in lineas
                        if (m := re.match(r"\|\s*\*\*Actualizado\*\*\s*\|\s*[`*]*(\d{4}-\d{2}-\d{2})", l))), None)
    if not actualizado:
        fallos.append("falta la fila «| **Actualizado** | AAAA-MM-DD |» con la fecha del día")
    elif actualizado < fecha:
        fallos.append(f"«Actualizado» dice {actualizado} y el commit es del {fecha}: pon la fecha del día")
filas = [l for l in lineas if l.startswith("| **Tarea en curso")]
if not filas:
    fallos.append("no hay ninguna fila «Tarea en curso · `<rama>`»")
for fila in filas:
    m = re.match(r"\| \*\*Tarea en curso · `([^`]+)`\*\* \|(.*)\|\s*$", fila)
    if not m:
        fallos.append(f"fila sin rama, debe ser «| **Tarea en curso · `<rama>`** | … |»: {fila[:80]}…")
        continue
    rama, texto = m.group(1), m.group(2).strip()
    if len(texto) > TOPE:
        fallos.append(f"«Tarea en curso» de {rama}: {len(texto)} caracteres (tope {TOPE}); lo hecho va a «Hecho recientemente»")
ramas = [m.group(1) for f in filas if (m := re.match(r"\| \*\*Tarea en curso · `([^`]+)`\*\*", f))]
for rama in sorted({r for r in ramas if ramas.count(r) > 1}):
    fallos.append(f"dos filas «Tarea en curso» para {rama}: cada rama tiene una sola")
for f in fallos:
    print(f"bitácora: {f}")
sys.exit(1 if fallos else 0)
