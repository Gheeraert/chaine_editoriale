from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from chaine_editoriale import publier as publier_module
from chaine_editoriale.configuration import ChaineConfig, ConfigLoadResult, DependencyCheck, DependencyVerification
from chaine_editoriale.erreurs import (
    AssetPreparationError,
    ChecksumError,
    DependencyVerificationError,
    InvalidMetadataError,
    ManifestWriteError,
    SiteBuildError,
    TeiConversionError,
    TeiWriteError,
)
from chaine_editoriale.modeles import PublicationOptions


def _successful_verification() -> DependencyVerification:
    check = lambda name: DependencyCheck(name, Path(f"C:/{name}"), Path(f"C:/{name}/src"), Path(f"C:/{name}/src/{name}/__init__.py"), "success", "OK")
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

    result = publier_module.publier(
        minimal_docx_path, metadata_path, workspace, output, options=PublicationOptions(pdf_export_mode="none")
    )

    assets_root = captured_assets_dir["assets_dir"]
    assert assets_root == workspace / "impressions-assets"
    assert (assets_root / "images" / "media" / "abc.png").read_bytes() == b"fake-png-bytes"
    assert result.assets_root == assets_root
    # pdf_export_mode="none" : la copie LaTEI vers output_dir/media/ n'est pas necessaire.
    assert not (output / "media").exists()


def test_prepare_media_layout_places_media_for_html_and_latei_separately(tmp_path: Path) -> None:
    """Protege les deux usages distincts et incompatibles decouverts pour Impressions.

    HTML lit ``assets_dir/images/media/`` (prefixe assets/images/ ajoute par
    tei_to_html.xsl) ; LaTEI/PDF lit ``output_dir/media/`` (resolution
    relative au fichier TEI source dans purh_site.latei_assets). Voir la
    docstring de ``prepare_media_layout_for_impressions``.
    """
    workspace = tmp_path / "workspace"
    output = tmp_path / "output"
    media_source = workspace / "source" / "media"
    media_source.mkdir(parents=True)
    (media_source / "abc.png").write_bytes(b"fake-png-bytes")

    assets_root, layout = publier_module.prepare_media_layout_for_impressions(
        media_source, workspace, output, pdf_export_requested=True
    )

    assert assets_root == workspace / "impressions-assets"
    html_media_dir = assets_root / "images" / "media"
    latei_media_dir = output / "media"
    assert html_media_dir.is_dir()
    assert latei_media_dir.is_dir()
    assert (html_media_dir / "abc.png").read_bytes() == b"fake-png-bytes"
    assert (latei_media_dir / "abc.png").read_bytes() == b"fake-png-bytes"
    # Le contrat HTML n'a jamais besoin d'un dossier "media" nu a la racine des assets.
    assert not (assets_root / "media").exists()

    assert layout == {
        "source_media_directory": media_source,
        "html_media_directory": html_media_dir,
        "latei_media_directory": latei_media_dir,
    }


def test_prepare_media_layout_skips_latei_copy_when_pdf_not_requested(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    output = tmp_path / "output"
    media_source = workspace / "source" / "media"
    media_source.mkdir(parents=True)
    (media_source / "abc.png").write_bytes(b"fake-png-bytes")

    assets_root, layout = publier_module.prepare_media_layout_for_impressions(
        media_source, workspace, output, pdf_export_requested=False
    )

    assert (assets_root / "images" / "media" / "abc.png").is_file()
    assert layout["latei_media_directory"] is None
    assert not output.exists()


def test_publier_media_conflict_raises(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, minimal_docx_path: Path) -> None:
    workspace = tmp_path / "workspace"
    output = tmp_path / "output"
    media_source = workspace / "source" / "media"
    media_source.mkdir(parents=True)
    (media_source / "abc.png").write_bytes(b"fake-png-bytes")

    existing = workspace / "impressions-assets" / "images" / "media"
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

    with pytest.raises(AssetPreparationError):
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
    failing_check = DependencyCheck("mini_metopes", Path("C:/x"), None, None, "error", "paquet introuvable")
    ok_check = DependencyCheck("purh_site", Path("C:/y"), Path("C:/y"), Path("C:/y/purh_site/__init__.py"), "success", "OK")
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


# ---------------------------------------------------------------------------
# pdf_status : "latei" ne doit jamais valoir "unavailable"


@pytest.mark.parametrize(
    ("pdf_export_mode", "pdf_path", "expected"),
    [
        ("none", None, "not_requested"),
        ("none", Path("C:/out/book.pdf"), "not_requested"),
        ("latei", None, "not_requested"),
        ("latei", Path("C:/out/book.pdf"), "not_requested"),
        ("latei_pdf", Path("C:/out/book.pdf"), "generated"),
        ("latei_pdf", None, "unavailable"),
    ],
)
def test_pdf_status_matrix(pdf_export_mode: str, pdf_path: Path | None, expected: str) -> None:
    assert publier_module._pdf_status(pdf_export_mode, pdf_path) == expected


def test_publier_latei_mode_detects_tex_without_pdf(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, minimal_docx_path: Path) -> None:
    workspace = tmp_path / "workspace"
    output = tmp_path / "output"
    build_result = _FakeBuildResult(output, output / "index.html", None, output / "build_report.txt")

    class _LateiOnlySiteBuilder(_FakeSiteBuilder):
        def build_from_master(self, xml_path: Path, config: Any) -> _FakeBuildResult:
            result = super().build_from_master(xml_path, config)
            generated = output / "assets" / "generated"
            generated.mkdir(parents=True, exist_ok=True)
            (generated / "book.tex").write_text("% latei", encoding="utf-8")
            return result

    _install_fake_business_apis(
        monkeypatch,
        metadata_result=_FakeMetadataResult(metadata=object()),
        conversion_result=_FakeConversionResult(is_successful=True),
        site_builder_factory=lambda: _LateiOnlySiteBuilder(build_result),
    )
    metadata_path = tmp_path / "meta.json"
    metadata_path.write_text("{}", encoding="utf-8")

    result = publier_module.publier(
        minimal_docx_path, metadata_path, workspace, output, options=PublicationOptions(pdf_export_mode="latei")
    )

    assert result.latei_path == output / "assets" / "generated" / "book.tex"
    assert result.pdf_path is None
    assert result.pdf_status == "not_requested"


# ---------------------------------------------------------------------------
# Enveloppement des erreurs d'assets, d'empreintes et de manifeste


def test_publier_asset_copy_failure_is_wrapped(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, minimal_docx_path: Path) -> None:
    workspace = tmp_path / "workspace"
    output = tmp_path / "output"
    media_source = workspace / "source" / "media"
    media_source.mkdir(parents=True)
    (media_source / "abc.png").write_bytes(b"fake-png-bytes")

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

    def _failing_copy2(*_args: object, **_kwargs: object) -> None:
        raise OSError("disque plein simule")

    monkeypatch.setattr(publier_module.shutil, "copy2", _failing_copy2)

    metadata_path = tmp_path / "meta.json"
    metadata_path.write_text("{}", encoding="utf-8")

    with pytest.raises(AssetPreparationError) as excinfo:
        publier_module.publier(minimal_docx_path, metadata_path, workspace, output)
    assert isinstance(excinfo.value.__cause__, OSError)


def test_files_identical_wraps_read_failure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    left = tmp_path / "left.png"
    right = tmp_path / "right.png"
    left.write_bytes(b"same-size-a")
    right.write_bytes(b"same-size-b")

    def _failing_read_bytes(self: Path) -> bytes:
        raise OSError("media illisible simule")

    monkeypatch.setattr(Path, "read_bytes", _failing_read_bytes)

    with pytest.raises(AssetPreparationError) as excinfo:
        publier_module._files_identical(left, right)
    assert isinstance(excinfo.value.__cause__, OSError)


def test_publier_checksum_failure_is_wrapped(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, minimal_docx_path: Path) -> None:
    workspace = tmp_path / "workspace"
    output = tmp_path / "output"
    build_result = _FakeBuildResult(output, output / "index.html", None, output / "build_report.txt")

    def _failing_sha256(path: Path) -> str:
        raise OSError("empreinte impossible simulee")

    mini_metopes_api = publier_module._MiniMetopesApi(
        load_metadata_file=lambda path: _FakeMetadataResult(metadata=object()),
        convert_docx_to_tei=lambda path, metadata: _FakeConversionResult(is_successful=True),
        write_tei_conversion_result=_make_write_tei(None),
        compute_file_sha256=_failing_sha256,
    )
    purh_site_api = publier_module._PurhSiteApi(BuildConfig=lambda **kwargs: kwargs, SiteBuilder=lambda: _FakeSiteBuilder(build_result))
    monkeypatch.setattr(publier_module, "_charger_dependances_metier", lambda: (mini_metopes_api, purh_site_api))

    metadata_path = tmp_path / "meta.json"
    metadata_path.write_text("{}", encoding="utf-8")

    with pytest.raises(ChecksumError) as excinfo:
        publier_module.publier(minimal_docx_path, metadata_path, workspace, output)
    assert isinstance(excinfo.value.__cause__, OSError)
    assert excinfo.value.path is not None


def test_manifest_write_preserves_existing_file_on_failure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from chaine_editoriale import manifeste as manifeste_module

    path = tmp_path / "publication.json"
    path.write_text('{"schema": "old"}', encoding="utf-8")
    original_text = path.read_text(encoding="utf-8")

    def _failing_replace(*_args: object, **_kwargs: object) -> None:
        raise OSError("remplacement impossible simule")

    monkeypatch.setattr(manifeste_module.os, "replace", _failing_replace)

    with pytest.raises(ManifestWriteError) as excinfo:
        manifeste_module.write_publication_manifest({"schema": "new"}, path)

    assert isinstance(excinfo.value.__cause__, OSError)
    assert excinfo.value.path == str(path)
    assert path.read_text(encoding="utf-8") == original_text


# ---------------------------------------------------------------------------
# Chemins de publication.json resolubles depuis le dossier du manifeste


def test_manifest_paths_are_resolvable_from_manifest_directory(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, minimal_docx_path: Path) -> None:
    """workspace_dir et output_dir sont deux dossiers freres : les chemins doivent rester resolubles."""
    root = tmp_path / "projet"
    workspace = root / "workspace"
    output = root / "output"
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

    import json

    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    manifest_dir = result.manifest_path.parent

    expected_targets = {
        ("sources", "docx", "path"): minimal_docx_path.resolve(),
        ("sources", "metadata", "path"): metadata_path.resolve(),
        ("intermediate", "tei", "path"): workspace / "source" / "document.xml",
        ("outputs", "index_html"): build_result.html_path,
        ("outputs", "build_report"): build_result.report_path,
    }
    for keys, expected_target in expected_targets.items():
        node: object = manifest
        for key in keys:
            node = node[key]  # type: ignore[index]
        assert isinstance(node, str), keys
        resolved = (manifest_dir / node).resolve() if not Path(node).is_absolute() else Path(node).resolve()
        assert resolved == expected_target.resolve(), (keys, node)

    # index.html vit sous output/, hors du dossier du manifeste (workspace/) :
    # le chemin relatif doit donc remonter d'un niveau.
    assert manifest["outputs"]["index_html"].startswith("../")
