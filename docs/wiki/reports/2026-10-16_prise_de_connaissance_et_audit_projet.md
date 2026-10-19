# Rapport de Session : Prise de Connaissance et Audit Technique de HyprSmart

- **Date** : 2026-10-16
- **Branche active** : `feat/progressive-change` (basée sur `v0.7.0` / `fe946fc`, avec modifications indexées vers `0.7.1`)
- **Auteur** : Agent IA Antigravity `[ai]`

---

## 1. Contexte & Demande Utilisateur

L'utilisateur a demandé de prendre connaissance de l'ensemble du projet **HyprSmart**, de lire le guide d'ingénierie [`AGENT.md`](../../AGENT.md) et de rédiger un rapport complet sur l'état actuel du dépôt.

---

## 2. Analyse Technique & Constatations

### 2.1 Architecture et Fonctionnement Global
**HyprSmart** est un démon résident d'accessibilité et de transparence adaptative pour le compositeur Wayland **Hyprland**. Contrairement à la v1 historique (`old/` et `dataset/`) qui reposait sur un modèle Vision-LLM local via Ollama (`qwen3.5:0.8b`), l'architecture actuelle (`src/hyprsmart/`) est **100 % déterministe, vectorisée (NumPy/Pillow) et temps réel (< 1.5 ms par calcul)** :

1. **Couche Système & Primitives (`src/hyprsmart/primitive/`)** :
   - [`get_mon.py`](../../src/hyprsmart/primitive/get_mon.py) & [`get_win.py`](../../src/hyprsmart/primitive/get_win.py) : Interrogation JSON de Hyprland (`hyprctl monitors -j`, `hyprctl activewindow -j`, `hyprctl clients -j`).
   - [`window.py`](../../src/hyprsmart/primitive/window.py) : Modèle `Window`, capture ciblée via `grim -g "<x>,<y> <w>x<h>" -`, et application de l'opacité via `hyprctl dispatch hl.dsp.window.set_prop(...)`.

2. **Moteur Optique & Mathématique (`src/hyprsmart/opacity/`)** :
   - [`backdrop.py`](../../src/hyprsmart/opacity/backdrop.py) : Rendu du fond d'écran en mode *cover* sous-échantillonné (`DOWN = 4`), calcul de la luminance relative sRGB (WCAG 2.x) enrichie de la saillance chromatique de Helmholtz-Kohlrausch, et calcul de l'énergie des contours par filtre de Sobel 2D + différences finies adjacentes (`WALLPAPER_CACHE`).
   - [`win_col.py`](../../src/hyprsmart/opacity/win_col.py) : Extraction des propriétés visuelles de la fenêtre (`WindowVisuals` : `text_l`, `bg_l`, `text_density`, `bg_ratio`) par quantification 12-bits (bit-shifting), agrégation de voisinage, détection de glyphes par gradient et **dé-mélange optique** (`unblend_luminance`) inversant l'alpha compositing sans clignotement.
   - [`compute.py`](../../src/hyprsmart/opacity/compute.py) : Solveur WCAG adaptatif (`decide_opacity`) combinant une contrainte primaire et un plancher de sécurité (*worst-case*), modulés par l'encombrement spatial du fond d'écran (`edge_energy`) et la densité de texte.
   - [`video_detect.py`](../../src/hyprsmart/opacity/video_detect.py) : Détecteur multi-signaux sans IA combinant `idle_inhibit` Wayland (+0.35), flux audio actif PipeWire/PulseAudio avec traversée `/proc/<pid>/status` (+0.35), heuristique visuelle (+0.25) et état `fullscreen` (+0.15), fixant l'opacité à `video_opacity` si $S \ge 0.55$.

3. **Démon, Cache & IPC (`src/hyprsmart/daemon/`, `cli.py`, `config.py`)** :
   - [`socket.py`](../../src/hyprsmart/daemon/socket.py) : Écoute résiliente avec reconnexion automatique sur `.socket2.sock`.
   - [`handle.py`](../../src/hyprsmart/daemon/handle.py) : Ordonnanceur à temporisation glissante (`DebouncedScheduler`), architecture multi-threadée à 3 files (`CAPTURE_QUEUE`, `LUMINANCE_QUEUE`, `CACHE_HIT_QUEUE`), surveillance en direct de `config.yaml` (`config_watcher_worker`), diffing d'opacité ($\Delta\alpha < 0.03$), préchargement au démarrage (`preload_all_windows`) et restauration de l'opacité à `1.0` à l'arrêt (`restore_all_managed_windows`).
   - [`cache.py`](../../src/hyprsmart/daemon/cache.py) : Cache d'instance (`WIN_CACHE`, TTL 30 min) et profils génériques par classe d'application (`CLASS_PROFILES`) appris par moyenne mobile exponentielle (EMA) et persistés atomiquement dans `~/.config/hyprsmart/profiles.json`.
   - [`control_server.py`](../../src/hyprsmart/daemon/control_server.py) & [`cli.py`](../../src/hyprsmart/cli.py) : Serveur IPC UNIX (`$XDG_RUNTIME_DIR/hyprsmart/control.sock`) pilotant les sous-commandes CLI (`start`, `stop`, `reload`, `status`, `what-is-it-doing`, `monitor`, `settings`).

---

### 2.2 Analyse des Modifications Indexées (`git status` sur `feat/progressive-change`)
Un audit de l'index Git révèle **11 fichiers modifiés/ajoutés déjà indexés (`staged`)** préparant la version `0.7.1` :
- **Nouveau module de diagnostic développeur (`src/hyprsmart/daemon/dev_trace.py`)** :
  - Activé via le flag CLI `--yes-am-a-dev-on-this-project-and-i-fully-understand-what-this-flag-does` (ou la commande IPC `set_dev_mode`).
  - Génère pour chaque décision d'opacité un dossier horodaté dans `~/.local/state/hyprsmart/dev_captures/` contenant `before.png`, `after.png` et `metadata.json` (incluant la décomposition complète du solveur WCAG et la détection automatique d'anomalies).
- **Améliorations dans `backdrop.py`** :
  - Prise en charge des fonds d'écran animés (`.gif`, `.webp`) par moyennage jusqu'à 6 frames réparties uniformément.
  - Prise en compte de l'effet Helmholtz-Kohlrausch ($0.70 \cdot L + 0.30 \cdot \max(R_{lin}, G_{lin}, B_{lin})$).
  - Support du facteur d'échelle HiDPI (`monitor_scale`) dans `backdrop_behind`.
- **Raffinements dans `win_col.py`, `cache.py` et `compute.py`** :
  - Rééchantillonnage `NEAREST` en $640 \times 640$ et clustering de voisinage autour du bin dominant pour éviter la fragmentation 12-bits.
  - Sanitization des profils (`_sanitize_profile_visuals`) et EMA pondérée par la confiance (`captured_alpha`).
  - Modèle de perturbation gamma sRGB ($L^{0.58}$) dans `decide_opacity`.
- **Dépendances (`pyproject.toml`)** :
  - Passage de la version à `0.7.1`. Note : `fastapi` et `ollama` figurent encore dans `dependencies` alors qu'ils relèvent de l'approche v1 archivée.

---

### 2.3 Divergences Documentaires Identifiées
1. **Section 3 de `AGENT.md` obsolète** : La section *"3. Analyse du Projet : État Actuel (POC Fonctionnel)"* décrit encore les bugs initiaux de la v0.1.0 (chemin wallpaper en dur, bug `lum[x0:x1, y0:y1]`, absence de CLI/config/tests/signaux), alors que la section 5 (*Feuille de Route*) et le code actuel (`v0.7.0+`) ont résolu tous ces points.
2. **Documentation `wiki/under-the-hood/` à synchroniser avec `feat/progressive-change`** :
   - Les changements indexés dans `compute.py`, `win_col.py` et `dev_trace.py` (modèle gamma $L^{0.58}$, clustering de fond, échantillonnage multi-frames GIF, mode diagnostic dev) ne sont pas encore répercutés dans `CHANGELOG.md` ni dans `wiki/under-the-hood/`.

---

## 3. Modifications Apportées & Fichiers Touchés

Conformément à la demande de prise de connaissance et de rapport (sans altérer le travail indexé en cours de l'utilisateur) :
- Création du présent rapport d'audit dans [`wiki/reports/2026-10-16_prise_de_connaissance_et_audit_projet.md`](2026-10-16_prise_de_connaissance_et_audit_projet.md).

---

## 4. Tests et Vérifications Exécutés

Exécution de la suite de tests unitaires via `uv run python -m unittest discover tests` :
- **Résultat global** : **27 / 31 tests réussis**, **4 échecs** introduits par les modifications actuellement indexées (`staged`) sur `feat/progressive-change` :

| Test en échec | Fichier | Cause racine identifiée dans les changements indexés |
| :--- | :--- | :--- |
| `test_class_cache_fallback` | [`tests/test_caching_and_defer.py:56`](../../tests/test_caching_and_defer.py) | `_sanitize_profile_visuals()` dans `cache.py` plafonne `text_l` à `0.54` lorsque `bg_l < 0.35` et `text_l > 0.62` (transformant `0.92` en `0.54`). |
| `test_save_and_load_profiles_json` | [`tests/test_preload_profiles.py:39`](../../tests/test_preload_profiles.py) | Même cause : `_sanitize_profile_visuals()` plafonne `text_l=0.75` à `0.54` lors de `update_class_profile`. |
| `test_decide_opacity_adaptive_terminal` | [`tests/test_opacity_and_config.py:87`](../../tests/test_opacity_and_config.py) | Le nouveau calcul de `disturb_l` avec exposant gamma (`raw_bleed ** 0.58 + 0.45 * std + 1.10 * edge_energy`) et `cal_text_l <= 0.60` dans `compute.py` produit `alpha_calm = 0.90` au lieu de `<= 0.75`. |
| `test_fullscreen_presentation` | [`tests/test_video_detect.py:157`](../../tests/test_video_detect.py) | Dans `video_detect.py:178`, le seuil `visuals.bg_ratio < 0.30` (au lieu de `< 0.40` ou `<= 0.30`) exclut le cas de test où `bg_ratio = 0.30`, donnant un score de `0.85` au lieu de `1.0`. |

---

## 5. Prochaines Étapes Suggérées

1. **Correction des 4 régressions de tests sur `feat/progressive-change`** :
   - Harmoniser `_sanitize_profile_visuals` / `cal_text_l` (éviter de plafonner brutalement `text_l` à `0.54` dans les profils sauvegardés ou ajuster la calibration et les assertions des tests).
   - Ajuster la pénalité de perturbation dans `compute.py` pour qu'un terminal sombre sur fond calme (`b_calm`) conserve une transparence $\alpha \le 0.75$.
   - Utiliser `visuals.bg_ratio <= 0.30` (ou `< 0.35`) dans `video_detect.py` pour préserver la détection sur `test_fullscreen_presentation`.
2. **Mise à jour de `CHANGELOG.md` et `wiki/under-the-hood/` pour la `v0.7.1`** :
   - Documenter `dev_trace.py`, le support des wallpapers animés/HiDPI et les améliorations du solveur une fois les tests au vert, puis effectuer le commit `[ai]`.
3. **Actualisation de `AGENT.md` (Section 3)** et nettoyage des dépendances inutilisées (`ollama`, `fastapi`) dans `pyproject.toml`.
