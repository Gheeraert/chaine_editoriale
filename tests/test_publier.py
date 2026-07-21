from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from chaine_editoriale import publier as publier_module
from chaine_editoriale.configuration import ChaineConfig, ConfigLoadResult, DependencyCheck, DependencyVerification
from chaine_editoriale.erreurs import (
    DependencyVerificationError,
    InvalidMetadataError,
    SiteBuildError,
    TeiConversionError,
    TeiWriteError,
)
from chaine_editoriale.modeles import PublicationOptions


def _successful_verification() -> DependencyVerification:
    check = lambda name: DependencyCheck(name, Path(f"C:/{name}"), Path(f"C:/{name}/src"), Path(f"C:/{name}/src/{name}/__init__.py"), True, "OK")
    return DependencyVerification(mini_metopes=check("mini_metopes"), purh_site=check("purh_site"))


@pytest.fixture(autouse=True)
def _stub_dependency_activation(monkeypatch: pytest.MonkeyPatch) -> None:
    """Par defaut, simuler une configuration deja activee avec succes."""
    monkeypatch.setattr(
        publier_module,
        "load_config",
        lambda: ConfigLoadResult(
            ChaineConfig(mini_metopes_path=Path("C:/mini_metopes"), purh_site_path=Path("C:/purh_site")),
            (),
            Path("C:/fake/config_chaine.json"),
        ),
    )
    monkeypatch.setattr(publier_module, "activate_configured_dependencies", lambda config: _successful_verification())


@dataclass
class _FakeMetadataResult:
    metadata: object | None
    issues: tuple[object, ...] = ()


@dataclass
class _FakeConversionResult:
    is_successful: bool
    diagnostics: tuple[object, ...] = ()
    validation_issues: tuple[object, ...] = ()


@dataclass
class _FakeWriteResult:
    media_directory: str | None = None


@dataclass
class _FakeBuildResult:
    output_dir: Path
    html_path: Path
    normalized_tei_path: Path | None
    report_path: Path


class _FakeSiteBuilder:
    def __init__(self, build_result: _FakeBuildResult, error: Exception | None = None) -> None:
        self._build_result = build_result
        self._error = error

    def build_from_master(self, xml_path: Path, config: Any) -> _FakeBuildResult:
        if self._error is not None:
            raise self._error
        self._build_result.output_dir.mkdir(parents=True, exist_ok=True)
        self._build_result.html_path.write_text("<html></html>", encoding="utf-8")
        self._build_result.report_path.write_text("rapport", encoding="utf-8")
        return self._build_result


def _install_fake_business_apis(
    monkeypatch: pytest.MonkeyPatch,
    *,
    metadata_result: _FakeMetadataResult,
    conversion_result: _FakeConversionResult | None = None,
    write_tei_side_effect: Exception | None = None,
    site_builder_factory=None,
) -> None:
    mini_metopes_api = publier_module._MiniMetopesApi(
        load_metadata_file=lambda path: metadata_result,
        convert_docx_to_tei=lambda path, metadata: conversion_result,
        write_tei_conversion_result=_make_write_tei(write_tei_side_effect),
        compute_file_sha256=lambda path: "0" * 64,
    )
    purh_site_api = publier_module._PurhSiteApi(
        BuildConfig=lambda **kwargs: kwargs,
        SiteBuilder=site_builder_factory or (lambda: _FakeSiteBuilder(_FakeBuildResult(Path("."), Path("."), None, Path(".")))),
    )
    monkeypatch.setattr(publier_module, "_charger_dependances_metier", lambda: (mini_metopes_api, purh_site_api))


def _make_write_tei(side_effect: Exception | None):
    def _write(conversion: Any, output_path: Path) -> _FakeWriteResult:
        if side_effect is not None:
            raise side_effect
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text("<TEI/>", encoding="utf-8")
        return _FakeWriteResult(media_directory=None)

    return _write


def test_publier_invalid_metadata_never_calls_purh_site(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, minimal_docx_path: Path) -> None:
    called = {"site_builder": False}

    class _ExplodingSiteBuilder:
        def build_from_master(self, *_args: object, **_kwargs: object) -> None:
            called["site_builder"] = True
            raise AssertionError("purh_site ne doit jamais etre appele")

    _install_fake_business_apis(
        monkeypatch,
        metadata_result=_FakeMetadataResult(metadata=None, issues=("bad-metadata",)),
        site_builder_factory=lambda: _ExplodingSiteBuilder(),
    )
    metadata_path = tmp_path / "meta.json"
    metadata_path.write_text("{}", encoding="utf-8")

    with pytest.raises(InvalidMetadataError):
        publier_module.publier(
            minimal_docx_path, metadata_path, tmp_path / "workspace", tmp_path / "output"
        )
    assert not called["site_builder"]


def test_publier_invalid_conversion_never_calls_purh_site(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, minimal_docx_path: Path) -> None:
    called = {"site_builder": False}

    class _ExplodingSiteBuilder:
        def build_from_master(self, *_args: object, **_kwargs: object) -> None:
            called["site_builder"] = True
            raise AssertionError("purh_site ne doit jamais etre appele")

    _install_fake_business_apis(
        monkeypatch,
        metadata_result=_FakeMetadataResult(metadata=object()),
        conversion_result=_FakeConversionResult(is_successful=False, diagnostics=("bad-conversion",)),
        site_builder_factory=lambda: _ExplodingSiteBuilder(),
    )
    metadata_path = tmp_path / "meta.json"
    metadata_path.write_text("{}", encoding="utf-8")

    with pytest.raises(TeiConversionError):
        publier_module.publier(
            minimal_docx_path, metadata_path, tmp_path / "workspace", tmp_path / "output"
        )
    assert not called["site_builder"]


def test_publier_tei_write_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, minimal_docx_path: Path) -> None:
    _install_fake_business_apis(
        monkeypatch,
        metadata_result=_FakeMetadataResult(metadata=object()),
        conversion_result=_FakeConversionResult(is_successful=True),
        write_tei_side_effect=ValueError("boom"),
    )
    metadata_path = tmp_path / "meta.json"
    metadata_path.write_text("{}", encoding="utf-8")

    with pytest.raises(TeiWriteError):
        publier_module.publier(
            minimal_docx_path, metadata_path, tmp_path / "workspace", tmp_path / "output"
        )


def test_publier_site_build_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, minimal_docx_path: Path) -> None:
    _install_fake_business_apis(
        monkeypatch,
        metadata_result=_FakeMetadataResult(metadata=object()),
        conversion_result=_FakeConversionResult(is_successful=True),
        site_builder_factory=lambda: _FakeSiteBuilder(
            _FakeBuildResult(Path("."), Path("."), None, Path(".")), error=RuntimeError("site cassE")
        ),
    )
    metadata_path = tmp_path / "meta.json"
    metadata_path.write_text("{}", encoding="utf-8")

    with pytest.raises(SiteBuildError):
        publier_module.publier(
            minimal_docx_path, metadata_path, tmp_path / "workspace", tmp_path / "output"
        )


def test_publier_preserves_media_level_and_detects_conflict(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, minimal_docx_path: Path) -> None:
    workspace = tmp_path / "workspace"
    output = tmp_path / "output"
    media_source = workspace / "source" / "media"
    media_source.mkdir(parents=True)
    (media_source / "abc.png").write_bytes(b"fake-png-bytes")

    def _write_tei(conversion: Any, output_path: Path) -> _FakeWriteResult:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text("<TEI/>", encoding="utf-8")
        return _FakeWriteResult(media_directory=str(media_source))

    build_result = _FakeBuildResult(output, output / "index.html", None, output / "build_report.txt")
    mini_metopes_api = publier_module._MiniMetopesApi(
        load_metadata_file=lambda path: _FakeMetadataResult(metadata=object()),
        convert_docx_to_tei=lambda path, metadata: _FakeConversionResult(is_successful=True),
        write_tei_conversion_result=_write_tei,
        compute_file_sha256=lambda path: "0" * 64,
    )
    captured_assets_dir: dict[str, Path] = {}

    def _build_config(**kwargs: object) -> dict:
        captured_assets_dir["assets_dir"] = kwargs["assets_dir"]
        return kwargs

    purh_site_api = publier_module._PurhSiteApi(BuildConfig=_build_config, SiteBuilder=lambda: _FakeSiteBuilder(build_result))
    monkeypatch.setattr(publier_module, "_charger_dependances_metier", lambda: (mini_metopes_api, purh_site_api))

    metadata_path = tmp_path / "meta.json"
    metadata_path.write_text("{}", encoding="utf-8")

    result = publier_module.publier(minimal_docx_path, metadata_path, workspace, output)

    assets_root = captured_assets_dir["assets_dir"]
    assert assets_root == workspace / "impressions-assets"
    assert (assets_root / "media" / "abc.png").read_bytes() == b"fake-png-bytes"
    assert result.assets_root == assets_root


def test_publier_media_conflict_raises(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, minimal_docx_path: Path) -> None:
    workspace = tmp_path / "workspace"
    output = tmp_path / "output"
    media_source = workspace / "source" / "media"
    media_source.mkdir(parents=True)
    (media_source / "abc.png").write_bytes(b"fake-png-bytes")

    existing = workspace / "impressions-assets" / "media"
    existing.mkdir(parents=True)
    (existing / "abc.png").write_bytes(b"different-bytes")

    def _write_tei(conversion: Any, output_path: Path) -> _FakeWriteResult:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text("<TEI/>", encoding="utf-8")
        return _FakeWriteResult(media_directory=str(media_source))

    mini_metopes_api = publier_module._MiniMetopesApi(
        load_metadata_file=lambda path: _FakeMetadataResult(metadata=object()),
        convert_docx_to_tei=lambda path, metadata: _FakeConversionResult(is_successful=True),
        write_tei_conversion_result=_write_tei,
        compute_file_sha256=lambda path: "0" * 64,
    )
    purh_site_api = publier_module._PurhSiteApi(
        BuildConfig=lambda **kwargs: kwargs,
        SiteBuilder=lambda: _FakeSiteBuilder(_FakeBuildResult(Path("."), Path("."), None, Path("."))),
    )
    monkeypatch.setattr(publier_module, "_charger_dependances_metier", lambda: (mini_metopes_api, purh_site_api))

    metadata_path = tmp_path / "meta.json"
    metadata_path.write_text("{}", encoding="utf-8")

    with pytest.raises(TeiWriteError):
        publier_module.publier(minimal_docx_path, metadata_path, workspace, output)


def test_publier_manifest_deterministic(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, minimal_docx_path: Path) -> None:
    workspace = tmp_path / "workspace"
    output = tmp_path / "output"
    build_result = _FakeBuildResult(output, output / "index.html", None, output / "build_report.txt")
    _install_fake_business_apis(
        monkeypatch,
        metadata_result=_FakeMetadataResult(metadata=object()),
        conversion_result=_FakeConversionResult(is_successful=True),
        site_builder_factory=lambda: _FakeSiteBuilder(build_result),
    )
    metadata_path = tmp_path / "meta.json"
    metadata_path.write_text("{}", encoding="utf-8")

    result = publier_module.publier(minimal_docx_path, metadata_path, workspace, output)
    first_text = result.manifest_path.read_text(encoding="utf-8")

    workspace2 = tmp_path / "workspace2"
    output2 = tmp_path / "output2"
    build_result2 = _FakeBuildResult(output2, output2 / "index.html", None, output2 / "build_report.txt")
    _install_fake_business_apis(
        monkeypatch,
        metadata_result=_FakeMetadataResult(metadata=object()),
        conversion_result=_FakeConversionResult(is_successful=True),
        site_builder_factory=lambda: _FakeSiteBuilder(build_result2),
    )
    result2 = publier_module.publier(minimal_docx_path, metadata_path, workspace2, output2)
    second_text = result2.manifest_path.read_text(encoding="utf-8")

    import json

    first_data = json.loads(first_text)
    second_data = json.loads(second_text)
    first_data["sources"]["docx"]["path"] = None
    second_data["sources"]["docx"]["path"] = None
    first_data["outputs"] = None
    second_data["outputs"] = None
    assert first_data == second_data


def test_publier_dependency_unavailable_raises_structured_error_not_import_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, minimal_docx_path: Path
) -> None:
    failing_check = DependencyCheck("mini_metopes", Path("C:/x"), None, None, False, "paquet introuvable")
    ok_check = DependencyCheck("purh_site", Path("C:/y"), Path("C:/y"), Path("C:/y/purh_site/__init__.py"), True, "OK")
    monkeypatch.setattr(
        publier_module, "activate_configured_dependencies", lambda config: DependencyVerification(failing_check, ok_check)
    )
    metadata_path = tmp_path / "meta.json"
    metadata_path.write_text("{}", encoding="utf-8")

    with pytest.raises(DependencyVerificationError):
        publier_module.publier(minimal_docx_path, metadata_path, tmp_path / "workspace", tmp_path / "output")


def test_publier_returns_well_formed_result(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, minimal_docx_path: Path) -> None:
    workspace = tmp_path / "workspace"
    output = tmp_path / "output"
    build_result = _FakeBuildResult(output, output / "index.html", None, output / "build_report.txt")
    _install_fake_business_apis(
        monkeypatch,
        metadata_result=_FakeMetadataResult(metadata=object()),
        conversion_result=_FakeConversionResult(is_successful=True, diagnostics=("info-diag",)),
        site_builder_factory=lambda: _FakeSiteBuilder(build_result),
    )
    metadata_path = tmp_path / "meta.json"
    metadata_path.write_text("{}", encoding="utf-8")

    result = publier_module.publier(
        minimal_docx_path, metadata_path, workspace, output, options=PublicationOptions(pdf_export_mode="none")
    )

    assert result.xml_path == workspace / "source" / "document.xml"
    assert result.media_directory is None
    assert result.assets_root is None
    assert result.site_result is build_result
    assert result.latei_path is None
    assert result.pdf_path is None
    assert result.pdf_status == "not_requested"
    assert result.manifest_path == workspace / "publication.json"
    assert result.conversion_diagnostics == ("info-diag",)
    assert result.manifest_path.exists()
