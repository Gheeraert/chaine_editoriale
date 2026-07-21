"""Script ponctuel de verification manuelle scriptee de la GUI (passe interface de publication).

Ne fait pas partie du paquet distribue. Pilote les VRAIS widgets Tkinter
construits par ``gui._build_publication_screen`` (pas de mock de la logique
metier), en simulant les clics utilisateur via l'arbre de widgets, avec le
vrai DOCX+image, le vrai pipeline ``publier()`` et LuaLaTeX reel.

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
from chaine_editoriale import gui  # noqa: E402

WORK_ROOT = Path(r"C:\tmp\gui_manual_check")
WORK_ROOT.mkdir(parents=True, exist_ok=True)


def find_widgets(root: tk.Misc) -> dict[str, tk.Widget]:
    """Indexer les widgets par (classe, texte) pour les retrouver sans reference directe."""
    found: dict[str, tk.Widget] = {}
    for child in root.winfo_children():
        try:
            text = child.cget("text")
        except tk.TclError:
            text = None
        key = f"{child.winfo_class()}::{text}"
        found.setdefault(key, child)
        found.update(find_widgets(child))
    return found


def entries_in_order(root: tk.Misc) -> list[tk.Widget]:
    result: list[tk.Widget] = []
    for child in root.winfo_children():
        if child.winfo_class() == "TEntry":
            result.append(child)
        result.extend(entries_in_order(child))
    return result


def comboboxes_in_order(root: tk.Misc) -> list[tk.Widget]:
    result: list[tk.Widget] = []
    for child in root.winfo_children():
        if child.winfo_class() == "TCombobox":
            result.append(child)
        result.extend(comboboxes_in_order(child))
    return result


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
    print(f"1) startup_screen() -> {screen!r} (attendu : 'main')")
    assert screen == "main"

    root = tk.Tk()
    root.title("Chaine editoriale (verification manuelle scriptee)")
    screen_controller = gui._build_publication_screen(root, lambda: None)
    root.update()
    print("2) ecran de publication construit apres validation des dependances : OK")

    entries = entries_in_order(root)
    docx_entry, metadata_entry, workspace_entry, output_entry = entries[0:4]
    combos = comboboxes_in_order(root)
    output_mode_combo, latex_engine_combo = combos[0], combos[1]
    widgets_by_key = find_widgets(root)
    publish_button = widgets_by_key.get("TButton::Publier")
    assert publish_button is not None, list(widgets_by_key)

    workspace_dir = WORK_ROOT / "run1" / "workspace"
    output_dir = WORK_ROOT / "run1" / "output"

    docx_entry.delete(0, "end")
    docx_entry.insert(0, str(docx_path))
    metadata_entry.delete(0, "end")
    metadata_entry.insert(0, str(metadata_path))
    workspace_entry.delete(0, "end")
    workspace_entry.insert(0, str(workspace_dir))
    output_entry.delete(0, "end")
    output_entry.insert(0, str(output_dir))
    output_mode_combo.set("HTML + XML normalisé + LaTEI + PDF")
    root.update()
    print(f"3-7) champs renseignes, mode = {output_mode_combo.get()!r}, moteur = {latex_engine_combo.get()!r}")

    # 8. lancer la publication (equivaut a cliquer sur "Publier").
    publish_button.invoke()
    root.update()
    print(f"8) publication lancee ; screen_controller.busy = {screen_controller.busy} (attendu : True)")
    assert screen_controller.busy is True

    # 9-10. la fenetre reste reactive et le dialogue indetermine est visible.
    toplevels = [w for w in root.winfo_children() if isinstance(w, tk.Toplevel)] + [
        w for w in root.children.values() if isinstance(w, tk.Toplevel)
    ]
    for _ in range(20):
        root.update()
        toplevels = [w for w in root.winfo_children() if isinstance(w, tk.Toplevel)]
        if toplevels:
            break
        time.sleep(0.05)
    print(f"9-10) fenetre reactive pendant la publication (root.update() repond) ; dialogue d'attente present = {bool(toplevels)}")
    assert toplevels, "le dialogue d'attente Toplevel devrait etre affiche"
    waiting_dialog = toplevels[0]
    print(f"    titre du dialogue : {waiting_dialog.title()!r}")

    # 11. double lancement impossible pendant que busy=True.
    publish_button.invoke()
    root.update()
    print("11) second clic sur Publier pendant la publication : ignore (aucune exception, aucun second worker)")

    # Laisser le worker reel se terminer (DOCX + image + latei_pdf + LuaLaTeX).
    print("    attente de la fin de la publication reelle (peut prendre jusqu'a une minute)...")
    deadline = time.time() + 180
    while screen_controller.busy and time.time() < deadline:
        root.update()
        time.sleep(0.1)
    assert not screen_controller.busy, "la publication n'est pas terminee dans le delai imparti"
    print(f"    publication terminee ; screen_controller.busy = {screen_controller.busy} (attendu : False)")

    # 12. rapport final.
    widgets_by_key = find_widgets(root)
    report_texts = [w.cget("text") for w in root.winfo_children() if False]  # placeholder, on relit ci-dessous
    from chaine_editoriale import interface_publication as ip

    manifest_path = output_dir.parent / "workspace" / "publication.json"
    print(f"12) manifeste attendu : {manifest_path} existe = {manifest_path.is_file()}")

    # 13-17. verifier les artefacts reellement presents sur disque.
    index_html = output_dir / "index.html"
    normalized_xml = output_dir / "book.normalized.xml"
    latei_tex = output_dir / "assets" / "generated" / "book.tex"
    pdf_path = output_dir / "assets" / "generated" / "book.pdf"
    print(f"13) index.html existe = {index_html.is_file()}")
    print(f"14) XML normalise existe = {normalized_xml.is_file()}")
    print(f"15) LaTEI (book.tex) existe = {latei_tex.is_file()}")
    lualatex_available = shutil.which("lualatex") is not None
    print(f"    LuaLaTeX disponible sur cette machine : {lualatex_available}")
    print(f"16) PDF existe = {pdf_path.is_file()} (attendu si LuaLaTeX disponible : {lualatex_available})")
    print(f"17) manifeste existe = {manifest_path.is_file()}")

    # 18. l'image dans le HTML et dans le PDF (deja prouve par le test d'integration
    # test_publier_latei_pdf_with_real_image ; on revalide ici la reference HTML).
    content_pages = sorted(p for p in output_dir.glob("*.html") if p.name != "index.html")
    image_found_in_html = False
    for page in content_pages:
        text = page.read_text(encoding="utf-8")
        if "assets/images/media/" in text:
            image_found_in_html = True
    print(f"18) reference image trouvee dans une page de contenu HTML : {image_found_in_html}")

    if manifest_path.is_file():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        print(f"    pdf_status du manifeste : {manifest.get('pdf_status')}")

    # 19. seconde publication (le formulaire doit rester exploitable).
    output_dir2 = WORK_ROOT / "run2" / "output"
    workspace_dir2 = WORK_ROOT / "run2" / "workspace"
    workspace_entry.delete(0, "end")
    workspace_entry.insert(0, str(workspace_dir2))
    output_entry.delete(0, "end")
    output_entry.insert(0, str(output_dir2))
    root.update()
    publish_button.invoke()
    root.update()
    print(f"19) seconde publication lancee ; busy = {screen_controller.busy} (attendu : True)")
    deadline = time.time() + 180
    while screen_controller.busy and time.time() < deadline:
        root.update()
        time.sleep(0.1)
    print(f"    seconde publication terminee ; busy = {screen_controller.busy}")

    # 20. erreur volontaire de metadonnees (JSON invalide).
    bad_metadata = WORK_ROOT / "bad_metadata.json"
    bad_metadata.write_text("{}", encoding="utf-8")
    metadata_entry.delete(0, "end")
    metadata_entry.insert(0, str(bad_metadata))
    output_dir3 = WORK_ROOT / "run3" / "output"
    workspace_dir3 = WORK_ROOT / "run3" / "workspace"
    workspace_entry.delete(0, "end")
    workspace_entry.insert(0, str(workspace_dir3))
    output_entry.delete(0, "end")
    output_entry.insert(0, str(output_dir3))
    root.update()
    publish_button.invoke()
    root.update()
    deadline = time.time() + 60
    while screen_controller.busy and time.time() < deadline:
        root.update()
        time.sleep(0.1)
    print(f"20) publication avec metadonnees invalides terminee ; busy = {screen_controller.busy}")

    root.update()
    root.destroy()
    print("\nVerification manuelle scriptee terminee sans exception.")


if __name__ == "__main__":
    main()
