# AGENTS.md

## Frontiere architecturale

- `mini_metopes` (`C:\minimetopes`) et `purh_site` (`C:\impression2`) sont
  deux depots independants, geres ailleurs. Ne jamais les modifier depuis ce
  depot.
- `chaine_editoriale` est la seule couche qui depend des deux. Ni
  `mini_metopes` ni `purh_site` ne doivent jamais importer l'autre, ni
  `chaine_editoriale`.
- Utiliser uniquement les facades publiques :
  `mini_metopes.metadata`, `mini_metopes.tei`, `purh_site.config`,
  `purh_site.site_builder`. Ne pas importer leurs sous-modules internes
  (`serialization`, `conversion`, `serializer`, etc.).
- Aucune logique metier des deux bibliotheques ne doit etre recopiee ici.
- Aucun sous-processus, aucun serveur, aucun port reseau.

## Imports differes

`gui.py` et `configuration.py` n'importent jamais `mini_metopes` ni
`purh_site` au chargement du module. Ces imports sont regroupes dans
`publier._charger_dependances_metier()`, appele uniquement apres que
`configuration.activate_configured_dependencies()` a verifie avec succes
les chemins configures.

## Tests

- `pytest -m "not integration"` pour la suite rapide (aucune dependance
  reelle a `C:\minimetopes` / `C:\impression2`).
- `pytest -m integration` pour le pipeline complet, ignore automatiquement
  si ces depots sont absents de la machine.
