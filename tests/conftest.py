from __future__ import annotations

import json
from pathlib import Path

import pytest

FIXTURES_DIR = Path(__file__).parent / "fixtures"
REAL_MINI_METOPES_PATH = Path(r"C:\minimetopes")
REAL_PURH_SITE_PATH = Path(r"C:\impression2")


@pytest.fixture
def fixtures_dir() -> Path:
    return FIXTURES_DIR


@pytest.fixture
def minimal_docx_path() -> Path:
    return FIXTURES_DIR / "document_minimal.docx"


@pytest.fixture
def minimal_metadata_path() -> Path:
    return FIXTURES_DIR / "document_minimal.metadata.json"


@pytest.fixture
def real_repos() -> tuple[Path, Path]:
    if not REAL_MINI_METOPES_PATH.is_dir() or not REAL_PURH_SITE_PATH.is_dir():
        pytest.skip("depots reels mini_metopes/purh_site introuvables sur cette machine")
    return REAL_MINI_METOPES_PATH, REAL_PURH_SITE_PATH


@pytest.fixture
def tmp_config_path(tmp_path: Path) -> Path:
    return tmp_path / "config" / "config_chaine.json"


def write_raw_config(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


@pytest.fixture
def write_config_file():
    return write_raw_config


@pytest.fixture
def activated_config_path(tmp_config_path: Path, real_repos: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch) -> Path:
    """Ecrire une config_chaine.json valide pointant vers les vrais depots et l'activer par defaut."""
    mini_metopes_path, purh_site_path = real_repos
    write_raw_config(
        tmp_config_path,
        {
            "schema": "chaine-editoriale-config",
            "schema_version": 1,
            "mini_metopes_path": str(mini_metopes_path),
            "purh_site_path": str(purh_site_path),
            "last_verified": None,
        },
    )
    monkeypatch.setattr("chaine_editoriale.configuration.default_config_path", lambda: tmp_config_path)
    return tmp_config_path
