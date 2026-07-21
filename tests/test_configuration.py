from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

from chaine_editoriale import configuration as cfg
from chaine_editoriale.erreurs import ConfigurationError


# ---------------------------------------------------------------------------
# Lecture / ecriture de config_chaine.json


def test_load_config_absent(tmp_path: Path) -> None:
    result = cfg.load_config(tmp_path / "nope.json")
    assert result.config is None
    assert not result.valid
    assert result.issues[0].code == "config_missing"


def test_load_config_valid(tmp_path: Path, write_config_file) -> None:
    path = tmp_path / "config_chaine.json"
    write_config_file(
        path,
        {
            "schema": "chaine-editoriale-config",
            "schema_version": 1,
            "mini_metopes_path": r"C:\minimetopes",
            "purh_site_path": r"C:\impression2",
            "last_verified": "2026-07-21",
        },
    )
    result = cfg.load_config(path)
    assert result.valid
    assert result.config == cfg.ChaineConfig(
        mini_metopes_path=Path(r"C:\minimetopes"),
        purh_site_path=Path(r"C:\impression2"),
        last_verified="2026-07-21",
    )


def test_load_config_invalid_json(tmp_path: Path) -> None:
    path = tmp_path / "config_chaine.json"
    path.write_text("{not json", encoding="utf-8")
    result = cfg.load_config(path)
    assert result.config is None
    assert result.issues[0].code == "config_invalid_json"


def test_load_config_invalid_root(tmp_path: Path) -> None:
    path = tmp_path / "config_chaine.json"
    path.write_text("[1, 2, 3]", encoding="utf-8")
    result = cfg.load_config(path)
    assert result.config is None
    assert result.issues[0].code == "config_invalid_root"


def test_load_config_missing_field(tmp_path: Path, write_config_file) -> None:
    path = tmp_path / "config_chaine.json"
    write_config_file(path, {"schema": "chaine-editoriale-config", "schema_version": 1, "mini_metopes_path": "C:/x"})
    result = cfg.load_config(path)
    assert result.config is None
    assert any(issue.code == "config_missing_field" and issue.path == "purh_site_path" for issue in result.issues)


def test_load_config_invalid_field_type(tmp_path: Path, write_config_file) -> None:
    path = tmp_path / "config_chaine.json"
    write_config_file(
        path,
        {
            "schema": "chaine-editoriale-config",
            "schema_version": 1,
            "mini_metopes_path": 123,
            "purh_site_path": "C:/y",
        },
    )
    result = cfg.load_config(path)
    assert result.config is None
    assert any(issue.code == "config_invalid_field_type" for issue in result.issues)


def test_load_config_unknown_schema(tmp_path: Path, write_config_file) -> None:
    path = tmp_path / "config_chaine.json"
    write_config_file(
        path,
        {"schema": "autre-chose", "schema_version": 1, "mini_metopes_path": "C:/x", "purh_site_path": "C:/y"},
    )
    result = cfg.load_config(path)
    assert result.config is None
    assert any(issue.code == "config_unknown_schema" for issue in result.issues)


def test_load_config_unknown_schema_version(tmp_path: Path, write_config_file) -> None:
    path = tmp_path / "config_chaine.json"
    write_config_file(
        path,
        {
            "schema": "chaine-editoriale-config",
            "schema_version": 99,
            "mini_metopes_path": "C:/x",
            "purh_site_path": "C:/y",
        },
    )
    result = cfg.load_config(path)
    assert result.config is None
    assert any(issue.code == "config_unknown_schema_version" for issue in result.issues)


def test_write_config_atomic_and_deterministic(tmp_path: Path) -> None:
    path = tmp_path / "sub" / "config_chaine.json"
    config = cfg.ChaineConfig(mini_metopes_path=Path("C:/a"), purh_site_path=Path("C:/b"), last_verified="2026-07-21")
    written_path = cfg.write_config(config, path)
    assert written_path == path
    first_text = path.read_text(encoding="utf-8")
    cfg.write_config(config, path)
    second_text = path.read_text(encoding="utf-8")
    assert first_text == second_text
    assert list(path.parent.glob(".*")) == []  # aucun fichier temporaire residuel


def test_write_config_does_not_overwrite_on_failure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = tmp_path / "config_chaine.json"
    original = cfg.ChaineConfig(mini_metopes_path=Path("C:/a"), purh_site_path=Path("C:/b"))
    cfg.write_config(original, path)
    original_text = path.read_text(encoding="utf-8")

    def failing_replace(*_args: object, **_kwargs: object) -> None:
        raise OSError("simulated failure")

    monkeypatch.setattr(cfg.os, "replace", failing_replace)
    broken = cfg.ChaineConfig(mini_metopes_path=Path("C:/z"), purh_site_path=Path("C:/z"))
    with pytest.raises(ConfigurationError):
        cfg.write_config(broken, path)
    assert path.read_text(encoding="utf-8") == original_text


# ---------------------------------------------------------------------------
# Verification structurelle des depots


def test_verify_repository_missing_directory(tmp_path: Path) -> None:
    config = cfg.ChaineConfig(mini_metopes_path=tmp_path / "absent", purh_site_path=tmp_path / "absent2")
    verification = cfg.verify_config(config)
    assert not verification.mini_metopes.success
    assert not verification.purh_site.success


def test_verify_repository_not_a_directory(tmp_path: Path) -> None:
    file_path = tmp_path / "not_a_dir.txt"
    file_path.write_text("x", encoding="utf-8")
    config = cfg.ChaineConfig(mini_metopes_path=file_path, purh_site_path=file_path)
    verification = cfg.verify_config(config)
    assert not verification.mini_metopes.success
    assert "dossier" in verification.mini_metopes.message


def test_verify_repository_package_absent(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "pyproject.toml").write_text("[project]\nname='x'\n", encoding="utf-8")
    config = cfg.ChaineConfig(mini_metopes_path=repo, purh_site_path=repo)
    verification = cfg.verify_config(config)
    assert not verification.mini_metopes.success
    assert verification.mini_metopes.import_root is None


def test_detect_import_root_src_layout(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    (repo / "src" / "mini_metopes").mkdir(parents=True)
    (repo / "src" / "mini_metopes" / "__init__.py").write_text("", encoding="utf-8")
    root = cfg._detect_import_root(repo, "mini_metopes")
    assert root == repo / "src"


def test_detect_import_root_flat_layout(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    (repo / "purh_site").mkdir(parents=True)
    (repo / "purh_site" / "__init__.py").write_text("", encoding="utf-8")
    root = cfg._detect_import_root(repo, "purh_site")
    assert root == repo


def test_detect_import_root_rejects_lookalike_folder(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    (repo / "mini_metopes_old").mkdir(parents=True)
    root = cfg._detect_import_root(repo, "mini_metopes")
    assert root is None


# ---------------------------------------------------------------------------
# Activation reelle (sys.path, importlib, sys.modules)


def test_activate_configured_dependencies_real_repos(real_repos: tuple[Path, Path]) -> None:
    mini_metopes_path, purh_site_path = real_repos
    config = cfg.ChaineConfig(mini_metopes_path=mini_metopes_path, purh_site_path=purh_site_path)
    verification = cfg.activate_configured_dependencies(config)
    assert verification.success, (verification.mini_metopes.message, verification.purh_site.message)
    assert verification.mini_metopes.module_path is not None
    assert verification.purh_site.module_path is not None


def test_activate_is_idempotent_and_deduplicates_sys_path(real_repos: tuple[Path, Path]) -> None:
    mini_metopes_path, purh_site_path = real_repos
    config = cfg.ChaineConfig(mini_metopes_path=mini_metopes_path, purh_site_path=purh_site_path)
    cfg.activate_configured_dependencies(config)
    before = list(sys.path)
    verification = cfg.activate_configured_dependencies(config)
    after = list(sys.path)
    assert verification.success
    assert before == after
    resolved_entries = [Path(entry).resolve() for entry in after if entry]
    mini_metopes_root = Path(mini_metopes_path, "src").resolve()
    purh_site_root = Path(purh_site_path).resolve()
    assert sum(1 for entry in resolved_entries if entry == mini_metopes_root) == 1
    assert sum(1 for entry in resolved_entries if entry == purh_site_root) == 1


# ---------------------------------------------------------------------------
# Priorite de la racine configuree dans sys.path (_prioritize_sys_path_entry)


@pytest.fixture
def restore_sys_path(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "path", list(sys.path))


def test_prioritize_sys_path_inserts_at_head(tmp_path: Path, restore_sys_path: None) -> None:
    target = tmp_path / "root"
    target.mkdir()
    sys.path[:] = [r"C:\autre", r"C:\encore-autre"]
    cfg._prioritize_sys_path_entry(target)
    assert sys.path[0] == str(target.resolve())


def test_prioritize_sys_path_moves_existing_entry_to_head(tmp_path: Path, restore_sys_path: None) -> None:
    target = tmp_path / "root"
    target.mkdir()
    sys.path[:] = [r"C:\autre", str(target), r"C:\encore-autre"]
    cfg._prioritize_sys_path_entry(target)
    assert sys.path == [str(target.resolve()), r"C:\autre", r"C:\encore-autre"]


def test_prioritize_sys_path_removes_equivalent_duplicates(tmp_path: Path, restore_sys_path: None) -> None:
    target = tmp_path / "root"
    target.mkdir()
    sys.path[:] = [str(target), r"C:\autre", str(target) + os.sep, r"C:\encore-autre"]
    cfg._prioritize_sys_path_entry(target)
    resolved_target = str(target.resolve())
    assert sys.path.count(resolved_target) == 1
    assert sys.path[0] == resolved_target


def test_prioritize_sys_path_stable_order_after_two_activations(tmp_path: Path, restore_sys_path: None) -> None:
    target = tmp_path / "root"
    target.mkdir()
    sys.path[:] = [r"C:\autre", r"C:\encore-autre"]
    cfg._prioritize_sys_path_entry(target)
    first = list(sys.path)
    cfg._prioritize_sys_path_entry(target)
    second = list(sys.path)
    assert first == second


def test_prioritize_sys_path_does_not_grow_on_repeated_activation(tmp_path: Path, restore_sys_path: None) -> None:
    target = tmp_path / "root"
    target.mkdir()
    sys.path[:] = [r"C:\autre"]
    length_before = len(sys.path)
    cfg._prioritize_sys_path_entry(target)
    cfg._prioritize_sys_path_entry(target)
    cfg._prioritize_sys_path_entry(target)
    assert len(sys.path) == length_before + 1


def test_prioritize_sys_path_robust_to_unresolvable_entries(tmp_path: Path, restore_sys_path: None) -> None:
    target = tmp_path / "root"
    target.mkdir()
    sys.path[:] = ["", r"C:\autre", "\x00invalid"]
    cfg._prioritize_sys_path_entry(target)
    assert sys.path[0] == str(target.resolve())


# ---------------------------------------------------------------------------
# Modele d'etat des dependances (success / restart_required / error)


def _check(state: cfg.DependencyState, name: str = "mini_metopes") -> cfg.DependencyCheck:
    return cfg.DependencyCheck(name, Path("C:/repo"), Path("C:/repo/src"), Path("C:/repo/src/pkg/__init__.py"), state, "message")


def test_dependency_verification_both_success() -> None:
    verification = cfg.DependencyVerification(_check("success", "mini_metopes"), _check("success", "purh_site"))
    assert verification.success
    assert verification.can_be_saved
    assert not verification.restart_required


def test_dependency_verification_one_restart_required() -> None:
    verification = cfg.DependencyVerification(_check("restart_required", "mini_metopes"), _check("success", "purh_site"))
    assert not verification.success
    assert verification.can_be_saved
    assert verification.restart_required


def test_dependency_verification_both_restart_required() -> None:
    verification = cfg.DependencyVerification(_check("restart_required", "mini_metopes"), _check("restart_required", "purh_site"))
    assert not verification.success
    assert verification.can_be_saved
    assert verification.restart_required


def test_dependency_verification_one_error_blocks_save() -> None:
    verification = cfg.DependencyVerification(_check("error", "mini_metopes"), _check("success", "purh_site"))
    assert not verification.success
    assert not verification.can_be_saved
    assert not verification.restart_required


def test_dependency_verification_error_with_restart_required_blocks_save() -> None:
    verification = cfg.DependencyVerification(_check("error", "mini_metopes"), _check("restart_required", "purh_site"))
    assert not verification.can_be_saved


def test_activate_detects_conflict_with_already_loaded_module(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, real_repos: tuple[Path, Path]) -> None:
    mini_metopes_path, purh_site_path = real_repos
    # Le vrai depot est deja importe (via l'installation editable du venv de test).
    other_repo = tmp_path / "other_mini_metopes"
    (other_repo / "mini_metopes").mkdir(parents=True)
    (other_repo / "mini_metopes" / "__init__.py").write_text("", encoding="utf-8")
    (other_repo / "pyproject.toml").write_text("[project]\nname='x'\n", encoding="utf-8")

    import mini_metopes  # garantir que le vrai module est deja charge

    config = cfg.ChaineConfig(mini_metopes_path=other_repo, purh_site_path=purh_site_path)
    verification = cfg.activate_configured_dependencies(config)
    assert not verification.mini_metopes.success
    assert verification.mini_metopes.state == "restart_required"
    assert verification.mini_metopes.restart_required
    assert verification.mini_metopes.can_be_saved
    assert not verification.success
    assert verification.can_be_saved
    assert verification.restart_required
    assert "redemarrez" in verification.mini_metopes.message.lower()


def test_activate_returns_structured_result_without_raw_import_error(tmp_path: Path) -> None:
    repo = tmp_path / "totally_empty"
    repo.mkdir()
    config = cfg.ChaineConfig(mini_metopes_path=repo, purh_site_path=repo)
    verification = cfg.activate_configured_dependencies(config)
    assert not verification.success
    assert isinstance(verification.mini_metopes.message, str)


def test_last_verified_only_meaningful_after_successful_activation(real_repos: tuple[Path, Path], tmp_path: Path) -> None:
    mini_metopes_path, purh_site_path = real_repos
    config = cfg.ChaineConfig(mini_metopes_path=mini_metopes_path, purh_site_path=purh_site_path)
    assert config.last_verified is None
    verification = cfg.activate_configured_dependencies(config)
    assert verification.success
    config_with_date = cfg.ChaineConfig(
        mini_metopes_path=mini_metopes_path,
        purh_site_path=purh_site_path,
        last_verified=cfg.today_iso(),
    )
    written = cfg.write_config(config_with_date, tmp_path / "config_chaine.json")
    reloaded = cfg.load_config(written)
    assert reloaded.config is not None
    assert reloaded.config.last_verified == cfg.today_iso()


def test_default_config_path_uses_appdata(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APPDATA", r"C:\Users\Someone\AppData\Roaming")
    path = cfg.default_config_path()
    assert path == Path(r"C:\Users\Someone\AppData\Roaming") / "ChaineEditoriale" / "config_chaine.json"
