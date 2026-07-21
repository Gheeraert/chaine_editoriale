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
