"""Tests of figures.py: each case builds a git repo in a tempdir; every failure case asserts its message.
Run: python3 -m unittest discover -s skills/gw-media-content/scripts"""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
FIGURES = HERE / "figures.py"
ENV = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}
CONFIG = {"version": "0.4.0", "language": "es", "log": "docs/handoff.md", "check": ["true"], "protectedBranch": "main",
          "pushToProtected": "direct", "reviewMark": "docs/records/reviewed.txt", "content": ["^docs/"]}
CHANGELOG = "# Changelog\n\n## [1.1.0] - 2026-10-02\n\n### Added\n\n- a\n\n### Fixed\n\n- b\n\n## [1.0.0]\n\n### Old\n"


def clean_env(**extra):
    """The environment without any inherited GIT_* variable (GIT_DIR, GIT_WORK_TREE, GIT_INDEX_FILE... leak in when the
    tests run from a git hook and would point git at the wrong repository), plus a fixed identity and no user config."""
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env.update(ENV, GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM="1")
    env.update(extra)
    return env


def git(cwd, *args, date=None):
    extra = {"GIT_AUTHOR_DATE": date, "GIT_COMMITTER_DATE": date} if date else {}
    subprocess.run(["git", "-C", str(cwd), *args], check=True, capture_output=True, env=clean_env(**extra))


def run(cwd, *args):
    proc = subprocess.run([sys.executable, str(FIGURES), *args], cwd=str(cwd), capture_output=True, text=True,
                          env=clean_env())
    return proc


class Figures(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.repo = Path(self._tmp.name) / "project"
        self.repo.mkdir()
        git(self.repo, "init", "-q")
        self.commit("a.txt", "uno\n", "primero", "2026-09-01T10:00:00")

    def commit(self, rel, text, msg, date="2026-10-01T10:00:00"):
        path = self.repo / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-q", "-m", msg, date=date)

    def figures(self, *args):
        proc = run(self.repo, *args)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        return json.loads(proc.stdout)

    def test_old_option_name_still_works_with_a_warning(self):
        git(self.repo, "tag", "v1.0.0")
        self.commit("b.txt", "dos\n", "segundo", "2026-10-03T10:00:00")
        proc = run(self.repo, "--desde", "v1.0.0")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("warning: --desde is deprecated; use --since", proc.stderr)
        out = json.loads(proc.stdout)
        self.assertEqual(out["since"], "--since v1.0.0")
        self.assertEqual(out["figures"]["commits_since"]["value"], 1)
        proc = run(self.repo, "--desde=v1.0.0")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("use --since", proc.stderr)
        self.assertEqual(json.loads(proc.stdout)["figures"]["commits_since"]["value"], 1)

    def test_outside_a_repo_fails_closed_with_the_fix(self):
        with tempfile.TemporaryDirectory() as tmp:
            proc = run(tmp)
        self.assertEqual(proc.returncode, 2)
        self.assertIn("not inside a git repository", proc.stderr)
        self.assertIn("cd <project>", proc.stderr)
        self.assertEqual(proc.stdout, "")

    def test_repo_without_commits(self):
        with tempfile.TemporaryDirectory() as tmp:
            git(tmp, "init", "-q")
            proc = run(tmp)
        self.assertEqual(proc.returncode, 2)
        self.assertIn("has no commits yet", proc.stderr)

    def test_unknown_ref(self):
        proc = run(self.repo, "--since", "no-existe")
        self.assertEqual(proc.returncode, 2)
        self.assertIn("--since no-existe: git does not know that ref", proc.stderr)
        self.assertIn("git tag --list", proc.stderr)

    def test_unknown_version_file(self):
        proc = run(self.repo, "--version-file", "nada.json")
        self.assertEqual(proc.returncode, 2)
        self.assertIn("--version-file nada.json: no such file", proc.stderr)

    def test_version_file_without_a_version(self):
        self.commit("pkg.json", '{"name": "x"}', "pkg")
        proc = run(self.repo, "--version-file", "pkg.json")
        self.assertEqual(proc.returncode, 2)
        self.assertIn("no version found in it", proc.stderr)

    def test_bad_option_exits_2(self):
        proc = run(self.repo, "--nothing")
        self.assertEqual(proc.returncode, 2)
        self.assertIn("unrecognized arguments: --nothing", proc.stderr)

    def test_inherited_git_env_does_not_leak_into_the_script(self):
        # a GIT_DIR pointing elsewhere (as in a hook) must not matter: the helpers drop every GIT_* variable
        os.environ["GIT_DIR"] = str(Path(self._tmp.name) / "other.git")
        self.addCleanup(os.environ.pop, "GIT_DIR", None)
        self.assertEqual(self.figures()["figures"]["commits_since"]["value"], 1)

    def test_without_tags_counts_the_whole_history(self):
        self.commit("b.txt", "dos\n", "segundo", "2026-10-03T10:00:00")
        out = self.figures()
        self.assertIn("first commit", out["since"])
        c = out["figures"]
        self.assertEqual(c["commits_since"]["value"], 2)
        self.assertEqual(c["commits_since"]["source"], "git rev-list --count HEAD")
        self.assertIsNone(c["last_tag"]["value"])
        self.assertIn("no version tags", c["last_tag"]["note"])
        self.assertEqual(c["date_range"]["value"], {"first": "2026-09-01", "last": "2026-10-03"})
        self.assertEqual(c["changed_files"]["value"], {"files": 2})
        self.assertEqual([s.split(" ", 1)[1] for s in c["commit_subjects"]["value"]], ["segundo", "primero"])

    def test_from_the_last_tag(self):
        git(self.repo, "tag", "v1.0.0")
        self.commit("b.txt", "dos\n", "segundo", "2026-10-03T10:00:00")
        self.commit("b.txt", "dos\ntres\n", "cambia b", "2026-10-05T10:00:00")  # same file again: still 1 file
        self.commit("c.txt", "x\n", "tercero", "2026-10-06T10:00:00")
        out = self.figures()
        self.assertEqual(out["since"], "last tag v1.0.0")
        c = out["figures"]
        self.assertEqual(c["last_tag"]["value"], "v1.0.0")
        self.assertEqual(c["commits_since"]["value"], 3)
        self.assertEqual(c["commits_no_merges"]["value"], 3)
        self.assertEqual(c["commits_since"]["source"], "git rev-list --count v1.0.0..HEAD")
        self.assertEqual(c["changed_files"]["value"], {"files": 2, "lines_added": 3, "lines_removed": 0})
        self.assertEqual(c["changed_files"]["source"], "git diff --numstat v1.0.0...HEAD")
        self.assertEqual(c["date_range"]["value"], {"first": "2026-10-03", "last": "2026-10-06"})

    def test_merge_commits_are_counted_apart_and_not_listed(self):
        git(self.repo, "tag", "v1.0.0")
        git(self.repo, "checkout", "-q", "-b", "rama")
        self.commit("r.txt", "r\n", "en la rama", "2026-10-02T10:00:00")
        git(self.repo, "checkout", "-q", "-")
        self.commit("m.txt", "m\n", "en la principal", "2026-10-03T10:00:00")
        git(self.repo, "merge", "-q", "--no-ff", "-m", "Merge rama", "rama", date="2026-10-04T10:00:00")
        c = self.figures()["figures"]
        self.assertEqual((c["commits_since"]["value"], c["commits_no_merges"]["value"]), (3, 2))
        self.assertEqual(sorted(s.split(" ", 1)[1] for s in c["commit_subjects"]["value"]),
                         ["en la principal", "en la rama"])

    def test_since_overrides_the_tag(self):
        git(self.repo, "tag", "v1.0.0")
        self.commit("b.txt", "dos\n", "segundo", "2026-10-03T10:00:00")
        git(self.repo, "tag", "v1.1.0")
        self.commit("c.txt", "x\n", "tercero", "2026-10-06T10:00:00")
        out = self.figures("--since", "v1.0.0")
        self.assertEqual(out["since"], "--since v1.0.0")
        self.assertEqual(out["figures"]["commits_since"]["value"], 2)
        self.assertEqual(out["figures"]["last_tag"]["value"], "v1.1.0")

    def test_zero_commits_since_the_ref(self):
        c = self.figures("--since", "HEAD")["figures"]
        self.assertEqual(c["commits_since"]["value"], 0)
        self.assertIsNone(c["date_range"]["value"])
        self.assertIn("no commits in the range", c["date_range"]["note"])
        self.assertEqual(c["changed_files"]["value"]["files"], 0)

    def test_version_from_known_files_and_the_option(self):
        self.assertIsNone(self.figures()["figures"]["project_version"]["value"])
        self.assertIn("--version-file", self.figures()["figures"]["project_version"]["note"])
        self.commit("pyproject.toml", '[project]\nname = "x"\nversion = "2.3.4"\n', "py")
        v = self.figures()["figures"]["project_version"]
        self.assertEqual((v["value"], v["source"]), ("2.3.4", "read pyproject.toml"))
        self.commit(".claude-plugin/plugin.json", '{"version": "0.9.1"}', "plugin")
        self.assertEqual(self.figures()["figures"]["project_version"]["value"], "0.9.1")  # first in the list wins
        self.commit("VERSION", "7.0.0\n", "ver")
        self.assertEqual(self.figures("--version-file", "VERSION")["figures"]["project_version"]["value"], "7.0.0")

    def version(self, rel, text, *args):
        """Commit a version file with these exact bytes and read the version figure back."""
        path = self.repo / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(text if isinstance(text, bytes) else text.encode("utf-8"))
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-q", "-m", f"ver {rel}")
        return self.figures(*args)["figures"]["project_version"]

    def assert_not_readable(self, fig, rel, why):
        self.assertIsNone(fig["value"])
        self.assertIn(f"{rel} found, but its version is not readable", fig["note"])
        self.assertIn(why, fig["note"])
        self.assertNotIn("no known version file", fig["note"])

    def test_pyproject_reads_project_not_the_first_version_of_any_table(self):
        v = self.version("pyproject.toml", '[tool.mypy]\nversion = "3.11"\n\n[tool.poetry.dependencies]\n'
                         'version = "9.9"\n\n[project]\nname = "x"\nversion = "2.3.4"\n')
        self.assertEqual((v["value"], v["source"]), ("2.3.4", "read pyproject.toml"))

    def test_pyproject_with_a_version_only_outside_project_is_not_readable(self):
        v = self.version("pyproject.toml", '[tool.mypy]\nversion = "3.11"\n[project]\nname = "x"\n')
        self.assert_not_readable(v, "pyproject.toml", "no version key")

    def test_pyproject_falls_back_to_tool_poetry(self):
        v = self.version("pyproject.toml", '[tool.black]\nversion = "1"\n[tool.poetry]\nname = "x"\nversion = "0.7.1"\n')
        self.assertEqual(v["value"], "0.7.1")

    def test_single_quoted_and_commented_versions(self):
        v = self.version("pyproject.toml", "[project]\nversion = '1.2.3'  # bump me\n")
        self.assertEqual(v["value"], "1.2.3")

    def test_dynamic_version_is_not_a_number(self):
        v = self.version("pyproject.toml", '[project]\nname = "x"\ndynamic = ["readme", "version"]\n')
        self.assert_not_readable(v, "pyproject.toml", 'dynamic = ["version"]')
        v = self.version("pyproject.toml", "[project]\nname = 'x'\ndynamic = [\n  'version',\n]\n")
        self.assert_not_readable(v, "pyproject.toml", 'dynamic = ["version"]')

    def test_dynamic_without_version_in_the_list_does_not_hide_the_version(self):
        v = self.version("pyproject.toml", '[project]\nversion = "1.0.0"\ndynamic = ["readme"]\n')
        self.assertEqual(v["value"], "1.0.0")

    def test_cargo_package_version_and_workspace_inheritance(self):
        v = self.version("Cargo.toml", '[package]\nname = "x"\nversion = "0.1.0"\n\n[dependencies.foo]\nversion = "9"\n')
        self.assertEqual((v["value"], v["source"]), ("0.1.0", "read Cargo.toml"))
        v = self.version("Cargo.toml", '[package]\nname = "x"\nversion.workspace = true\n\n[dependencies]\n'
                         'foo = { version = "9" }\n[dev-dependencies.bar]\nversion = "2"\n')
        self.assert_not_readable(v, "Cargo.toml", "inherits it from the workspace")
        v = self.version("Cargo.toml", '[package]\nname = "x"\nversion = { workspace = true }\n')
        self.assert_not_readable(v, "Cargo.toml", "inherits it from the workspace")
        v = self.version("Cargo.toml", '[workspace]\nmembers = ["a"]\n[workspace.package]\nversion = "3.0.0"\n')
        self.assertEqual(v["value"], "3.0.0")

    def test_bom_is_ignored_in_every_kind_of_file(self):
        bom = b"\xef\xbb\xbf"
        self.assertEqual(self.version("pyproject.toml", bom + b'[project]\nversion = "1.0.1"\n')["value"], "1.0.1")
        self.assertEqual(self.version("package.json", bom + b'{"version": "1.0.2"}')["value"], "1.0.2")
        (self.repo / "package.json").unlink()
        (self.repo / "pyproject.toml").unlink()
        self.assertEqual(self.version("VERSION", bom + b"1.0.3\n")["value"], "1.0.3")

    def test_plain_version_file_skips_blank_lines_and_comments(self):
        v = self.version("VERSION", "\n# the release\n\n  4.5.6  \n# trailing\n")
        self.assertEqual(v["value"], "4.5.6")

    def test_plain_version_file_with_only_comments_is_not_readable(self):
        v = self.version("VERSION", "# nothing yet\n\n")
        self.assert_not_readable(v, "VERSION", "blank or a # comment")

    def test_json_without_a_string_version_is_not_readable(self):
        v = self.version("package.json", '{"name": "x", "version": 3}')
        self.assert_not_readable(v, "package.json", 'no string "version" key')
        v = self.version("package.json", "{not json")
        self.assert_not_readable(v, "package.json", "not valid JSON")

    def test_an_unreadable_file_does_not_hide_a_later_readable_one(self):
        self.commit("pyproject.toml", '[project]\ndynamic = ["version"]\n', "py dinamico")
        v = self.version("VERSION", "8.0.0\n")
        self.assertEqual((v["value"], v["source"]), ("8.0.0", "read VERSION"))

    def test_every_unreadable_file_is_named_in_the_note(self):
        self.commit("pyproject.toml", '[project]\ndynamic = ["version"]\n', "py dinamico")
        v = self.version("VERSION", "# none\n")
        self.assertIsNone(v["value"])
        self.assertIn("pyproject.toml found, but its version is not readable", v["note"])
        self.assertIn("VERSION found, but its version is not readable", v["note"])
        self.assertIn("--version-file", v["note"])

    def test_explicit_version_file_that_is_not_readable_fails_with_the_reason(self):
        self.commit("pyproject.toml", '[project]\ndynamic = ["version"]\n', "py dinamico")
        proc = run(self.repo, "--version-file", "pyproject.toml")
        self.assertEqual(proc.returncode, 2)
        self.assertIn("no version found in it", proc.stderr)
        self.assertIn('dynamic = ["version"]', proc.stderr)

    def test_shallow_clone_fails_closed_with_the_fix(self):
        self.commit("b.txt", "dos\n", "segundo", "2026-10-03T10:00:00")
        git(self.repo, "tag", "v1.0.0")
        self.commit("c.txt", "tres\n", "tercero", "2026-10-04T10:00:00")
        clone = Path(self._tmp.name) / "clone"
        subprocess.run(["git", "clone", "-q", "--depth", "1", self.repo.resolve().as_uri(), str(clone)], check=True,
                       capture_output=True, env=clean_env())
        proc = run(clone)
        self.assertEqual(proc.returncode, 2)
        self.assertIn("shallow clone", proc.stderr)
        self.assertIn("git fetch --unshallow --tags", proc.stderr)
        self.assertEqual(proc.stdout, "")
        proc = run(clone, "--since", "HEAD")  # a flag must not bypass it
        self.assertEqual(proc.returncode, 2)
        self.assertIn("git fetch --unshallow --tags", proc.stderr)
        subprocess.run(["git", "-C", str(clone), "fetch", "-q", "--unshallow", "--tags"], check=True,
                       capture_output=True, env=clean_env())
        proc = run(clone)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        c = json.loads(proc.stdout)["figures"]
        self.assertEqual((c["last_tag"]["value"], c["commits_since"]["value"]), ("v1.0.0", 1))

    def test_tag_on_head_counts_from_the_previous_tag(self):
        git(self.repo, "tag", "v1.0.0")
        self.commit("b.txt", "dos\n", "segundo", "2026-10-03T10:00:00")
        self.commit("c.txt", "tres\n", "tercero", "2026-10-04T10:00:00")
        git(self.repo, "tag", "-a", "-m", "release", "v1.1.0")
        out = self.figures()
        self.assertEqual(out["since"], "tag v1.1.0 on HEAD; counting from previous tag v1.0.0")
        c = out["figures"]
        self.assertEqual(c["last_tag"]["value"], "v1.1.0")
        self.assertIn("points at HEAD", c["last_tag"]["note"])
        self.assertEqual(c["commits_since"]["value"], 2)
        self.assertEqual(c["commits_since"]["source"], "git rev-list --count v1.0.0..HEAD")
        self.assertEqual(c["changed_files"]["value"]["files"], 2)

    def test_tag_on_head_without_a_previous_tag_counts_from_the_first_commit(self):
        self.commit("b.txt", "dos\n", "segundo", "2026-10-03T10:00:00")
        git(self.repo, "tag", "v0.1")
        out = self.figures()
        self.assertEqual(out["since"], "tag v0.1 on HEAD and no previous version tag; counting from the first commit")
        self.assertEqual(out["figures"]["commits_since"]["value"], 2)
        self.assertEqual(out["figures"]["commits_since"]["source"], "git rev-list --count HEAD")

    def test_tagged_merge_finds_the_previous_tag_through_the_second_parent(self):
        git(self.repo, "checkout", "-q", "-b", "feat")
        self.commit("f.txt", "rama\n", "en la rama", "2026-10-02T10:00:00")
        git(self.repo, "checkout", "-q", "-")
        self.commit("b.txt", "dos\n", "segundo", "2026-10-03T10:00:00")
        git(self.repo, "tag", "v1.0.0")
        git(self.repo, "checkout", "-q", "feat")
        git(self.repo, "merge", "-q", "--no-edit", "-", date="2026-10-04T10:00:00")
        git(self.repo, "tag", "v1.1.0")
        out = self.figures()
        self.assertEqual(out["since"], "tag v1.1.0 on HEAD; counting from previous tag v1.0.0")
        c = out["figures"]
        self.assertEqual((c["commits_since"]["value"], c["commits_no_merges"]["value"]), (2, 1))
        self.assertEqual(c["changed_files"]["value"]["files"], 1)

    def test_since_off_the_history_diffs_from_the_merge_base(self):
        git(self.repo, "checkout", "-q", "-b", "vieja")
        self.commit("solo-vieja.txt", "x\n", "solo en la rama vieja", "2026-10-02T10:00:00")
        git(self.repo, "checkout", "-q", "-")
        self.commit("b.txt", "dos\n", "segundo", "2026-10-03T10:00:00")
        c = self.figures("--since", "vieja")["figures"]
        self.assertEqual(c["commits_since"]["value"], 1)
        self.assertEqual(c["changed_files"]["value"], {"files": 1, "lines_added": 1, "lines_removed": 0})
        self.assertEqual(c["changed_files"]["source"], "git diff --numstat vieja...HEAD")

    def test_since_wins_over_a_tag_on_head(self):
        git(self.repo, "tag", "v1.0.0")
        self.commit("b.txt", "dos\n", "segundo", "2026-10-03T10:00:00")
        git(self.repo, "tag", "v1.1.0")
        out = self.figures("--since", "v1.1.0")
        self.assertEqual(out["since"], "--since v1.1.0")
        self.assertEqual(out["figures"]["commits_since"]["value"], 0)

    def test_moving_lightweight_tags_are_not_the_last_tag(self):
        git(self.repo, "tag", "v1.0.0")
        self.commit("b.txt", "dos\n", "segundo", "2026-10-03T10:00:00")
        self.commit("c.txt", "tres\n", "tercero", "2026-10-04T10:00:00")
        for name in ("latest", "nightly", "1st-draft"):
            git(self.repo, "tag", name)  # all on HEAD
        out = self.figures()
        self.assertEqual(out["since"], "last tag v1.0.0")
        self.assertEqual(out["figures"]["last_tag"]["value"], "v1.0.0")
        self.assertEqual(out["figures"]["commits_since"]["value"], 2)

    def test_only_moving_tags_means_no_version_tag(self):
        git(self.repo, "tag", "latest")
        out = self.figures()
        self.assertIn("first commit", out["since"])
        self.assertIsNone(out["figures"]["last_tag"]["value"])
        self.assertIn("no version tags", out["figures"]["last_tag"]["note"])

    def test_dates_and_file_lists_use_portable_git_options(self):
        self.commit("con espacio y ñ.txt", "x\n", "raro", "2026-10-03T23:30:00")
        self.commit("tests/test ñ_a.py", "", "test raro", "2026-10-04T10:00:00")
        c = self.figures()["figures"]
        self.assertEqual(c["date_range"]["value"], {"first": "2026-09-01", "last": "2026-10-04"})
        self.assertIn("--date=short", c["date_range"]["source"])
        self.assertEqual(c["changed_files"]["value"], {"files": 3})
        self.assertEqual(c["test_files"]["value"], 0)  # "test ñ_a.py" is not a test_*.py name
        self.commit("tests/test_ñ.py", "", "test con ñ")
        self.assertEqual(self.figures()["figures"]["test_files"]["value"], 1)

    def test_changelog_latest_section(self):
        self.assertIsNone(self.figures()["figures"]["changelog_last_section"]["value"])
        self.assertIn("no CHANGELOG.md", self.figures()["figures"]["changelog_last_section"]["note"])
        self.commit("CHANGELOG.md", CHANGELOG, "cl")
        v = self.figures()["figures"]["changelog_last_section"]["value"]
        self.assertEqual(v, {"section": "[1.1.0] - 2026-10-02", "headings": ["Added", "Fixed"]})
        self.commit("CHANGELOG.md", "# Changelog\n\ntexto\n", "cl2")
        self.assertIn("no '## ' section", self.figures()["figures"]["changelog_last_section"]["note"])

    def test_counts_test_files(self):
        self.commit("tests/test_a.py", "", "t1")
        self.commit("src/b_test.go", "", "t2")
        self.commit("web/c.spec.ts", "", "t3")
        self.commit("src/contest.py", "", "no es un test")
        self.assertEqual(self.figures()["figures"]["test_files"]["value"], 3)

    def test_log_path_through_the_config_reader_when_the_project_has_one(self):
        self.assertNotIn("log", self.figures()["figures"])
        # config.py and the schema: <root>/.claude/gw/ when installed (apply.py), the repo root in the workflow's own repo
        gw = HERE.parents[2] / "gw" if HERE.parents[2].name == ".claude" else None
        sources = [(gw / "scripts" / "config.py", gw / "schema" / "gw.schema.json")] if gw else []
        sources.append((HERE.parents[2] / "scripts" / "config.py", HERE.parents[2] / "schema" / "gw.schema.json"))
        found = next(((c, s) for c, s in sources if c.is_file() and s.is_file()), None)
        if not found:
            self.skipTest("config.py and gw.schema.json not found in .claude/gw/ (installed) nor at the workflow root")
        (self.repo / ".claude/gw/scripts").mkdir(parents=True)
        (self.repo / ".claude/gw/schema").mkdir()
        (self.repo / ".claude/gw/scripts/config.py").write_text(found[0].read_text(encoding="utf-8"))
        (self.repo / ".claude/gw/schema/gw.schema.json").write_text(found[1].read_text(encoding="utf-8"))
        self.commit(".claude/gw.json", json.dumps(CONFIG), "cfg")
        b = self.figures()["figures"]["log"]
        self.assertEqual(b["value"], "docs/handoff.md")
        self.assertEqual(b["source"], "python3 .claude/gw/scripts/config.py get log")

    def subjects_with(self, extra):
        if not (self.repo / ".claude/gw/scripts").is_dir():
            for i in range(3):
                self.commit(f"f{i}.txt", "x\n", f"cambio {i}", f"2026-10-0{i + 2}T10:00:00")
            self.test_log_path_through_the_config_reader_when_the_project_has_one()
        self.commit(".claude/gw.json", json.dumps(dict(CONFIG, **extra)) + "\n" * (1 + len(str(extra))), "cfg nueva")
        return self.figures()["figures"]["commit_subjects"]

    def test_a13_max_subjects_default_set_value_and_bad_value(self):
        default = self.subjects_with({})
        self.assertEqual(len(default["value"]), 6)  # 1 + 3 + the config commits: under the default 20
        self.assertIn("--max-count=20", default["source"])
        two = self.subjects_with({"mediaContent": {"maxSubjects": 2}})
        self.assertEqual(len(two["value"]), 2)
        self.assertIn("--max-count=2 ", two["source"])
        self.assertIn("the newest 2 at most", two["note"])
        bad = self.subjects_with({"mediaContent": {"maxSubjects": 0}})  # the config fails closed: the literal 20
        self.assertIn("--max-count=20", bad["source"])

    def test_invalid_config_is_reported_not_hidden(self):
        self.test_log_path_through_the_config_reader_when_the_project_has_one()
        self.commit(".claude/gw.json", '{"version": "0.4.0"}', "cfg roto")
        b = self.figures()["figures"]["log"]
        self.assertIsNone(b["value"])
        self.assertIn("invalid", b["note"])

    def test_output_is_json_with_root_and_today(self):
        out = self.figures()
        self.assertEqual(Path(out["root"]).resolve(), self.repo.resolve())
        self.assertRegex(out["today"], r"^\d{4}-\d{2}-\d{2}$")
        for name, fig in out["figures"].items():
            self.assertIn("source", fig, name)
            self.assertIn("value", fig, name)


if __name__ == "__main__":
    unittest.main()
