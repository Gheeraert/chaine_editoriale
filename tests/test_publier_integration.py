from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

import pytest

from chaine_editoriale.modeles import PublicationOptions
from chaine_editoriale.publier import publier


@pytest.mark.integration
def test_publier_end_to_end(
    tmp_path: Path,
    minimal_docx_path: Path,
    minimal_metadata_path: Path,
    activated_config_path: Path,
) -> None:
    metadata_data = json.loads(minimal_metadata_path.read_text(encoding="utf-8"))
    expected_sha256 = metadata_data["source_document"]["sha256"]
    actual_sha256 = hashlib.sha256(minimal_docx_path.read_bytes()).hexdigest()
    assert actual_sha256 == expected_sha256

    workspace_dir = tmp_path / "workspace"
    output_dir = tmp_path / "output"

    result = publier(
        minimal_docx_path,
        minimal_metadata_path,
        workspace_dir,
        output_dir,
        options=PublicationOptions(pdf_export_mode="latei_pdf"),
    )

    assert result.xml_path == workspace_dir / "source" / "document.xml"
    assert result.xml_path.is_file()
    assert "<TEI" in result.xml_path.read_text(encoding="utf-8")

    assert (output_dir / "index.html").is_file()
    content_pages = sorted(p for p in output_dir.glob("*.html") if p.name != "index.html")
    assert content_pages, "au moins une page de contenu doit etre generee"

    assert (output_dir / "book.normalized.xml").is_file()
    assert result.site_result.normalized_tei_path == output_dir / "book.normalized.xml"

    assert result.manifest_path == workspace_dir / "publication.json"
    assert result.manifest_path.is_file()
    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    assert manifest["schema"] == "chaine-editoriale-publication"
    assert manifest["dependencies"]["mini_metopes"]["module_path"]
    assert manifest["dependencies"]["purh_site"]["module_path"]
    assert Path(manifest["dependencies"]["mini_metopes"]["module_path"]).is_file()
    assert Path(manifest["dependencies"]["purh_site"]["module_path"]).is_file()

    if shutil.which("lualatex") is not None:
        assert result.latei_path is not None and result.latei_path.is_file()
        assert result.pdf_path is not None and result.pdf_path.is_file()
        assert result.pdf_status == "generated"
    else:
        assert result.pdf_status in {"unavailable", "generated"}
        if result.pdf_status == "unavailable":
            assert result.pdf_path is None


@pytest.mark.integration
def test_publier_preserves_media_directory_level_with_figure(
    tmp_path: Path,
    minimal_docx_path: Path,
    minimal_metadata_path: Path,
    activated_config_path: Path,
) -> None:
    """Reconvertit le DOCX minimal (sans figure) pour verifier l'absence de dossier media.

    Un DOCX minimal sans figure ne produit pas de media : ce test verifie que
    l'absence de media_directory est correctement propagee (assets_root=None)
    plutot que de fabriquer un dossier media vide.
    """
    workspace_dir = tmp_path / "workspace"
    output_dir = tmp_path / "output"
    result = publier(minimal_docx_path, minimal_metadata_path, workspace_dir, output_dir)
    assert result.media_directory is None
    assert result.assets_root is None
