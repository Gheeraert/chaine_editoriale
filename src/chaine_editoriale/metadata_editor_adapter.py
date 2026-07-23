"""Adaptateur local vers l'editeur de metadonnees embarquable de Mini-Metopes.

Ce module reste independant de Tkinter au niveau de ses imports : ``parent``
est traite comme un objet opaque, et ``mini_metopes.gui`` / ``mini_metopes.metadata``
ne sont importes qu'a l'interieur des fonctions, jamais au chargement de ce
module (donc jamais au chargement de ``chaine_editoriale``).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from .erreurs import MetadataEditorIntegrationError

MetadataEditorStatus = Literal["saved", "cancelled"]

_UNAVAILABLE_HINT = (
    "Vérifiez que C:\\minimetopes contient l'API open_metadata_editor puis "
    "redémarrez la chaîne éditoriale."
)


@dataclass(frozen=True, slots=True)
class MetadataEditorOutcome:
    """Conversion locale de ``mini_metopes.gui.MetadataEditorResult``.

    Cette petite conversion protege l'orchestrateur d'une dependance directe
    aux classes internes de presentation de Mini-Metopes.
    """

    status: MetadataEditorStatus
    docx_path: Path
    metadata_path: Path | None

    @property
    def saved(self) -> bool:
        return self.status == "saved" and self.metadata_path is not None


def conventional_metadata_path(docx_path: Path) -> Path:
    """Chemin conventionnel du JSON associe au DOCX, calcule par Mini-Metopes.

    La convention elle-meme n'est jamais recopiee ici : Mini-Metopes
    (``mini_metopes.metadata.default_metadata_path``) reste la seule source
    de verite.
    """
    try:
        from mini_metopes.metadata import default_metadata_path
    except ImportError as error:
        raise MetadataEditorIntegrationError(
            "La version de Mini-Métopes configurée ne fournit pas "
            f"default_metadata_path.\n{_UNAVAILABLE_HINT}"
        ) from error
    return default_metadata_path(docx_path)


def edit_metadata(parent: object, docx_path: Path, metadata_path: Path | None) -> MetadataEditorOutcome:
    """Ouvrir l'editeur de metadonnees integre de Mini-Metopes et convertir son resultat.

    Appelle ``mini_metopes.gui.open_metadata_editor`` avec
    ``prompt_for_new_destination=False`` et ``show_tei_generation=False`` :
    la boite est modale et cette fonction ne retourne qu'a sa fermeture.

    Les erreurs metier de Mini-Metopes (``DocxInspectionError``, ``OSError``)
    ne sont jamais interceptees ici : elles remontent telles quelles a
    l'appelant, qui reste responsable de leur presentation.
    """
    try:
        from mini_metopes.gui import open_metadata_editor
    except ImportError as error:
        raise MetadataEditorIntegrationError(
            "La version de Mini-Métopes configurée ne fournit pas l'éditeur de "
            f"métadonnées intégrable.\n{_UNAVAILABLE_HINT}"
        ) from error

    result = open_metadata_editor(
        parent,
        docx_path,
        metadata_path,
        prompt_for_new_destination=False,
        show_tei_generation=False,
    )
    return _convert_result(result)


def _convert_result(result: object) -> MetadataEditorOutcome:
    status = getattr(result, "status", None)
    if status not in ("saved", "cancelled"):
        raise MetadataEditorIntegrationError(
            "Résultat inattendu de l'éditeur de métadonnées Mini-Métopes : "
            f"statut {status!r}.\n{_UNAVAILABLE_HINT}"
        )

    docx_path = getattr(result, "docx_path", None)
    if not isinstance(docx_path, Path):
        raise MetadataEditorIntegrationError(
            "Résultat inattendu de l'éditeur de métadonnées Mini-Métopes : "
            f"docx_path absent ou invalide.\n{_UNAVAILABLE_HINT}"
        )

    metadata_path = getattr(result, "metadata_path", None)
    if metadata_path is not None and not isinstance(metadata_path, Path):
        raise MetadataEditorIntegrationError(
            "Résultat inattendu de l'éditeur de métadonnées Mini-Métopes : "
            f"metadata_path invalide.\n{_UNAVAILABLE_HINT}"
        )

    if status == "saved" and metadata_path is None:
        raise MetadataEditorIntegrationError(
            "L'éditeur de métadonnées Mini-Métopes a signalé un enregistrement "
            f"sans chemin de métadonnées.\n{_UNAVAILABLE_HINT}"
        )

    return MetadataEditorOutcome(status=status, docx_path=docx_path, metadata_path=metadata_path)
