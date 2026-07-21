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
