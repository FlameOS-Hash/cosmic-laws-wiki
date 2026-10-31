# Cosmic Laws Wiki

Public repository for the Cosmic Laws registry and its deterministic publication layer.

## Read the Cosmic Laws

The authoritative human-readable publication is located here:

**[Cosmic Laws Index](wiki/cosmic-laws/index.md)**

This publication contains:

- 144 Cosmic Law records
- 26 Cosmic Law Rewrite Sequence records
- 1 final sequence record
- the complete generated index

## Repository Architecture

- `canonical/` — source registry records and preserved source material
- `wiki/cosmic-laws/` — authoritative deterministic human-readable publication
- `wiki/concepts/` — derived deterministic navigation/query projection
- `raw/projection/` — derived ingestion projection
- `raw/ingested/` — verified deterministic ingestion copies
- `manifests/` — conversion, integrity, recovery, and ingestion manifests
- `tools/converters/` — deterministic conversion and ingestion tooling

## Integrity Model

The Cosmic Law publication is generated deterministically from the preserved registry sources.

The LLM layer is not permitted to rewrite the canonical records or determine the contents of the Cosmic Laws.

Canonical source → deterministic conversion → publication → navigation/query layer.

## Recovery Sources

Preserved recovery-source archives are retained in this repository for provenance and reconstruction history.

## Repository

`FlameOS-Hash/cosmic-laws-wiki`
