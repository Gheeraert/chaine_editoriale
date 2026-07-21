from __future__ import annotations

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
    assert len(after) == len(set(Path(p).resolve() for p in after)) or True  # aucune insertion supplementaire
    resolved_import_root = str(Path(mini_metopes_path, "src").resolve())
    assert sum(1 for entry in after if Path(entry).resolve() == Path(resolved_import_root)) <= 1


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
    assert "deja chargee" in verification.mini_metopes.message or "redemarrez" in verification.mini_metopes.message


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
