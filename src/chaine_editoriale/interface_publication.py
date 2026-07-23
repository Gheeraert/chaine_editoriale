"""Logique de l'ecran de publication, independante de Tkinter.

Ce module concentre tout ce qui peut etre teste sans ouvrir de fenetre :
modele de formulaire, validation, construction de la requete, worker
(executable directement ou dans un thread), formatage des resultats et des
erreurs, et description des artefacts ouvrables. ``gui.py`` ne fait
qu'assembler ces fonctions autour de widgets Tkinter.

Aucune logique de ``publier()`` n'est dupliquee ici : ``execute_publication_request``
se contente de l'appeler.
"""

from __future__ import annotations

import os
import traceback
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from .erreurs import (
    AssetPreparationError,
    ChaineEditorialeError,
    ChecksumError,
    ConfigurationError,
    DependencyVerificationError,
    InvalidMetadataError,
    ManifestWriteError,
    SiteBuildError,
    TeiConversionError,
    TeiWriteError,
)
from .modeles import PdfExportMode, PublicationOptions, PublicationResult
from .publier import publier

# ---------------------------------------------------------------------------
# Modes de sortie : une seule table de correspondance, jamais dispersee.

OutputMode = Literal["html", "html_latei", "html_latei_pdf"]

OUTPUT_MODE_CHOICES: tuple[tuple[OutputMode, str], ...] = (
    ("html", "HTML + XML normalisé"),
    ("html_latei", "HTML + XML normalisé + LaTEI"),
    ("html_latei_pdf", "HTML + XML normalisé + LaTEI + PDF"),
)

DEFAULT_OUTPUT_MODE: OutputMode = "html_latei_pdf"

_PDF_EXPORT_MODE_BY_OUTPUT_MODE: dict[str, PdfExportMode] = {
    "html": "none",
    "html_latei": "latei",
    "html_latei_pdf": "latei_pdf",
}

_OUTPUT_MODE_LABELS: dict[str, str] = dict(OUTPUT_MODE_CHOICES)
_OUTPUT_MODE_BY_LABEL: dict[str, str] = {label: mode for mode, label in OUTPUT_MODE_CHOICES}


def output_mode_label(mode: str) -> str:
    """Libelle lisible d'un mode de sortie, ou le mode lui-meme si inconnu."""
    return _OUTPUT_MODE_LABELS.get(mode, mode)


def output_mode_from_label(label: str) -> str | None:
    """Retrouver la valeur technique d'un mode a partir de son libelle affiche."""
    return _OUTPUT_MODE_BY_LABEL.get(label)


def pdf_export_mode_for(output_mode: str) -> PdfExportMode | None:
    """Traduire un mode de sortie du formulaire vers ``PublicationOptions.pdf_export_mode``."""
    return _PDF_EXPORT_MODE_BY_OUTPUT_MODE.get(output_mode)


def is_known_output_mode(output_mode: str) -> bool:
    return output_mode in _PDF_EXPORT_MODE_BY_OUTPUT_MODE


def latex_engine_required_for(output_mode: str) -> bool:
    """Le moteur LaTeX n'est pertinent que si LaTEI (ou le PDF) est demande."""
    return output_mode in {"html_latei", "html_latei_pdf"}


# ---------------------------------------------------------------------------
# Moteur LaTeX : uniquement ce qu'Impressions supporte reellement.
#
# ``purh_site.config.BuildConfig.latex_engine`` accepte n'importe quelle
# chaine (elle est passee telle quelle a ``shutil.which``), mais le
# preambule LaTEI genere (``purh_site/latei_preamble.py``) charge
# inconditionnellement ``fontspec`` et le pilote de sortie compile via
# ``luatex.def`` : seul LuaLaTeX est donc reellement pris en charge en
# pratique. Ne pas proposer de faux choix (XeLaTeX, pdfLaTeX...).

SUPPORTED_LATEX_ENGINES: tuple[str, ...] = ("lualatex",)
LATEX_ENGINE_LABELS: dict[str, str] = {"lualatex": "LuaLaTeX"}
DEFAULT_LATEX_ENGINE = "lualatex"


def latex_engine_label(engine: str) -> str:
    return LATEX_ENGINE_LABELS.get(engine, engine)


def is_known_latex_engine(engine: str) -> bool:
    return engine in SUPPORTED_LATEX_ENGINES


# ---------------------------------------------------------------------------
# Modele du formulaire


@dataclass(slots=True)
class PublicationFormState:
    """Etat mutable du formulaire de publication (un document a la fois)."""

    docx_path: str = ""
    metadata_path: str = ""
    workspace_dir: str = ""
    output_dir: str = ""
    output_mode: str = DEFAULT_OUTPUT_MODE
    latex_engine: str = DEFAULT_LATEX_ENGINE
    # True tant que metadata_path a ete calcule automatiquement (chemin
    # conventionnel) et non choisi/enregistre explicitement par
    # l'utilisateur : pilote si un changement de DOCX doit recalculer le JSON
    # (cf. gui.synchronize_metadata_path_for_current_docx) ou le laisser
    # intact. Vit sur form_state (pas dans une closure Tkinter) pour survivre
    # a la reconstruction de l'ecran apres un aller-retour par la
    # configuration.
    metadata_path_is_automatic: bool = True


@dataclass(frozen=True, slots=True)
class PublicationValidationIssue:
    """Un probleme de formulaire, rattache a un champ."""

    field: str
    message: str


@dataclass(slots=True)
class PublicationScreenController:
    """Etat de l'ecran de publication : formulaire conserve, un seul lancement a la fois.

    Ne contient aucune reference Tkinter : testable par appel direct. Le
    formulaire est conserve a l'identique entre deux publications (succes ou
    echec) pour permettre une nouvelle publication sans ressaisie.
    """

    form_state: PublicationFormState = field(default_factory=PublicationFormState)
    busy: bool = False

    def begin_publication(self) -> bool:
        """Passer a l'etat occupe. Retourne False si deja occupe (double lancement refuse)."""
        if self.busy:
            return False
        self.busy = True
        return True

    def end_publication(self) -> None:
        """Revenir a l'etat disponible, que la publication ait reussi ou echoue."""
        self.busy = False


@dataclass(frozen=True, slots=True)
class PublicationRequest:
    """Requete immuable, directement transmissible au worker."""

    docx_path: Path
    metadata_path: Path
    workspace_dir: Path
    output_dir: Path
    options: PublicationOptions


# ---------------------------------------------------------------------------
# Validation (fonctions pures, jamais de logique metier profonde)


def normalized_path(raw_value: str) -> Path:
    """Normalisation unique des quatre chemins du formulaire : strip puis Path.

    Utilisee systematiquement par la validation, la comparaison
    workspace/output, la construction de la requete et les suggestions de
    repertoire initial, pour qu'un chemin valide a la validation ne puisse
    jamais echouer plus tard a cause d'espaces residuels.
    """
    return Path(raw_value.strip())


def validate_publication_form(state: PublicationFormState) -> tuple[PublicationValidationIssue, ...]:
    """Valider le formulaire et retourner TOUS les problemes detectes."""
    issues: list[PublicationValidationIssue] = []

    _validate_input_file(state.docx_path, ".docx", "docx_path", "Le fichier DOCX", issues)
    _validate_metadata_field(state.docx_path, state.metadata_path, issues)

    issues.extend(validate_directory_path(state.workspace_dir, field_name="workspace_dir", label="dossier de travail"))
    issues.extend(validate_directory_path(state.output_dir, field_name="output_dir", label="dossier de publication"))

    workspace_text = state.workspace_dir.strip()
    output_text = state.output_dir.strip()
    if workspace_text and output_text:
        # Pas de resolve() ici : les chemins de sortie peuvent ne pas encore
        # exister, et resolve() ferait inutilement dependre la comparaison du
        # repertoire courant du processus. Seule la normalisation (strip) est
        # appliquee, des deux cotes, de la meme maniere qu'ailleurs.
        if normalized_path(state.workspace_dir) == normalized_path(state.output_dir):
            issues.append(
                PublicationValidationIssue(
                    "output_dir", "Le dossier de publication doit être différent du dossier de travail."
                )
            )

    if not is_known_output_mode(state.output_mode):
        issues.append(PublicationValidationIssue("output_mode", f"Mode de sortie inconnu : {state.output_mode!r}."))

    if not is_known_latex_engine(state.latex_engine):
        issues.append(PublicationValidationIssue("latex_engine", f"Moteur LaTeX inconnu : {state.latex_engine!r}."))

    return tuple(issues)


def validate_directory_path(
    raw_value: str, *, field_name: str, label: str
) -> tuple[PublicationValidationIssue, ...]:
    """Valider un champ dossier (workspace ou output) sans jamais le creer.

    - champ vide -> erreur ;
    - chemin absent -> valide (sera cree pendant la publication) ;
    - chemin existant et repertoire -> valide ;
    - chemin existant et fichier -> erreur (jamais confondu avec un dossier
      "non vide" a confirmer) ;
    - chemin existant mais illisible -> erreur lisible, jamais une exception
      brute remontee a l'appelant.
    """
    text = raw_value.strip()
    if not text:
        return (PublicationValidationIssue(field_name, f"Le {label} est obligatoire."),)

    path = normalized_path(raw_value)
    try:
        exists = path.exists()
    except OSError as error:
        return (PublicationValidationIssue(field_name, f"Le chemin du {label} est illisible : {path}\n{error}"),)
    if not exists:
        return ()

    try:
        is_directory = path.is_dir()
    except OSError as error:
        return (PublicationValidationIssue(field_name, f"Le chemin du {label} est illisible : {path}\n{error}"),)
    if not is_directory:
        return (
            PublicationValidationIssue(
                field_name, f"Le chemin du {label} existe mais n'est pas un dossier :\n{path}"
            ),
        )
    return ()


def _validate_input_file(
    raw_value: str, expected_suffix: str, field_name: str, label: str, issues: list[PublicationValidationIssue]
) -> None:
    text = raw_value.strip()
    if not text:
        issues.append(PublicationValidationIssue(field_name, f"{label} est obligatoire."))
        return
    path = normalized_path(raw_value)
    if not path.exists():
        issues.append(PublicationValidationIssue(field_name, f"{label} est introuvable : {path}"))
        return
    if not path.is_file():
        issues.append(PublicationValidationIssue(field_name, f"{label} n'est pas un fichier régulier : {path}"))
        return
    if path.suffix.lower() != expected_suffix:
        issues.append(
            PublicationValidationIssue(field_name, f"{label} doit avoir l'extension {expected_suffix} : {path}")
        )


def _validate_metadata_field(
    docx_value: str, metadata_value: str, issues: list[PublicationValidationIssue]
) -> None:
    """Valider le champ metadonnees, avec un diagnostic actionnable quand le JSON reste a creer.

    Distingue explicitement le cas ou un DOCX valide est deja choisi mais ou
    le JSON conventionnel n'existe pas encore : le message renvoie alors vers
    le bouton "Creer les metadonnees..." plutot que d'annoncer un simple
    fichier introuvable.
    """
    text = metadata_value.strip()
    if not text:
        issues.append(PublicationValidationIssue("metadata_path", "Le fichier de métadonnées JSON est obligatoire."))
        return

    path = normalized_path(metadata_value)
    if not path.exists():
        if path.suffix.lower() == ".json" and docx_value.strip():
            issues.append(
                PublicationValidationIssue(
                    "metadata_path",
                    "Les métadonnées n'ont pas encore été créées.\n"
                    "Cliquez sur « Créer les métadonnées… » avant de publier.",
                )
            )
        else:
            issues.append(
                PublicationValidationIssue("metadata_path", f"Le fichier de métadonnées JSON est introuvable : {path}")
            )
        return

    if not path.is_file():
        issues.append(
            PublicationValidationIssue(
                "metadata_path", f"Le fichier de métadonnées JSON n'est pas un fichier régulier : {path}"
            )
        )
        return

    if path.suffix.lower() != ".json":
        issues.append(
            PublicationValidationIssue("metadata_path", f"Le fichier de métadonnées JSON doit avoir l'extension .json : {path}")
        )


def build_publication_request(state: PublicationFormState) -> PublicationRequest:
    """Construire la requete immuable a partir d'un formulaire deja valide."""
    pdf_export_mode = pdf_export_mode_for(state.output_mode)
    if pdf_export_mode is None:
        raise ValueError(f"mode de sortie inconnu : {state.output_mode!r}")
    options = PublicationOptions(
        write_normalized_tei=True,
        pdf_export_mode=pdf_export_mode,
        latex_engine=state.latex_engine,
    )
    return PublicationRequest(
        docx_path=normalized_path(state.docx_path),
        metadata_path=normalized_path(state.metadata_path),
        workspace_dir=normalized_path(state.workspace_dir),
        output_dir=normalized_path(state.output_dir),
        options=options,
    )


# ---------------------------------------------------------------------------
# Dossiers deja existants


def directory_is_non_empty(path: Path) -> bool:
    """True si path existe, est un dossier, et contient au moins une entree.

    Un dossier absent est considere comme vide (rien a ecraser). Un chemin
    qui existe mais designe un fichier n'est PAS un cas de confirmation
    d'ecrasement : ``validate_publication_form``/``validate_directory_path``
    le rejette deja en amont comme une erreur de formulaire, donc cette
    fonction leve ``NotADirectoryError`` (sous-classe d'``OSError``) plutot
    que de le confondre avec un dossier non vide. Une erreur de lecture
    n'est jamais confondue avec un dossier vide : elle remonte telle quelle.
    """
    if not path.exists():
        return False
    if not path.is_dir():
        raise NotADirectoryError(f"le chemin existe mais n'est pas un dossier : {path}")
    with os.scandir(path) as entries:
        return next(iter(entries), None) is not None


# ---------------------------------------------------------------------------
# Worker : appelable directement (tests) ou depuis un thread (gui.py)


@dataclass(frozen=True, slots=True)
class PublicationJobEvent:
    """Evenement transmis du worker vers le thread principal."""

    kind: Literal["success", "error"]
    result: PublicationResult | None = None
    error: BaseException | None = None


def execute_publication_request(request: PublicationRequest) -> PublicationResult:
    """Appeler publier() une seule fois, sans dupliquer sa logique."""
    return publier(
        request.docx_path,
        request.metadata_path,
        request.workspace_dir,
        request.output_dir,
        options=request.options,
    )


def run_publication_job(request: PublicationRequest) -> PublicationJobEvent:
    """Executer la publication et retourner un evenement structure, jamais une exception avalee en silence."""
    try:
        result = execute_publication_request(request)
    except Exception as error:  # noqa: BLE001 - transmis au thread principal via l'evenement, jamais masque.
        return PublicationJobEvent(kind="error", error=error)
    return PublicationJobEvent(kind="success", result=result)


def log_unexpected_error(error: BaseException) -> None:
    """Ecrire la trace complete sur stderr, pour le diagnostic de developpement uniquement."""
    traceback.print_exception(type(error), error, error.__traceback__)


# ---------------------------------------------------------------------------
# Formatage des resultats


_PDF_STATUS_LABELS: dict[str, str] = {
    "not_requested": "non demandé",
    "generated": "produit",
    "unavailable": "demandé mais non produit",
}


def format_pdf_status_label(status: str) -> str:
    return _PDF_STATUS_LABELS.get(status, status)


def format_publication_summary(result: PublicationResult) -> str:
    """Rapport lisible apres une publication reussie : jamais un artefact non verifie."""

    def produced(path: Path | None) -> str:
        return "produit" if path is not None and path.exists() else "non produit"

    lines = [
        "Publication terminée",
        "",
        f"XML Commons intermédiaire : {produced(result.xml_path)}",
        f"Site HTML : {produced(result.site_result.html_path)}",
        f"XML normalisé : {produced(result.site_result.normalized_tei_path)}",
        f"LaTEI : {produced(result.latei_path)}",
        f"PDF : {format_pdf_status_label(result.pdf_status)}",
        f"Manifeste : {produced(result.manifest_path)}",
        "",
        f"Dossier de publication : {result.site_result.output_dir}",
    ]
    return "\n".join(lines)


@dataclass(frozen=True, slots=True)
class ArtifactAction:
    """Une action d'ouverture proposee a l'utilisateur, pour un chemin qui existe reellement."""

    label: str
    path: Path


def describe_openable_artifacts(result: PublicationResult) -> tuple[ArtifactAction, ...]:
    """Ne proposer que des chemins dont l'existence a ete verifiee sur le disque."""
    candidates: tuple[tuple[str, Path | None], ...] = (
        ("Ouvrir le site", result.site_result.html_path),
        ("Ouvrir le XML intermédiaire", result.xml_path),
        ("Ouvrir le XML normalisé", result.site_result.normalized_tei_path),
        ("Ouvrir le LaTEI", result.latei_path),
        ("Ouvrir le PDF", result.pdf_path),
        ("Ouvrir le manifeste", result.manifest_path),
        ("Ouvrir le dossier de publication", result.site_result.output_dir),
    )
    return tuple(ArtifactAction(label, path) for label, path in candidates if path is not None and path.exists())


def action_grid_position(index: int, columns: int = 2) -> tuple[int, int]:
    """Position (ligne, colonne) d'une action dans une grille compacte, ligne par ligne."""
    if columns < 1:
        raise ValueError("columns doit etre strictement positif")
    return index // columns, index % columns


def open_artifact(path: Path) -> None:
    """Ouvrir un artefact avec l'association Windows par defaut (aucun sous-processus, aucun serveur)."""
    os.startfile(path)  # type: ignore[attr-defined]  # Windows uniquement, par conception de la chaine.


# ---------------------------------------------------------------------------
# Presentation des erreurs structurees


# Triee du plus specifique au plus general (DependencyVerificationError est
# une sous-classe de ConfigurationError, par exemple).
_ERROR_TYPE_LABELS: tuple[tuple[type[BaseException], str], ...] = (
    (DependencyVerificationError, "Dépendances non résolues"),
    (ConfigurationError, "Erreur de configuration"),
    (InvalidMetadataError, "Métadonnées invalides"),
    (TeiConversionError, "Conversion DOCX → TEI impossible"),
    (TeiWriteError, "Écriture de la TEI impossible"),
    (SiteBuildError, "Construction du site impossible"),
    (AssetPreparationError, "Préparation des médias impossible"),
    (ChecksumError, "Calcul d'empreinte impossible"),
    (ManifestWriteError, "Écriture du manifeste impossible"),
    (ChaineEditorialeError, "Erreur de la chaîne éditoriale"),
)


def _error_type_label(error: BaseException) -> str:
    for error_type, label in _ERROR_TYPE_LABELS:
        if isinstance(error, error_type):
            return label
    return "Erreur de la chaîne éditoriale"


def format_diagnostics(diagnostics: tuple[object, ...]) -> str:
    """Formater une serie de diagnostics structures (mini_metopes/purh_site ou internes).

    Exploite raisonnablement ``code``, ``severity``, ``message``, ``path`` et
    ``origin`` lorsqu'ils existent, sans jamais recourir a ``repr()``.
    """
    if not diagnostics:
        return ""
    lines: list[str] = []
    for diagnostic in diagnostics:
        severity = getattr(diagnostic, "severity", None)
        code = getattr(diagnostic, "code", None)
        message = getattr(diagnostic, "message", None) or str(diagnostic)
        path = getattr(diagnostic, "path", None) or getattr(diagnostic, "metadata_path", None)
        origin = getattr(diagnostic, "origin", None)

        prefix_parts = [part for part in (f"[{severity}]" if severity else None, code) if part]
        prefix = " ".join(prefix_parts)
        line = f"{prefix} {message}".strip() if prefix else message
        extra_parts = [part for part in (f"origine : {origin}" if origin else None, f"chemin : {path}" if path else None) if part]
        if extra_parts:
            line = f"{line} ({', '.join(extra_parts)})"
        lines.append(f"- {line}")
    return "\n".join(lines)


def format_publication_error(error: BaseException) -> str:
    """Presenter une erreur pour la boite de dialogue, sans jamais afficher de trace brute."""
    if isinstance(error, ChaineEditorialeError):
        lines = [_error_type_label(error), str(error)]

        diagnostics = getattr(error, "diagnostics", ())
        if diagnostics:
            formatted = format_diagnostics(tuple(diagnostics))
            if formatted:
                lines.append("")
                lines.append("Diagnostics :")
                lines.append(formatted)

        validation_issues = getattr(error, "validation_issues", ())
        if validation_issues:
            formatted = format_diagnostics(tuple(validation_issues))
            if formatted:
                lines.append("")
                lines.append("Validation TEI :")
                lines.append(formatted)

        path = getattr(error, "path", None)
        if path:
            lines.append("")
            lines.append(f"Chemin concerné : {path}")

        cause = error.__cause__
        if cause is not None:
            lines.append("")
            lines.append(f"Cause : {type(cause).__name__}: {cause}")

        return "\n".join(lines)

    return "Une erreur inattendue s'est produite.\n" f"{type(error).__name__} : {error}"


# ---------------------------------------------------------------------------
# Aide au remplissage du formulaire (repertoires initiaux, suggestions)


def initial_directory_for(*candidates: str) -> str:
    """Choisir un repertoire initial raisonnable pour un dialogue de fichier.

    Essaie chaque candidat dans l'ordre (typiquement : le champ courant,
    puis le dossier du DOCX deja choisi), sans jamais dependre du
    repertoire courant du processus.
    """
    for candidate in candidates:
        text = candidate.strip()
        if not text:
            continue
        path = normalized_path(candidate)
        if path.is_file():
            return str(path.parent)
        if path.is_dir():
            return str(path)
        if path.parent.is_dir():
            return str(path.parent)
    return str(Path.home())


def suggest_workspace_and_output_dirs(docx_path: Path) -> tuple[str, str]:
    """Suggerer workspace/output a partir du DOCX choisi, sans jamais rien creer."""
    stem = docx_path.stem
    parent = docx_path.parent
    return str(parent / f"{stem}-travail"), str(parent / f"{stem}-site")


# ---------------------------------------------------------------------------
# Presentation de l'etat du chemin des metadonnees (parcours creer/modifier)
#
# Fonctions pures : elles ne valident jamais le contenu JSON (responsabilite
# de publier()/Mini-Metopes) et n'importent ni Tkinter ni mini_metopes.

MetadataPathState = Literal["no_docx", "invalid_docx", "missing", "available", "invalid_metadata_path"]


@dataclass(frozen=True, slots=True)
class MetadataPathPresentation:
    """Description de l'etat du chemin des metadonnees, prete a afficher."""

    state: MetadataPathState
    status_text: str
    editor_button_text: str
    can_edit: bool


_CREATE_BUTTON_TEXT = "Créer les métadonnées…"
_MODIFY_BUTTON_TEXT = "Modifier les métadonnées…"


def describe_metadata_path(docx_value: str, metadata_value: str) -> MetadataPathPresentation:
    """Decrire l'etat du chemin des metadonnees pour piloter le bouton dynamique et le statut.

    Le DOCX est valide en premier (existence, type fichier, extension) : tant
    qu'il ne l'est pas, l'edition des metadonnees reste desactivee (``state``
    vaut ``"invalid_docx"``), meme si le champ metadonnees contient un texte
    non vide.
    """
    docx_text = docx_value.strip()
    if not docx_text:
        return MetadataPathPresentation(
            state="no_docx",
            status_text="Choisissez d'abord un document DOCX.",
            editor_button_text=_CREATE_BUTTON_TEXT,
            can_edit=False,
        )

    docx_path = normalized_path(docx_value)

    try:
        docx_exists = docx_path.exists()
    except OSError as error:
        return MetadataPathPresentation(
            state="invalid_docx",
            status_text=f"Le document DOCX est illisible : {docx_path}\n{error}",
            editor_button_text=_CREATE_BUTTON_TEXT,
            can_edit=False,
        )
    if not docx_exists:
        return MetadataPathPresentation(
            state="invalid_docx",
            status_text="Le document DOCX est introuvable.",
            editor_button_text=_CREATE_BUTTON_TEXT,
            can_edit=False,
        )

    try:
        docx_is_file = docx_path.is_file()
    except OSError as error:
        return MetadataPathPresentation(
            state="invalid_docx",
            status_text=f"Le document DOCX est illisible : {docx_path}\n{error}",
            editor_button_text=_CREATE_BUTTON_TEXT,
            can_edit=False,
        )
    if not docx_is_file:
        return MetadataPathPresentation(
            state="invalid_docx",
            status_text="Le chemin DOCX ne désigne pas un fichier.",
            editor_button_text=_CREATE_BUTTON_TEXT,
            can_edit=False,
        )

    if docx_path.suffix.lower() != ".docx":
        return MetadataPathPresentation(
            state="invalid_docx",
            status_text="Le document doit avoir l'extension .docx.",
            editor_button_text=_CREATE_BUTTON_TEXT,
            can_edit=False,
        )

    text = metadata_value.strip()
    if not text:
        return MetadataPathPresentation(
            state="missing",
            status_text="Métadonnées à créer.",
            editor_button_text=_CREATE_BUTTON_TEXT,
            can_edit=True,
        )

    path = normalized_path(metadata_value)
    name = path.name

    if path.suffix.lower() != ".json":
        return MetadataPathPresentation(
            state="invalid_metadata_path",
            status_text="Le chemin des métadonnées n'est pas un fichier JSON utilisable.",
            editor_button_text=_CREATE_BUTTON_TEXT,
            can_edit=False,
        )

    try:
        exists = path.exists()
    except OSError as error:
        return MetadataPathPresentation(
            state="invalid_metadata_path",
            status_text=f"Le chemin des métadonnées est illisible : {path}\n{error}",
            editor_button_text=_CREATE_BUTTON_TEXT,
            can_edit=False,
        )

    if not exists:
        return MetadataPathPresentation(
            state="missing",
            status_text=f"Métadonnées à créer : {name}",
            editor_button_text=_CREATE_BUTTON_TEXT,
            can_edit=True,
        )

    try:
        is_file = path.is_file()
    except OSError as error:
        return MetadataPathPresentation(
            state="invalid_metadata_path",
            status_text=f"Le chemin des métadonnées est illisible : {path}\n{error}",
            editor_button_text=_CREATE_BUTTON_TEXT,
            can_edit=False,
        )

    if not is_file:
        return MetadataPathPresentation(
            state="invalid_metadata_path",
            status_text="Le chemin des métadonnées n'est pas un fichier JSON utilisable.",
            editor_button_text=_CREATE_BUTTON_TEXT,
            can_edit=False,
        )

    return MetadataPathPresentation(
        state="available",
        status_text=f"Fichier de métadonnées trouvé : {name}",
        editor_button_text=_MODIFY_BUTTON_TEXT,
        can_edit=True,
    )


def docx_change_resets_metadata(previous_docx_value: str, new_docx_value: str) -> bool:
    """True si un changement explicite de DOCX doit remplacer le JSON par le chemin conventionnel.

    Compare les chemins normalises : une re-saisie identique (espaces
    residuels, focus sans modification) ne doit jamais reinitialiser un JSON
    deja choisi.
    """
    return normalized_path(previous_docx_value) != normalized_path(new_docx_value)


def docx_is_usable_for_metadata_sync(docx_value: str) -> bool:
    """True si le DOCX visible est exploitable pour calculer un chemin conventionnel.

    Exige un texte non vide, un chemin existant, un fichier regulier et
    l'extension ``.docx``. Utilisee par la synchronisation silencieuse
    (``gui.synchronize_metadata_path_for_current_docx``) pour eviter d'appeler
    l'adaptateur Mini-Metopes sur un DOCX vide ou invalide : la validation
    normale (``validate_publication_form``) affichera ensuite le diagnostic
    adapte.
    """
    text = docx_value.strip()
    if not text:
        return False
    path = normalized_path(docx_value)
    try:
        if not path.exists() or not path.is_file():
            return False
    except OSError:
        return False
    return path.suffix.lower() == ".docx"
