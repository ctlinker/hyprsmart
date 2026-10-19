# Rapport de Session : Persistance des Profils et Préchargement au Démarrage

- **Date** : 2026-10-14
- **Version** : 0.7.0
- **Branche** : `feat/caching-and-deferred-execution`
- **Auteur** : Agent IA Antigravity `[ai]`

---

## 1. Contexte & Demande Utilisateur
L'utilisateur a validé le comportement adaptatif de la v0.6.1 (ajustements visuels sur focus, redimensionnement et déplacement) et a formulé la demande suivante :
> *"hum next feature i would say that startup preload a profil for every window, this profile would just a something cached in dot config, just so that the user doesn't have to focus every window when starting the deamon"*

Jusqu'alors, les profils de classes visuelles (`CLASS_PROFILES`) n'existaient qu'en mémoire vive et étaient perdus à chaque redémarrage du démon. De plus, seul le focus actif déclenchait l'ajustement d'opacité, laissant toutes les autres fenêtres opaques jusqu'à ce que l'utilisateur clique dessus.

---

## 2. Conception & Réalisations Techniques

### A. Persistance des Profils de Classe (`~/.config/hyprsmart/profiles.json`)
- Implémentation des fonctions `load_class_profiles()` et `save_class_profiles()` dans `src/hyprsmart/daemon/cache.py`.
- Format JSON clair et lisible stockant les métriques visuelles de chaque classe d'application (`text_l`, `bg_l`, `text_density`, `bg_ratio`).
- Sauvegarde atomique via un fichier `.tmp` pour garantir l'intégrité des données même en cas de coupure brutale.
- Mise à jour et sauvegarde automatiques à chaque observation via la moyenne mobile exponentielle (EMA : 70% prior, 30% new).

### B. Préchargement Universel au Démarrage (`preload_all_windows`)
- Ajout de la routine `preload_all_windows()` exécutée dans un thread d'arrière-plan dès le lancement des workers (`load_hyprsmart_daemons()`).
- Récupération de l'ensemble des fenêtres mappées et visibles sur tous les espaces de travail via `get_hyprland_windows()`.
- Pour chaque fenêtre dont la classe est connue :
  - Découpage direct du fond d'écran sous sa géométrie locale.
  - Calcul déterministe de l'opacité requise via `decide_opacity(profile, backdrop)`.
  - Application immédiate via `set_hyprland_win_opacity` avec étiquette dédiée `[PRELOAD]`.
- **Résultat** : Toutes les fenêtres existantes (navigateurs, éditeurs, terminaux, applications de chat) sur tous les espaces de travail adoptent instantanément leur niveau de transparence sans aucune action de l'utilisateur.

### C. Multi-Monitor Mapping
- Ajout de `monitor_id` dans la structure de données `Window` (`src/hyprsmart/primitive/window.py`).
- Prise en charge explicite du moniteur cible dans `apply_window_decision` pour résoudre correctement les fonds d'écran sur les configurations multi-écrans.

---

## 3. Tests et Vérifications

1. **Suite de tests unitaires** :
   - Création de `tests/test_preload_profiles.py` validant la sérialisation, la désérialisation et le préchargement isolé.
   - Exécution : `uv run python -m unittest discover tests` : **31/31 tests réussis en 1.16s**.
2. **Vérification en direct du démon** :
   - Démarrage du démon (PID 202850).
   - Log d'initialisation en direct :
     ```text
     [PRELOAD] (cache hit) alpha: 0.50 (text_dens=0.02, bg_ratio=0.47, wall_edge=0.028) for 0x5630fc90bc40
     [PRELOAD] (cache hit) alpha: 0.60 (text_dens=0.02, bg_ratio=0.47, wall_edge=0.028) for 0x5630fc8e1880
     [PRELOAD] (cache hit) alpha: 0.55 (text_dens=0.07, bg_ratio=0.73, wall_edge=0.028) for 0x5630fcc623b0
     [PRELOAD] (cache hit) alpha: 0.50 (text_dens=0.04, bg_ratio=0.78, wall_edge=0.028) for 0x5630fc98e320
     [PRELOAD] (cache hit) alpha: 0.50 (text_dens=0.02, bg_ratio=0.47, wall_edge=0.028) for 0x5630fc9d89d0
     [PRELOAD] (cache hit) alpha: 0.95 (text_dens=0.07, bg_ratio=0.55, wall_edge=0.028) for 0x5630fb6418c0
     [INFO] Preloaded profiles for 6 window(s) across workspaces
     ```
   - Les fenêtres réparties sur les workspaces 2, 3, 4, 6 et special ont toutes été rendues transparentes dès la première seconde sans intervention.

---

## 4. Fichiers Modifiés
- `src/hyprsmart/primitive/window.py`
- `src/hyprsmart/daemon/cache.py`
- `src/hyprsmart/daemon/handle.py`
- `tests/test_preload_profiles.py` (nouveau)
- `pyproject.toml` (version 0.7.0)
- `CHANGELOG.md`
- `wiki/under-the-hood/08_optical_unblending_and_class_profiles.md`
- `wiki/reports/2026-10-14_profils_persistants_et_prechargement_demarrage.md`
