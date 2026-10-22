#!/usr/bin/env python3
# galivelop-workflow v0.2.0
"""The transcript (.jsonl) of the Claude Code session working on this repo. Shared by recuperar.py and doctor.py.

Claude Code stores each session in ~/.claude/projects/<working folder with every non-alphanumeric as "-">/. A session
opened in a folder that contains the repo (in the cloud, /home/user with several repos in it) stores it in that
folder's directory, not the repo's, and did not load the repo's .claude/settings.json (VeriNews P3). So the search
covers the repo folder and its parent folders (never sibling repos), plus the cloud start folder (-home-user), and
the newest transcript wins. When it is not the repo's own folder, a warning goes to stderr.

  python3 registro_sesion.py --path          # print the transcript path (exit 1 if there is none)
  python3 registro_sesion.py --path --root R # for the repo at R (default: see config.find_root)

Python 3.8+ standard library only.
"""
import argparse
import glob
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
CLOUD_START = "-home-user"  # cloud sessions start in /home/user whatever repo they work on


def folder_of(path):
    """Name Claude Code gives to the transcript folder of a working directory."""
    return re.sub(r"[^A-Za-z0-9]", "-", path)


def projects_dir():
    return os.path.join(os.path.expanduser("~"), ".claude", "projects")


def candidate_folders(root):
    root = os.path.abspath(str(root))
    folders, current = [], root
    while True:
        folders.append(folder_of(current))
        parent = os.path.dirname(current)
        if parent == current:
            break
        current = parent
    folders.append(CLOUD_START)
    return list(dict.fromkeys(folders))


def find(root, transcript=None, warn=True):
    """(path, own) of the newest transcript for root; own is False when it lives in another folder. (None, False)
    if there is none. An explicit transcript (e.g. the hook's transcript_path) wins when it exists."""
    root = os.path.abspath(str(root))
    if transcript and os.path.isfile(transcript):
        return transcript, os.path.basename(os.path.dirname(transcript)) == folder_of(root)
    base = projects_dir()
    candidates = [p for f in candidate_folders(root) for p in glob.glob(os.path.join(glob.escape(base), f, "*.jsonl"))]
    if not candidates:
        return None, False
    path = max(candidates, key=os.path.getmtime)
    folder = os.path.basename(os.path.dirname(path))
    own = folder == folder_of(root)
    if not own and warn:
        print(f"warning: the session transcript is in {folder}, not the repo's folder ({folder_of(root)}): the session "
              f"was opened outside the repo and may not have loaded its .claude/settings.json; if it is not this "
              f"session, pass the transcript explicitly, or restart Claude Code from the repo: cd {root} && claude",
              file=sys.stderr)
    return path, own


def opened_outside(root):
    """The folder name when the newest transcript is not the repo's own (session opened outside it), else None."""
    path, own = find(root, warn=False)
    if path is None or own:
        return None
    return os.path.basename(os.path.dirname(path))


def default_root():
    sys.dont_write_bytecode = True  # no __pycache__ in the project's .claude/gw/scripts
    sys.path.insert(0, HERE)
    try:
        import config
        return str(config.find_root())
    except Exception:  # config.ConfigError or an import problem: fall back to the current directory
        return os.getcwd()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--path", action="store_true", help="print the transcript path")
    parser.add_argument("--root", help="repo path (default: the git top level, as config.py finds it)")
    args = parser.parse_args(argv)
    if not args.path:
        parser.print_help()
        return 2
    root = args.root or default_root()
    path, _ = find(root)
    if path is None:
        print(f"no session transcript under {projects_dir()} for {root} or its parent folders; "
              f"start Claude Code from the repo: cd {root} && claude", file=sys.stderr)
        return 1
    print(path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
