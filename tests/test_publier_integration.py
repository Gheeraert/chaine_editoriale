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
def test_publier_without_media_leaves_assets_root_none(
    tmp_path: Path,
    minimal_docx_path: Path,
    minimal_metadata_path: Path,
    activated_config_path: Path,
) -> None:
    """Le DOCX minimal ne contient aucune image : aucun dossier media ne doit etre fabrique.

    Nomme honnetement (contrairement a l'ancien nom qui laissait croire a une
    figure) : ce document n'a pas de media, donc media_directory/assets_root
    doivent rester None plutot que de produire un dossier media vide.
    """
    workspace_dir = tmp_path / "workspace"
    output_dir = tmp_path / "output"
    result = publier(minimal_docx_path, minimal_metadata_path, workspace_dir, output_dir)
    assert result.media_directory is None
    assert result.assets_root is None


@pytest.mark.integration
def test_publier_end_to_end_with_real_image(
    tmp_path: Path,
    fixtures_dir: Path,
    activated_config_path: Path,
) -> None:
    """Pipeline complet avec une veritable image PNG incorporee dans le DOCX."""
    from lxml import html as lxml_html

    docx_path = fixtures_dir / "document_avec_image.docx"
    metadata_path = fixtures_dir / "document_avec_image.metadata.json"
    metadata_data = json.loads(metadata_path.read_text(encoding="utf-8"))
    expected_sha256 = metadata_data["source_document"]["sha256"]
    assert hashlib.sha256(docx_path.read_bytes()).hexdigest() == expected_sha256

    workspace_dir = tmp_path / "workspace"
    output_dir = tmp_path / "output"

    result = publier(docx_path, metadata_path, workspace_dir, output_dir, options=PublicationOptions(pdf_export_mode="none"))

    # 1-2. un media intermediaire a bien ete produit par Mini-Metopes.
    assert result.media_directory is not None
    assert result.media_directory.is_dir()
    source_media_files = sorted(p for p in result.media_directory.iterdir() if p.is_file())
    assert len(source_media_files) >= 1

    # 3-4. le niveau media/ est preserve sous workspace/impressions-assets/media/.
    assert result.assets_root is not None
    workspace_media_dir = result.assets_root / "media"
    assert workspace_media_dir.is_dir()
    for source_file in source_media_files:
        target = workspace_media_dir / source_file.name
        assert target.is_file(), target
        assert target.read_bytes() == source_file.read_bytes()

    # 5. les memes fichiers se retrouvent sous output/assets/media/ (niveau media/ non aplati).
    output_media_dir = output_dir / "assets" / "media"
    assert output_media_dir.is_dir()
    for source_file in source_media_files:
        target = output_media_dir / source_file.name
        assert target.is_file(), target
        assert target.read_bytes() == source_file.read_bytes()

    # 6-7. le HTML de contenu reference reellement le media, et la cible existe.
    content_pages = sorted(p for p in output_dir.glob("*.html") if p.name != "index.html")
    assert content_pages, "au moins une page de contenu doit etre generee"
    found_image_reference = False
    for page in content_pages:
        document = lxml_html.fromstring(page.read_text(encoding="utf-8"))
        for img in document.xpath("//img[@src]"):
            src = img.get("src")
            if not src or src.startswith(("http://", "https://", "data:")):
                continue
            target_path = (page.parent / src).resolve()
            if target_path.is_file() and target_path.parent.name == "media":
                found_image_reference = True
                assert target_path.read_bytes() in {f.read_bytes() for f in source_media_files}
    assert found_image_reference, "aucune reference HTML vers le media n'a ete trouvee et resolue"

    # 9. publication.json contient un chemin de media resoluble depuis le manifeste.
    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    manifest_media_directory = manifest["intermediate"]["media_directory"]
    assert manifest_media_directory is not None
    resolved_manifest_media = (result.manifest_path.parent / manifest_media_directory).resolve()
    assert resolved_manifest_media == result.media_directory.resolve()
