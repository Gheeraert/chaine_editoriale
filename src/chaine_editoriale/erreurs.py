"""Hierarchie d'exceptions propre a la chaine editoriale.

Les bibliotheques dependantes (mini_metopes, purh_site) ne doivent jamais
laisser remonter une ``ImportError``, une ``ModuleNotFoundError``, une
``ValueError`` interne ou une trace brute jusqu'a l'utilisateur final : ce
module fournit les types dans lesquels ces echecs doivent etre convertis,
avec leurs diagnostics structures lorsqu'ils existent.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


class ChaineEditorialeError(Exception):
    """Racine commune de toutes les erreurs de la chaine editoriale."""


class ConfigurationError(ChaineEditorialeError):
    """La configuration technique locale (config_chaine.json) est en cause."""


class DependencyVerificationError(ConfigurationError):
    """Mini-Metopes ou Impressions n'a pas pu etre resolu depuis les chemins configures."""

    def __init__(self, message: str, *, diagnostics: tuple[Any, ...] = ()) -> None:
        super().__init__(message)
        self.diagnostics = diagnostics


class InvalidMetadataError(ChaineEditorialeError):
    """Les metadonnees JSON n'ont pas pu etre chargees ou sont invalides."""

    def __init__(self, message: str, *, diagnostics: tuple[Any, ...] = ()) -> None:
        super().__init__(message)
        self.diagnostics = diagnostics


class TeiConversionError(ChaineEditorialeError):
    """La conversion DOCX -> TEI a echoue."""

    def __init__(self, message: str, *, diagnostics: tuple[Any, ...] = (), validation_issues: tuple[Any, ...] = ()) -> None:
        super().__init__(message)
        self.diagnostics = diagnostics
        self.validation_issues = validation_issues


class TeiWriteError(ChaineEditorialeError):
    """L'ecriture de la TEI ou de ses medias a echoue."""

    def __init__(self, message: str, *, cause: BaseException | None = None) -> None:
        super().__init__(message)
        self.__cause__ = cause


class SiteBuildError(ChaineEditorialeError):
    """La construction du site (HTML/XML normalise/LaTEI/PDF) a echoue."""

    def __init__(self, message: str, *, cause: BaseException | None = None) -> None:
        super().__init__(message)
        self.__cause__ = cause


class AssetPreparationError(ChaineEditorialeError):
    """La preparation des assets (copie des medias vers impressions-assets) a echoue."""

    def __init__(self, message: str, *, cause: BaseException | None = None) -> None:
        super().__init__(message)
        self.__cause__ = cause


class ChecksumError(ChaineEditorialeError):
    """Le calcul d'une empreinte SHA-256 a echoue pour un fichier attendu."""

    def __init__(self, message: str, *, path: str | None = None, cause: BaseException | None = None) -> None:
        super().__init__(message)
        self.path = path
        self.__cause__ = cause


class ManifestWriteError(ChaineEditorialeError):
    """L'ecriture de publication.json a echoue."""

    def __init__(self, message: str, *, path: str | None = None, cause: BaseException | None = None) -> None:
        super().__init__(message)
        self.path = path
        self.__cause__ = cause


@dataclass(frozen=True, slots=True)
class DiagnosticSnapshot:
    """Representation texte stable d'un diagnostic externe, pour affichage."""

    code: str
    severity: str
    message: str
    origin: str | None = None
    extra: dict[str, str] = field(default_factory=dict)
