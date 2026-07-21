"""Script ponctuel de verification manuelle scriptee de la GUI (passe finition GUI).

Ne fait pas partie du paquet distribue. Pilote les VRAIS widgets Tkinter
construits par ``gui._build_publication_screen``/``gui.run_gui`` (pas de mock
de la logique metier), en simulant les actions utilisateur via l'arbre de
widgets, avec le vrai DOCX+image, le vrai pipeline ``publier()`` et LuaLaTeX
reel.

Ce script fournit une inspection scriptee et reproductible des proprietes
reelles de la fenetre (taille, position des widgets, texte affiche,
redimensionnement). Il ne remplace pas une inspection visuelle humaine par
capture d'ecran, qu'un agent sans capacite de perception visuelle ne peut
pas realiser lui-meme.

Usage : .venv\\Scripts\\python.exe scripts\\_manual_gui_check.py
"""

from __future__ import annotations

import json
import shutil
import sys
import time
import tkinter as tk
from pathlib import Path
from tkinter import ttk

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from chaine_editoriale import configuration as cfgmod  # noqa: E402
from chaine_editoriale import gui, interface_publication as ip  # noqa: E402

WORK_ROOT = Path(r"C:\tmp\manual_visual_check")
WORK_ROOT.mkdir(parents=True, exist_ok=True)


def widgets_by_class(widget, class_name: str) -> list:
    found = []
    for child in widget.winfo_children():
        if child.winfo_class() == class_name:
            found.append(child)
        found.extend(widgets_by_class(child, class_name))
    return found


def entries_in_order(root) -> list:
    return widgets_by_class(root, "TEntry")


def main() -> None:
    fixtures_dir = ROOT / "tests" / "fixtures"
    docx_path = fixtures_dir / "document_avec_image.docx"
    metadata_path = fixtures_dir / "document_avec_image.metadata.json"
    assert docx_path.is_file() and metadata_path.is_file()

    config_path = WORK_ROOT / "config_chaine.json"
    cfgmod.write_config(
        cfgmod.ChaineConfig(mini_metopes_path=Path(r"C:\minimetopes"), purh_site_path=Path(r"C:\impression2")),
        config_path,
    )
    cfgmod.default_config_path = lambda: config_path

    screen, controller = gui.startup_screen(config_path)
    print(f"[2] startup_screen() -> {screen!r} (attendu : 'main')")
    assert screen == "main"

    root = tk.Tk()
    root.title("Chaine editoriale (inspection scriptee)")
    root.geometry("900x650")
    root.minsize(760, 520)

    publication_controller = ip.PublicationScreenController()
    gui._build_publication_screen(root, publication_controller, lambda: None)
    root.update_idletasks()
    root.update()

    # [1] taille initiale / [2] taille minimale
    print(f"[1] geometrie initiale demandee: 900x650 -> reelle: {root.winfo_width()}x{root.winfo_height()}")
    min_w, min_h = root.minsize()
    print(f"[2] taille minimale configuree: {min_w}x{min_h}")

    # [3] alignement des quatre chemins
    entries = entries_in_order(root)
    labels = widgets_by_class(root, "TLabel")
    path_labels = [w.cget("text") for w in labels if w.cget("text") in (
        "Document DOCX", "Métadonnées JSON", "Dossier de travail", "Dossier de publication"
    )]
    print(f"[3] labels des 4 chemins trouves dans l'ordre attendu: {path_labels}")
    x_positions = [entry.winfo_x() for entry in entries[:4]]
    print(f"[3] alignement horizontal des 4 champs (colonne x, doivent etre egaux): {x_positions}")
    assert len(set(x_positions)) == 1, "les 4 champs de chemin doivent etre alignes verticalement"

    # [4] lisibilite des accents (contenu reel des chaines, independant de l'affichage console)
    title_label = next(w for w in labels if "éditoriale" in w.cget("text") or "Chaîne" in w.cget("text"))
    print(f"[4] texte du titre (contient des caracteres accentues) : {title_label.cget('text')!r}")
    assert "é" in title_label.cget("text") or "î" in title_label.cget("text")

    # [5] affichage de LuaLaTeX
    combos = widgets_by_class(root, "TCombobox")
    print(f"[5] valeur du combo moteur LaTeX : {combos[1].get()!r} (attendu 'LuaLaTeX')")
    assert combos[1].get() == "LuaLaTeX"

    # [6] redimensionnement horizontal : la colonne des chemins doit s'agrandir
    entry_width_before = entries[0].winfo_width()
    root.geometry("1300x650")
    root.update_idletasks()
    root.update()
    entry_width_after = entries[0].winfo_width()
    print(f"[6] largeur du champ DOCX avant/apres elargissement de la fenetre : {entry_width_before} -> {entry_width_after}")
    assert entry_width_after > entry_width_before, "la colonne des chemins doit s'etendre horizontalement"

    # [7] redimensionnement vertical : le cadre de resultat doit s'etendre
    report_frame = next(w for w in widgets_by_class(root, "TLabelframe") if w.cget("text") == "Résultat")
    report_height_before = report_frame.winfo_height()
    root.geometry("1300x900")
    root.update_idletasks()
    root.update()
    report_height_after = report_frame.winfo_height()
    print(f"[7] hauteur du cadre 'Résultat' avant/apres agrandissement vertical : {report_height_before} -> {report_height_after}")
    assert report_height_after > report_height_before, "le cadre de resultat doit s'etendre verticalement"

    # Retour a une taille etroite pour verifier l'absence de debordement des boutons ([8], verifie plus bas apres publication).
    root.geometry("900x650")
    root.update_idletasks()
    root.update()

    # [16] publication reelle avec l'image
    docx_entry, metadata_entry, workspace_entry, output_entry = entries[0:4]
    workspace_dir = WORK_ROOT / "run1" / "workspace"
    output_dir = WORK_ROOT / "run1" / "output"
    docx_entry.insert(0, str(docx_path))
    metadata_entry.insert(0, str(metadata_path))
    workspace_entry.insert(0, str(workspace_dir))
    output_entry.insert(0, str(output_dir))
    root.update()

    publish_button = next(b for b in widgets_by_class(root, "TButton") if b.cget("text") == "Publier")
    publish_button.invoke()
    root.update()
    print(f"[16] publication lancee ; busy = {publication_controller.busy} (attendu True)")

    deadline = time.time() + 180
    while publication_controller.busy and time.time() < deadline:
        root.update()
        time.sleep(0.1)
    assert not publication_controller.busy
    print("[16] publication terminee")

    # [9] lisibilite du resume + [8] absence de debordement des boutons
    report_labels = widgets_by_class(report_frame, "TLabel")
    summary_text = report_labels[0].cget("text") if report_labels else ""
    print("[9] resume affiche :")
    print(summary_text)

    artifact_buttons = [b for b in widgets_by_class(report_frame, "TButton") if b.cget("text").startswith("Ouvrir")]
    root.update_idletasks()
    frame_width = root.winfo_width()
    max_button_right_edge = max((b.winfo_x() + b.winfo_width() for b in artifact_buttons), default=0)
    print(f"[8] largeur fenetre = {frame_width} ; bord droit du bouton le plus a droite = {max_button_right_edge}")
    assert max_button_right_edge <= frame_width, "un bouton d'ouverture deborde de la fenetre"
    rows = sorted({b.grid_info()["row"] for b in artifact_buttons})
    print(f"[8] boutons d'ouverture repartis sur {len(rows)} ligne(s) de grille : {rows}")

    # [17] ouverture des artefacts (os.startfile mocke pour ne rien ouvrir reellement)
    opened: list[str] = []
    import chaine_editoriale.interface_publication as ip_module

    original_startfile = getattr(ip_module.os, "startfile", None)
    ip_module.os.startfile = lambda path: opened.append(str(path))
    try:
        for button in artifact_buttons:
            button.invoke()
    finally:
        if original_startfile is not None:
            ip_module.os.startfile = original_startfile
    print(f"[17] artefacts 'ouverts' (os.startfile mocke) : {len(opened)} action(s)")
    for path in opened:
        print(f"     - {path}")

    # [18] verifier l'image dans le HTML
    content_pages = sorted(p for p in output_dir.glob("*.html") if p.name != "index.html")
    image_found = any("assets/images/media/" in p.read_text(encoding="utf-8") for p in content_pages)
    print(f"[18] reference image trouvee dans le HTML : {image_found}")
    lualatex_available = shutil.which("lualatex") is not None
    print(f"     LuaLaTeX disponible : {lualatex_available}")
    pdf_path = output_dir / "assets" / "generated" / "book.pdf"
    print(f"[18] PDF present : {pdf_path.is_file()}")

    # [10] lisibilite d'une erreur longue
    bad_metadata = WORK_ROOT / "bad_metadata.json"
    bad_metadata.write_text("{}", encoding="utf-8")
    metadata_entry.delete(0, "end")
    metadata_entry.insert(0, str(bad_metadata))
    workspace_entry.delete(0, "end")
    workspace_entry.insert(0, str(WORK_ROOT / "run_error" / "workspace"))
    output_entry.delete(0, "end")
    output_entry.insert(0, str(WORK_ROOT / "run_error" / "output"))
    root.update()
    publish_button.invoke()
    root.update()
    deadline = time.time() + 60
    while publication_controller.busy and time.time() < deadline:
        root.update()
        time.sleep(0.1)
    error_text_widgets = widgets_by_class(report_frame, "Text")
    error_text = error_text_widgets[0].get("1.0", "end") if error_text_widgets else ""
    print(f"[10] longueur du texte d'erreur affiche : {len(error_text)} caracteres")
    print(error_text[:400])

    # [11]/[12]/[13]/[14]/[15] passage vers la configuration, bouton Retour, conservation
    metadata_entry.delete(0, "end")
    metadata_entry.insert(0, str(metadata_path))
    workspace_entry.delete(0, "end")
    workspace_entry.insert(0, str(WORK_ROOT / "run2" / "workspace"))
    output_entry.delete(0, "end")
    output_entry.insert(0, str(WORK_ROOT / "run2" / "output"))
    docx_before = docx_entry.get()
    workspace_before = workspace_entry.get()
    output_before = output_entry.get()
    root.update()

    config_button = next(b for b in widgets_by_class(root, "TButton") if b.cget("text") == "Configurer les dépendances…")
    config_opened = []
    # Reconstruire l'ecran avec un vrai callback de config pour l'inspection.
    for child in list(root.winfo_children()):
        child.destroy()
    gui._build_publication_screen(root, publication_controller, lambda: config_opened.append(True))
    root.update()
    entries2 = entries_in_order(root)
    print(f"[13] champ docx deja repeuple depuis form_state conserve : {entries2[0].get() == docx_before}")
    print(f"[13] champ workspace deja repeuple depuis form_state conserve : {entries2[2].get() == workspace_before}")
    root.update()
    config_button2 = next(b for b in widgets_by_class(root, "TButton") if b.cget("text") == "Configurer les dépendances…")
    config_button2.invoke()
    print(f"[11] ouverture de la configuration demandee : {config_opened}")
    print(f"[13] docx conserve dans form_state : {publication_controller.form_state.docx_path == docx_before}")
    print(f"[13] workspace conserve dans form_state : {publication_controller.form_state.workspace_dir == workspace_before}")
    print(f"[14] mode conserve dans form_state : {publication_controller.form_state.output_mode!r}")

    root.destroy()
    print("\nInspection scriptee terminee sans exception.")


if __name__ == "__main__":
    main()
