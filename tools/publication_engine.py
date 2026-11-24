"""Manifest-driven publication extensions and guarded filesystem promotion."""
import argparse
import fcntl
import hashlib
import html
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import tempfile

INVENTORY = ".publication-inventory.json"
MARKER = ".cosmic-laws-derived"


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def inventory(path):
    if path.is_symlink() or not path.is_dir():
        raise ValueError(f"Expected real directory: {path}")
    result = {}
    for item in sorted(path.rglob("*")):
        if item.is_symlink():
            raise ValueError(f"Symlink not allowed: {item}")
        if item.is_file():
            result[item.relative_to(path).as_posix()] = digest(item)
        elif not item.is_dir():
            raise ValueError(f"Unsupported filesystem entry: {item}")
    return result


def relative_path(value):
    if not isinstance(value, str) or not re.fullmatch(
        r"[A-Za-z0-9_-][A-Za-z0-9_.-]*(/[A-Za-z0-9_-][A-Za-z0-9_.-]*)*", value
    ):
        raise ValueError(f"Unsafe path: {value!r}")
    p = PurePosixPath(value)
    if any(part in (".", "..") for part in p.parts):
        raise ValueError(f"Unsafe path: {value!r}")
    return p


def checked_source(root, value):
    path = relative_path(value)
    if path.parts[0] not in ("gateway_source", "site_source"):
        raise ValueError("Module sources must be under gateway_source/ or site_source/")
    current = root
    for part in path.parts:
        current = current / part
        if current.is_symlink():
            raise ValueError(f"Symlink source: {current}")
    return current


def modules(root):
    manifest = root / "manifests" / "publication-manifest.json"
    if manifest.is_symlink() or manifest.parent.is_symlink():
        raise ValueError("Manifest symlinks not allowed")
    obj = json.loads(manifest.read_text(encoding="utf-8"))
    if obj.get("schema_version") != 1 or not isinstance(obj.get("modules"), list):
        raise ValueError("Unsupported publication manifest")
    seen, destinations, result = set(), [], []
    for module in obj["modules"]:
        ident = module["id"]
        if not isinstance(ident, str) or not re.fullmatch(r"[a-z0-9-]+", ident) or ident in seen:
            raise ValueError(f"Invalid or duplicate module ID: {ident}")
        seen.add(ident)
        dest = relative_path(module["destination"])
        if dest.parts[0] in ("records", "assets", "_layouts", "_config.yml", "index.md",
                             "laws.md", "search.md", "search-index.json"):
            raise ValueError(f"Reserved core destination: {dest}")
        if any(dest == x or dest in x.parents or x in dest.parents for x in destinations):
            raise ValueError(f"Overlapping destination: {dest}")
        destinations.append(dest)
        source = checked_source(root, module["source"])
        entry = relative_path(module["entrypoint"])
        if entry.name != "index.html":
            raise ValueError("Module entrypoint must be index.html")
        for key in ("navigation_label", "homepage_label"):
            if not isinstance(module[key], str) or not module[key].strip():
                raise ValueError(f"Missing module label: {ident}/{key}")
        files = inventory(source)
        if entry.as_posix() not in files:
            raise ValueError(f"Missing entrypoint: {ident}/{entry}")
        result.append((module, source, dest, entry, files))
    return result


def inject_once(path, needle, addition):
    text = path.read_text(encoding="utf-8")
    if text.count(needle) != 1:
        raise ValueError(f"Expected unique insertion point in {path}")
    path.write_text(text.replace(needle, addition + needle), encoding="utf-8")


def validate_module_links(stage, destination):
    """Check explicit Jekyll relative_url references in module pages.
    Does not claim to validate arbitrary Markdown, JS or external URLs."""
    for path in destination.rglob("*"):
        if not path.is_file() or path.suffix not in (".html", ".md"):
            continue
        text = path.read_text(encoding="utf-8")
        for url in re.findall(r"\{\{\s*['\"](/[^'\"]*)['\"]\s*\|\s*relative_url\s*\}\}", text):
            clean = url.split("#", 1)[0].split("?", 1)[0].lstrip("/")
            if not clean:
                continue
            rel = relative_path(clean.rstrip("/"))
            target = stage / rel
            if url.endswith("/"):
                candidates = [target / "index.html", target / "index.md"]
                # Jekyll pages may explicitly publish to /some/page/.
                candidates += [target.with_suffix(".md"), target.with_suffix(".html")]
            else:
                candidates = [target]
                if target.suffix == ".html":
                    candidates.append(target.with_suffix(".md"))
            if not any(p.is_file() for p in candidates):
                raise ValueError(f"Broken module link in {path}: {url}")


def assemble(root, stage):
    registered = modules(root)
    nav, home = [], []
    for module, source, dest, entry, files in registered:
        target = stage / dest
        if target.exists():
            raise ValueError(f"Module collides with generated output: {dest}")
        shutil.copytree(source, target)
        if inventory(target) != files or inventory(source) != files:
            raise ValueError(f"Module copy integrity failure: {module['id']}")
        url = "/" + (dest / entry.parent).as_posix().rstrip("/") + "/"
        nav.append("        <a href=\"{{ '" + url + "' | relative_url }}\">" +
                   html.escape(module["navigation_label"]) + "</a>\n")
        home.append('    <a class="button" href="{{ \'' + url +
                    '\' | relative_url }}">' + html.escape(module["homepage_label"]) + "</a>\n")
    if nav:
        inject_once(stage / "_layouts/default.html", "      </nav>", "".join(nav))
        inject_once(stage / "index.md", "  </div>\n</section>", "".join(home))
    for _, _, dest, _, _ in registered:
        validate_module_links(stage, stage / dest)
    result = {"schema_version": 1,
              "files": inventory(stage),
              "modules": [m["id"] for m, *_ in registered]}
    (stage / INVENTORY).write_text(json.dumps(result, indent=2, sort_keys=True) + "\n",
                                   encoding="utf-8")
    return result


def guard_existing(output, stage):
    if not output.exists() and not output.is_symlink():
        return
    old = inventory(output)
    if MARKER not in old:
        raise ValueError("Refusing to replace an unmarked publication directory")
    new = inventory(stage)
    removed = sorted(set(old) - set(new))
    if removed:
        raise ValueError("Refusing to delete publication files: " + ", ".join(removed))
    if INVENTORY in old:
        previous = json.loads((output / INVENTORY).read_text(encoding="utf-8"))
        if previous.get("schema_version") != 1 or not isinstance(previous.get("files"), dict):
            raise ValueError("Invalid previous publication inventory")
        actual = {k: v for k, v in old.items() if k != INVENTORY}
        if previous["files"] != actual:
            drift = sorted(k for k in set(previous["files"]) | set(actual)
                           if previous["files"].get(k) != actual.get(k))
            raise ValueError("Existing output differs from inventory; preserve edits first: "
                             + ", ".join(drift))


def promote(root, output, stage, check=False):
    """Validate without mutation, or retain a rollback snapshot before promotion."""
    if check:
        guard_existing(output, stage)
        print("CHECK PASSED: staged publication validated; docs unchanged")
        return
    lock_path = root / ".publication.lock"
    fd = os.open(lock_path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        guard_existing(output, stage)
        backup = None
        if output.exists():
            backup_root = root / ".publication-backups"
            if backup_root.is_symlink():
                raise ValueError("Backup root cannot be a symlink")
            backup_root.mkdir(exist_ok=True)
            slot = Path(tempfile.mkdtemp(prefix="site-", dir=backup_root))
            backup = slot / "docs"
            output.rename(backup)
        try:
            stage.rename(output)
        except BaseException:
            if backup is not None:
                backup.rename(output)
            raise
        if backup is not None:
            print(f"Previous site retained at: {backup}")


def parse_options():
    parser = argparse.ArgumentParser(description="Build the deterministic public site")
    parser.add_argument("--check", action="store_true",
                        help="Validate in staging without replacing docs")
    return parser.parse_args()
