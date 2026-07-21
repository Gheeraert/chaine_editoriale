"""Interface Tkinter de la chaine editoriale.

``tkinter`` est un module de la bibliotheque standard : son import au
chargement de ce fichier n'est pas un import metier et reste sans effet de
bord (aucune fenetre n'est creee avant l'appel explicite a ``run_gui``). Les
imports de ``mini_metopes``/``purh_site`` restent en revanche differes
jusqu'a la verification de la configuration ; ``ConfigController`` ne
manipule que ``chaine_editoriale.configuration``.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .configuration import (
    ChaineConfig,
    DependencyVerification,
    activate_configured_dependencies,
    default_config_path,
    load_config,
    today_iso,
    write_config,
)
from .erreurs import ConfigurationError

SUGGESTED_MINI_METOPES_PATH = r"C:\minimetopes"
SUGGESTED_PURH_SITE_PATH = r"C:\impression2"


def suggest_default_paths() -> tuple[str, str]:
    """Suggerer des chemins uniquement lorsqu'ils existent reellement."""
    mini_metopes = SUGGESTED_MINI_METOPES_PATH if Path(SUGGESTED_MINI_METOPES_PATH).is_dir() else ""
    purh_site = SUGGESTED_PURH_SITE_PATH if Path(SUGGESTED_PURH_SITE_PATH).is_dir() else ""
    return mini_metopes, purh_site


@dataclass
class ConfigController:
    """Logique de l'ecran de configuration, testable sans fenetre Tk reelle."""

    mini_metopes_path: str = ""
    purh_site_path: str = ""
    config_path: Path | None = None
    verification: DependencyVerification | None = None
    startup_warning: str | None = None
    _verified_for: tuple[str, str] | None = None

    def set_mini_metopes_path(self, value: str) -> None:
        if value != self.mini_metopes_path:
            self.mini_metopes_path = value
            self._invalidate()

    def set_purh_site_path(self, value: str) -> None:
        if value != self.purh_site_path:
            self.purh_site_path = value
            self._invalidate()

    def _invalidate(self) -> None:
        self.verification = None

    def verify(self) -> DependencyVerification:
        """Verifier la configuration courante des deux champs, sans l'enregistrer."""
        candidate = ChaineConfig(
            mini_metopes_path=Path(self.mini_metopes_path),
            purh_site_path=Path(self.purh_site_path),
        )
        self.verification = activate_configured_dependencies(candidate)
        self._verified_for = (self.mini_metopes_path, self.purh_site_path)
        return self.verification

    def can_save(self) -> bool:
        """Le bouton Enregistrer accepte un succes complet ou un redemarrage requis, jamais une erreur."""
        if self.verification is None or not self.verification.can_be_saved:
            return False
        return self._verified_for == (self.mini_metopes_path, self.purh_site_path)

    def save(self, path: Path | None = None) -> Path:
        if not self.can_save():
            raise RuntimeError("la configuration doit etre verifiee avec succes avant d'etre enregistree")
        assert self.verification is not None
        # Un redemarrage requis empeche de garantir que la resolution reussie
        # decrit encore l'etat reel du process : last_verified reste null.
        last_verified = today_iso() if self.verification.success else None
        config = ChaineConfig(
            mini_metopes_path=Path(self.mini_metopes_path),
            purh_site_path=Path(self.purh_site_path),
            last_verified=last_verified,
        )
        return write_config(config, path if path is not None else self.config_path)

    def status_text(self) -> str:
        """Rendu texte du dernier resultat de verification, une dependance par bloc."""
        if self.verification is None:
            return ""
        lines: list[str] = []
        state_labels = {"success": "OK", "restart_required": "REDEMARRAGE REQUIS", "error": "ECHEC"}
        for check in (self.verification.mini_metopes, self.verification.purh_site):
            label = "Mini-Metopes" if check.dependency_name == "mini_metopes" else "Impressions"
            lines.append(f"{label} : {state_labels[check.state]}")
            lines.append(f"Depot : {check.configured_repository}")
            if check.import_root is not None:
                lines.append(f"Racine d'import : {check.import_root}")
            if check.module_path is not None:
                lines.append(f"Module : {check.module_path}")
            if not check.success:
                lines.append(check.message)
            lines.append("")
        return "\n".join(lines).rstrip()

    def post_save_message(self) -> str:
        """Message a afficher juste apres un enregistrement reussi."""
        assert self.verification is not None
        if self.verification.success:
            return "Mini-Metopes et Impressions sont configures.\nLa chaine editoriale est prete."
        return (
            "La nouvelle configuration a ete enregistree.\n\n"
            "Une autre version de Mini-Metopes ou d'Impressions est encore chargee en memoire.\n"
            "Redemarrez la Chaine editoriale pour utiliser les nouveaux chemins."
        )


def startup_screen(config_path: Path | None = None) -> tuple[str, ConfigController]:
    """Determiner l'ecran de depart : 'main' si la configuration enregistree est valide, sinon 'config'."""
    resolved_path = config_path if config_path is not None else default_config_path()
    load_result = load_config(resolved_path)
    if not load_result.valid or load_result.config is None:
        mini_metopes, purh_site = suggest_default_paths()
        return "config", ConfigController(mini_metopes, purh_site, config_path=resolved_path)

    config = load_result.config
    controller = ConfigController(
        str(config.mini_metopes_path), str(config.purh_site_path), config_path=resolved_path
    )
    verification = activate_configured_dependencies(config)
    controller.verification = verification
    controller._verified_for = (controller.mini_metopes_path, controller.purh_site_path)
    if verification.success:
        try:
            write_config(ChaineConfig(config.mini_metopes_path, config.purh_site_path, last_verified=today_iso()), resolved_path)
        except ConfigurationError as error:
            # Seule l'ecriture de last_verified est en cause : la resolution
            # des dependances reste un succes reel, donc l'ecran principal
            # doit rester accessible. Une erreur non prevue (hors
            # ConfigurationError) n'est en revanche jamais avalee ici.
            controller.startup_warning = f"date de derniere verification non mise a jour : {error}"
        return "main", controller
    return "config", controller


def run_gui() -> None:
    """Lancer l'application Tkinter (ecran de configuration puis ecran principal)."""
    import tkinter as tk
    from tkinter import filedialog, messagebox

    screen, controller = startup_screen()

    root = tk.Tk()
    root.title("Chaine editoriale")

    def show_main_screen() -> None:
        for child in root.winfo_children():
            child.destroy()
        frame = tk.Frame(root, padx=16, pady=16)
        frame.pack(fill="both", expand=True)
        tk.Label(
            frame,
            text="Mini-Metopes et Impressions sont configures.\nLa chaine editoriale est prete.",
            justify="left",
        ).pack(anchor="w")
        if controller.startup_warning:
            tk.Label(frame, text=controller.startup_warning, justify="left", fg="#a15c00").pack(anchor="w", pady=(4, 0))
        tk.Button(frame, text="Configurer les dependances...", command=show_config_screen).pack(anchor="w", pady=(12, 0))

    def show_restart_required_screen() -> None:
        for child in root.winfo_children():
            child.destroy()
        frame = tk.Frame(root, padx=16, pady=16)
        frame.pack(fill="both", expand=True)
        tk.Label(frame, text=controller.post_save_message(), justify="left").pack(anchor="w")
        tk.Button(frame, text="Fermer", command=root.destroy).pack(anchor="w", pady=(12, 0))

    def show_config_screen() -> None:
        for child in root.winfo_children():
            child.destroy()
        frame = tk.Frame(root, padx=16, pady=16)
        frame.pack(fill="both", expand=True)

        mini_metopes_var = tk.StringVar(value=controller.mini_metopes_path)
        purh_site_var = tk.StringVar(value=controller.purh_site_path)
        status_var = tk.StringVar(value=controller.status_text())
        save_button: tk.Button

        def on_field_change(*_args: object) -> None:
            controller.set_mini_metopes_path(mini_metopes_var.get())
            controller.set_purh_site_path(purh_site_var.get())
            status_var.set("")
            save_button.configure(state="disabled")

        def browse_mini_metopes() -> None:
            selected = filedialog.askdirectory()
            if selected:
                mini_metopes_var.set(selected)

        def browse_purh_site() -> None:
            selected = filedialog.askdirectory()
            if selected:
                purh_site_var.set(selected)

        def on_verify() -> None:
            controller.set_mini_metopes_path(mini_metopes_var.get())
            controller.set_purh_site_path(purh_site_var.get())
            controller.verify()
            status_var.set(controller.status_text())
            save_button.configure(state=("normal" if controller.can_save() else "disabled"))

        def on_save() -> None:
            if not controller.can_save():
                return
            assert controller.verification is not None
            fully_active = controller.verification.success
            controller.save()
            if fully_active:
                show_main_screen()
            else:
                # Un redemarrage est necessaire : ne jamais afficher l'ecran
                # principal comme si les nouvelles dependances etaient deja
                # actives, et ne pas tenter de decharger/reimporter les
                # paquets deja charges depuis un autre emplacement.
                show_restart_required_screen()

        tk.Label(frame, text="Depot Mini-Metopes").grid(row=0, column=0, sticky="w")
        tk.Entry(frame, textvariable=mini_metopes_var, width=50).grid(row=0, column=1, sticky="we")
        tk.Button(frame, text="Parcourir...", command=browse_mini_metopes).grid(row=0, column=2)

        tk.Label(frame, text="Depot Impressions").grid(row=1, column=0, sticky="w")
        tk.Entry(frame, textvariable=purh_site_var, width=50).grid(row=1, column=1, sticky="we")
        tk.Button(frame, text="Parcourir...", command=browse_purh_site).grid(row=1, column=2)

        tk.Button(frame, text="Verifier", command=on_verify).grid(row=2, column=0, pady=(8, 0))
        save_button = tk.Button(frame, text="Enregistrer", command=on_save, state="disabled")
        save_button.grid(row=2, column=1, pady=(8, 0), sticky="w")

        status_label = tk.Label(frame, textvariable=status_var, justify="left", anchor="w")
        status_label.grid(row=3, column=0, columnspan=3, sticky="w", pady=(8, 0))

        mini_metopes_var.trace_add("write", on_field_change)
        purh_site_var.trace_add("write", on_field_change)

    if screen == "main":
        show_main_screen()
    else:
        show_config_screen()

    root.mainloop()


if __name__ == "__main__":  # pragma: no cover
    run_gui()
