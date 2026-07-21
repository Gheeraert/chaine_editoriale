"""Interface Tkinter de la chaine editoriale.

``tkinter`` est un module de la bibliotheque standard : son import au
chargement de ce fichier n'est pas un import metier et reste sans effet de
bord (aucune fenetre n'est creee avant l'appel explicite a ``run_gui``). Les
imports de ``mini_metopes``/``purh_site`` restent en revanche differes
jusqu'a la verification de la configuration ; ``ConfigController`` ne
manipule que ``chaine_editoriale.configuration``, et l'ecran de publication
(``_build_publication_screen``) ne manipule que
``chaine_editoriale.interface_publication`` (qui appelle ``publier()``, lequel
active les dependances avant tout import metier).
"""

from __future__ import annotations

import queue
import threading
from dataclasses import dataclass
from pathlib import Path

from . import interface_publication as ip
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


def _build_publication_screen(root, open_config_screen) -> "ip.PublicationScreenController":
    """Construire l'ecran de publication (un document a la fois).

    Toute la logique (validation, requete, worker, formatage, etat occupe)
    vit dans ``interface_publication`` et reste testable sans Tk ; cette
    fonction ne fait qu'assembler des widgets ``ttk`` autour de ces
    fonctions/objets purs. Le controleur retourne permet a ``run_gui()`` de
    refuser de fermer la fenetre pendant une publication en cours.
    """
    import queue as queue_module
    import tkinter as tk
    from tkinter import filedialog, messagebox, scrolledtext, ttk

    screen_controller = ip.PublicationScreenController()
    form_state = screen_controller.form_state

    frame = ttk.Frame(root, padding=16)
    frame.pack(fill="both", expand=True)
    frame.columnconfigure(1, weight=1)

    ttk.Label(frame, text="Chaîne éditoriale", font=("TkDefaultFont", 12, "bold")).grid(
        row=0, column=0, columnspan=3, sticky="w"
    )
    ttk.Label(frame, text="Publier un document DOCX en site HTML, XML normalisé, LaTEI et PDF.", justify="left").grid(
        row=1, column=0, columnspan=3, sticky="w", pady=(0, 12)
    )

    docx_var = tk.StringVar(value=form_state.docx_path)
    metadata_var = tk.StringVar(value=form_state.metadata_path)
    workspace_var = tk.StringVar(value=form_state.workspace_dir)
    output_var = tk.StringVar(value=form_state.output_dir)
    output_mode_var = tk.StringVar(value=ip.output_mode_label(form_state.output_mode))
    latex_engine_var = tk.StringVar(value=ip.latex_engine_label(form_state.latex_engine))

    def browse_docx() -> None:
        initial = ip.initial_directory_for(docx_var.get())
        selected = filedialog.askopenfilename(
            title="Choisir le document DOCX",
            initialdir=initial,
            filetypes=[("Documents Word", "*.docx"), ("Tous les fichiers", "*.*")],
        )
        if not selected:
            return
        docx_var.set(selected)
        if not workspace_var.get().strip() and not output_var.get().strip():
            suggested_workspace, suggested_output = ip.suggest_workspace_and_output_dirs(Path(selected))
            workspace_var.set(suggested_workspace)
            output_var.set(suggested_output)

    def browse_metadata() -> None:
        initial = ip.initial_directory_for(metadata_var.get(), docx_var.get())
        selected = filedialog.askopenfilename(
            title="Choisir les métadonnées JSON",
            initialdir=initial,
            filetypes=[("Métadonnées JSON", "*.json"), ("Tous les fichiers", "*.*")],
        )
        if selected:
            metadata_var.set(selected)

    def browse_workspace() -> None:
        initial = ip.initial_directory_for(workspace_var.get(), docx_var.get())
        selected = filedialog.askdirectory(title="Choisir le dossier de travail", initialdir=initial)
        if selected:
            workspace_var.set(selected)

    def browse_output() -> None:
        initial = ip.initial_directory_for(output_var.get(), docx_var.get())
        selected = filedialog.askdirectory(title="Choisir le dossier de publication", initialdir=initial)
        if selected:
            output_var.set(selected)

    row = 2
    ttk.Label(frame, text="Document DOCX").grid(row=row, column=0, sticky="w", pady=2)
    docx_entry = ttk.Entry(frame, textvariable=docx_var)
    docx_entry.grid(row=row, column=1, sticky="we", padx=(8, 8))
    docx_browse_button = ttk.Button(frame, text="Parcourir…", command=browse_docx)
    docx_browse_button.grid(row=row, column=2)
    row += 1

    ttk.Label(frame, text="Métadonnées JSON").grid(row=row, column=0, sticky="w", pady=2)
    metadata_entry = ttk.Entry(frame, textvariable=metadata_var)
    metadata_entry.grid(row=row, column=1, sticky="we", padx=(8, 8))
    metadata_browse_button = ttk.Button(frame, text="Parcourir…", command=browse_metadata)
    metadata_browse_button.grid(row=row, column=2)
    row += 1

    ttk.Label(frame, text="Dossier de travail").grid(row=row, column=0, sticky="w", pady=2)
    workspace_entry = ttk.Entry(frame, textvariable=workspace_var)
    workspace_entry.grid(row=row, column=1, sticky="we", padx=(8, 8))
    workspace_browse_button = ttk.Button(frame, text="Parcourir…", command=browse_workspace)
    workspace_browse_button.grid(row=row, column=2)
    row += 1

    ttk.Label(frame, text="Dossier de publication").grid(row=row, column=0, sticky="w", pady=2)
    output_entry = ttk.Entry(frame, textvariable=output_var)
    output_entry.grid(row=row, column=1, sticky="we", padx=(8, 8))
    output_browse_button = ttk.Button(frame, text="Parcourir…", command=browse_output)
    output_browse_button.grid(row=row, column=2)
    row += 1

    output_mode_labels = [label for _mode, label in ip.OUTPUT_MODE_CHOICES]

    def on_output_mode_change(*_args: object) -> None:
        mode = ip.output_mode_from_label(output_mode_var.get())
        engine_needed = mode is not None and ip.latex_engine_required_for(mode)
        latex_engine_combo.configure(state=("readonly" if engine_needed else "disabled"))

    ttk.Label(frame, text="Sortie").grid(row=row, column=0, sticky="w", pady=2)
    output_mode_combo = ttk.Combobox(
        frame, textvariable=output_mode_var, values=output_mode_labels, state="readonly"
    )
    output_mode_combo.grid(row=row, column=1, sticky="we", padx=(8, 8))
    output_mode_var.trace_add("write", on_output_mode_change)
    row += 1

    ttk.Label(frame, text="Moteur LaTeX").grid(row=row, column=0, sticky="w", pady=2)
    latex_engine_combo = ttk.Combobox(
        frame,
        textvariable=latex_engine_var,
        values=[ip.latex_engine_label(engine) for engine in ip.SUPPORTED_LATEX_ENGINES],
        state="readonly",
    )
    latex_engine_combo.grid(row=row, column=1, sticky="we", padx=(8, 8))
    row += 1

    field_widgets = {
        "docx_path": docx_entry,
        "metadata_path": metadata_entry,
        "workspace_dir": workspace_entry,
        "output_dir": output_entry,
        "output_mode": output_mode_combo,
        "latex_engine": latex_engine_combo,
    }
    browse_buttons = (docx_browse_button, metadata_browse_button, workspace_browse_button, output_browse_button)

    button_row_frame = ttk.Frame(frame)
    button_row_frame.grid(row=row, column=0, columnspan=3, sticky="w", pady=(12, 0))
    publish_button = ttk.Button(button_row_frame, text="Publier")
    publish_button.pack(side="left")
    config_button = ttk.Button(button_row_frame, text="Configurer les dépendances…", command=open_config_screen)
    config_button.pack(side="left", padx=(8, 0))
    row += 1

    report_frame = ttk.LabelFrame(frame, text="Résultat", padding=12)
    report_frame.grid(row=row, column=0, columnspan=3, sticky="nsew", pady=(16, 0))
    frame.rowconfigure(row, weight=1)

    def set_form_enabled(enabled: bool) -> None:
        state = "normal" if enabled else "disabled"
        for entry in (docx_entry, metadata_entry, workspace_entry, output_entry):
            entry.configure(state=state)
        for button in browse_buttons:
            button.configure(state=state)
        combo_state = "disabled" if not enabled else "readonly"
        output_mode_combo.configure(state=combo_state)
        if enabled:
            on_output_mode_change()
        else:
            latex_engine_combo.configure(state="disabled")
        publish_button.configure(state=state)
        config_button.configure(state=state)

    def clear_report() -> None:
        for child in report_frame.winfo_children():
            child.destroy()

    def open_artifact_safe(path: Path) -> None:
        try:
            ip.open_artifact(path)
        except OSError as error:
            messagebox.showerror("Ouverture impossible", f"Impossible d'ouvrir :\n{path}\n\n{error}", parent=root)

    def show_success_report(result) -> None:
        clear_report()
        summary_label = ttk.Label(report_frame, text=ip.format_publication_summary(result), justify="left")
        summary_label.pack(anchor="w")
        actions = ip.describe_openable_artifacts(result)
        if actions:
            actions_frame = ttk.Frame(report_frame)
            actions_frame.pack(anchor="w", pady=(12, 0))
            for action in actions:
                ttk.Button(
                    actions_frame, text=action.label, command=lambda path=action.path: open_artifact_safe(path)
                ).pack(side="left", padx=(0, 6), pady=(0, 6))

    def show_error_report(message: str) -> None:
        clear_report()
        ttk.Label(report_frame, text="La publication a échoué.", justify="left").pack(anchor="w")
        text_widget = scrolledtext.ScrolledText(report_frame, height=10, wrap="word")
        text_widget.insert("1.0", message)
        text_widget.configure(state="disabled")
        text_widget.pack(fill="both", expand=True, pady=(8, 0))

    def poll_job(result_queue: "queue_module.Queue", waiting_dialog) -> None:
        try:
            event = result_queue.get_nowait()
        except queue_module.Empty:
            root.after(100, lambda: poll_job(result_queue, waiting_dialog))
            return
        waiting_dialog.destroy()
        screen_controller.end_publication()
        set_form_enabled(True)
        if event.kind == "success":
            assert event.result is not None
            show_success_report(event.result)
        else:
            assert event.error is not None
            if not isinstance(event.error, ip.ChaineEditorialeError):
                ip.log_unexpected_error(event.error)
            show_error_report(ip.format_publication_error(event.error))

    def show_waiting_dialog():
        dialog = tk.Toplevel(root)
        dialog.title("Publication en cours")
        dialog.resizable(False, False)
        dialog.transient(root)
        dialog.protocol("WM_DELETE_WINDOW", lambda: None)
        inner = ttk.Frame(dialog, padding=20)
        inner.pack()
        ttk.Label(inner, text="ℹ Publication en cours…", font=("TkDefaultFont", 10, "bold")).pack(anchor="w")
        ttk.Label(
            inner,
            justify="left",
            text=(
                "Conversion du DOCX, génération du site et des fichiers éditoriaux.\n"
                "Cette opération peut durer plusieurs minutes."
            ),
        ).pack(anchor="w", pady=(4, 12))
        progress = ttk.Progressbar(inner, mode="indeterminate", length=280)
        progress.pack(fill="x")
        progress.start(12)
        dialog.update_idletasks()
        dialog.grab_set()
        return dialog

    def check_directory(path: Path) -> bool | None:
        try:
            return ip.directory_is_non_empty(path)
        except OSError as error:
            messagebox.showerror("Dossier illisible", f"Impossible de lire {path} :\n{error}", parent=root)
            return None

    def on_publish() -> None:
        if screen_controller.busy:
            # Refuse silencieusement un second lancement : le bouton est deja
            # desactive pendant une publication, ce garde-fou couvre aussi
            # un evenement en file d'attente juste avant la desactivation.
            return

        form_state.docx_path = docx_var.get()
        form_state.metadata_path = metadata_var.get()
        form_state.workspace_dir = workspace_var.get()
        form_state.output_dir = output_var.get()
        mode = ip.output_mode_from_label(output_mode_var.get())
        if mode is not None:
            form_state.output_mode = mode
        engine = ip.DEFAULT_LATEX_ENGINE
        form_state.latex_engine = engine

        issues = ip.validate_publication_form(form_state)
        if issues:
            message = "\n".join(f"- {issue.message}" for issue in issues)
            messagebox.showerror("Formulaire incomplet", message, parent=root)
            first_widget = field_widgets.get(issues[0].field)
            if first_widget is not None:
                first_widget.focus_set()
            return

        request = ip.build_publication_request(form_state)

        workspace_non_empty = check_directory(request.workspace_dir)
        if workspace_non_empty is None:
            return
        output_non_empty = check_directory(request.output_dir)
        if output_non_empty is None:
            return
        non_empty_dirs = [
            str(path)
            for path, flag in ((request.workspace_dir, workspace_non_empty), (request.output_dir, output_non_empty))
            if flag
        ]
        if non_empty_dirs:
            listing = "\n".join(f"- {entry}" for entry in non_empty_dirs)
            proceed = messagebox.askyesno(
                "Dossier non vide",
                "Le(s) dossier(s) suivant(s) existent déjà et contiennent des fichiers :\n"
                f"{listing}\n\n"
                "Des fichiers portant les mêmes noms pourront être remplacés. Continuer ?",
                parent=root,
            )
            if not proceed:
                return

        if not screen_controller.begin_publication():
            return
        clear_report()
        set_form_enabled(False)
        waiting_dialog = show_waiting_dialog()
        result_queue: "queue_module.Queue" = queue_module.Queue()

        def worker() -> None:
            event = ip.run_publication_job(request)
            result_queue.put(event)

        threading.Thread(target=worker, daemon=True).start()
        root.after(100, lambda: poll_job(result_queue, waiting_dialog))

    publish_button.configure(command=on_publish)
    on_output_mode_change()

    # tk.Variable ne conserve que le nom de la variable Tcl cote widget : sans
    # reference Python vivante, le garbage collector appelle Variable.__del__
    # (qui "unset" la variable Tcl) des le retour de cette fonction. Toutes
    # les StringVar doivent donc survivre au-dela de cet appel, meme celles
    # qu'aucune fermeture ne referme (ex. latex_engine_var, jamais relue
    # ailleurs que par le widget lui-meme).
    frame.publication_form_vars = (
        docx_var,
        metadata_var,
        workspace_var,
        output_var,
        output_mode_var,
        latex_engine_var,
    )
    return screen_controller


def run_gui() -> None:
    """Lancer l'application Tkinter (ecran de configuration puis ecran principal)."""
    import tkinter as tk
    from tkinter import filedialog, messagebox

    screen, controller = startup_screen()

    root = tk.Tk()
    root.title("Chaine editoriale")

    # Reference partagee vers le controleur d'ecran de publication courant :
    # une publication en cours ne doit jamais etre interrompue brutalement
    # par la fermeture de la fenetre principale.
    active_publication_screen: dict = {"controller": None}

    def on_close_request() -> None:
        screen_controller = active_publication_screen["controller"]
        if screen_controller is not None and screen_controller.busy:
            messagebox.showinfo(
                "Publication en cours",
                "Une publication est en cours. Attendez sa fin avant de fermer la fenetre.",
                parent=root,
            )
            return
        root.destroy()

    root.protocol("WM_DELETE_WINDOW", on_close_request)

    def show_main_screen() -> None:
        for child in root.winfo_children():
            child.destroy()
        if controller.startup_warning:
            warning_frame = tk.Frame(root, padx=16, pady=(8, 0))
            warning_frame.pack(fill="x")
            tk.Label(warning_frame, text=controller.startup_warning, justify="left", fg="#a15c00").pack(anchor="w")
        active_publication_screen["controller"] = _build_publication_screen(root, show_config_screen)

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
