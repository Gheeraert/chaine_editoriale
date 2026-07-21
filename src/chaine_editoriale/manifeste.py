"""Construction et ecriture de publication.json.

``publication.json`` decrit une publication particuliere (sources, TEI
intermediaire, sorties, options, dependances effectivement utilisees). Il
est toujours distinct de ``config_chaine.json``, qui decrit la configuration
technique locale de l'application.

Tous les chemins relatifs enregistres dans ``sources``, ``intermediate`` et
``outputs`` sont relatifs au dossier qui contient ``publication.json``
lui-meme (``manifest_dir``), jamais a ``workspace_dir`` ou ``output_dir``
pris isolement : ce sont ces deux dossiers determinent generalement des
volumes differents. Seuls les chemins de ``dependencies`` restent absolus,
car ils decrivent l'environnement local utilise.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

from .erreurs import ManifestWriteError
from .modeles import PublicationOptions

MANIFEST_SCHEMA_NAME = "chaine-editoriale-publication"
MANIFEST_SCHEMA_VERSION = 1


def path_for_manifest(path: Path | None, manifest_dir: Path) -> str | None:
    """Rendre ``path`` resoluble depuis le dossier de ``publication.json``.

    Retourne un chemin relatif a ``manifest_dir`` avec des ``/`` lorsque
    c'est possible (meme volume) ; sinon un chemin absolu. Ne depend jamais
    du repertoire courant.
    """
    if path is None:
        return None
    resolved = path.resolve()
    resolved_manifest_dir = manifest_dir.resolve()
    try:
        relative = os.path.relpath(resolved, resolved_manifest_dir)
    except ValueError:
        # Chemins sur deux lecteurs Windows differents : aucun relatif possible.
        return resolved.as_posix()
    return Path(relative).as_posix()


def build_publication_manifest(
    *,
    manifest_dir: Path,
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

    def rel(path: Path | None) -> str | None:
        return path_for_manifest(path, manifest_dir)

    return {
        "schema": MANIFEST_SCHEMA_NAME,
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "sources": {
            "docx": {
                "path": rel(docx_path),
                "sha256": docx_sha256,
            },
            "metadata": {
                "path": rel(metadata_path),
                "sha256": metadata_sha256,
            },
        },
        "intermediate": {
            "tei": {
                "path": rel(tei_path),
                "sha256": tei_sha256,
            },
            "media_directory": rel(media_directory),
        },
        "options": {
            "write_normalized_tei": options.write_normalized_tei,
            "pdf_export_mode": options.pdf_export_mode,
            "latex_engine": options.latex_engine,
        },
        "outputs": {
            "index_html": rel(outputs.get("index_html")),
            "normalized_tei": rel(outputs.get("normalized_tei")),
            "latei": rel(outputs.get("latei")),
            "pdf": rel(outputs.get("pdf")),
            "build_report": rel(outputs.get("build_report")),
        },
        "pdf_status": pdf_status,
        "dependencies": dependencies,
    }


def write_publication_manifest(manifest: dict[str, Any], path: Path) -> Path:
    """Ecrire publication.json en UTF-8, de maniere atomique et lisible.

    N'expose jamais un ``OSError`` brut a la frontiere publique : toute
    erreur systeme est convertie en ``ManifestWriteError`` avec la cause
    d'origine conservee.
    """
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
    except OSError as error:
        raise ManifestWriteError(f"impossible de creer le dossier du manifeste : {path.parent}", path=str(path), cause=error) from error

    payload = json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=False) + "\n"
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=path.parent, prefix=f".{path.name}.", suffix=".tmp", delete=False
        ) as temporary:
            temporary.write(payload)
            temporary_path = Path(temporary.name)
        os.replace(temporary_path, path)
    except OSError as error:
        if temporary_path is not None:
            try:
                temporary_path.unlink(missing_ok=True)
            except OSError:
                pass
        raise ManifestWriteError(f"ecriture du manifeste impossible : {path}", path=str(path), cause=error) from error
    return path
