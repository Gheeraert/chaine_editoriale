"""Tests automatises des scenarios de configuration et de redemarrage.

Couvre ``ConfigController`` et ``startup_screen`` sans ouvrir de fenetre Tk
reelle et sans toucher a la vraie configuration ``%APPDATA%`` : toutes les
verifications de dependances sont remplacees par des
``DependencyVerification`` factices via ``monkeypatch``.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from chaine_editoriale import gui
from chaine_editoriale.configuration import DependencyCheck, DependencyState, DependencyVerification
from chaine_editoriale.erreurs import ConfigurationError


def _check(name: str, state: DependencyState) -> DependencyCheck:
    return DependencyCheck(
        name,
        Path(f"C:/{name}"),
        Path(f"C:/{name}/src"),
        Path(f"C:/{name}/src/{name}/__init__.py"),
        state,
        f"{name}: {state}",
    )


def _verification(mini_metopes_state: DependencyState, purh_site_state: DependencyState) -> DependencyVerification:
    return DependencyVerification(_check("mini_metopes", mini_metopes_state), _check("purh_site", purh_site_state))


# ---------------------------------------------------------------------------
# Verification reussie


def test_controller_success_flow_writes_today_and_reaches_main(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    config_path = tmp_path / "config_chaine.json"
    controller = gui.ConfigController("C:/mini_metopes", "C:/purh_site", config_path=config_path)
    monkeypatch.setattr(gui, "activate_configured_dependencies", lambda config: _verification("success", "success"))

    verification = controller.verify()
    assert verification.success
    assert controller.can_save() is True

    written = controller.save()
    assert written == config_path
    saved = json.loads(config_path.read_text(encoding="utf-8"))
    assert saved["last_verified"] == gui.today_iso()

    # L'ecran principal est accessible : une verification automatique
    # ulterieure de cette configuration reussit immediatement.
    screen, _controller = gui.startup_screen(config_path)
    assert screen == "main"


# ---------------------------------------------------------------------------
# Redemarrage requis


def test_controller_restart_required_flow_writes_null_and_blocks_main(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config_path = tmp_path / "config_chaine.json"
    controller = gui.ConfigController("C:/mini_metopes", "C:/purh_site", config_path=config_path)
    monkeypatch.setattr(gui, "activate_configured_dependencies", lambda config: _verification("restart_required", "success"))

    verification = controller.verify()
    assert not verification.success
    assert controller.can_save() is True

    written = controller.save()
    saved = json.loads(written.read_text(encoding="utf-8"))
    assert saved["last_verified"] is None

    message = controller.post_save_message()
    assert "redemarr" in message.lower()

    # L'application ne doit pas se considerer immediatement prete : la
    # verification en memoire reste un echec (non "success"), ce qui est
    # exactement ce que run_gui() teste pour choisir entre l'ecran principal
    # et l'ecran de redemarrage requis (voir gui.run_gui.on_save).
    assert controller.verification is not None
    assert not controller.verification.success

    # Aucun acces direct a l'ecran principal dans le meme processus : tant
    # que sys.modules n'a pas ete nettoye par un redemarrage reel, une
    # nouvelle verification automatique de cette configuration echoue encore.
    monkeypatch.setattr(gui, "activate_configured_dependencies", lambda config: _verification("restart_required", "success"))
    screen, _controller = gui.startup_screen(config_path)
    assert screen == "config"


# ---------------------------------------------------------------------------
# Erreur reelle


def test_controller_error_flow_cannot_save(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    config_path = tmp_path / "config_chaine.json"
    controller = gui.ConfigController("C:/bad-repo", "C:/purh_site", config_path=config_path)
    monkeypatch.setattr(gui, "activate_configured_dependencies", lambda config: _verification("error", "success"))

    verification = controller.verify()
    assert not verification.success
    assert controller.can_save() is False

    with pytest.raises(RuntimeError):
        controller.save()
    assert not config_path.exists()


# ---------------------------------------------------------------------------
# Modification d'un champ apres verification


def test_controller_field_change_invalidates_previous_verification(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    controller = gui.ConfigController("C:/mini_metopes", "C:/purh_site", config_path=tmp_path / "config_chaine.json")
    monkeypatch.setattr(gui, "activate_configured_dependencies", lambda config: _verification("success", "success"))

    controller.verify()
    assert controller.can_save() is True

    controller.set_mini_metopes_path("C:/autre-mini-metopes")
    assert controller.verification is None
    assert controller.can_save() is False


def test_controller_field_change_back_to_verified_value_still_requires_reverify(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Une verification n'est valable que pour l'appel explicite qui l'a produite."""
    controller = gui.ConfigController("C:/mini_metopes", "C:/purh_site", config_path=tmp_path / "config_chaine.json")
    monkeypatch.setattr(gui, "activate_configured_dependencies", lambda config: _verification("success", "success"))
    controller.verify()
    controller.set_purh_site_path("C:/changed")
    controller.set_purh_site_path("C:/purh_site")  # revient a la valeur verifiee
    assert controller.can_save() is False  # _verified_for a ete efface par _invalidate()


# ---------------------------------------------------------------------------
# Lancement suivant : configuration enregistree avec last_verified=null


def test_startup_screen_next_launch_reaches_main_and_updates_last_verified(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, write_config_file
) -> None:
    config_path = tmp_path / "config_chaine.json"
    write_config_file(
        config_path,
        {
            "schema": "chaine-editoriale-config",
            "schema_version": 1,
            "mini_metopes_path": "C:/mini_metopes",
            "purh_site_path": "C:/purh_site",
            "last_verified": None,
        },
    )
    monkeypatch.setattr(gui, "activate_configured_dependencies", lambda config: _verification("success", "success"))

    screen, controller = gui.startup_screen(config_path)

    assert screen == "main"
    assert controller.startup_warning is None
    saved = json.loads(config_path.read_text(encoding="utf-8"))
    assert saved["last_verified"] == gui.today_iso()


def test_startup_screen_reopens_config_screen_when_verification_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, write_config_file
) -> None:
    config_path = tmp_path / "config_chaine.json"
    write_config_file(
        config_path,
        {
            "schema": "chaine-editoriale-config",
            "schema_version": 1,
            "mini_metopes_path": "C:/moved-away",
            "purh_site_path": "C:/purh_site",
            "last_verified": "2026-01-01",
        },
    )
    monkeypatch.setattr(gui, "activate_configured_dependencies", lambda config: _verification("error", "success"))

    screen, controller = gui.startup_screen(config_path)

    assert screen == "config"
    assert controller.mini_metopes_path == str(Path("C:/moved-away"))
    assert controller.purh_site_path == str(Path("C:/purh_site"))


# ---------------------------------------------------------------------------
# Echec de mise a jour de last_verified au lancement (objectif 2)


def test_startup_screen_keeps_main_when_last_verified_update_fails_with_configuration_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, write_config_file
) -> None:
    config_path = tmp_path / "config_chaine.json"
    write_config_file(
        config_path,
        {
            "schema": "chaine-editoriale-config",
            "schema_version": 1,
            "mini_metopes_path": "C:/mini_metopes",
            "purh_site_path": "C:/purh_site",
            "last_verified": None,
        },
    )
    monkeypatch.setattr(gui, "activate_configured_dependencies", lambda config: _verification("success", "success"))

    def _failing_write_config(*_args: object, **_kwargs: object) -> Path:
        raise ConfigurationError("ecriture impossible simulee")

    monkeypatch.setattr(gui, "write_config", _failing_write_config)

    screen, controller = gui.startup_screen(config_path)

    assert screen == "main"
    assert controller.startup_warning is not None
    assert "ecriture impossible simulee" in controller.startup_warning


def test_startup_screen_does_not_swallow_unexpected_errors(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, write_config_file
) -> None:
    config_path = tmp_path / "config_chaine.json"
    write_config_file(
        config_path,
        {
            "schema": "chaine-editoriale-config",
            "schema_version": 1,
            "mini_metopes_path": "C:/mini_metopes",
            "purh_site_path": "C:/purh_site",
            "last_verified": None,
        },
    )
    monkeypatch.setattr(gui, "activate_configured_dependencies", lambda config: _verification("success", "success"))

    def _unexpectedly_failing_write_config(*_args: object, **_kwargs: object) -> Path:
        raise ValueError("erreur totalement inattendue, ne doit pas devenir un simple avertissement")

    monkeypatch.setattr(gui, "write_config", _unexpectedly_failing_write_config)

    with pytest.raises(ValueError):
        gui.startup_screen(config_path)


# ---------------------------------------------------------------------------
# Premier lancement : pas de configuration valide


def test_startup_screen_first_launch_without_config_shows_config_screen(tmp_path: Path) -> None:
    config_path = tmp_path / "config_chaine.json"
    screen, controller = gui.startup_screen(config_path)
    assert screen == "config"
    assert controller.verification is None
    assert controller.can_save() is False


# ---------------------------------------------------------------------------
# Mecanisme de restauration de la configuration active (objectif 4)
#
# Le bouton "Retour a la publication" vit dans une fermeture imbriquee de
# run_gui() (qui bloque sur root.mainloop()) et n'est pas accessible
# isolement sans reecrire cette architecture. Le test ci-dessous protege
# directement le mecanisme d'instantane/restauration que gui.on_cancel_return
# applique aux memes attributs de ConfigController ; le cablage reel du
# bouton est verifie par inspection visuelle manuelle (voir le rapport de
# passe).


def test_config_controller_snapshot_and_restore_discards_unverified_changes() -> None:
    controller = gui.ConfigController("C:/a", "C:/b", config_path=Path("unused"))
    controller.verification = _verification("success", "success")
    controller._verified_for = ("C:/a", "C:/b")

    # Instantane pris a l'ouverture de l'ecran de configuration, comme le fait show_config_screen.
    snapshot = (controller.mini_metopes_path, controller.purh_site_path, controller.verification, controller._verified_for)

    controller.set_mini_metopes_path("C:/changed-but-not-saved")
    assert controller.verification is None  # invalide par la modification du champ

    # Restauration comme le fait on_cancel_return, sans reverification ni enregistrement.
    controller.mini_metopes_path, controller.purh_site_path, controller.verification, controller._verified_for = snapshot

    assert controller.mini_metopes_path == "C:/a"
    assert controller.purh_site_path == "C:/b"
    assert controller.verification is not None and controller.verification.success
    assert controller.can_save() is True


# ---------------------------------------------------------------------------
# Tests sur de vrais widgets Tkinter (defauts reellement rencontres)


def _widgets_by_class(widget, class_name: str) -> list:
    found = []
    for child in widget.winfo_children():
        if child.winfo_class() == class_name:
            found.append(child)
        found.extend(_widgets_by_class(child, class_name))
    return found


@pytest.fixture(scope="module")
def tk_root():
    """Une seule racine Tk partagee par les tests de ce module.

    Creer un ``tk.Tk()`` distinct par test (ou une racine "sonde" jetable en
    plus de la racine reelle) s'est revele source de plantages Tcl
    intermittents ("Can't find a usable init.tcl") sur cette machine
    lorsque plusieurs interpretes Tcl sont crees/detruits en rafale dans le
    meme processus. Une seule racine reelle est donc creee ici ; si Tk est
    reellement indisponible, la creation echoue et le module est ignore
    proprement pour tous ses tests. Chaque test nettoie les widgets enfants
    avant de construire son propre ecran.
    """
    import tkinter as tk

    try:
        root = tk.Tk()
    except Exception as error:  # noqa: BLE001 - environnement sans affichage : ignorer proprement.
        pytest.skip(f"Tk indisponible sur cette machine : {error}")
    yield root
    root.destroy()


def test_publication_screen_latex_engine_field_survives_rebuild(tk_root) -> None:
    from chaine_editoriale import interface_publication as ip

    root = tk_root
    for child in list(root.winfo_children()):
        child.destroy()
    controller = ip.PublicationScreenController()
    gui._build_publication_screen(root, controller, lambda: None)
    root.update_idletasks()
    root.update()
    combos = _widgets_by_class(root, "TCombobox")
    assert len(combos) == 2
    assert combos[1].get() == "LuaLaTeX"

    for child in list(root.winfo_children()):
        child.destroy()
    gui._build_publication_screen(root, controller, lambda: None)
    root.update_idletasks()
    root.update()
    combos_after_rebuild = _widgets_by_class(root, "TCombobox")
    assert combos_after_rebuild[1].get() == "LuaLaTeX"


def test_publication_screen_uses_the_controller_it_is_given(tk_root) -> None:
    from chaine_editoriale import interface_publication as ip

    root = tk_root
    for child in list(root.winfo_children()):
        child.destroy()
    controller = ip.PublicationScreenController()
    controller.form_state.docx_path = "C:/deja-saisi.docx"
    gui._build_publication_screen(root, controller, lambda: None)
    root.update()
    entries = _widgets_by_class(root, "TEntry")
    assert entries[0].get() == "C:/deja-saisi.docx"


def test_publication_screen_syncs_form_state_before_opening_config(tk_root) -> None:
    """Ouvrir "Configurer les dependances..." doit reporter la saisie visible dans form_state avant de detruire les widgets."""
    from chaine_editoriale import interface_publication as ip

    root = tk_root
    for child in list(root.winfo_children()):
        child.destroy()
    opened: list[bool] = []
    controller = ip.PublicationScreenController()
    gui._build_publication_screen(root, controller, lambda: opened.append(True))
    root.update()
    entries = _widgets_by_class(root, "TEntry")
    entries[0].insert(0, "C:/mon-document.docx")
    entries[2].insert(0, "C:/mon-workspace")
    root.update()

    config_button = next(
        button for button in _widgets_by_class(root, "TButton") if button.cget("text") == "Configurer les dépendances…"
    )
    config_button.invoke()

    assert opened == [True]
    assert controller.form_state.docx_path == "C:/mon-document.docx"
    assert controller.form_state.workspace_dir == "C:/mon-workspace"

    # Rebâtir l'ecran (comme le ferait le retour a la publication) :
    # les valeurs saisies doivent reapparaitre dans les widgets.
    for child in list(root.winfo_children()):
        child.destroy()
    gui._build_publication_screen(root, controller, lambda: None)
    root.update()
    entries_after_rebuild = _widgets_by_class(root, "TEntry")
    assert entries_after_rebuild[0].get() == "C:/mon-document.docx"
    assert entries_after_rebuild[2].get() == "C:/mon-workspace"


def test_publication_screen_busy_state_never_lost_across_rebuild(tk_root) -> None:
    from chaine_editoriale import interface_publication as ip

    root = tk_root
    for child in list(root.winfo_children()):
        child.destroy()
    controller = ip.PublicationScreenController()
    controller.begin_publication()
    gui._build_publication_screen(root, controller, lambda: None)
    root.update()
    assert controller.busy is True
    for child in list(root.winfo_children()):
        child.destroy()
    gui._build_publication_screen(root, controller, lambda: None)
    root.update()
    assert controller.busy is True
    controller.end_publication()


def test_publication_screen_artifact_buttons_span_multiple_rows(
    tk_root, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Protege l'objectif 6 : jusqu'a sept boutons ne doivent jamais rester sur une seule ligne."""
    import time
    from tkinter import messagebox

    from chaine_editoriale import interface_publication as ip

    output_dir = tmp_path / "output"
    output_dir.mkdir()
    fake_result = _fake_publication_result(tmp_path, output_dir)

    monkeypatch.setattr(ip, "run_publication_job", lambda request: ip.PublicationJobEvent(kind="success", result=fake_result))
    # output_dir contient deja les artefacts factices : la confirmation
    # "dossier non vide" est reelle et bloquante ; on l'auto-confirme ici,
    # ce comportement etant deja couvert separement par les tests purs de
    # directory_is_non_empty()/validate_publication_form().
    monkeypatch.setattr(messagebox, "askyesno", lambda *args, **kwargs: True)

    docx_path = tmp_path / "doc.docx"
    docx_path.write_bytes(b"fake")
    metadata_path = tmp_path / "doc.json"
    metadata_path.write_text("{}", encoding="utf-8")

    root = tk_root
    for child in list(root.winfo_children()):
        child.destroy()
    controller = ip.PublicationScreenController()
    # Le champ JSON est desormais readonly : un chemin explicite se prepare
    # sur form_state avant construction de l'ecran (equivalent a un retour de
    # "Choisir un autre JSON..."), jamais par insertion directe dans le widget.
    controller.form_state.metadata_path = str(metadata_path)
    controller.form_state.metadata_path_is_automatic = False
    gui._build_publication_screen(root, controller, lambda: None)
    root.update()

    entries = _widgets_by_class(root, "TEntry")
    entries[0].insert(0, str(docx_path))
    entries[2].insert(0, str(tmp_path / "ws"))
    entries[3].insert(0, str(output_dir))
    root.update()

    publish_button = next(button for button in _widgets_by_class(root, "TButton") if button.cget("text") == "Publier")
    publish_button.invoke()

    deadline = time.time() + 5
    while controller.busy and time.time() < deadline:
        root.update()
        time.sleep(0.02)
    assert not controller.busy

    artifact_buttons = [
        button for button in _widgets_by_class(root, "TButton") if button.cget("text").startswith("Ouvrir")
    ]
    assert len(artifact_buttons) >= 3
    rows = {int(button.grid_info()["row"]) for button in artifact_buttons}
    assert len(rows) >= 2, "les boutons d'ouverture doivent occuper plusieurs lignes de la grille"
    columns = {int(button.grid_info()["column"]) for button in artifact_buttons}
    assert columns == {0, 1}


# ---------------------------------------------------------------------------
# Parcours de creation/modification des metadonnees integre a la GUI


def _find_button(root, text: str):
    return next(button for button in _widgets_by_class(root, "TButton") if button.cget("text") == text)


def _find_docx_browse_button(root):
    """Le bouton "Parcourir..." du DOCX n'est pas unique par texte (workspace/output le partagent).

    Les trois boutons "Parcourir..." different par leur ligne de grille : le
    DOCX est toujours a la ligne 2 (cf. gui._build_publication_screen). Ne
    jamais se rabattre sur le premier match par texte seul : cliquer par
    erreur sur un bouton "Parcourir..." relie a askdirectory() ouvrirait une
    vraie boite de dialogue Windows, bloquant indefiniment le test.
    """
    for button in _widgets_by_class(root, "TButton"):
        if button.cget("text") == "Parcourir…" and int(button.grid_info().get("row", -1)) == 2:
            return button
    raise AssertionError("bouton Parcourir... du DOCX introuvable a la ligne 2")


def _find_label_texts(root) -> list[str]:
    return [label.cget("text") for label in _widgets_by_class(root, "TLabel")]


def test_choosing_docx_without_json_injects_conventional_path_without_creating_file(
    tk_root, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from chaine_editoriale import interface_publication as ip
    from chaine_editoriale import metadata_editor_adapter

    docx_path = tmp_path / "chapitre.docx"
    docx_path.write_bytes(b"fake")
    conventional_json = tmp_path / "chapitre.metadata.json"

    monkeypatch.setattr(metadata_editor_adapter, "conventional_metadata_path", lambda docx: conventional_json)
    monkeypatch.setattr("tkinter.filedialog.askopenfilename", lambda **kwargs: str(docx_path))

    root = tk_root
    for child in list(root.winfo_children()):
        child.destroy()
    controller = ip.PublicationScreenController()
    gui._build_publication_screen(root, controller, lambda: None)
    root.update()

    docx_browse_button = _find_docx_browse_button(root)
    docx_browse_button.invoke()
    root.update()

    entries = _widgets_by_class(root, "TEntry")
    assert entries[1].get() == str(conventional_json)
    assert not conventional_json.exists()
    assert _find_button(root, "Créer les métadonnées…") is not None
    assert any("à créer" in text for text in _find_label_texts(root))


def test_choosing_docx_with_existing_json_shows_modify_button(
    tk_root, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from chaine_editoriale import interface_publication as ip
    from chaine_editoriale import metadata_editor_adapter

    docx_path = tmp_path / "chapitre.docx"
    docx_path.write_bytes(b"fake")
    conventional_json = tmp_path / "chapitre.metadata.json"
    conventional_json.write_text("{}", encoding="utf-8")

    monkeypatch.setattr(metadata_editor_adapter, "conventional_metadata_path", lambda docx: conventional_json)
    monkeypatch.setattr("tkinter.filedialog.askopenfilename", lambda **kwargs: str(docx_path))

    root = tk_root
    for child in list(root.winfo_children()):
        child.destroy()
    controller = ip.PublicationScreenController()
    gui._build_publication_screen(root, controller, lambda: None)
    root.update()

    docx_browse_button = _find_docx_browse_button(root)
    docx_browse_button.invoke()
    root.update()

    entries = _widgets_by_class(root, "TEntry")
    assert entries[1].get() == str(conventional_json)
    assert _find_button(root, "Modifier les métadonnées…") is not None
    assert any("trouvé" in text for text in _find_label_texts(root))


def test_edit_metadata_saved_result_updates_both_paths(
    tk_root, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from chaine_editoriale import interface_publication as ip
    from chaine_editoriale import metadata_editor_adapter

    docx_path = tmp_path / "chapitre.docx"
    docx_path.write_bytes(b"fake")
    other_docx = tmp_path / "autre" / "relocalise.docx"
    other_docx.parent.mkdir()
    other_docx.write_bytes(b"fake")
    other_json = tmp_path / "autre" / "relocalise.metadata.json"
    other_json.write_text("{}", encoding="utf-8")

    outcome = metadata_editor_adapter.MetadataEditorOutcome(status="saved", docx_path=other_docx, metadata_path=other_json)
    monkeypatch.setattr(metadata_editor_adapter, "edit_metadata", lambda parent, docx, metadata: outcome)

    root = tk_root
    for child in list(root.winfo_children()):
        child.destroy()
    controller = ip.PublicationScreenController()
    controller.form_state.docx_path = str(docx_path)
    controller.form_state.metadata_path = ""
    gui._build_publication_screen(root, controller, lambda: None)
    root.update()

    edit_button = _find_button(root, "Créer les métadonnées…")
    edit_button.invoke()
    root.update()

    entries = _widgets_by_class(root, "TEntry")
    assert entries[0].get() == str(other_docx)
    assert entries[1].get() == str(other_json)
    assert _find_button(root, "Modifier les métadonnées…") is not None
    assert controller.form_state.metadata_path_is_automatic is False


def test_edit_metadata_cancelled_result_keeps_form_and_shows_no_error(
    tk_root, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from tkinter import messagebox

    from chaine_editoriale import interface_publication as ip
    from chaine_editoriale import metadata_editor_adapter

    docx_path = tmp_path / "chapitre.docx"
    docx_path.write_bytes(b"fake")
    json_path = tmp_path / "chapitre.metadata.json"

    outcome = metadata_editor_adapter.MetadataEditorOutcome(status="cancelled", docx_path=docx_path, metadata_path=None)
    monkeypatch.setattr(metadata_editor_adapter, "edit_metadata", lambda parent, docx, metadata: outcome)
    error_calls: list[tuple] = []
    monkeypatch.setattr(messagebox, "showerror", lambda *args, **kwargs: error_calls.append(args))

    root = tk_root
    for child in list(root.winfo_children()):
        child.destroy()
    controller = ip.PublicationScreenController()
    controller.form_state.docx_path = str(docx_path)
    controller.form_state.metadata_path = str(json_path)
    gui._build_publication_screen(root, controller, lambda: None)
    root.update()

    edit_button = _find_button(root, "Créer les métadonnées…")
    edit_button.invoke()
    root.update()

    assert error_calls == []
    entries = _widgets_by_class(root, "TEntry")
    assert entries[0].get() == str(docx_path)
    assert entries[1].get() == str(json_path)


def test_choose_other_json_updates_field_without_opening_editor(
    tk_root, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from chaine_editoriale import interface_publication as ip
    from chaine_editoriale import metadata_editor_adapter

    docx_path = tmp_path / "chapitre.docx"
    docx_path.write_bytes(b"fake")
    other_json = tmp_path / "ailleurs.metadata.json"
    other_json.write_text("{}", encoding="utf-8")

    edit_calls: list[object] = []
    monkeypatch.setattr(
        metadata_editor_adapter, "edit_metadata", lambda parent, docx, metadata: edit_calls.append(1) or None
    )
    monkeypatch.setattr("tkinter.filedialog.askopenfilename", lambda **kwargs: str(other_json))

    root = tk_root
    for child in list(root.winfo_children()):
        child.destroy()
    controller = ip.PublicationScreenController()
    controller.form_state.docx_path = str(docx_path)
    controller.form_state.metadata_path = ""
    gui._build_publication_screen(root, controller, lambda: None)
    root.update()

    choose_button = _find_button(root, "Choisir un autre JSON…")
    choose_button.invoke()
    root.update()

    entries = _widgets_by_class(root, "TEntry")
    assert entries[1].get() == str(other_json)
    assert edit_calls == []
    assert _find_button(root, "Modifier les métadonnées…") is not None


def test_metadata_buttons_disabled_while_busy_and_reenabled_after(
    tk_root, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import time

    from tkinter import messagebox

    from chaine_editoriale import interface_publication as ip

    output_dir = tmp_path / "output"
    output_dir.mkdir()
    fake_result = _fake_publication_result(tmp_path, output_dir)
    monkeypatch.setattr(ip, "run_publication_job", lambda request: ip.PublicationJobEvent(kind="success", result=fake_result))
    monkeypatch.setattr(messagebox, "askyesno", lambda *args, **kwargs: True)

    docx_path = tmp_path / "doc.docx"
    docx_path.write_bytes(b"fake")
    metadata_path = tmp_path / "doc.json"
    metadata_path.write_text("{}", encoding="utf-8")

    root = tk_root
    for child in list(root.winfo_children()):
        child.destroy()
    controller = ip.PublicationScreenController()
    # Le champ JSON est desormais readonly : un chemin explicite se prepare
    # sur form_state avant construction de l'ecran plutot que par insertion
    # directe dans le widget.
    controller.form_state.metadata_path = str(metadata_path)
    controller.form_state.metadata_path_is_automatic = False
    gui._build_publication_screen(root, controller, lambda: None)
    root.update()

    entries = _widgets_by_class(root, "TEntry")
    entries[0].insert(0, str(docx_path))
    entries[2].insert(0, str(tmp_path / "ws"))
    entries[3].insert(0, str(output_dir))
    root.update()

    publish_button = _find_button(root, "Publier")
    publish_button.invoke()
    root.update()

    # La synchronisation prealable a la publication rafraichit la
    # presentation : le JSON existant deja, le bouton affiche desormais
    # "Modifier..." (et non plus le "Creer..." initial d'un formulaire vide).
    edit_button = next(
        button
        for button in _widgets_by_class(root, "TButton")
        if button.cget("text") in ("Créer les métadonnées…", "Modifier les métadonnées…")
    )
    choose_button = _find_button(root, "Choisir un autre JSON…")
    assert str(edit_button.cget("state")) == "disabled"
    assert str(choose_button.cget("state")) == "disabled"

    deadline = time.time() + 5
    while controller.busy and time.time() < deadline:
        root.update()
        time.sleep(0.02)
    assert not controller.busy

    edit_button_after = _find_button(root, "Modifier les métadonnées…")
    choose_button_after = _find_button(root, "Choisir un autre JSON…")
    assert str(edit_button_after.cget("state")) == "normal"
    assert str(choose_button_after.cget("state")) == "normal"


def test_metadata_presentation_survives_screen_rebuild(tk_root, tmp_path: Path) -> None:
    from chaine_editoriale import interface_publication as ip

    docx_path = tmp_path / "chapitre.docx"
    docx_path.write_bytes(b"fake")
    json_path = tmp_path / "chapitre.metadata.json"
    json_path.write_text("{}", encoding="utf-8")

    root = tk_root
    for child in list(root.winfo_children()):
        child.destroy()
    controller = ip.PublicationScreenController()
    controller.form_state.docx_path = str(docx_path)
    controller.form_state.metadata_path = str(json_path)
    gui._build_publication_screen(root, controller, lambda: None)
    root.update()
    assert _find_button(root, "Modifier les métadonnées…") is not None

    for child in list(root.winfo_children()):
        child.destroy()
    gui._build_publication_screen(root, controller, lambda: None)
    root.update()
    assert _find_button(root, "Modifier les métadonnées…") is not None
    entries = _widgets_by_class(root, "TEntry")
    assert entries[0].get() == str(docx_path)
    assert entries[1].get() == str(json_path)


# ---------------------------------------------------------------------------
# Distinction JSON automatique / explicite (defaut 1)


def test_publish_recomputes_automatic_json_for_manually_changed_docx(
    tk_root, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Un DOCX modifie a la main (sans <FocusOut>) doit voir son JSON automatique recalcule avant publication."""
    import time
    from tkinter import messagebox

    from chaine_editoriale import interface_publication as ip
    from chaine_editoriale import metadata_editor_adapter

    docx1 = tmp_path / "livre1.docx"
    docx1.write_bytes(b"fake")
    metadata1 = tmp_path / "livre1.metadata.json"
    metadata1.write_text("{}", encoding="utf-8")
    docx2 = tmp_path / "livre2.docx"
    docx2.write_bytes(b"fake")
    metadata2 = tmp_path / "livre2.metadata.json"
    metadata2.write_text("{}", encoding="utf-8")

    output_dir = tmp_path / "output"
    output_dir.mkdir()
    fake_result = _fake_publication_result(tmp_path, output_dir)

    def _fake_conventional(docx_path: Path) -> Path:
        return docx_path.with_name(docx_path.stem + ".metadata.json")

    monkeypatch.setattr(metadata_editor_adapter, "conventional_metadata_path", _fake_conventional)

    captured_requests: list[ip.PublicationRequest] = []

    def _fake_run_publication_job(request):
        captured_requests.append(request)
        return ip.PublicationJobEvent(kind="success", result=fake_result)

    monkeypatch.setattr(ip, "run_publication_job", _fake_run_publication_job)
    monkeypatch.setattr(messagebox, "askyesno", lambda *args, **kwargs: True)

    root = tk_root
    for child in list(root.winfo_children()):
        child.destroy()
    controller = ip.PublicationScreenController()
    controller.form_state.docx_path = str(docx1)
    controller.form_state.metadata_path = str(metadata1)
    controller.form_state.workspace_dir = str(tmp_path / "ws")
    controller.form_state.output_dir = str(output_dir)
    controller.form_state.metadata_path_is_automatic = True
    gui._build_publication_screen(root, controller, lambda: None)
    root.update()

    entries = _widgets_by_class(root, "TEntry")
    entries[0].delete(0, "end")
    entries[0].insert(0, str(docx2))
    root.update()

    publish_button = _find_button(root, "Publier")
    publish_button.invoke()
    root.update()

    deadline = time.time() + 5
    while controller.busy and time.time() < deadline:
        root.update()
        time.sleep(0.02)
    assert not controller.busy

    assert len(captured_requests) == 1
    assert captured_requests[0].docx_path == docx2
    assert captured_requests[0].metadata_path == metadata2
    assert captured_requests[0].metadata_path != metadata1


def test_publish_preserves_explicit_json_after_manual_docx_change(
    tk_root, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Un JSON choisi explicitement ne doit jamais etre ecrase par un changement ulterieur de DOCX."""
    import time
    from tkinter import messagebox

    from chaine_editoriale import interface_publication as ip
    from chaine_editoriale import metadata_editor_adapter

    docx1 = tmp_path / "livre1.docx"
    docx1.write_bytes(b"fake")
    docx2 = tmp_path / "livre2.docx"
    docx2.write_bytes(b"fake")
    explicit_json = tmp_path / "ailleurs" / "explicit.metadata.json"
    explicit_json.parent.mkdir()
    explicit_json.write_text("{}", encoding="utf-8")

    conventional_calls: list[Path] = []

    def _fake_conventional(docx_path: Path) -> Path:
        conventional_calls.append(docx_path)
        return docx_path.with_name(docx_path.stem + ".metadata.json")

    monkeypatch.setattr(metadata_editor_adapter, "conventional_metadata_path", _fake_conventional)
    monkeypatch.setattr("tkinter.filedialog.askopenfilename", lambda **kwargs: str(docx1))

    output_dir = tmp_path / "output"
    output_dir.mkdir()
    fake_result = _fake_publication_result(tmp_path, output_dir)
    captured_requests: list[ip.PublicationRequest] = []

    def _fake_run_publication_job(request):
        captured_requests.append(request)
        return ip.PublicationJobEvent(kind="success", result=fake_result)

    monkeypatch.setattr(ip, "run_publication_job", _fake_run_publication_job)
    monkeypatch.setattr(messagebox, "askyesno", lambda *args, **kwargs: True)

    root = tk_root
    for child in list(root.winfo_children()):
        child.destroy()
    controller = ip.PublicationScreenController()
    gui._build_publication_screen(root, controller, lambda: None)
    root.update()

    docx_browse_button = _find_docx_browse_button(root)
    docx_browse_button.invoke()
    root.update()
    assert controller.form_state.metadata_path_is_automatic is True

    monkeypatch.setattr("tkinter.filedialog.askopenfilename", lambda **kwargs: str(explicit_json))
    choose_button = _find_button(root, "Choisir un autre JSON…")
    choose_button.invoke()
    root.update()
    assert controller.form_state.metadata_path_is_automatic is False

    entries = _widgets_by_class(root, "TEntry")
    entries[2].insert(0, str(tmp_path / "ws"))
    entries[3].insert(0, str(output_dir))
    entries[0].delete(0, "end")
    entries[0].insert(0, str(docx2))
    root.update()

    publish_button = _find_button(root, "Publier")
    publish_button.invoke()
    root.update()

    deadline = time.time() + 5
    while controller.busy and time.time() < deadline:
        root.update()
        time.sleep(0.02)
    assert not controller.busy

    assert len(captured_requests) == 1
    assert captured_requests[0].docx_path == docx2
    assert captured_requests[0].metadata_path == explicit_json
    assert docx2 not in conventional_calls


def test_metadata_path_is_automatic_flag_survives_rebuild(tk_root, tmp_path: Path) -> None:
    from chaine_editoriale import interface_publication as ip

    root = tk_root
    for child in list(root.winfo_children()):
        child.destroy()
    controller = ip.PublicationScreenController()
    controller.form_state.metadata_path_is_automatic = False
    gui._build_publication_screen(root, controller, lambda: None)
    root.update()
    assert controller.form_state.metadata_path_is_automatic is False

    for child in list(root.winfo_children()):
        child.destroy()
    gui._build_publication_screen(root, controller, lambda: None)
    root.update()
    assert controller.form_state.metadata_path_is_automatic is False


# ---------------------------------------------------------------------------
# Champ JSON en lecture seule (defaut 1)


def test_metadata_entry_is_readonly_at_startup(tk_root) -> None:
    from chaine_editoriale import interface_publication as ip

    root = tk_root
    for child in list(root.winfo_children()):
        child.destroy()
    controller = ip.PublicationScreenController()
    gui._build_publication_screen(root, controller, lambda: None)
    root.update()

    entries = _widgets_by_class(root, "TEntry")
    assert str(entries[1].cget("state")) == "readonly"


def test_metadata_entry_disabled_during_publication(
    tk_root, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import time
    from tkinter import messagebox

    from chaine_editoriale import interface_publication as ip

    docx_path = tmp_path / "doc.docx"
    docx_path.write_bytes(b"fake")
    metadata_path = tmp_path / "doc.json"
    metadata_path.write_text("{}", encoding="utf-8")
    output_dir = tmp_path / "output"
    output_dir.mkdir()
    fake_result = _fake_publication_result(tmp_path, output_dir)
    monkeypatch.setattr(ip, "run_publication_job", lambda request: ip.PublicationJobEvent(kind="success", result=fake_result))
    monkeypatch.setattr(messagebox, "askyesno", lambda *args, **kwargs: True)

    root = tk_root
    for child in list(root.winfo_children()):
        child.destroy()
    controller = ip.PublicationScreenController()
    controller.form_state.metadata_path = str(metadata_path)
    controller.form_state.metadata_path_is_automatic = False
    gui._build_publication_screen(root, controller, lambda: None)
    root.update()

    entries = _widgets_by_class(root, "TEntry")
    entries[0].insert(0, str(docx_path))
    entries[2].insert(0, str(tmp_path / "ws"))
    entries[3].insert(0, str(output_dir))
    root.update()

    publish_button = _find_button(root, "Publier")
    publish_button.invoke()
    root.update()

    assert str(entries[1].cget("state")) == "disabled"

    deadline = time.time() + 5
    while controller.busy and time.time() < deadline:
        root.update()
        time.sleep(0.02)
    assert not controller.busy


def test_metadata_entry_readonly_after_publication_completes(
    tk_root, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Ni "normal" ni "disabled" ne doivent subsister apres le retour a l'etat disponible."""
    import time
    from tkinter import messagebox

    from chaine_editoriale import interface_publication as ip

    docx_path = tmp_path / "doc.docx"
    docx_path.write_bytes(b"fake")
    metadata_path = tmp_path / "doc.json"
    metadata_path.write_text("{}", encoding="utf-8")
    output_dir = tmp_path / "output"
    output_dir.mkdir()
    fake_result = _fake_publication_result(tmp_path, output_dir)
    monkeypatch.setattr(ip, "run_publication_job", lambda request: ip.PublicationJobEvent(kind="success", result=fake_result))
    monkeypatch.setattr(messagebox, "askyesno", lambda *args, **kwargs: True)

    root = tk_root
    for child in list(root.winfo_children()):
        child.destroy()
    controller = ip.PublicationScreenController()
    controller.form_state.metadata_path = str(metadata_path)
    controller.form_state.metadata_path_is_automatic = False
    gui._build_publication_screen(root, controller, lambda: None)
    root.update()

    entries = _widgets_by_class(root, "TEntry")
    entries[0].insert(0, str(docx_path))
    entries[2].insert(0, str(tmp_path / "ws"))
    entries[3].insert(0, str(output_dir))
    root.update()

    publish_button = _find_button(root, "Publier")
    publish_button.invoke()
    root.update()

    deadline = time.time() + 5
    while controller.busy and time.time() < deadline:
        root.update()
        time.sleep(0.02)
    assert not controller.busy

    entries_after = _widgets_by_class(root, "TEntry")
    state_after = str(entries_after[1].cget("state"))
    assert state_after == "readonly"
    assert state_after not in ("normal", "disabled")


# ---------------------------------------------------------------------------
# Effacement de l'ancien JSON automatique avant recalcul (defaut 2)


def test_synchronize_clears_old_automatic_json_when_conventional_computation_fails(
    tk_root, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from chaine_editoriale import interface_publication as ip
    from chaine_editoriale import metadata_editor_adapter
    from chaine_editoriale.erreurs import MetadataEditorIntegrationError

    docx1 = tmp_path / "livre1.docx"
    docx1.write_bytes(b"fake")
    metadata1 = tmp_path / "livre1.metadata.json"
    metadata1.write_text("{}", encoding="utf-8")
    docx2 = tmp_path / "livre2.docx"
    docx2.write_bytes(b"fake")

    def _failing_conventional(docx_path: Path) -> Path:
        raise MetadataEditorIntegrationError("Mini-Metopes indisponible (simule)")

    monkeypatch.setattr(metadata_editor_adapter, "conventional_metadata_path", _failing_conventional)

    root = tk_root
    for child in list(root.winfo_children()):
        child.destroy()
    controller = ip.PublicationScreenController()
    controller.form_state.docx_path = str(docx1)
    controller.form_state.metadata_path = str(metadata1)
    controller.form_state.metadata_path_is_automatic = True
    gui._build_publication_screen(root, controller, lambda: None)
    root.update()

    entries = _widgets_by_class(root, "TEntry")
    entries[0].delete(0, "end")
    entries[0].insert(0, str(docx2))
    entries[0].event_generate("<FocusOut>")
    root.update()

    assert entries[1].get() == ""
    assert entries[1].get() != str(metadata1)


def test_synchronize_clears_automatic_json_for_invalid_docx(
    tk_root, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from chaine_editoriale import interface_publication as ip

    docx1 = tmp_path / "livre1.docx"
    docx1.write_bytes(b"fake")
    metadata1 = tmp_path / "livre1.metadata.json"
    metadata1.write_text("{}", encoding="utf-8")

    invalid_docx_value = str(tmp_path / "absent.docx")

    root = tk_root
    for child in list(root.winfo_children()):
        child.destroy()
    controller = ip.PublicationScreenController()
    controller.form_state.docx_path = str(docx1)
    controller.form_state.metadata_path = str(metadata1)
    controller.form_state.metadata_path_is_automatic = True
    gui._build_publication_screen(root, controller, lambda: None)
    root.update()

    entries = _widgets_by_class(root, "TEntry")
    entries[0].delete(0, "end")
    entries[0].insert(0, invalid_docx_value)
    entries[0].event_generate("<FocusOut>")
    root.update()

    assert entries[1].get() == ""


def test_synchronize_preserves_explicit_json_and_never_calls_conventional_path(
    tk_root, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from chaine_editoriale import interface_publication as ip
    from chaine_editoriale import metadata_editor_adapter
    from chaine_editoriale.erreurs import MetadataEditorIntegrationError

    docx1 = tmp_path / "livre1.docx"
    docx1.write_bytes(b"fake")
    docx2 = tmp_path / "livre2.docx"
    docx2.write_bytes(b"fake")
    explicit_json = tmp_path / "ailleurs" / "explicit.metadata.json"
    explicit_json.parent.mkdir()
    explicit_json.write_text("{}", encoding="utf-8")

    calls: list[Path] = []

    def _failing_conventional(docx_path: Path) -> Path:
        calls.append(docx_path)
        raise MetadataEditorIntegrationError("ne devrait jamais etre appelee")

    monkeypatch.setattr(metadata_editor_adapter, "conventional_metadata_path", _failing_conventional)

    root = tk_root
    for child in list(root.winfo_children()):
        child.destroy()
    controller = ip.PublicationScreenController()
    controller.form_state.docx_path = str(docx1)
    controller.form_state.metadata_path = str(explicit_json)
    controller.form_state.metadata_path_is_automatic = False
    gui._build_publication_screen(root, controller, lambda: None)
    root.update()

    entries = _widgets_by_class(root, "TEntry")
    entries[0].delete(0, "end")
    entries[0].insert(0, str(docx2))
    entries[0].event_generate("<FocusOut>")
    root.update()

    assert calls == []
    assert entries[1].get() == str(explicit_json)


# ---------------------------------------------------------------------------
# Reconstruction : le champ reste readonly (defaut 1)


def test_metadata_entry_stays_readonly_after_rebuild(tk_root, tmp_path: Path) -> None:
    from chaine_editoriale import interface_publication as ip

    json_path = tmp_path / "chapitre.metadata.json"
    json_path.write_text("{}", encoding="utf-8")

    root = tk_root
    for child in list(root.winfo_children()):
        child.destroy()
    controller = ip.PublicationScreenController()
    controller.form_state.metadata_path = str(json_path)
    controller.form_state.metadata_path_is_automatic = False
    gui._build_publication_screen(root, controller, lambda: None)
    root.update()
    assert controller.form_state.metadata_path_is_automatic is False

    for child in list(root.winfo_children()):
        child.destroy()
    gui._build_publication_screen(root, controller, lambda: None)
    root.update()

    assert controller.form_state.metadata_path_is_automatic is False
    entries = _widgets_by_class(root, "TEntry")
    assert str(entries[1].cget("state")) == "readonly"
    assert entries[1].get() == str(json_path)


# ---------------------------------------------------------------------------
# Boutons de metadonnees desactives pour un DOCX invalide (defaut 2)


def _make_directory(path: Path) -> Path:
    path.mkdir()
    return path


def _make_text_file(path: Path) -> Path:
    path.write_text("x", encoding="utf-8")
    return path


@pytest.mark.parametrize(
    "make_docx",
    [
        lambda tmp_path: str(tmp_path / "absent.docx"),
        lambda tmp_path: str(_make_directory(tmp_path / "un-dossier")),
        lambda tmp_path: str(_make_text_file(tmp_path / "livre.txt")),
    ],
    ids=["nonexistent", "directory", "wrong_extension"],
)
def test_metadata_buttons_disabled_for_invalid_docx(tk_root, tmp_path: Path, make_docx) -> None:
    from chaine_editoriale import interface_publication as ip

    docx_value = make_docx(tmp_path)

    root = tk_root
    for child in list(root.winfo_children()):
        child.destroy()
    controller = ip.PublicationScreenController()
    controller.form_state.docx_path = docx_value
    gui._build_publication_screen(root, controller, lambda: None)
    root.update()

    edit_button = next(
        button
        for button in _widgets_by_class(root, "TButton")
        if button.cget("text") in ("Créer les métadonnées…", "Modifier les métadonnées…")
    )
    choose_button = _find_button(root, "Choisir un autre JSON…")
    assert str(edit_button.cget("state")) == "disabled"
    assert str(choose_button.cget("state")) == "disabled"


def test_metadata_buttons_enabled_for_valid_docx(tk_root, tmp_path: Path) -> None:
    from chaine_editoriale import interface_publication as ip

    docx = tmp_path / "chapitre.docx"
    docx.write_bytes(b"fake")

    root = tk_root
    for child in list(root.winfo_children()):
        child.destroy()
    controller = ip.PublicationScreenController()
    controller.form_state.docx_path = str(docx)
    gui._build_publication_screen(root, controller, lambda: None)
    root.update()

    edit_button = _find_button(root, "Créer les métadonnées…")
    choose_button = _find_button(root, "Choisir un autre JSON…")
    assert str(edit_button.cget("state")) == "normal"
    assert str(choose_button.cget("state")) == "normal"


def _fake_publication_result(tmp_path: Path, output_dir: Path):
    from dataclasses import dataclass

    from chaine_editoriale.modeles import PublicationResult

    @dataclass
    class _FakeBuildResult:
        output_dir: Path
        html_path: Path
        normalized_tei_path: Path | None
        report_path: Path

    html_path = output_dir / "index.html"
    html_path.write_text("<html></html>", encoding="utf-8")
    normalized_tei_path = output_dir / "book.normalized.xml"
    normalized_tei_path.write_text("<TEI/>", encoding="utf-8")
    report_path = output_dir / "build_report.txt"
    report_path.write_text("rapport", encoding="utf-8")
    xml_path = tmp_path / "ws" / "source" / "document.xml"
    xml_path.parent.mkdir(parents=True, exist_ok=True)
    xml_path.write_text("<TEI/>", encoding="utf-8")
    latei_path = output_dir / "assets" / "generated" / "book.tex"
    latei_path.parent.mkdir(parents=True, exist_ok=True)
    latei_path.write_text("% latei", encoding="utf-8")
    manifest_path = tmp_path / "ws" / "publication.json"
    manifest_path.write_text("{}", encoding="utf-8")

    return PublicationResult(
        xml_path=xml_path,
        media_directory=None,
        assets_root=None,
        site_result=_FakeBuildResult(output_dir, html_path, normalized_tei_path, report_path),
        latei_path=latei_path,
        pdf_path=None,
        pdf_status="not_requested",
        manifest_path=manifest_path,
        conversion_diagnostics=(),
    )
