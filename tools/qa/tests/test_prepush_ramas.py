"""QA-74: tools/qa/prepush-ramas.sh, la parte de .githooks/pre-push que mira cada rama (QA-35, QA-66, QA-69)."""
import os
import subprocess
import unittest

from comun import ENV_GIT, QA, carpeta, escribir, git, leer

CERO = '0' * 40
# Una fecha que ningún commit adelanta: cada commit que cambia la bitácora la comprueba (QA-115).
AL_DIA = '| **Actualizado** | 2999-12-31 |\n'
BITACORA_OK = AL_DIA + '| **Tarea en curso · `r`** | algo |\n'


class PrepushRamas(unittest.TestCase):
    def setUp(self):
        remoto = carpeta()
        git(remoto, 'init', '-q', '--bare', '-b', 'main')
        self.repo = carpeta()
        git(self.repo, 'clone', '-q', remoto, '.')
        self.commit('docs/registros/traspaso.md', BITACORA_OK, 'base')
        git(self.repo, 'push', '-q', 'origin', 'HEAD:main')
        git(self.repo, 'fetch', '-q', 'origin')
        git(self.repo, 'checkout', '-q', '-b', 'r')

    def commit(self, ruta: str, texto: str, mensaje: str) -> str:
        escribir(os.path.join(self.repo, ruta), texto)
        git(self.repo, 'add', '-A')
        git(self.repo, 'commit', '-q', '-m', mensaje)
        return git(self.repo, 'rev-parse', 'HEAD')

    def correr(self, sha_local: str, sha_remoto: str, extra_env: dict | None = None) -> tuple[int, str, str]:
        d = carpeta()
        cambiados, subidos = os.path.join(d, 'c'), os.path.join(d, 's')
        r = subprocess.run(['bash', os.path.join(QA, 'prepush-ramas.sh'), cambiados, subidos],
                           input=f'refs/heads/r {sha_local} refs/heads/r {sha_remoto}\n', cwd=self.repo,
                           env={**ENV_GIT, 'BITACORA_PY': os.path.join(QA, 'bitacora.py'), **(extra_env or {})}, capture_output=True, text=True)
        return r.returncode, leer(cambiados), leer(subidos)

    def test_rama_nueva_lista_sus_commits_y_lo_que_cambian(self):
        sha = self.commit('backend/uploads/images/x.png', 'img', 'imagen nueva')
        codigo, cambiados, subidos = self.correr(sha, CERO)
        self.assertEqual(codigo, 0)
        self.assertIn('imagen nueva', subidos)
        self.assertIn('backend/uploads/images/x.png', cambiados)

    def test_lo_ya_subido_no_cuenta(self):
        sha = self.commit('a.txt', 'a', 'ya subido')
        git(self.repo, 'push', '-q', 'origin', 'r')
        _, _, subidos = self.correr(sha, sha)
        self.assertEqual(subidos.strip(), '')

    def test_sha_remota_desconocida_no_deja_la_lista_vacia(self):
        # La otra cuenta subió algo que aquí no se ha traído: la sha remota no existe en local.
        sha = self.commit('a.txt', 'a', 'mi commit')
        codigo, _, subidos = self.correr(sha, 'f' * 40)
        self.assertEqual(codigo, 0)
        self.assertIn('mi commit', subidos)

    def test_bitacora_mala_en_el_commit_falla_aunque_en_disco_este_bien(self):
        sha = self.commit('docs/registros/traspaso.md', AL_DIA + '| **Tarea en curso** | sin rama |\n', 'bitácora mala')
        escribir(os.path.join(self.repo, 'docs/registros/traspaso.md'), BITACORA_OK)
        codigo, _, _ = self.correr(sha, CERO)
        self.assertEqual(codigo, 1)

    def test_fila_de_otra_rama_o_compartida_falla_salvo_con_la_variable(self):
        """QA-145: cada rama escribe solo en su fila; `BITACORA_COMPARTIDA=1` lo permite."""
        base = '## Estado actual\n\n' + AL_DIA + '| **Hito** | 0.3 |\n| **Tarea en curso · `r`** | algo |\n| **Tarea en curso · `o`** | de otra |\n'
        self.commit('docs/registros/traspaso.md', base, 'base con otra rama')
        git(self.repo, 'push', '-q', 'origin', 'r')
        propia = base.replace('| algo |', '| mío |').replace('2999-12-31', '2999-12-30')
        sha = self.commit('docs/registros/traspaso.md', propia + '| **Tests** | verde |\n', 'solo lo mío')
        self.assertEqual(self.correr(sha, CERO)[0], 0)
        ajena = propia.replace('| de otra |', '| tocada |')
        sha = self.commit('docs/registros/traspaso.md', ajena, 'toca la de otra')
        self.assertEqual(self.correr(sha, CERO)[0], 1)
        self.assertEqual(self.correr(sha, CERO, {'BITACORA_COMPARTIDA': '1'})[0], 0)
        sha = self.commit('docs/registros/traspaso.md', ajena.replace('0.3', '0.4'), 'toca el hito')
        self.assertEqual(self.correr(sha, CERO)[0], 1)

    def test_commit_de_una_subrama_local_fusionada_de_vuelta_se_comprueba_contra_ella(self):
        """QA-136/QA-145: la fila de la subrama sin subir vale; sin la subrama, el mismo commit se rechaza."""
        base = '## Estado actual\n\n' + AL_DIA + '| **Tarea en curso · `r`** | algo |\n| **Tarea en curso · `s`** | sub |\n'
        self.commit('docs/registros/traspaso.md', base, 'base con subrama')
        git(self.repo, 'push', '-q', 'origin', 'r')
        git(self.repo, 'checkout', '-q', '-b', 's')
        self.commit('docs/registros/traspaso.md', base.replace('| sub |', '| nuevo |'), 'edita su fila')
        git(self.repo, 'checkout', '-q', 'r')
        self.commit('docs/x.md', 'x', 'avanza r')
        git(self.repo, 'merge', '-q', '--no-ff', '-m', 'fusiona s', 's')
        sha = git(self.repo, 'rev-parse', 'HEAD')
        self.assertEqual(self.correr(sha, CERO)[0], 0)
        git(self.repo, 'branch', '-q', '-D', 's')
        self.assertEqual(self.correr(sha, CERO)[0], 1)

    def test_bitacora_mala_en_un_commit_intermedio_falla(self):
        self.commit('docs/registros/traspaso.md', AL_DIA + '| **Tarea en curso · `r`** | a |\n| **Tarea en curso · `r`** | b |\n', 'dos filas')
        sha = self.commit('docs/registros/traspaso.md', BITACORA_OK, 'arreglada')
        codigo, _, _ = self.correr(sha, CERO)
        self.assertEqual(codigo, 1)

    def test_fecha_vieja_falla_solo_si_el_commit_cambia_la_bitacora(self):
        """QA-115: el commit de hoy que toca la bitácora la pone al día; uno que no la toca no cuenta."""
        vieja = BITACORA_OK.replace('2999-12-31', '2000-01-01')
        sha = self.commit('docs/registros/traspaso.md', vieja, 'bitácora con fecha vieja')
        self.assertEqual(self.correr(sha, CERO)[0], 1)
        hoy = git(self.repo, 'log', '-1', '--format=%as')
        git(self.repo, 'reset', '-q', '--hard', 'HEAD~1')
        self.commit('docs/registros/traspaso.md', BITACORA_OK.replace('2999-12-31', hoy), 'al día')
        sha = self.commit('docs/x.md', 'otro cambio', 'sin bitácora')
        self.assertEqual(self.correr(sha, CERO)[0], 0)


if __name__ == '__main__':
    unittest.main()
