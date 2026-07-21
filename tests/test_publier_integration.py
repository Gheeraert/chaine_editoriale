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

    # 3-4. le niveau media/ est preserve sous workspace/impressions-assets/images/media/
    # (seul emplacement reellement lu par le HTML d'Impressions, voir
    # publier.prepare_media_layout_for_impressions).
    assert result.assets_root is not None
    workspace_media_dir = result.assets_root / "images" / "media"
    assert workspace_media_dir.is_dir()
    for source_file in source_media_files:
        target = workspace_media_dir / source_file.name
        assert target.is_file(), target
        assert target.read_bytes() == source_file.read_bytes()

    # 5. les memes fichiers se retrouvent sous output/assets/images/media/ (niveau media/ non aplati).
    output_media_dir = output_dir / "assets" / "images" / "media"
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


@pytest.mark.integration
def test_publier_latei_pdf_with_real_image(
    tmp_path: Path,
    fixtures_dir: Path,
    activated_config_path: Path,
) -> None:
    """Pipeline complet DOCX avec image -> TEI -> HTML -> LaTEI -> PDF.

    Determine, a partir d'une execution reelle (aucun mock), le contrat
    definitif de resolution des chemins d'images entre Mini-Metopes et
    Impressions pour le HTML *et* pour LaTEI/PDF. Voir
    ``publier.prepare_media_layout_for_impressions`` pour la decision prise.
    """
    from lxml import etree
    from lxml import html as lxml_html

    docx_path = fixtures_dir / "document_avec_image.docx"
    metadata_path = fixtures_dir / "document_avec_image.metadata.json"

    workspace_dir = tmp_path / "workspace"
    output_dir = tmp_path / "output"

    result = publier(docx_path, metadata_path, workspace_dir, output_dir, options=PublicationOptions(pdf_export_mode="latei_pdf"))

    diagnostics: dict[str, str] = {}

    # 1. le DOCX est reellement converti en TEI.
    assert result.xml_path.is_file()
    tei_root = etree.parse(str(result.xml_path)).getroot()

    # 2. la TEI contient une figure et un graphic/media.
    tei_ns = {"tei": "http://www.tei-c.org/ns/1.0"}
    figures = tei_root.xpath("//tei:figure", namespaces=tei_ns)
    assert figures, "la TEI doit contenir au moins une figure"
    graphics = tei_root.xpath("//tei:figure//tei:graphic", namespaces=tei_ns)
    assert graphics, "la figure doit contenir un graphic"
    tei_image_url = graphics[0].get("url")
    assert tei_image_url and tei_image_url.startswith("media/")
    diagnostics["tei_image_path"] = tei_image_url

    # 3. le media extrait existe reellement.
    assert result.media_directory is not None
    media_files = sorted(p for p in result.media_directory.iterdir() if p.is_file())
    assert media_files, "au moins un media doit avoir ete extrait"
    image_sha256 = tei_image_url.split("/", 1)[1].rsplit(".", 1)[0]
    assert any(image_sha256 in f.name for f in media_files)

    # 4. la page HTML contient une image dont la cible existe.
    content_pages = sorted(p for p in output_dir.glob("*.html") if p.name != "index.html")
    assert content_pages, "au moins une page de contenu doit etre generee"
    html_image_src: str | None = None
    for page in content_pages:
        document = lxml_html.fromstring(page.read_text(encoding="utf-8"))
        for img in document.xpath("//img[@src]"):
            src = img.get("src")
            if src and image_sha256 in src:
                target_path = (page.parent / src).resolve()
                assert target_path.is_file(), f"cible HTML introuvable : {target_path}"
                html_image_src = src
                diagnostics["html_image_path"] = src
                diagnostics["html_image_resolved"] = str(target_path)
    assert html_image_src is not None, "aucune reference HTML vers l'image n'a ete trouvee"

    # 5. le LaTEI existe.
    assert result.latei_path is not None and result.latei_path.is_file()
    latei_text = result.latei_path.read_text(encoding="utf-8")

    # 6. le LaTEI contient une reference vers l'image (URL documentaire TEI,
    # via la macro \teiGraphic) et, si l'empaquetage a reussi, une entree
    # \lateiDeclareGraphic vers le fichier local reellement copie.
    assert tei_image_url in latei_text, "le LaTEI doit referencer l'URL documentaire TEI de l'image"
    generated_dir = output_dir / "assets" / "generated"
    graphics_map_candidates = sorted(generated_dir.glob("*graphics_map*"))
    assert graphics_map_candidates, "le mapping graphique LaTEI doit etre produit"
    graphics_map_text = graphics_map_candidates[0].read_text(encoding="utf-8")
    assert f"Image not found for LaTEI package: {tei_image_url}" not in graphics_map_text, (
        "le contournement prepare_media_layout_for_impressions doit permettre a "
        "purh_site.latei_assets.package_latei_graphics de trouver l'image "
        f"(voir {graphics_map_candidates[0]})"
    )
    declare_match = None
    for line in graphics_map_text.splitlines():
        if line.startswith(r"\lateiDeclareGraphic") and tei_image_url in line:
            declare_match = line
    assert declare_match is not None, "aucune entree \\lateiDeclareGraphic pour l'image de la figure"

    # 7. le chemin local declare est resoluble depuis le repertoire de
    # compilation reel (assets/generated/), conformement a la documentation
    # d'Impressions (LuaLaTeX compile depuis pdf_path.parent).
    local_latex_path = declare_match.split("}{", 1)[1].rstrip("}")
    compile_dir = generated_dir
    resolved_latei_image = (compile_dir / local_latex_path).resolve()
    assert resolved_latei_image.is_file(), f"chemin LaTEI non resoluble depuis le repertoire de compilation : {resolved_latei_image}"
    diagnostics["latei_image_path"] = local_latex_path
    diagnostics["latei_compile_dir"] = str(compile_dir)
    diagnostics["latei_image_resolved"] = str(resolved_latei_image)

    if shutil.which("lualatex") is not None:
        # 8. le PDF existe, la compilation ne signale pas d'image introuvable.
        assert result.pdf_path is not None and result.pdf_path.is_file()
        assert result.pdf_status == "generated"
        log_candidates = sorted(generated_dir.glob("*.log"))
        assert log_candidates, "un journal de compilation LuaLaTeX doit exister"
        missing_image_markers = ("File `", "not found", "LaTeX Error: File", "Error: File")
        for log_path in log_candidates:
            log_text = log_path.read_text(encoding="utf-8", errors="replace")
            lowered = log_text.lower()
            assert "! latex error: file" not in lowered or "png" not in lowered, (
                f"le journal {log_path} signale un fichier image introuvable"
            )
            assert "not found" not in lowered or image_sha256 not in lowered, (
                f"le journal {log_path} signale l'image de la figure comme introuvable"
            )
    else:
        # 9. lualatex indisponible : HTML/TEI/LaTEI restent verifies ci-dessus ;
        # seule l'assertion PDF est adaptee, le reste du test n'est jamais saute.
        assert result.pdf_status in {"unavailable", "generated"}
        if result.pdf_status == "unavailable":
            assert result.pdf_path is None

    print("\n--- Diagnostic chemins d'image (pipeline complet DOCX avec image) ---")
    for key, value in diagnostics.items():
        print(f"{key}: {value}")
    print(f"lualatex disponible: {shutil.which('lualatex') is not None}")
