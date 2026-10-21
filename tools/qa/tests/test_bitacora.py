"""QA-74: tools/qa/bitacora.py (QA-69)."""
import os
import subprocess
import unittest

from comun import QA, carpeta, escribir, git


def comprobar(texto: str, *args: str) -> subprocess.CompletedProcess:
    ruta = os.path.join(carpeta(), 'traspaso.md')
    escribir(ruta, texto)
    return subprocess.run(['python3', os.path.join(QA, 'bitacora.py'), ruta, *args], capture_output=True, text=True)


class Bitacora(unittest.TestCase):
    def test_una_fila_corta_por_rama_pasa(self):
        r = comprobar('| **Tarea en curso · `a`** | algo |\n| **Tarea en curso · `b`** | otra |\n')
        self.assertEqual(r.returncode, 0, r.stdout)

    def test_fila_sin_rama_falla(self):
        r = comprobar('| **Tarea en curso** | algo |\n')
        self.assertEqual(r.returncode, 1)
        self.assertIn('fila sin rama', r.stdout)

    def test_fila_larga_falla(self):
        r = comprobar('| **Tarea en curso · `a`** | ' + 'x' * 601 + ' |\n')
        self.assertEqual(r.returncode, 1)
        self.assertIn('601 caracteres', r.stdout)

    def test_dos_filas_de_la_misma_rama_fallan(self):
        r = comprobar('| **Tarea en curso · `a`** | uno |\n| **Tarea en curso · `a`** | dos |\n')
        self.assertEqual(r.returncode, 1)
        self.assertIn('dos filas', r.stdout)

    def test_sin_ninguna_fila_falla(self):
        self.assertEqual(comprobar('| **Hito** | 0.3 |\n').returncode, 1)

    def test_fecha_anterior_al_commit_falla(self):
        """QA-115: con `--fecha`, «Actualizado» no puede ser de un día anterior."""
        texto = '| **Actualizado** | 2026-10-17 |\n| **Tarea en curso · `a`** | algo |\n'
        r = comprobar(texto, '--fecha', '2026-10-19')
        self.assertEqual(r.returncode, 1)
        self.assertIn('«Actualizado» dice 2026-10-17 y el commit es del 2026-10-19', r.stdout)
        self.assertEqual(comprobar(texto, '--fecha', '2026-10-17').returncode, 0)
        self.assertEqual(comprobar(texto).returncode, 0)

    def test_fecha_con_formato_suelto_o_sin_fila(self):
        texto = '|  **Actualizado**  |  `2026-10-17` |\n| **Tarea en curso · `a`** | algo |\n'
        self.assertIn('dice 2026-10-17', comprobar(texto, '--fecha', '2026-10-19').stdout)
        r = comprobar('| **Tarea en curso · `a`** | algo |\n', '--fecha', '2026-10-19')
        self.assertNotEqual(r.returncode, 0)
        self.assertIn('falta la fila «| **Actualizado**', r.stdout)

    def test_fecha_mal_escrita_da_uso(self):
        self.assertIn('Uso', comprobar('| **Tarea en curso · `a`** | algo |\n', '--fecha', 'ayer').stderr)


class Ajenas(unittest.TestCase):
    """QA-145: un commit no cambia la fila de otra rama ni una fila compartida (salvo `--compartida`)."""
    BASE = ('## Estado actual\n\n| **Actualizado** | 2026-10-19 |\n| **Hito** | 0.3 |\n| **Tests** | verde |\n'
            '| **Tarea en curso · `a`** | uno |\n| **Tarea en curso · `b`** | dos |\n')

    def commit(self, repo: str, texto: str) -> str:
        escribir(os.path.join(repo, 'docs/registros/traspaso.md'), texto)
        git(repo, 'add', '-A')
        git(repo, 'commit', '-q', '-m', 'x')
        return git(repo, 'rev-parse', 'HEAD')

    def correr(self, texto: str, *extra: str):
        repo = carpeta()
        git(repo, 'init', '-q')
        self.commit(repo, self.BASE)
        sha = self.commit(repo, texto)
        return subprocess.run(['python3', os.path.join(QA, 'bitacora.py'), '--ajenas', sha, 'a', *extra],
                              cwd=repo, capture_output=True, text=True)

    def test_la_propia_y_las_libres_pasan(self):
        t = self.BASE.replace('| uno |', '| nuevo |').replace('2026-10-19', '2026-10-20').replace('verde', 'rojo')
        self.assertEqual(self.correr(t).returncode, 0)

    def test_la_de_otra_rama_falla(self):
        r = self.correr(self.BASE.replace('| dos |', '| tres |'))
        self.assertEqual(r.returncode, 1)
        self.assertIn('Tarea en curso · b', r.stdout)
        self.assertIn('BITACORA_COMPARTIDA=1', r.stdout)

    def test_compartida_falla_y_se_permite_con_la_opcion(self):
        t = self.BASE.replace('0.3', '0.4')
        self.assertIn('«Hito»', self.correr(t).stdout)
        self.assertEqual(self.correr(t, '--compartida').returncode, 0)

    def test_quitar_o_anadir_una_fila_ajena_falla(self):
        self.assertEqual(self.correr(self.BASE.replace('| **Tarea en curso · `b`** | dos |\n', '')).returncode, 1)
        self.assertEqual(self.correr(self.BASE + '| **Tarea en curso · `c`** | tres |\n').returncode, 1)

    def test_una_tabla_de_otra_seccion_no_es_fila_compartida(self):
        t = self.BASE + '\n## Otra\n\n| **Hito** | 0.9 |\n'
        self.assertEqual(self.correr(t).returncode, 0)

    def test_clave_repetida_no_oculta_un_cambio(self):
        base = self.BASE + '| **Hito** | 0.5 |\n'
        repo = carpeta()
        git(repo, 'init', '-q')
        self.commit(repo, base)
        sha = self.commit(repo, base.replace('| 0.3 |', '| 0.4 |'))
        r = subprocess.run(['python3', os.path.join(QA, 'bitacora.py'), '--ajenas', sha, 'a'], cwd=repo,
                           capture_output=True, text=True)
        self.assertEqual(r.returncode, 1)
        self.assertIn('«Hito»', r.stdout)

    def test_uso(self):
        r = subprocess.run(['python3', os.path.join(QA, 'bitacora.py'), '--ajenas', 'x'], capture_output=True, text=True)
        self.assertIn('Uso', r.stderr)


class Cerradas(unittest.TestCase):
    """QA-85: lo que se tacha en un roadmap sale tachado en «Hecho recientemente»."""

    def setUp(self):
        self.repo = carpeta()
        git(self.repo, 'init', '-q')
        self.base = self.commit('- **QA-1 · Una**\n- ~~**QA-2 · Dos**~~ ✅\n', '## Hecho recientemente\n\n- ~~`QA-2`~~\n')

    def commit(self, roadmap: str, bitacora: str) -> str:
        escribir(os.path.join(self.repo, 'docs/05-plan-de-trabajo.md'), roadmap)
        escribir(os.path.join(self.repo, 'docs/registros/traspaso.md'), bitacora)
        git(self.repo, 'add', '-A')
        git(self.repo, 'commit', '-q', '-m', 'c')
        return git(self.repo, 'rev-parse', 'HEAD')

    def correr(self, sha: str) -> subprocess.CompletedProcess:
        return subprocess.run(['python3', os.path.join(QA, 'bitacora.py'), '--cerradas', self.base, sha],
                              cwd=self.repo, capture_output=True, text=True)

    def test_tachada_sin_bitacora_falla(self):
        sha = self.commit('- ~~**QA-1 · Una**~~ ✅\n- ~~**QA-2 · Dos**~~ ✅\n',
                          '## Hecho recientemente\n\n- `QA-1` diagnosticado\n- ~~`QA-2`~~\n')
        r = self.correr(sha)
        self.assertEqual(r.returncode, 1)
        self.assertIn('QA-1', r.stdout)

    def test_tachada_en_hecho_recientemente_pasa(self):
        sha = self.commit('- ~~**QA-1 · Una**~~ ✅\n- ~~**QA-2 · Dos**~~ ✅\n',
                          '## Hecho recientemente\n\n- ~~`QA-1`~~ hecho\n- ~~`QA-2`~~\n')
        self.assertEqual(self.correr(sha).returncode, 0)

    def test_un_rango_tachado_cuenta_para_todas(self):
        sha = self.commit('- ~~`QA-1`…`QA-3`~~ ✅\n- ~~**QA-2 · Dos**~~ ✅\n',
                          '## Hecho recientemente\n\n- ~~`QA-1`…`QA-3`~~\n')
        self.assertEqual(self.correr(sha).returncode, 0)

    def test_una_movida_de_hito_no_es_una_cerrada(self):
        sha = self.commit('- ~~**QA-1 · Una**~~ → pasa al `0.4`\n- ~~**QA-2 · Dos**~~ ✅\n', '## Hecho recientemente\n\n- ~~`QA-2`~~\n')
        self.assertEqual(self.correr(sha).returncode, 0)

    def test_lo_que_nombra_el_titulo_no_cuenta(self):
        sha = self.commit('- ~~**QA-1 · Una (ver QA-9)**~~ ✅\n- ~~**QA-2 · Dos**~~ ✅\n',
                          '## Hecho recientemente\n\n- ~~`QA-1`~~\n- ~~`QA-2`~~\n')
        self.assertEqual(self.correr(sha).returncode, 0)

    def test_rango_con_raya(self):
        sha = self.commit('- ~~`QA-1`–`QA-3`~~ ✅\n- ~~**QA-2 · Dos**~~ ✅\n', '## Hecho recientemente\n\n- ~~`QA-1`…`QA-3`~~\n')
        self.assertEqual(self.correr(sha).returncode, 0)
        sha = self.commit('- ~~`QA-1`–`QA-3`~~ ✅\n- ~~**QA-2 · Dos**~~ ✅\n- ~~`QA-4`–`QA-6`~~\n', '## Hecho recientemente\n\n- ~~`QA-1`…`QA-3`~~\n- ~~`QA-4`~~\n')
        r = self.correr(sha)
        self.assertEqual(r.returncode, 1)
        self.assertIn('QA-5', r.stdout)

    def test_lo_cerrado_en_main_no_se_pide_a_la_rama(self):
        sha = self.commit('- ~~**QA-1 · Una**~~ ✅\n- ~~**QA-2 · Dos**~~ ✅\n', '## Hecho recientemente\n\n- ~~`QA-2`~~\n')
        git(self.repo, 'update-ref', 'refs/remotes/origin/main', sha)
        self.assertEqual(self.correr(sha).returncode, 0)

    def test_casilla_marcada_sin_bitacora_falla(self):
        """En el plan del instalador una tarea se cierra con su casilla (`- [x] **INS-7** …`)."""
        self.base = self.commit('- [ ] **INS-7** Narrador\n- [x] **INS-6** Bytecode\n', '## Hecho recientemente\n\n- nada\n')
        sha = self.commit('- [x] **INS-7** Narrador\n- [x] **INS-6** Bytecode\n', '## Hecho recientemente\n\n- nada\n')
        r = self.correr(sha)
        self.assertEqual(r.returncode, 1)
        self.assertIn('INS-7', r.stdout)
        self.assertNotIn('INS-6', r.stdout)
        sha = self.commit('- [x] **INS-7** Narrador\n- [x] **INS-6** Bytecode\n', '## Hecho recientemente\n\n- ~~`INS-7`~~ narrador\n')
        self.assertEqual(self.correr(sha).returncode, 0)

    def test_retocar_una_ya_tachada_no_pide_nada(self):
        sha = self.commit('- **QA-1 · Una**\n- ~~**QA-2 · Dos**~~ ✅ con más texto\n', '## Hecho recientemente\n\n- nada\n')
        self.assertEqual(self.correr(sha).returncode, 0)



class EnCurso(unittest.TestCase):
    """QA-182: aviso de una tarea 🚧 que los commits nombran y cuya entrada del roadmap no cambia."""

    def setUp(self):
        self.repo = carpeta()
        git(self.repo, 'init', '-q')
        self.roadmap = ('- **QA-1 · Una** 🚧 en curso:\n  falta X.\n- **QA-2 · Dos**\n'
                        '- ~~**QA-3 · Tres**~~ ✅\n| QA-4 | Cuatro 🚧 |\n')
        self.base = self.commit(self.roadmap, 'base')

    def commit(self, roadmap: str, mensaje: str) -> str:
        escribir(os.path.join(self.repo, 'docs/05-plan-de-trabajo.md'), roadmap)
        escribir(os.path.join(self.repo, 'otro.txt'), mensaje)
        git(self.repo, 'add', '-A')
        git(self.repo, 'commit', '-q', '-m', mensaje)
        return git(self.repo, 'rev-parse', 'HEAD')

    def correr(self, sha: str) -> subprocess.CompletedProcess:
        return subprocess.run(['python3', os.path.join(QA, 'bitacora.py'), '--en-curso', self.base, sha],
                              cwd=self.repo, capture_output=True, text=True)

    def test_avisa_sin_fallar_de_la_en_curso_sin_tocar(self):
        r = self.correr(self.commit(self.roadmap, 'Avanza QA-1, QA-2, QA-3 y QA-4'))
        self.assertEqual(r.returncode, 0)
        self.assertIn('QA-1', r.stdout)
        self.assertIn('QA-4', r.stdout)
        self.assertNotIn('QA-2', r.stdout)
        self.assertNotIn('QA-3', r.stdout)

    def test_la_entrada_tocada_aunque_sea_en_su_continuacion_no_avisa(self):
        r = self.correr(self.commit(self.roadmap.replace('falta X', 'falta Y'), 'Avanza QA-1'))
        self.assertEqual(r.stdout, '')

    def test_con_casilla_avisa_la_abierta_y_no_la_marcada(self):
        self.base = self.commit('- [ ] **INS-31** URL 🚧 en curso\n- [x] **INS-32** Fuentes 🚧\n', 'base')
        r = self.correr(self.commit('- [ ] **INS-31** URL 🚧 en curso\n- [x] **INS-32** Fuentes 🚧\n', 'Avanza INS-31 e INS-32'))
        self.assertIn('INS-31', r.stdout)
        self.assertNotIn('INS-32', r.stdout)

    def test_sin_nombrarla_no_avisa(self):
        self.assertEqual(self.correr(self.commit(self.roadmap, 'Otra cosa')).stdout, '')


if __name__ == '__main__':
    unittest.main()
