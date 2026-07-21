"""Fonction coeur de la chaine editoriale : DOCX + JSON -> site publie.

Les imports metier de mini_metopes et purh_site sont regroupes dans
``_charger_dependances_metier`` et ne sont executes qu'apres verification
reussie de la configuration des chemins (voir ``configuration.py``).
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .configuration import activate_configured_dependencies, load_config
from .erreurs import (
    AssetPreparationError,
    ChecksumError,
    DependencyVerificationError,
    InvalidMetadataError,
    SiteBuildError,
    TeiConversionError,
    TeiWriteError,
)
from .manifeste import build_publication_manifest, write_publication_manifest
from .modeles import PublicationOptions, PublicationResult


@dataclass(frozen=True, slots=True)
class _MiniMetopesApi:
    load_metadata_file: Any
    convert_docx_to_tei: Any
    write_tei_conversion_result: Any
    compute_file_sha256: Any


@dataclass(frozen=True, slots=True)
class _PurhSiteApi:
    BuildConfig: Any
    SiteBuilder: Any


def _charger_dependances_metier() -> tuple[_MiniMetopesApi, _PurhSiteApi]:
    """Importer les facades publiques des deux bibliotheques, une fois activees."""
    from mini_metopes.metadata import compute_file_sha256, load_metadata_file
    from mini_metopes.tei import convert_docx_to_tei, write_tei_conversion_result
    from purh_site.config import BuildConfig
    from purh_site.site_builder import SiteBuilder

    return (
        _MiniMetopesApi(load_metadata_file, convert_docx_to_tei, write_tei_conversion_result, compute_file_sha256),
        _PurhSiteApi(BuildConfig, SiteBuilder),
    )


def _verifier_dependances() -> dict[str, dict[str, str]]:
    """Verifier la configuration activee et retourner les chemins reellement resolus."""
    load_result = load_config()
    if not load_result.valid or load_result.config is None:
        raise DependencyVerificationError(
            "la configuration de la chaine editoriale (config_chaine.json) est absente ou invalide ; "
            "ouvrez l'ecran de configuration avant de publier",
            diagnostics=load_result.issues,
        )
    verification = activate_configured_dependencies(load_result.config)
    if not verification.success:
        raise DependencyVerificationError(
            "mini_metopes ou purh_site n'a pas pu etre resolu depuis les chemins configures : "
            f"mini_metopes={verification.mini_metopes.message} ; purh_site={verification.purh_site.message}",
            diagnostics=(verification.mini_metopes, verification.purh_site),
        )
    return {
        "mini_metopes": {
            "configured_repository": str(verification.mini_metopes.configured_repository),
            "import_root": str(verification.mini_metopes.import_root),
            "module_path": str(verification.mini_metopes.module_path),
        },
        "purh_site": {
            "configured_repository": str(verification.purh_site.configured_repository),
            "import_root": str(verification.purh_site.import_root),
            "module_path": str(verification.purh_site.module_path),
        },
    }


def publier(
    docx_path: Path,
    metadata_path: Path,
    workspace_dir: Path,
    output_dir: Path,
    *,
    options: PublicationOptions | None = None,
) -> PublicationResult:
    """Publier un DOCX+JSON en un site (HTML, XML normalise, LaTEI, PDF eventuel).

    La configuration technique locale (chemins de mini_metopes et de
    purh_site) est lue depuis ``configuration.default_config_path()`` et
    activee avant tout import metier.
    """
    resolved_options = options if options is not None else PublicationOptions()
    dependencies = _verifier_dependances()
    mini_metopes_api, purh_site_api = _charger_dependances_metier()

    docx_path = docx_path.resolve()
    metadata_path = metadata_path.resolve()
    if not docx_path.is_file():
        raise InvalidMetadataError(f"fichier DOCX introuvable : {docx_path}")
    if not metadata_path.is_file():
        raise InvalidMetadataError(f"fichier de metadonnees introuvable : {metadata_path}")

    metadata_result = mini_metopes_api.load_metadata_file(metadata_path)
    if metadata_result.metadata is None:
        raise InvalidMetadataError(
            f"metadonnees invalides : {metadata_path}",
            diagnostics=metadata_result.issues,
        )

    conversion = mini_metopes_api.convert_docx_to_tei(docx_path, metadata=metadata_result.metadata)
    if not conversion.is_successful:
        raise TeiConversionError(
            f"conversion DOCX -> TEI impossible : {docx_path}",
            diagnostics=conversion.diagnostics,
            validation_issues=conversion.validation_issues,
        )

    source_dir = workspace_dir / "source"
    tei_path = source_dir / "document.xml"
    try:
        write_result = mini_metopes_api.write_tei_conversion_result(conversion, tei_path)
    except (OSError, ValueError) as error:
        raise TeiWriteError(f"ecriture de la TEI impossible : {tei_path}", cause=error) from error

    media_directory = Path(write_result.media_directory) if write_result.media_directory else None
    assets_root, media_layout = prepare_media_layout_for_impressions(
        media_directory,
        workspace_dir,
        output_dir,
        latei_export_requested=resolved_options.pdf_export_mode != "none",
    )

    build_config = purh_site_api.BuildConfig(
        output_dir=output_dir,
        assets_dir=assets_root,
        write_normalized_tei=resolved_options.write_normalized_tei,
        collection_title=resolved_options.collection_title,
        collection_number=resolved_options.collection_number,
        collection_issn=resolved_options.collection_issn,
        pdf_export_mode=resolved_options.pdf_export_mode,
        latex_engine=resolved_options.latex_engine,
    )
    try:
        site_result = purh_site_api.SiteBuilder().build_from_master(tei_path, build_config)
    except Exception as error:  # noqa: BLE001 - converti en erreur propre a la chaine.
        raise SiteBuildError(f"construction du site impossible depuis {tei_path}", cause=error) from error

    latei_path = _existing_or_none(output_dir / "assets" / "generated" / "book.tex")
    pdf_path = _existing_or_none(output_dir / "assets" / "generated" / "book.pdf")
    pdf_status = _pdf_status(resolved_options.pdf_export_mode, pdf_path)

    if media_layout:
        # Repertoire HTML final : uniquement connu une fois SiteBuilder execute
        # (voir prepare_media_layout_for_impressions pour la distinction entre
        # repertoire source et repertoire final).
        media_layout["html_output_directory"] = _existing_or_none(output_dir / "assets" / "images" / "media")

    manifest_path = workspace_dir / "publication.json"
    manifest = build_publication_manifest(
        manifest_dir=manifest_path.parent,
        docx_path=docx_path,
        docx_sha256=_compute_sha256(mini_metopes_api, docx_path),
        metadata_path=metadata_path,
        metadata_sha256=_compute_sha256(mini_metopes_api, metadata_path),
        tei_path=tei_path,
        tei_sha256=_compute_sha256(mini_metopes_api, tei_path),
        media_directory=media_directory,
        options=resolved_options,
        outputs={
            "index_html": _existing_or_none(site_result.html_path),
            "normalized_tei": site_result.normalized_tei_path,
            "latei": latei_path,
            "pdf": pdf_path,
            "build_report": _existing_or_none(site_result.report_path),
        },
        pdf_status=pdf_status,
        dependencies=dependencies,
        media_layout=media_layout,
    )
    write_publication_manifest(manifest, manifest_path)

    return PublicationResult(
        xml_path=tei_path,
        media_directory=media_directory,
        assets_root=assets_root,
        site_result=site_result,
        latei_path=latei_path,
        pdf_path=pdf_path,
        pdf_status=pdf_status,
        manifest_path=manifest_path,
        conversion_diagnostics=conversion.diagnostics,
    )


def _existing_or_none(path: Path | None) -> Path | None:
    if path is None:
        return None
    return path if path.exists() else None


def _compute_sha256(mini_metopes_api: _MiniMetopesApi, path: Path) -> str:
    """Encadrer le calcul d'empreinte : jamais d'erreur systeme brute a la frontiere publique."""
    try:
        return mini_metopes_api.compute_file_sha256(path)
    except OSError as error:
        raise ChecksumError(f"empreinte SHA-256 impossible a calculer : {path}", path=str(path), cause=error) from error


def _pdf_status(pdf_export_mode: str, pdf_path: Path | None) -> str:
    """``latei`` demande volontairement le LaTEI sans PDF : ce n'est jamais 'unavailable'."""
    if pdf_export_mode in {"none", "latei"}:
        return "not_requested"
    if pdf_path is not None:
        return "generated"
    return "unavailable"


def prepare_media_layout_for_impressions(
    media_directory: Path | None,
    workspace_dir: Path,
    output_dir: Path,
    *,
    latei_export_requested: bool,
) -> tuple[Path | None, dict[str, Path | None]]:
    """Placer les medias intermediaires aux emplacements reellement lus par Impressions.

    Impressions expose deux contrats de resolution distincts et
    **incompatibles entre eux** pour une meme URL ``tei:graphic/@url`` du
    type ``media/<sha256><ext>`` (convention fixe de la TEI Commons
    Publishing produite par Mini-Metopes) :

    1. **HTML** (``purh_site.site_builder`` + ``resources/tei_to_html.xsl``) :
       ``SiteBuilder`` copie tel quel le contenu de ``BuildConfig.assets_dir``
       (le repertoire *source* prepare ici) sous ``output_dir/assets/``
       (``_copy_user_assets``), et le fragment XSLT prefixe toute URL ne
       commencant pas deja par ``assets/`` avec ``assets/images/`` (template
       ``resolved-image-src``). La reference HTML reelle est donc
       ``assets/images/media/<sha256><ext>`` : il faut placer les medias sous
       ``assets_dir/images/media/`` (repertoire *source*, transmis a
       ``BuildConfig.assets_dir``) pour qu'ils soient copies par
       ``SiteBuilder`` sous ``output_dir/assets/images/media/`` (repertoire
       *final* du site, uniquement connu une fois ``SiteBuilder`` execute).

    2. **LaTEI/PDF** (``purh_site.latei_assets.package_latei_graphics``,
       appele par ``purh_site.site_builder._build_pdf_site_artifacts``, et ce
       des que ``pdf_export_mode`` vaut ``"latei"`` ou ``"latei_pdf"``) :
       cette etape resout chaque ``@url`` **relativement au dossier du
       fichier TEI source** passe a l'export reversible, qui est toujours
       ``output_dir/book.normalized.xml`` pour le pipeline site — donc
       relativement a ``output_dir`` lui-meme, jamais a ``assets_dir``. Sans
       media a cet endroit, l'empaquetage LaTEI echoue silencieusement
       (avertissement dans le rapport, aucune erreur) et la figure est
       remplacee dans le PDF par un encadre "Image absente ou non fournie"
       (voir ``purh_site.latei_driver`` / macro LaTeX
       ``\\latei_figure_fallback:``). C'est le repertoire de *resolution
       initiale* de LaTEI, distinct des deux precedents.

    Ces trois repertoires (source HTML, final HTML, source LaTEI) ne peuvent
    pas etre unifies sans modifier Impressions (voir le rapport de passe
    pour la proposition de correction upstream). Cette fonction documente
    donc explicitement les copies necessaires, chacune protegee par un test
    d'integration distinct, plutot que de dupliquer implicitement la copie
    dans le corps de ``publier()``.

    Retourne l'``assets_dir`` a transmettre a ``BuildConfig`` (ou ``None``
    en l'absence de media) et un dictionnaire de diagnostic destine au
    manifeste (``media_layout``), avec les cles ``source_media_directory``,
    ``html_assets_source_directory`` et ``latei_source_directory``. La cle
    ``html_output_directory`` (repertoire final, connu seulement apres
    ``SiteBuilder``) est ajoutee par l'appelant.
    """
    if media_directory is None:
        return None, {}
    if not media_directory.exists():
        raise AssetPreparationError(f"dossier de medias annonce mais introuvable : {media_directory}")

    try:
        source_files = sorted(path for path in media_directory.iterdir() if path.is_file())
    except OSError as error:
        raise AssetPreparationError(f"lecture du dossier de medias impossible : {media_directory}", cause=error) from error

    assets_root = workspace_dir / "impressions-assets"
    html_assets_source_dir = assets_root / "images" / "media"
    _copy_media_tree(source_files, html_assets_source_dir)

    media_layout: dict[str, Path | None] = {
        "source_media_directory": media_directory,
        "html_assets_source_directory": html_assets_source_dir,
        "latei_source_directory": None,
    }

    if latei_export_requested:
        # Contournement minimal et documente pour purh_site.latei_assets :
        # voir la docstring ci-dessus. output_dir n'existe pas forcement
        # encore a ce stade (SiteBuilder le cree normalement lui-meme).
        try:
            output_dir.mkdir(parents=True, exist_ok=True)
        except OSError as error:
            raise AssetPreparationError(f"preparation du dossier de sortie impossible : {output_dir}", cause=error) from error
        latei_source_dir = output_dir / "media"
        _copy_media_tree(source_files, latei_source_dir)
        media_layout["latei_source_directory"] = latei_source_dir

    return assets_root, media_layout


def _copy_media_tree(source_files: list[Path], destination: Path) -> None:
    try:
        destination.mkdir(parents=True, exist_ok=True)
    except OSError as error:
        raise AssetPreparationError(f"preparation des assets impossible : {destination}", cause=error) from error

    for source_file in source_files:
        target_file = destination / source_file.name
        if target_file.exists():
            if not _files_identical(source_file, target_file):
                raise AssetPreparationError(
                    f"conflit de media existant : {target_file} differe du contenu produit par Mini-Metopes"
                )
            continue
        try:
            shutil.copy2(source_file, target_file)
        except OSError as error:
            raise AssetPreparationError(f"copie de media impossible : {source_file} -> {target_file}", cause=error) from error


def _files_identical(left: Path, right: Path) -> bool:
    try:
        if left.stat().st_size != right.stat().st_size:
            return False
        return left.read_bytes() == right.read_bytes()
    except OSError as error:
        raise AssetPreparationError(f"comparaison de medias impossible : {left} / {right}", cause=error) from error
