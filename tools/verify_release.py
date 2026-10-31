#!/usr/bin/env python3

from pathlib import Path
import argparse
import hashlib
import json
import subprocess
import sys


IDENTITY = "cosmic-laws-release"
NAMESPACE = "cosmic-laws-release"


def die(message):
    print(f"VERIFY FAIL: {message}", file=sys.stderr)
    raise SystemExit(1)


def sha256(path):
    h = hashlib.sha256()

    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)

    return h.hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("release_dir")
    parser.add_argument(
        "--allowed-signers",
        default="trust/cosmic-laws-release.allowed_signers",
    )
    args = parser.parse_args()

    release = Path(args.release_dir).resolve()
    allowed = Path(args.allowed_signers).resolve()

    manifest = release / "MANIFEST.sha256"
    signature = release / "MANIFEST.sha256.sig"
    release_json = release / "RELEASE.json"

    for required in (
        manifest,
        signature,
        release_json,
        allowed,
    ):
        if not required.is_file():
            die(f"missing required file: {required}")

    # Verify Mother Vault signature first.
    result = subprocess.run(
        [
            "ssh-keygen",
            "-Y", "verify",
            "-f", str(allowed),
            "-I", IDENTITY,
            "-n", NAMESPACE,
            "-s", str(signature),
        ],
        input=manifest.read_bytes(),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )

    if result.returncode != 0:
        die(
            "signature verification failed:\n"
            + result.stdout.decode(errors="replace")
        )

    # Verify every signed file hash.
    checked = 0

    for line in manifest.read_text(
        encoding="utf-8"
    ).splitlines():
        if not line.strip():
            continue

        try:
            expected, relative = line.split("  ", 1)
        except ValueError:
            die(f"malformed manifest line: {line}")

        rel = Path(relative)

        if rel.is_absolute() or ".." in rel.parts:
            die(f"unsafe manifest path: {relative}")

        target = (release / rel).resolve()

        try:
            target.relative_to(release)
        except ValueError:
            die(f"path escapes release: {relative}")

        if not target.is_file():
            die(f"missing signed file: {relative}")

        actual = sha256(target)

        if actual != expected:
            die(
                f"hash mismatch: {relative}\n"
                f"expected {expected}\n"
                f"actual   {actual}"
            )

        checked += 1

    metadata = json.loads(
        release_json.read_text(encoding="utf-8")
    )

    if metadata.get("mirror_policy") != "read-only":
        die("release mirror policy is not read-only")

    if metadata.get("law_count") != 144:
        die("release does not declare 144 laws")

    if metadata.get("authority") != "Mother Vault":
        die("release authority mismatch")

    print("===== RELEASE VERIFIED =====")
    print(f"Release:       {metadata['release_id']}")
    print("Signature:     PASS")
    print(f"Signed files:  {checked}")
    print("Hashes:        PASS")
    print("Mirror policy: READ-ONLY")
    print("Authority:     Mother Vault")


if __name__ == "__main__":
    main()
