#!/usr/bin/env python3
# galivelop-workflow v0.9.0
"""Per-person and per-role profiles (E4, Q-25 to Q-30): who works with which profile, kept in .claude/gw.json.

  python3 profile.py list                       # profiles on disk, roles -> profile, people per role/profile
  python3 profile.py new NAME [--from OTHER]    # create <profiles.dir>/NAME.json ({} or a copy of OTHER)
  python3 profile.py assign EMAIL --role ROLE [--profile NAME]    # at least one of --role / --profile
  python3 profile.py role ROLE PROFILE          # profiles.roles: the role works with that profile
  python3 profile.py show [EMAIL]               # the profile that applies (default: git user.email) and its layer

Writing commands and `list` read the project's config alone (no profile layers), so `new` and `role` can fix a profile or
role that is missing; `show` applies the layers. Layers (Q-25): default (the project's .claude/gw.json) -> the person's role profile -> the person's own profile; CI
always runs with the default (Q-28). `assign` writes only the SHA-256 of the e-mail (trimmed, lower case; config.email_hash)
into `profiles.people`, never the address (Q-27: the repo may be public). It is convenience, not access control (Q-29).
Writes edit .claude/gw.json in place like mode.py: only the text of the affected value changes (EOL, tabs, compact
sections and key order stay), through a temp file and os.replace, validated with config.load, and the old text is put
back if the result is invalid. (config-guard.py asks the user before an agent runs `new`, `assign` or `role` or edits a profile, E4.) Project root and
config: config.find_root and config.load. Fails closed: no config, an invalid one, an unknown or invalid name -> exit 2
with the command that fixes it. Python 3.8+ standard library only.
"""
import argparse
import json
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.dont_write_bytecode = True  # no __pycache__ in the project's .claude/gw/scripts
sys.path.insert(0, str(HERE))
import config  # noqa: E402
import mode  # noqa: E402  (its JSON text-editing helpers)

NAME = Path(__file__).name


class Fail(Exception):
    """A user-facing failure: the message names the command that fixes it."""


def set_at(text, start, keys, value):
    """`text` with the value at `keys` (a path of object keys) inside the object whose `{` is at text[start] set to
    `value`; a missing key (or section) is added after the last member with its indent and line ending."""
    inner, end = mode.members(text, start)
    key, rest = keys[0], keys[1:]
    found = [m for m in inner if m[0] == key]
    if found:
        _, _, v_start, v_end = found[0]
        if not rest:
            return text[:v_start] + json.dumps(value) + text[v_end:]
        if text[v_start] == "{":
            return set_at(text, v_start, rest, value)
        return text[:v_start] + json.dumps(nest(rest, value)) + text[v_end:]
    member = json.dumps(key) + ": " + json.dumps(nest(rest, value))
    if inner:
        last = inner[-1]
        return text[:last[3]] + "," + mode.lead_of(text, last[1]) + member + text[last[3]:]
    return text[:start] + "{" + member + "}" + text[end + 1:]


def nest(keys, value):
    for key in reversed(keys):
        value = {key: value}
    return value


def edit_text(text, keys, value):
    """`text` (a gw.json) with the value at `keys` set to `value`, changing only that text."""
    return set_at(text, mode._WS.match(text, 0).end(), list(keys), value)


def check_chain(root, raw, email):
    """Fail closed unless the profiles that apply to `email` under the raw config `raw` load and are valid (CI or not):
    Fail with config.apply_profiles's reason."""
    try:
        raw, _done = config.migrate(json.loads(json.dumps(raw)))  # as load() does before it layers the profiles
        config.apply_profiles(raw, root, None, config._schema(), email=email, force=True)
    except config.ConfigError as exc:
        raise Fail(f"{exc}")


def write(root, keys, value, check_email=None):
    """Set the config value at `keys` in root/.claude/gw.json, changing only that text; atomic (temp file +
    os.replace). With `check_email`, the profile chain of that e-mail under the new config is validated first
    (check_chain); the file is then validated with config.load without layers, putting the old text back if it is
    invalid (ConfigError)."""
    path = Path(root) / config.CONFIG_REL
    old = path.read_bytes().decode("utf-8")
    expected = json.loads(old)
    node = expected
    for key in keys[:-1]:
        if not isinstance(node.get(key), dict):
            node[key] = {}
        node = node[key]
    node[keys[-1]] = value
    new = edit_text(old, keys, value)
    if json.loads(new) != expected:
        raise ValueError("the edit would change more than " + ".".join(keys[:2]))
    if check_email is not None:
        check_chain(root, expected, check_email)
    mode.replace(path, new)
    try:
        config.load(root, profiles=False)
    except config.ConfigError:
        mode.replace(path, old)
        raise


def block(conf):
    b = conf.get("profiles")
    return b if isinstance(b, dict) else {}


def profile_dir(conf):
    default = config._schema()["properties"]["profiles"]["default"]["dir"]
    return Path(conf["_root"]) / (block(conf).get("dir") or default)


def valid_name(name, what="profile name"):
    if not config.PROFILE_NAME.match(name or ""):
        raise Fail(f"invalid {what} `{name}` (letters, digits, `.`, `_`, `-`; it starts with a letter or digit); "
                   f"choose another, then: python3 {NAME} list")


def on_disk(conf):
    folder = profile_dir(conf)
    return sorted(p.stem for p in folder.glob("*.json") if p.is_file()) if folder.is_dir() else []


def need_profile(conf, name):
    valid_name(name)
    if name not in on_disk(conf):
        raise Fail(f"unknown profile `{name}` (not in {profile_dir(conf)}); create it: python3 {NAME} new {name}")


def short(digest):
    return digest[:8]


def cmd_list(conf):
    b = block(conf)
    names, roles, people = on_disk(conf), b.get("roles") or {}, b.get("people") or {}
    print("profiles: " + (", ".join(names) or "none") + f"  ({profile_dir(conf)})")
    print("roles:" + ("" if roles else " none"))
    for role, prof in sorted(roles.items()):
        who = sorted(short(h) for h, p in people.items() if p.get("role") == role)
        print(f"  {role} -> {prof}{'' if prof in names else ' (missing on disk)'}: {len(who)} people"
              + (f" ({', '.join(who)})" if who else ""))
    own = {}
    for h, p in people.items():
        if p.get("profile"):
            own.setdefault(p["profile"], []).append(short(h))
    print("own profile:" + ("" if own else " none"))
    for prof, who in sorted(own.items()):
        print(f"  {prof}: {len(who)} people ({', '.join(sorted(who))})")
    return 0


def cmd_new(conf, name, source):
    valid_name(name)
    folder, target = profile_dir(conf), profile_dir(conf) / f"{name}.json"
    if target.exists():
        raise Fail(f"profile `{name}` already exists ({target}); edit it by hand, or pick another name: "
                   f"python3 {NAME} new <name>")
    data = b"{}\n"
    if source is not None:
        need_profile(conf, source)
        data = (folder / f"{source}.json").read_bytes()
    folder.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name(target.name + ".tmp")
    try:
        tmp.write_bytes(data)
        os.replace(tmp, target)
    finally:
        if tmp.exists():
            tmp.unlink()
    print(f"created {target}" + (f" (copy of {source})" if source else ""))
    return 0


def cmd_role(conf, role, name):
    valid_name(role, "role name")
    need_profile(conf, name)
    fake = "role-check@invalid"
    probe = json.loads((Path(conf["_root"]) / config.CONFIG_REL).read_text(encoding="utf-8"))
    probe = dict(probe, profiles=dict(probe.get("profiles") or {}, people={config.email_hash(fake): {"role": role}},
                                      roles=dict((probe.get("profiles") or {}).get("roles") or {}, **{role: name})))
    check_chain(conf["_root"], probe, fake)
    write(conf["_root"], ["profiles", "roles", role], name)
    print(f"profiles.roles.{role}: {name}")
    return 0


def cmd_assign(conf, email, role, name):
    if not role and not name:
        raise Fail(f"assign needs --role or --profile (or both); run: python3 {NAME} assign <email> --role <role>")
    if not config.EMAIL_ADDRESS.match(email.strip()):
        raise Fail(f"`{email}` is not an e-mail address; run: python3 {NAME} assign <email> --role <role>")
    if role:
        valid_name(role, "role name")
        if role not in (block(conf).get("roles") or {}):
            raise Fail(f"role `{role}` has no profile in profiles.roles; give it one: python3 {NAME} role {role} <profile>")
    if name:
        need_profile(conf, name)
    digest = config.email_hash(email)
    entry = dict((block(conf).get("people") or {}).get(digest) or {})
    entry.update({k: v for k, v in (("role", role), ("profile", name)) if v})
    if entry.get("role") and entry["role"] not in (block(conf).get("roles") or {}):
        raise Fail(f"the role `{entry['role']}` this person already has is not in profiles.roles any more; give it a "
                   f"profile: python3 {NAME} role {entry['role']} <profile>, or assign another: python3 {NAME} "
                   f"assign <email> --role <role>")
    write(conf["_root"], ["profiles", "people", digest], entry, check_email=email)
    print(f"profiles.people.{short(digest)}...: {json.dumps(entry)}  (the address itself is not stored)")
    return 0


def cmd_show(conf, email):
    who = email if email is not None else config.git_email(conf["_root"])
    if config.in_ci():
        print("CI is set in the environment: CI always runs with the default (Q-28), no role or person layer applies")
        return 0
    if not who.strip():
        print("no e-mail (git config user.email is unset): layer default; set one, or: python3 "
              f"{NAME} show <email>")
        return 0
    choice = config.choose_profile(conf, who)
    for name in choice.get("_chain", []):
        need_profile(conf, name)
    tag = f"person {short(config.email_hash(who))}"
    if choice["layer"] == "default":
        print(f"{tag}: layer default (no assignment), the project's .claude/gw.json applies")
    elif choice["layer"] == "role":
        print(f"{tag}: profile {choice['profile']}, layer role (role {choice['role']})")
    else:
        extra = f", over role {choice['role']} -> {choice['roleProfile']}" if choice.get("role") else ""
        print(f"{tag}: profile {choice['profile']}, layer person{extra}")
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--root", help="project path (default: config.find_root)")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("list")
    new = sub.add_parser("new")
    new.add_argument("name")
    new.add_argument("--from", dest="source")
    assign = sub.add_parser("assign")
    assign.add_argument("email")
    assign.add_argument("--role")
    assign.add_argument("--profile")
    role = sub.add_parser("role")
    role.add_argument("role")
    role.add_argument("profile")
    show = sub.add_parser("show")
    show.add_argument("email", nargs="?")
    args = parser.parse_args(argv)
    try:
        conf = config.load(args.root, profiles=False)
    except config.ConfigError as exc:
        print(f"gw profile: {exc}; fix .claude/gw.json, then: python3 {NAME} list", file=sys.stderr)
        return 2
    try:
        if args.command == "list":
            return cmd_list(conf)
        if args.command == "new":
            return cmd_new(conf, args.name, args.source)
        if args.command == "role":
            return cmd_role(conf, args.role, args.profile)
        if args.command == "assign":
            return cmd_assign(conf, args.email, args.role, args.profile)
        return cmd_show(conf, args.email)
    except Fail as exc:
        print(f"gw profile{' show' if args.command == 'show' else ''}: {exc}", file=sys.stderr)
        return 2
    except (OSError, ValueError, config.ConfigError) as exc:
        if args.command in ("list", "show"):
            print(f"gw profile {args.command}: {exc}; fix it, then: python3 {NAME} {args.command}", file=sys.stderr)
        else:
            print(f"gw profile: nothing was changed ({exc}); fix it, then: python3 config.py validate",
                  file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
