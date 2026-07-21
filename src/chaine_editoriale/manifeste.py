"""Construction et ecriture de publication.json.

``publication.json`` decrit une publication particuliere (sources, TEI
intermediaire, sorties, options, dependances effectivement utilisees). Il
est toujours distinct de ``config_chaine.json``, qui decrit la configuration
technique locale de l'application.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

from .modeles import PublicationOptions

MANIFEST_SCHEMA_NAME = "chaine-editoriale-publication"
MANIFEST_SCHEMA_VERSION = 1


def _relative_or_absolute(path: Path | None, *bases: Path) -> str | None:
    if path is None:
        return None
    resolved = path.resolve()
    for base in bases:
        try:
            return resolved.relative_to(base.resolve()).as_posix()
        except ValueError:
            continue
    return resolved.as_posix()


def build_publication_manifest(
    *,
    workspace_dir: Path,
    output_dir: Path,
    docx_path: Path,
    docx_sha256: str,
    metadata_path: Path,
    metadata_sha256: str,
    tei_path: Path,
    tei_sha256: str,
    media_directory: Path | None,
    options: PublicationOptions,
    outputs: dict[str, Path | None],
    pdf_status: str,
    dependencies: dict[str, dict[str, str]],
) -> dict[str, Any]:
    """Construire le manifeste de publication sous forme de dictionnaire deterministe."""
    bases = (workspace_dir, output_dir)
    return {
        "schema": MANIFEST_SCHEMA_NAME,
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "sources": {
            "docx": {
                "path": _relative_or_absolute(docx_path, *bases),
                "sha256": docx_sha256,
            },
            "metadata": {
                "path": _relative_or_absolute(metadata_path, *bases),
                "sha256": metadata_sha256,
            },
        },
        "intermediate": {
            "tei": {
                "path": _relative_or_absolute(tei_path, *bases),
                "sha256": tei_sha256,
            },
            "media_directory": _relative_or_absolute(media_directory, *bases),
        },
        "options": {
            "write_normalized_tei": options.write_normalized_tei,
            "pdf_export_mode": options.pdf_export_mode,
            "latex_engine": options.latex_engine,
        },
        "outputs": {
            "index_html": _relative_or_absolute(outputs.get("index_html"), *bases),
            "normalized_tei": _relative_or_absolute(outputs.get("normalized_tei"), *bases),
            "latei": _relative_or_absolute(outputs.get("latei"), *bases),
            "pdf": _relative_or_absolute(outputs.get("pdf"), *bases),
            "build_report": _relative_or_absolute(outputs.get("build_report"), *bases),
        },
        "pdf_status": pdf_status,
        "dependencies": dependencies,
    }


def write_publication_manifest(manifest: dict[str, Any], path: Path) -> Path:
    """Ecrire publication.json en UTF-8, de maniere atomique et lisible."""
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=False) + "\n"
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=path.parent, prefix=f".{path.name}.", suffix=".tmp", delete=False
        ) as temporary:
            temporary.write(payload)
            temporary_path = Path(temporary.name)
        os.replace(temporary_path, path)
    except OSError:
        if temporary_path is not None:
            try:
                temporary_path.unlink(missing_ok=True)
            except OSError:
                pass
        raise
    return path
