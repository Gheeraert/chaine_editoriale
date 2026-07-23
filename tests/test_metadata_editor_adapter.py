"""Tests de l'adaptateur local vers l'editeur de metadonnees Mini-Metopes.

Aucun import reel de mini_metopes ici : des faux modules sont injectes dans
``sys.modules`` via monkeypatch, pour verifier le contrat (parametres
transmis, conversion du resultat, import differe) sans dependre de la vraie
bibliotheque.
"""

from __future__ import annotations

import sys
import types
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import pytest

from chaine_editoriale import metadata_editor_adapter as adapter
from chaine_editoriale.erreurs import MetadataEditorIntegrationError


# ---------------------------------------------------------------------------
# Aucun import de mini_metopes au chargement du module


def test_module_does_not_import_mini_metopes_at_load_time() -> None:
    import inspect

    source = inspect.getsource(adapter)
    # Seules les lignes non indentees (colonne 0) sont de vrais imports de
    # module ; les imports differes vivent volontairement a l'interieur des
    # fonctions (indentes) et ne doivent pas etre confondus avec eux.
    top_level_imports = [
        line for line in source.splitlines() if line.startswith(("import mini_metopes", "from mini_metopes"))
    ]
    assert top_level_imports == []


def test_module_import_alone_does_not_load_mini_metopes(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delitem(sys.modules, "mini_metopes", raising=False)
    monkeypatch.delitem(sys.modules, "mini_metopes.gui", raising=False)
    monkeypatch.delitem(sys.modules, "mini_metopes.metadata", raising=False)
    import importlib

    importlib.reload(adapter)
    assert "mini_metopes" not in sys.modules
    assert "mini_metopes.gui" not in sys.modules


# ---------------------------------------------------------------------------
# Faux module mini_metopes.gui / mini_metopes.metadata


@dataclass(frozen=True, slots=True)
class _FakeResult:
    status: Literal["saved", "cancelled"]
    docx_path: Path
    metadata_path: Path | None


def _install_fake_mini_metopes(
    monkeypatch: pytest.MonkeyPatch,
    *,
    open_metadata_editor=None,
    default_metadata_path=None,
) -> None:
    package = types.ModuleType("mini_metopes")
    gui_module = types.ModuleType("mini_metopes.gui")
    metadata_module = types.ModuleType("mini_metopes.metadata")

    if open_metadata_editor is not None:
        gui_module.open_metadata_editor = open_metadata_editor
    if default_metadata_path is not None:
        metadata_module.default_metadata_path = default_metadata_path

    monkeypatch.setitem(sys.modules, "mini_metopes", package)
    monkeypatch.setitem(sys.modules, "mini_metopes.gui", gui_module)
    monkeypatch.setitem(sys.modules, "mini_metopes.metadata", metadata_module)


# ---------------------------------------------------------------------------
# conventional_metadata_path()


def test_conventional_metadata_path_calls_real_default_metadata_path(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[Path] = []

    def _fake_default_metadata_path(docx_path: Path) -> Path:
        calls.append(docx_path)
        return docx_path.with_suffix(".metadata.json")

    _install_fake_mini_metopes(monkeypatch, default_metadata_path=_fake_default_metadata_path)

    docx_path = Path("C:/livre/chapitre.docx")
    result = adapter.conventional_metadata_path(docx_path)

    assert calls == [docx_path]
    assert result == Path("C:/livre/chapitre.metadata.json")


def test_conventional_metadata_path_missing_api_raises_integration_error(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_fake_mini_metopes(monkeypatch, default_metadata_path=None)

    with pytest.raises(MetadataEditorIntegrationError):
        adapter.conventional_metadata_path(Path("C:/livre/chapitre.docx"))


# ---------------------------------------------------------------------------
# edit_metadata() : parametres transmis


def test_edit_metadata_transmits_exact_parameters(monkeypatch: pytest.MonkeyPatch) -> None:
    received: dict[str, object] = {}

    def _fake_open_metadata_editor(parent, docx_path, metadata_path=None, *, prompt_for_new_destination=True, show_tei_generation=False):
        received["parent"] = parent
        received["docx_path"] = docx_path
        received["metadata_path"] = metadata_path
        received["prompt_for_new_destination"] = prompt_for_new_destination
        received["show_tei_generation"] = show_tei_generation
        return _FakeResult("saved", docx_path, metadata_path)

    _install_fake_mini_metopes(monkeypatch, open_metadata_editor=_fake_open_metadata_editor)

    parent = object()
    docx_path = Path("C:/livre/chapitre.docx")
    metadata_path = Path("C:/livre/chapitre.metadata.json")

    adapter.edit_metadata(parent, docx_path, metadata_path)

    assert received["parent"] is parent
    assert received["docx_path"] == docx_path
    assert received["metadata_path"] == metadata_path
    assert received["prompt_for_new_destination"] is False
    assert received["show_tei_generation"] is False


# ---------------------------------------------------------------------------
# Conversion des resultats


def test_edit_metadata_converts_saved_result(monkeypatch: pytest.MonkeyPatch) -> None:
    docx_path = Path("C:/livre/chapitre.docx")
    metadata_path = Path("C:/livre/chapitre.metadata.json")

    def _fake_open_metadata_editor(parent, docx, metadata=None, **kwargs):
        return _FakeResult("saved", docx_path, metadata_path)

    _install_fake_mini_metopes(monkeypatch, open_metadata_editor=_fake_open_metadata_editor)

    outcome = adapter.edit_metadata(object(), docx_path, metadata_path)

    assert outcome.status == "saved"
    assert outcome.docx_path == docx_path
    assert outcome.metadata_path == metadata_path
    assert outcome.saved is True


def test_edit_metadata_converts_cancelled_result(monkeypatch: pytest.MonkeyPatch) -> None:
    docx_path = Path("C:/livre/chapitre.docx")

    def _fake_open_metadata_editor(parent, docx, metadata=None, **kwargs):
        return _FakeResult("cancelled", docx_path, None)

    _install_fake_mini_metopes(monkeypatch, open_metadata_editor=_fake_open_metadata_editor)

    outcome = adapter.edit_metadata(object(), docx_path, None)

    assert outcome.status == "cancelled"
    assert outcome.docx_path == docx_path
    assert outcome.metadata_path is None
    assert outcome.saved is False


def test_edit_metadata_preserves_relocated_paths(monkeypatch: pytest.MonkeyPatch) -> None:
    """L'editeur peut retourner un DOCX et un JSON differents de ceux fournis (relocalisation)."""
    original_docx = Path("C:/livre/chapitre.docx")
    other_docx = Path("C:/ailleurs/autre-chapitre.docx")
    other_metadata = Path("C:/ailleurs/autre-chapitre.metadata.json")

    def _fake_open_metadata_editor(parent, docx, metadata=None, **kwargs):
        return _FakeResult("saved", other_docx, other_metadata)

    _install_fake_mini_metopes(monkeypatch, open_metadata_editor=_fake_open_metadata_editor)

    outcome = adapter.edit_metadata(object(), original_docx, None)

    assert outcome.docx_path == other_docx
    assert outcome.metadata_path == other_metadata


# ---------------------------------------------------------------------------
# Statuts et resultats invalides


def test_edit_metadata_unknown_status_raises_integration_error(monkeypatch: pytest.MonkeyPatch) -> None:
    @dataclass(frozen=True, slots=True)
    class _BadResult:
        status: str
        docx_path: Path
        metadata_path: Path | None

    def _fake_open_metadata_editor(parent, docx, metadata=None, **kwargs):
        return _BadResult("unknown", docx, metadata)

    _install_fake_mini_metopes(monkeypatch, open_metadata_editor=_fake_open_metadata_editor)

    with pytest.raises(MetadataEditorIntegrationError):
        adapter.edit_metadata(object(), Path("C:/a.docx"), None)


def test_edit_metadata_saved_without_metadata_path_raises_integration_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def _fake_open_metadata_editor(parent, docx, metadata=None, **kwargs):
        return _FakeResult("saved", docx, None)

    _install_fake_mini_metopes(monkeypatch, open_metadata_editor=_fake_open_metadata_editor)

    with pytest.raises(MetadataEditorIntegrationError):
        adapter.edit_metadata(object(), Path("C:/a.docx"), None)


def test_edit_metadata_missing_api_raises_integration_error(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_fake_mini_metopes(monkeypatch, open_metadata_editor=None)

    with pytest.raises(MetadataEditorIntegrationError):
        adapter.edit_metadata(object(), Path("C:/a.docx"), None)


def test_edit_metadata_integration_error_message_is_actionable(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_fake_mini_metopes(monkeypatch, open_metadata_editor=None)

    with pytest.raises(MetadataEditorIntegrationError) as excinfo:
        adapter.edit_metadata(object(), Path("C:/a.docx"), None)

    message = str(excinfo.value)
    assert "minimetopes" in message
    assert "open_metadata_editor" in message


# ---------------------------------------------------------------------------
# Les exceptions metier de Mini-Metopes ne sont jamais masquees


def test_edit_metadata_lets_docx_inspection_error_propagate(monkeypatch: pytest.MonkeyPatch) -> None:
    class _DocxInspectionError(ValueError):
        pass

    def _failing_open_metadata_editor(parent, docx, metadata=None, **kwargs):
        raise _DocxInspectionError("document illisible")

    _install_fake_mini_metopes(monkeypatch, open_metadata_editor=_failing_open_metadata_editor)

    with pytest.raises(_DocxInspectionError):
        adapter.edit_metadata(object(), Path("C:/a.docx"), None)


def test_edit_metadata_lets_os_error_propagate(monkeypatch: pytest.MonkeyPatch) -> None:
    def _failing_open_metadata_editor(parent, docx, metadata=None, **kwargs):
        raise OSError("disque plein")

    _install_fake_mini_metopes(monkeypatch, open_metadata_editor=_failing_open_metadata_editor)

    with pytest.raises(OSError):
        adapter.edit_metadata(object(), Path("C:/a.docx"), None)


# ---------------------------------------------------------------------------
# Integration reelle : la Mini-Metopes configuree fournit-elle bien l'API ?


@pytest.mark.integration
def test_real_mini_metopes_provides_the_embeddable_metadata_editor_api(
    real_repos: tuple[Path, Path], activated_config_path: Path
) -> None:
    """Verifie, avec la vraie configuration activee, que l'adaptateur resout bien la vraie API.

    Ignore proprement (avec un message precis) si le depot Mini-Metopes
    configure ne fournit pas encore cette API : cette passe ne doit pas
    contourner l'absence de l'API par un autre mecanisme.
    """
    from chaine_editoriale.configuration import activate_configured_dependencies, load_config

    load_result = load_config(activated_config_path)
    assert load_result.config is not None
    verification = activate_configured_dependencies(load_result.config)
    if not verification.success:
        pytest.skip(f"depots configures non actives : {verification.mini_metopes.message}")

    try:
        from mini_metopes.gui import MetadataEditorResult, open_metadata_editor  # noqa: F401
        from mini_metopes.metadata import default_metadata_path  # noqa: F401
    except ImportError as error:
        pytest.skip(
            "Le depot Mini-Metopes configure ne fournit pas encore "
            f"l'API d'edition de metadonnees integrable : {error}"
        )

    docx_path = Path("C:/livre/chapitre.docx")
    resolved = adapter.conventional_metadata_path(docx_path)
    assert resolved == default_metadata_path(docx_path)
