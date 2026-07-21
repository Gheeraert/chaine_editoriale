"""Modeles de donnees propres a la chaine editoriale.

Aucun de ces types n'importe mini_metopes ni purh_site au chargement : les
annotations qui designent des types externes (``BuildResult``) restent des
chaines grace a ``from __future__ import annotations`` et ne sont resolues
que par les outils de typage statique (voir ``TYPE_CHECKING`` ci-dessous).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal, TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover - uniquement pour l'analyse statique.
    from purh_site.site_builder import BuildResult


PdfExportMode = Literal["none", "latei", "latei_pdf"]


@dataclass(frozen=True, slots=True)
class PublicationOptions:
    """Options controlant une publication, independantes de la configuration technique."""

    write_normalized_tei: bool = True
    pdf_export_mode: PdfExportMode = "latei_pdf"
    latex_engine: str = "lualatex"
    collection_title: str = ""
    collection_number: str = ""
    collection_issn: str = ""


@dataclass(frozen=True, slots=True)
class PublicationResult:
    """Bilan complet d'une publication : intermediaires, site, artefacts PDF, manifeste."""

    xml_path: Path
    media_directory: Path | None
    assets_root: Path | None
    site_result: "BuildResult"
    latei_path: Path | None
    pdf_path: Path | None
    pdf_status: str
    manifest_path: Path
    conversion_diagnostics: tuple[object, ...]
