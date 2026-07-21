"""Tests de la logique de l'ecran de publication (interface_publication.py).

Aucune fenetre Tk n'est ouverte ici : tout est teste par appel direct de
fonctions et de classes pures.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path

import pytest

from chaine_editoriale import interface_publication as ip
from chaine_editoriale.erreurs import (
    AssetPreparationError,
    ChecksumError,
    ChaineEditorialeError,
    ConfigurationError,
    DependencyVerificationError,
    InvalidMetadataError,
    ManifestWriteError,
    SiteBuildError,
    TeiConversionError,
    TeiWriteError,
)


# ---------------------------------------------------------------------------
# Fakes minimaux pour PublicationResult (BuildResult de purh_site)


@dataclass
class _FakeBuildResult:
    output_dir: Path
    html_path: Path
    normalized_tei_path: Path | None
    report_path: Path


def _make_result(
    tmp_path: Path,
    *,
    with_latei: bool = True,
    with_pdf: bool = True,
    pdf_status: str = "generated",
    diagnostics: tuple[object, ...] = (),
) -> object:
    output = tmp_path / "output"
    output.mkdir(parents=True, exist_ok=True)
    html_path = output / "index.html"
    html_path.write_text("<html></html>", encoding="utf-8")
    normalized_tei_path = output / "book.normalized.xml"
    normalized_tei_path.write_text("<TEI/>", encoding="utf-8")
    report_path = output / "build_report.txt"
    report_path.write_text("rapport", encoding="utf-8")

    xml_path = tmp_path / "workspace" / "source" / "document.xml"
    xml_path.parent.mkdir(parents=True, exist_ok=True)
    xml_path.write_text("<TEI/>", encoding="utf-8")

    latei_path = None
    if with_latei:
        latei_path = output / "assets" / "generated" / "book.tex"
        latei_path.parent.mkdir(parents=True, exist_ok=True)
        latei_path.write_text("% latei", encoding="utf-8")

    pdf_path = None
    if with_pdf:
        pdf_path = output / "assets" / "generated" / "book.pdf"
        pdf_path.parent.mkdir(parents=True, exist_ok=True)
        pdf_path.write_bytes(b"%PDF-1.4")

    manifest_path = tmp_path / "workspace" / "publication.json"
    manifest_path.write_text("{}", encoding="utf-8")

    from chaine_editoriale.modeles import PublicationResult

    return PublicationResult(
        xml_path=xml_path,
        media_directory=None,
        assets_root=None,
        site_result=_FakeBuildResult(output, html_path, normalized_tei_path, report_path),
        latei_path=latei_path,
        pdf_path=pdf_path,
        pdf_status=pdf_status,
        manifest_path=manifest_path,
        conversion_diagnostics=diagnostics,
    )


# ---------------------------------------------------------------------------
# Validation


def _valid_state(tmp_path: Path, minimal_docx_path: Path, minimal_metadata_path: Path) -> ip.PublicationFormState:
    return ip.PublicationFormState(
        docx_path=str(minimal_docx_path),
        metadata_path=str(minimal_metadata_path),
        workspace_dir=str(tmp_path / "workspace"),
        output_dir=str(tmp_path / "output"),
        output_mode="html_latei_pdf",
        latex_engine="lualatex",
    )


def test_validate_publication_form_fully_valid(tmp_path: Path, minimal_docx_path: Path, minimal_metadata_path: Path) -> None:
    state = _valid_state(tmp_path, minimal_docx_path, minimal_metadata_path)
    assert ip.validate_publication_form(state) == ()


def test_validate_publication_form_docx_missing(tmp_path: Path, minimal_metadata_path: Path) -> None:
    state = ip.PublicationFormState(
        docx_path=str(tmp_path / "absent.docx"),
        metadata_path=str(minimal_metadata_path),
        workspace_dir=str(tmp_path / "ws"),
        output_dir=str(tmp_path / "out"),
    )
    issues = ip.validate_publication_form(state)
    assert any(issue.field == "docx_path" for issue in issues)


def test_validate_publication_form_docx_wrong_extension(tmp_path: Path, minimal_metadata_path: Path) -> None:
    wrong_file = tmp_path / "document.txt"
    wrong_file.write_text("pas un docx", encoding="utf-8")
    state = ip.PublicationFormState(
        docx_path=str(wrong_file),
        metadata_path=str(minimal_metadata_path),
        workspace_dir=str(tmp_path / "ws"),
        output_dir=str(tmp_path / "out"),
    )
    issues = ip.validate_publication_form(state)
    assert any(issue.field == "docx_path" and ".docx" in issue.message for issue in issues)


def test_validate_publication_form_docx_extension_case_insensitive(tmp_path: Path, minimal_metadata_path: Path) -> None:
    upper_docx = tmp_path / "DOCUMENT.DOCX"
    upper_docx.write_bytes(b"fake")
    state = ip.PublicationFormState(
        docx_path=str(upper_docx),
        metadata_path=str(minimal_metadata_path),
        workspace_dir=str(tmp_path / "ws"),
        output_dir=str(tmp_path / "out"),
    )
    issues = ip.validate_publication_form(state)
    assert not any(issue.field == "docx_path" for issue in issues)


def test_validate_publication_form_metadata_missing(tmp_path: Path, minimal_docx_path: Path) -> None:
    state = ip.PublicationFormState(
        docx_path=str(minimal_docx_path),
        metadata_path=str(tmp_path / "absent.json"),
        workspace_dir=str(tmp_path / "ws"),
        output_dir=str(tmp_path / "out"),
    )
    issues = ip.validate_publication_form(state)
    assert any(issue.field == "metadata_path" for issue in issues)


def test_validate_publication_form_metadata_wrong_extension(tmp_path: Path, minimal_docx_path: Path) -> None:
    wrong_file = tmp_path / "metadata.txt"
    wrong_file.write_text("{}", encoding="utf-8")
    state = ip.PublicationFormState(
        docx_path=str(minimal_docx_path),
        metadata_path=str(wrong_file),
        workspace_dir=str(tmp_path / "ws"),
        output_dir=str(tmp_path / "out"),
    )
    issues = ip.validate_publication_form(state)
    assert any(issue.field == "metadata_path" and ".json" in issue.message for issue in issues)


def test_validate_publication_form_workspace_missing(tmp_path: Path, minimal_docx_path: Path, minimal_metadata_path: Path) -> None:
    state = ip.PublicationFormState(
        docx_path=str(minimal_docx_path), metadata_path=str(minimal_metadata_path), workspace_dir="", output_dir=str(tmp_path / "out")
    )
    issues = ip.validate_publication_form(state)
    assert any(issue.field == "workspace_dir" for issue in issues)


def test_validate_publication_form_output_missing(tmp_path: Path, minimal_docx_path: Path, minimal_metadata_path: Path) -> None:
    state = ip.PublicationFormState(
        docx_path=str(minimal_docx_path), metadata_path=str(minimal_metadata_path), workspace_dir=str(tmp_path / "ws"), output_dir=""
    )
    issues = ip.validate_publication_form(state)
    assert any(issue.field == "output_dir" for issue in issues)


def test_validate_publication_form_identical_directories(tmp_path: Path, minimal_docx_path: Path, minimal_metadata_path: Path) -> None:
    same_dir = str(tmp_path / "shared")
    state = ip.PublicationFormState(
        docx_path=str(minimal_docx_path), metadata_path=str(minimal_metadata_path), workspace_dir=same_dir, output_dir=same_dir
    )
    issues = ip.validate_publication_form(state)
    assert any(issue.field == "output_dir" and "différent" in issue.message for issue in issues)


def test_validate_publication_form_unknown_mode(tmp_path: Path, minimal_docx_path: Path, minimal_metadata_path: Path) -> None:
    state = _valid_state(tmp_path, minimal_docx_path, minimal_metadata_path)
    state.output_mode = "mode-inconnu"
    issues = ip.validate_publication_form(state)
    assert any(issue.field == "output_mode" for issue in issues)


def test_validate_publication_form_unknown_engine(tmp_path: Path, minimal_docx_path: Path, minimal_metadata_path: Path) -> None:
    state = _valid_state(tmp_path, minimal_docx_path, minimal_metadata_path)
    state.latex_engine = "pdflatex"
    issues = ip.validate_publication_form(state)
    assert any(issue.field == "latex_engine" for issue in issues)


def test_validate_publication_form_accumulates_multiple_issues(tmp_path: Path) -> None:
    state = ip.PublicationFormState(
        docx_path="",
        metadata_path="",
        workspace_dir="",
        output_dir="",
        output_mode="bad",
        latex_engine="bad",
    )
    issues = ip.validate_publication_form(state)
    fields = {issue.field for issue in issues}
    assert fields == {"docx_path", "metadata_path", "workspace_dir", "output_dir", "output_mode", "latex_engine"}


# ---------------------------------------------------------------------------
# Construction de la requete


def test_build_publication_request_html_mode(tmp_path: Path, minimal_docx_path: Path, minimal_metadata_path: Path) -> None:
    state = _valid_state(tmp_path, minimal_docx_path, minimal_metadata_path)
    state.output_mode = "html"
    request = ip.build_publication_request(state)
    assert request.options.pdf_export_mode == "none"
    assert request.options.write_normalized_tei is True


def test_build_publication_request_html_latei_mode(tmp_path: Path, minimal_docx_path: Path, minimal_metadata_path: Path) -> None:
    state = _valid_state(tmp_path, minimal_docx_path, minimal_metadata_path)
    state.output_mode = "html_latei"
    request = ip.build_publication_request(state)
    assert request.options.pdf_export_mode == "latei"
    assert request.options.write_normalized_tei is True


def test_build_publication_request_html_latei_pdf_mode(tmp_path: Path, minimal_docx_path: Path, minimal_metadata_path: Path) -> None:
    state = _valid_state(tmp_path, minimal_docx_path, minimal_metadata_path)
    state.output_mode = "html_latei_pdf"
    request = ip.build_publication_request(state)
    assert request.options.pdf_export_mode == "latei_pdf"
    assert request.options.write_normalized_tei is True


def test_build_publication_request_transmits_engine_and_normalizes_paths(
    tmp_path: Path, minimal_docx_path: Path, minimal_metadata_path: Path
) -> None:
    state = _valid_state(tmp_path, minimal_docx_path, minimal_metadata_path)
    request = ip.build_publication_request(state)
    assert request.options.latex_engine == "lualatex"
    assert isinstance(request.docx_path, Path)
    assert isinstance(request.metadata_path, Path)
    assert isinstance(request.workspace_dir, Path)
    assert isinstance(request.output_dir, Path)


# ---------------------------------------------------------------------------
# Dossiers


def test_directory_is_non_empty_absent(tmp_path: Path) -> None:
    assert ip.directory_is_non_empty(tmp_path / "absent") is False


def test_directory_is_non_empty_empty_dir(tmp_path: Path) -> None:
    empty = tmp_path / "empty"
    empty.mkdir()
    assert ip.directory_is_non_empty(empty) is False


def test_directory_is_non_empty_with_content(tmp_path: Path) -> None:
    populated = tmp_path / "populated"
    populated.mkdir()
    (populated / "file.txt").write_text("x", encoding="utf-8")
    assert ip.directory_is_non_empty(populated) is True


def test_directory_is_non_empty_read_error_propagates(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    target = tmp_path / "unreadable"
    target.mkdir()

    def _failing_scandir(_path: object):
        raise OSError("lecture impossible simulee")

    monkeypatch.setattr(ip.os, "scandir", _failing_scandir)
    with pytest.raises(OSError):
        ip.directory_is_non_empty(target)


# ---------------------------------------------------------------------------
# Worker


def test_run_publication_job_calls_publier_once_and_returns_success(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake_result = object()
    calls: list[tuple] = []

    def _fake_publier(docx_path, metadata_path, workspace_dir, output_dir, *, options=None):
        calls.append((docx_path, metadata_path, workspace_dir, output_dir, options))
        return fake_result

    monkeypatch.setattr(ip, "publier", _fake_publier)

    from chaine_editoriale.modeles import PublicationOptions

    request = ip.PublicationRequest(
        docx_path=tmp_path / "a.docx",
        metadata_path=tmp_path / "a.json",
        workspace_dir=tmp_path / "ws",
        output_dir=tmp_path / "out",
        options=PublicationOptions(),
    )
    event = ip.run_publication_job(request)

    assert len(calls) == 1
    assert event.kind == "success"
    assert event.result is fake_result
    assert event.error is None


def test_run_publication_job_transmits_public_exception(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    error = InvalidMetadataError("metadonnees invalides", diagnostics=())

    def _failing_publier(*_args: object, **_kwargs: object):
        raise error

    monkeypatch.setattr(ip, "publier", _failing_publier)

    from chaine_editoriale.modeles import PublicationOptions

    request = ip.PublicationRequest(
        docx_path=tmp_path / "a.docx",
        metadata_path=tmp_path / "a.json",
        workspace_dir=tmp_path / "ws",
        output_dir=tmp_path / "out",
        options=PublicationOptions(),
    )
    event = ip.run_publication_job(request)

    assert event.kind == "error"
    assert event.error is error
    assert event.result is None


def test_run_publication_job_transmits_unexpected_exception_without_swallowing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    error = ValueError("erreur totalement inattendue")

    def _failing_publier(*_args: object, **_kwargs: object):
        raise error

    monkeypatch.setattr(ip, "publier", _failing_publier)

    from chaine_editoriale.modeles import PublicationOptions

    request = ip.PublicationRequest(
        docx_path=tmp_path / "a.docx",
        metadata_path=tmp_path / "a.json",
        workspace_dir=tmp_path / "ws",
        output_dir=tmp_path / "out",
        options=PublicationOptions(),
    )
    event = ip.run_publication_job(request)

    assert event.kind == "error"
    assert event.error is error


def test_run_publication_job_makes_no_tkinter_call(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """S'assure que tkinter n'est meme pas importe par le worker."""
    import sys

    monkeypatch.setattr(ip, "publier", lambda *a, **k: object())
    from chaine_editoriale.modeles import PublicationOptions

    request = ip.PublicationRequest(
        docx_path=tmp_path / "a.docx",
        metadata_path=tmp_path / "a.json",
        workspace_dir=tmp_path / "ws",
        output_dir=tmp_path / "out",
        options=PublicationOptions(),
    )
    tkinter_was_loaded_before = "tkinter" in sys.modules
    ip.run_publication_job(request)
    if not tkinter_was_loaded_before:
        assert "tkinter" not in sys.modules


# ---------------------------------------------------------------------------
# Formatage


def test_format_publication_summary_full_success(tmp_path: Path) -> None:
    result = _make_result(tmp_path, with_latei=True, with_pdf=True, pdf_status="generated")
    summary = ip.format_publication_summary(result)
    assert "Publication terminée" in summary
    assert "Site HTML : produit" in summary
    assert "XML normalisé : produit" in summary
    assert "LaTEI : produit" in summary
    assert "PDF : produit" in summary
    assert "Manifeste : produit" in summary


def test_format_publication_summary_mode_without_latei_pdf(tmp_path: Path) -> None:
    result = _make_result(tmp_path, with_latei=False, with_pdf=False, pdf_status="not_requested")
    summary = ip.format_publication_summary(result)
    assert "LaTEI : non produit" in summary
    assert "PDF : non demandé" in summary


def test_format_publication_summary_pdf_unavailable_not_shown_as_failure(tmp_path: Path) -> None:
    result = _make_result(tmp_path, with_latei=True, with_pdf=False, pdf_status="unavailable")
    summary = ip.format_publication_summary(result)
    assert "PDF : demandé mais non produit" in summary
    assert "Site HTML : produit" in summary
    assert "LaTEI : produit" in summary


def test_format_diagnostics_multiple_entries() -> None:
    @dataclass
    class _Diag:
        code: str
        severity: str
        message: str
        path: str | None = None

    diagnostics = (
        _Diag("missing_title", "error", "titre obligatoire", "document.title"),
        _Diag("similar_keywords", "warning", "mots-clés équivalents"),
    )
    formatted = ip.format_diagnostics(diagnostics)
    assert "missing_title" in formatted
    assert "titre obligatoire" in formatted
    assert "document.title" in formatted
    assert "similar_keywords" in formatted
    assert formatted.count("\n") >= 1


def test_format_publication_error_unexpected_exception() -> None:
    error = RuntimeError("boum")
    formatted = ip.format_publication_error(error)
    assert "inattendue" in formatted
    assert "RuntimeError" in formatted
    assert "boum" in formatted


@pytest.mark.parametrize(
    "error",
    [
        ConfigurationError("config cassee"),
        DependencyVerificationError("deps cassees", diagnostics=()),
        InvalidMetadataError("metadonnees invalides", diagnostics=()),
        TeiConversionError("conversion impossible", diagnostics=(), validation_issues=()),
        TeiWriteError("ecriture impossible"),
        SiteBuildError("site casse"),
        AssetPreparationError("assets casses"),
        ChecksumError("empreinte impossible", path="C:/x.docx"),
        ManifestWriteError("manifeste impossible", path="C:/publication.json"),
    ],
)
def test_format_publication_error_all_public_error_types(error: ChaineEditorialeError) -> None:
    formatted = ip.format_publication_error(error)
    assert str(error) in formatted
    assert "Traceback" not in formatted
    assert isinstance(formatted, str)


def test_format_publication_error_includes_path_attribute() -> None:
    error = ChecksumError("empreinte impossible", path="C:/document.docx")
    formatted = ip.format_publication_error(error)
    assert "C:/document.docx" in formatted


def test_format_publication_error_includes_cause() -> None:
    try:
        try:
            raise OSError("disque plein")
        except OSError as inner:
            raise AssetPreparationError("copie impossible", cause=inner) from inner
    except AssetPreparationError as error:
        formatted = ip.format_publication_error(error)
    assert "disque plein" in formatted
    assert "OSError" in formatted


def test_describe_openable_artifacts_full_success(tmp_path: Path) -> None:
    result = _make_result(tmp_path, with_latei=True, with_pdf=True)
    actions = ip.describe_openable_artifacts(result)
    labels = {action.label for action in actions}
    assert labels == {
        "Ouvrir le site",
        "Ouvrir le XML intermédiaire",
        "Ouvrir le XML normalisé",
        "Ouvrir le LaTEI",
        "Ouvrir le PDF",
        "Ouvrir le manifeste",
        "Ouvrir le dossier de publication",
    }
    for action in actions:
        assert action.path.exists()


def test_describe_openable_artifacts_missing_artifact_not_proposed(tmp_path: Path) -> None:
    result = _make_result(tmp_path, with_latei=False, with_pdf=False, pdf_status="not_requested")
    actions = ip.describe_openable_artifacts(result)
    labels = {action.label for action in actions}
    assert "Ouvrir le LaTEI" not in labels
    assert "Ouvrir le PDF" not in labels
    assert "Ouvrir le site" in labels


def test_open_artifact_uses_os_startfile(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    called: list[Path] = []
    monkeypatch.setattr(ip.os, "startfile", lambda path: called.append(Path(path)), raising=False)
    target = tmp_path / "index.html"
    target.write_text("<html></html>", encoding="utf-8")
    ip.open_artifact(target)
    assert called == [target]


# ---------------------------------------------------------------------------
# Controleur d'ecran


def test_screen_controller_rejects_double_launch() -> None:
    controller = ip.PublicationScreenController()
    assert controller.begin_publication() is True
    assert controller.busy is True
    assert controller.begin_publication() is False, "un second lancement doit etre refuse"


def test_screen_controller_returns_to_idle_after_success() -> None:
    controller = ip.PublicationScreenController()
    controller.begin_publication()
    controller.end_publication()
    assert controller.busy is False
    assert controller.begin_publication() is True


def test_screen_controller_returns_to_idle_after_error() -> None:
    controller = ip.PublicationScreenController()
    controller.begin_publication()
    # meme chemin que success : end_publication est appele que le worker
    # ait renvoye un evenement "success" ou "error".
    controller.end_publication()
    assert controller.busy is False


def test_screen_controller_preserves_form_values_across_publications() -> None:
    controller = ip.PublicationScreenController()
    controller.form_state.docx_path = "C:/document.docx"
    controller.begin_publication()
    controller.end_publication()
    assert controller.form_state.docx_path == "C:/document.docx"


# ---------------------------------------------------------------------------
# Aide au remplissage (repertoire initial, suggestions)


def test_initial_directory_for_uses_existing_file_parent(tmp_path: Path) -> None:
    docx = tmp_path / "sub" / "doc.docx"
    docx.parent.mkdir()
    docx.write_bytes(b"x")
    assert ip.initial_directory_for(str(docx)) == str(docx.parent)


def test_initial_directory_for_falls_back_to_home_when_nothing_usable() -> None:
    assert ip.initial_directory_for("", "") == str(Path.home())


def test_suggest_workspace_and_output_dirs(tmp_path: Path) -> None:
    docx = tmp_path / "mon-document.docx"
    workspace, output = ip.suggest_workspace_and_output_dirs(docx)
    assert workspace == str(tmp_path / "mon-document-travail")
    assert output == str(tmp_path / "mon-document-site")


# ---------------------------------------------------------------------------
# Test d'integration de l'interface logique (formulaire -> requete -> worker)


@pytest.mark.integration
def test_publication_form_to_worker_end_to_end(
    tmp_path: Path, fixtures_dir: Path, activated_config_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Formulaire -> validation -> requete -> worker -> resume -> actions d'ouverture, sans mock de publier()."""
    docx_path = fixtures_dir / "document_avec_image.docx"
    metadata_path = fixtures_dir / "document_avec_image.metadata.json"

    state = ip.PublicationFormState(
        docx_path=str(docx_path),
        metadata_path=str(metadata_path),
        workspace_dir=str(tmp_path / "workspace"),
        output_dir=str(tmp_path / "output"),
        output_mode="html_latei_pdf",
        latex_engine="lualatex",
    )

    issues = ip.validate_publication_form(state)
    assert issues == ()

    request = ip.build_publication_request(state)
    assert request.options.pdf_export_mode == "latei_pdf"

    event = ip.run_publication_job(request)
    assert event.kind == "success", ip.format_publication_error(event.error) if event.error else None
    result = event.result
    assert result is not None

    # XML intermediaire, HTML, XML normalise.
    assert result.xml_path.is_file()
    assert result.site_result.html_path.is_file()
    assert result.site_result.normalized_tei_path is not None and result.site_result.normalized_tei_path.is_file()

    # LaTEI toujours produit en mode html_latei_pdf.
    assert result.latei_path is not None and result.latei_path.is_file()

    # PDF uniquement si LuaLaTeX est disponible sur cette machine.
    if shutil.which("lualatex") is not None:
        assert result.pdf_path is not None and result.pdf_path.is_file()
        assert result.pdf_status == "generated"
    else:
        assert result.pdf_status in {"unavailable", "generated"}

    # Manifeste.
    assert result.manifest_path.is_file()

    # Resume final lisible.
    summary = ip.format_publication_summary(result)
    assert "Publication terminée" in summary
    assert "Site HTML : produit" in summary

    # Liste des actions d'ouverture : chaque chemin propose existe reellement.
    actions = ip.describe_openable_artifacts(result)
    assert actions
    labels = {action.label for action in actions}
    assert "Ouvrir le site" in labels
    assert "Ouvrir le manifeste" in labels
    for action in actions:
        assert action.path.exists()

    # os.startfile() n'est jamais reellement appele dans les tests.
    opened: list[Path] = []
    monkeypatch.setattr(ip.os, "startfile", lambda path: opened.append(Path(path)), raising=False)
    for action in actions:
        ip.open_artifact(action.path)
    assert len(opened) == len(actions)
