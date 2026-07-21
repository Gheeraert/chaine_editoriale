"""Configuration technique locale de la chaine editoriale (config_chaine.json).

Ce module ne doit jamais importer ``mini_metopes`` ni ``purh_site`` au
chargement : ces bibliotheques ne sont importees, via ``importlib``, qu'au
moment ou ``activate_configured_dependencies`` verifie effectivement les
chemins configures.
"""

from __future__ import annotations

import importlib
import inspect
import json
import os
import sys
import tempfile
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Literal

CONFIG_SCHEMA_NAME = "chaine-editoriale-config"
CONFIG_SCHEMA_VERSION = 1

ConfigIssueSeverity = Literal["error", "warning"]
DependencyState = Literal["success", "restart_required", "error"]

# (nom du paquet Python, dependance decrite)
_DEPENDENCY_PACKAGES: tuple[tuple[str, str], ...] = (
    ("mini_metopes", "mini_metopes_path"),
    ("purh_site", "purh_site_path"),
)


@dataclass(frozen=True, slots=True)
class ChaineConfig:
    """Configuration technique locale persistee dans config_chaine.json."""

    mini_metopes_path: Path
    purh_site_path: Path
    schema_version: int = CONFIG_SCHEMA_VERSION
    last_verified: str | None = None


@dataclass(frozen=True, slots=True)
class ConfigIssue:
    """Diagnostic structure de lecture ou de validation de configuration."""

    code: str
    severity: ConfigIssueSeverity
    message: str
    path: str | None = None


@dataclass(frozen=True, slots=True)
class ConfigLoadResult:
    """Resultat de lecture de config_chaine.json, sans exception pour les cas attendus."""

    config: ChaineConfig | None
    issues: tuple[ConfigIssue, ...]
    source_path: Path

    @property
    def valid(self) -> bool:
        return self.config is not None and not any(issue.severity == "error" for issue in self.issues)


@dataclass(frozen=True, slots=True)
class DependencyCheck:
    """Bilan structure de la resolution d'une dependance (mini_metopes ou purh_site)."""

    dependency_name: str
    configured_repository: Path
    import_root: Path | None
    module_path: Path | None
    state: DependencyState
    message: str

    @property
    def success(self) -> bool:
        return self.state == "success"

    @property
    def can_be_saved(self) -> bool:
        return self.state in {"success", "restart_required"}

    @property
    def restart_required(self) -> bool:
        return self.state == "restart_required"


@dataclass(frozen=True, slots=True)
class DependencyVerification:
    """Bilan combine des deux dependances externes."""

    mini_metopes: DependencyCheck
    purh_site: DependencyCheck

    @property
    def success(self) -> bool:
        return self.mini_metopes.success and self.purh_site.success

    @property
    def can_be_saved(self) -> bool:
        return self.mini_metopes.can_be_saved and self.purh_site.can_be_saved

    @property
    def restart_required(self) -> bool:
        return self.can_be_saved and not self.success


def default_config_path() -> Path:
    """Emplacement utilisateur stable de config_chaine.json (jamais le repertoire courant)."""
    appdata = os.environ.get("APPDATA")
    base = Path(appdata) if appdata else Path.home() / "AppData" / "Roaming"
    return base / "ChaineEditoriale" / "config_chaine.json"


def load_config(path: Path | None = None) -> ConfigLoadResult:
    """Lire config_chaine.json en detectant proprement chaque cas d'echec attendu."""
    resolved_path = path if path is not None else default_config_path()
    if not resolved_path.exists():
        return ConfigLoadResult(None, (ConfigIssue("config_missing", "error", f"aucune configuration trouvee : {resolved_path}"),), resolved_path)
    try:
        raw_text = resolved_path.read_text(encoding="utf-8")
    except OSError as error:
        return ConfigLoadResult(None, (ConfigIssue("config_unreadable", "error", f"fichier de configuration illisible : {error}"),), resolved_path)

    try:
        data = json.loads(raw_text)
    except json.JSONDecodeError as error:
        return ConfigLoadResult(None, (ConfigIssue("config_invalid_json", "error", f"JSON invalide : {error}"),), resolved_path)

    if not isinstance(data, dict):
        return ConfigLoadResult(None, (ConfigIssue("config_invalid_root", "error", "la racine du JSON doit etre un objet"),), resolved_path)

    issues: list[ConfigIssue] = []
    schema = data.get("schema")
    if schema != CONFIG_SCHEMA_NAME:
        issues.append(ConfigIssue("config_unknown_schema", "error", f"schema de configuration inconnu : {schema!r}", "schema"))
    schema_version = data.get("schema_version")
    if schema_version != CONFIG_SCHEMA_VERSION:
        issues.append(ConfigIssue("config_unknown_schema_version", "error", f"version de schema inconnue : {schema_version!r}", "schema_version"))

    mini_metopes_path = _require_str_field(data, "mini_metopes_path", issues)
    purh_site_path = _require_str_field(data, "purh_site_path", issues)

    last_verified = data.get("last_verified")
    if last_verified is not None and not isinstance(last_verified, str):
        issues.append(ConfigIssue("config_invalid_field_type", "error", "last_verified doit etre une chaine ISO ou null", "last_verified"))
        last_verified = None

    if any(issue.severity == "error" for issue in issues):
        return ConfigLoadResult(None, tuple(issues), resolved_path)

    assert mini_metopes_path is not None and purh_site_path is not None
    config = ChaineConfig(
        mini_metopes_path=Path(mini_metopes_path),
        purh_site_path=Path(purh_site_path),
        schema_version=CONFIG_SCHEMA_VERSION,
        last_verified=last_verified,
    )
    return ConfigLoadResult(config, tuple(issues), resolved_path)


def _require_str_field(data: dict[str, object], field_name: str, issues: list[ConfigIssue]) -> str | None:
    if field_name not in data:
        issues.append(ConfigIssue("config_missing_field", "error", f"champ obligatoire absent : {field_name}", field_name))
        return None
    value = data[field_name]
    if not isinstance(value, str) or not value.strip():
        issues.append(ConfigIssue("config_invalid_field_type", "error", f"champ invalide : {field_name} doit etre une chaine non vide", field_name))
        return None
    return value


def write_config(config: ChaineConfig, path: Path | None = None) -> Path:
    """Ecrire config_chaine.json de maniere UTF-8, atomique et deterministe."""
    resolved_path = path if path is not None else default_config_path()
    resolved_path.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "schema": CONFIG_SCHEMA_NAME,
        "schema_version": CONFIG_SCHEMA_VERSION,
        "mini_metopes_path": str(config.mini_metopes_path),
        "purh_site_path": str(config.purh_site_path),
        "last_verified": config.last_verified,
    }
    payload = json.dumps(data, ensure_ascii=False, indent=2, sort_keys=False) + "\n"
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=resolved_path.parent, prefix=f".{resolved_path.name}.", suffix=".tmp", delete=False
        ) as temporary:
            temporary.write(payload)
            temporary_path = Path(temporary.name)
        os.replace(temporary_path, resolved_path)
    except OSError as error:
        if temporary_path is not None:
            try:
                temporary_path.unlink(missing_ok=True)
            except OSError:
                pass
        from .erreurs import ConfigurationError

        raise ConfigurationError(f"impossible d'ecrire la configuration : {error}") from error
    return resolved_path


def verify_config(config: ChaineConfig) -> DependencyVerification:
    """Verifier la structure des deux depots configures, sans importer quoi que ce soit."""
    return DependencyVerification(
        mini_metopes=_verify_repository_structure("mini_metopes", config.mini_metopes_path),
        purh_site=_verify_repository_structure("purh_site", config.purh_site_path),
    )


def _verify_repository_structure(package_name: str, repository_path: Path) -> DependencyCheck:
    if not repository_path.exists():
        return DependencyCheck(package_name, repository_path, None, None, "error", f"dossier introuvable : {repository_path}")
    if not repository_path.is_dir():
        return DependencyCheck(package_name, repository_path, None, None, "error", f"le chemin n'est pas un dossier : {repository_path}")
    if not (repository_path / "pyproject.toml").is_file():
        return DependencyCheck(package_name, repository_path, None, None, "error", f"le dossier ne ressemble pas a un depot Python (pyproject.toml absent) : {repository_path}")
    import_root = _detect_import_root(repository_path, package_name)
    if import_root is None:
        return DependencyCheck(package_name, repository_path, None, None, "error", f"paquet {package_name} introuvable sous {repository_path}")
    return DependencyCheck(package_name, repository_path, import_root, None, "success", f"structure valide, racine d'import {import_root}")


def _detect_import_root(repository_path: Path, package_name: str) -> Path | None:
    """Rechercher la racine qui contient reellement <package_name>/__init__.py."""
    candidates: list[Path] = [repository_path]
    try:
        children = sorted(child for child in repository_path.iterdir() if child.is_dir() and not child.name.startswith("."))
    except OSError:
        children = []
    candidates.extend(children)
    for candidate in candidates:
        if (candidate / package_name / "__init__.py").is_file():
            return candidate
    return None


def activate_configured_dependencies(config: ChaineConfig) -> DependencyVerification:
    """Activer sys.path pour les deux depots configures et importer/verifier reellement les paquets."""
    structural = verify_config(config)
    return DependencyVerification(
        mini_metopes=_activate_dependency(structural.mini_metopes),
        purh_site=_activate_dependency(structural.purh_site),
    )


def _activate_dependency(structural_check: DependencyCheck) -> DependencyCheck:
    if not structural_check.success or structural_check.import_root is None:
        return structural_check

    package_name = structural_check.dependency_name
    import_root = structural_check.import_root
    resolved_import_root = import_root.resolve()

    _prioritize_sys_path_entry(import_root)

    existing_module = sys.modules.get(package_name)
    if existing_module is not None:
        return _check_already_loaded_module(structural_check, existing_module, resolved_import_root)

    try:
        module = importlib.import_module(package_name)
    except Exception as error:  # noqa: BLE001 - converti en diagnostic structure, jamais relance brut.
        return DependencyCheck(
            package_name,
            structural_check.configured_repository,
            import_root,
            None,
            "error",
            f"le module {package_name} n'a pas pu etre importe depuis {import_root} : {error}",
        )

    return _check_resolved_module(structural_check, module, resolved_import_root)


def _check_already_loaded_module(
    structural_check: DependencyCheck, module: object, resolved_import_root: Path
) -> DependencyCheck:
    package_name = structural_check.dependency_name
    try:
        module_file = Path(inspect.getfile(module))  # type: ignore[arg-type]
    except (TypeError, OSError):
        return DependencyCheck(
            package_name, structural_check.configured_repository, structural_check.import_root, None, "error",
            f"module {package_name} deja charge mais son emplacement ne peut pas etre determine",
        )
    if not _is_under(module_file, resolved_import_root):
        return DependencyCheck(
            package_name, structural_check.configured_repository, structural_check.import_root, module_file, "restart_required",
            (
                f"une autre version de {package_name} est deja chargee depuis {module_file}. "
                "Enregistrez la nouvelle configuration puis redemarrez l'application."
            ),
        )
    return DependencyCheck(
        package_name, structural_check.configured_repository, structural_check.import_root, module_file, "success",
        f"deja charge et coherent avec le depot configure : {module_file}",
    )


def _check_resolved_module(
    structural_check: DependencyCheck, module: object, resolved_import_root: Path
) -> DependencyCheck:
    package_name = structural_check.dependency_name
    try:
        module_file = Path(inspect.getfile(module))  # type: ignore[arg-type]
    except (TypeError, OSError) as error:
        return DependencyCheck(
            package_name, structural_check.configured_repository, structural_check.import_root, None, "error",
            f"emplacement du module {package_name} indetermine : {error}",
        )
    if not _is_under(module_file, resolved_import_root):
        return DependencyCheck(
            package_name, structural_check.configured_repository, structural_check.import_root, module_file, "error",
            (
                f"conflit de resolution : {package_name} importe depuis {module_file} "
                f"au lieu du depot configure ({structural_check.configured_repository})"
            ),
        )
    return DependencyCheck(
        package_name, structural_check.configured_repository, structural_check.import_root, module_file, "success",
        f"module {package_name} resolu depuis {module_file}",
    )


def _is_under(candidate: Path, root: Path) -> bool:
    try:
        candidate.resolve().relative_to(root)
        return True
    except ValueError:
        return False


def _prioritize_sys_path_entry(path: Path) -> None:
    """Garantir que path occupe la position 0 de sys.path, sans doublon equivalent.

    Retire d'abord toute occurrence de sys.path resolue vers le meme chemin
    (ou illisible), puis insere path en tete. Le chemin configure est ainsi
    toujours prioritaire face a une autre installation du meme paquet
    presente ailleurs dans sys.path.
    """
    resolved = path.resolve()
    remaining = [entry for entry in sys.path if not _same_resolved_path(entry, resolved)]
    sys.path[:] = [str(resolved)] + remaining


def _same_resolved_path(entry: str, resolved: Path) -> bool:
    if not entry:
        return False
    try:
        return Path(entry).resolve() == resolved
    except OSError:
        return False


def today_iso() -> str:
    """Date du jour au format ISO AAAA-MM-JJ, pour last_verified."""
    return date.today().isoformat()
