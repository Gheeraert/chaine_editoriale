# Chaine editoriale

Couche d'orchestration entre deux bibliotheques independantes :

- **Mini-Metopes** (`mini_metopes`) : conversion DOCX -> TEI Commons Publishing.
- **Impressions** (`purh_site`) : conversion TEI -> site HTML, XML normalise, LaTEI et PDF.

`chaine_editoriale` ne recopie aucune logique metier des deux bibliotheques :
elle appelle uniquement leurs facades publiques (`mini_metopes.metadata`,
`mini_metopes.tei`, `purh_site.config`, `purh_site.site_builder`), sans
sous-processus, sans serveur, sans port reseau. `mini_metopes` n'importe
jamais `purh_site`, et reciproquement.

## Installation de developpement

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e C:\minimetopes
.\.venv\Scripts\python.exe -m pip install -e C:\impression2
.\.venv\Scripts\python.exe -m pip install -e .
```

Les deux premieres lignes relevent uniquement du developpement local : les
chemins `C:\minimetopes` et `C:\impression2` ne sont **jamais** ajoutes aux
dependances distribuees de `pyproject.toml`. En production, ces deux
bibliotheques sont supposees deja installees dans l'environnement Python
utilise par `chaine-editoriale`.

## Lancer la GUI

```powershell
.\.venv\Scripts\chaine-editoriale.exe
```

ou, de maniere equivalente :

```powershell
.\.venv\Scripts\python.exe -m chaine_editoriale.gui
```

## Lancer les tests

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

Les tests marques `@pytest.mark.integration` exercent le pipeline complet
(DOCX -> TEI -> site, eventuellement PDF via LuaLaTeX) avec les vrais depots
`C:\minimetopes` et `C:\impression2` ; ils sont ignores automatiquement si
ces depots sont absents de la machine.

## `config_chaine.json` vs `publication.json`

Ce sont deux fichiers JSON distincts, jamais fusionnes :

- **`config_chaine.json`** decrit la configuration technique *locale* de
  l'application : les chemins vers les depots Mini-Metopes et Impressions
  effectivement utilises sur cette machine, et la date de derniere
  verification reussie (`last_verified`). Il est ecrit par l'ecran de
  configuration (`Enregistrer`), jamais par `publier()`.
- **`publication.json`** decrit *une publication particuliere* : sources
  (DOCX + JSON, avec empreintes SHA-256), TEI intermediaire, options
  utilisees, artefacts produits et chemins de modules effectivement
  resolus au moment de la publication. Il est ecrit par `publier()` dans
  `workspace_dir/publication.json` a chaque publication.

Les chemins enregistres dans `config_chaine.json` sont la reference locale :
`activate_configured_dependencies()` verifie qu'ils resolvent effectivement
vers les modules importes (`importlib.import_module` + `inspect.getfile`),
et non pas seulement qu'un paquet `mini_metopes`/`purh_site` quelconque est
installe dans l'environnement.

### Emplacement par defaut

`config_chaine.json` est stocke a un emplacement utilisateur stable,
independant du repertoire courant :

```text
%APPDATA%\ChaineEditoriale\config_chaine.json
```

### Premier lancement

Au premier lancement (aucun `config_chaine.json` valide), l'ecran de
configuration s'affiche. Les champs sont prerempli uniquement si
`C:\minimetopes` et `C:\impression2` existent reellement ; sinon ils restent
vides. Le bouton `Enregistrer` reste desactive tant que `Verifier` n'a pas
reussi pour les valeurs exactes saisies.

### Depot deplace ou modifie

Aux lancements suivants, la configuration enregistree est systematiquement
revalidee (l'anciennete de `last_verified` n'est jamais une preuve
suffisante). Si un depot a ete deplace ou n'est plus valide, l'ecran de
configuration se rouvre avec les anciennes valeurs prereplies et un
diagnostic precis. Si un ancien exemplaire de `mini_metopes` ou `purh_site`
est deja charge en memoire depuis un autre emplacement, l'application
demande explicitement un redemarrage apres l'enregistrement de la nouvelle
configuration.

## Ecran de publication

Une fois les deux depots configures et valides, l'ecran principal permet de
publier **un document a la fois** (pas de traitement par lots dans cette
version). Il demande quatre chemins :

- le **document DOCX** a publier ;
- ses **metadonnees JSON** (voir Mini-Metopes pour leur schema) ;
- le **dossier de travail** : ou sont ecrits les intermediaires (`document.xml`
  Commons Publishing, medias extraits, `publication.json`) ;
- le **dossier de publication** : ou `purh_site.SiteBuilder` ecrit le site
  fini (`index.html`, `book.normalized.xml`, LaTEI/PDF eventuels).

### Creer ou modifier les metadonnees, sans quitter l'application

Le parcours normal est : **choisir un DOCX** -> **creer ou modifier les
metadonnees** -> **publier**. Lors d'une premiere publication, le fichier
JSON de metadonnees n'existe pas encore ; il n'est plus necessaire de le
fabriquer en dehors de l'application.

Des qu'un DOCX est choisi, `chaine_editoriale` calcule le chemin
conventionnel du JSON associe (`document.docx` -> `document.metadata.json`),
via `mini_metopes.metadata.default_metadata_path` (source de verite unique,
jamais recopiee). Ce chemin est affiche immediatement, meme si le fichier
n'existe pas encore : le bouton devient `Creer les metadonnees...`. Si un
fichier JSON existe deja a cet emplacement, il est detecte automatiquement
et le bouton devient `Modifier les metadonnees...`.

Cliquer sur ce bouton ouvre l'editeur de metadonnees de Mini-Metopes
(`mini_metopes.gui.open_metadata_editor`) comme une **boite modale integree**
a la meme fenetre (aucune nouvelle fenetre principale, aucun sous-processus).
A sa fermeture, la chaine editoriale recupere les **deux chemins reellement
retournes** (DOCX et JSON), car l'editeur peut relocaliser le DOCX ou charger
un autre couple DOCX/JSON. Une annulation conserve simplement le formulaire
tel quel, sans afficher d'erreur.

Le bouton `Choisir un autre JSON...` reste disponible pour associer un JSON
enregistre ailleurs (document deplace, reprise de travail existante) sans
ouvrir l'editeur automatiquement.

Le JSON reste un fichier reel sur disque a cote du DOCX (ou a l'emplacement
choisi) : rien n'est jamais cache dans un etat interne opaque.

Trois modes de sortie sont proposes :

| Libelle affiche                              | `pdf_export_mode` |
|-----------------------------------------------|--------------------|
| HTML + XML normalise                           | `none`             |
| HTML + XML normalise + LaTEI                   | `latei`             |
| HTML + XML normalise + LaTEI + PDF (par defaut)| `latei_pdf`         |

Le XML normalise est toujours produit, quel que soit le mode. Le moteur
LaTeX propose est uniquement **LuaLaTeX** (seul moteur reellement pris en
charge par Impressions, dont le preambule LaTEI charge `fontspec`). Si
LuaLaTeX n'est pas installe sur la machine, la publication en mode
`latei_pdf` produit tout de meme le HTML, le XML normalise et le LaTEI ; seul
le PDF est rapporte comme `unavailable` (« demande mais non produit »), sans
faire echouer le reste de la publication.

La publication s'execute dans un thread separe (la fenetre reste reactive)
et affiche un rapport final listant les artefacts reellement produits, avec
des boutons pour les ouvrir directement (association Windows par defaut).

Le dossier de travail et le dossier de publication sont valides reellement :
un chemin qui designe deja un fichier est refuse avant toute publication. Si
l'un de ces dossiers existe deja et contient des fichiers, une confirmation
explicite est demandee avant de reutiliser ce dossier (des fichiers portant
les memes noms pourront etre remplaces) ; un dossier absent ou vide ne
declenche aucune confirmation.

Le formulaire de publication (les quatre chemins, le mode de sortie et le
moteur LaTeX) est conserve pendant toute la session de l'application, y
compris lors d'un aller-retour par `Configurer les dependances...`. Depuis
cet ecran de configuration, un bouton `Retour a la publication` permet de
revenir sans rien enregistrer ni relancer de verification, tant qu'une
configuration valide est deja active (absent au tout premier lancement et
sur l'ecran de redemarrage requis).
