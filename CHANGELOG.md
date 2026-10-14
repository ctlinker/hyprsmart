# Journal des Modifications (CHANGELOG)

Toutes les modifications notables apportées à ce projet sont consignées dans ce fichier.
Le format est basé sur [Keep a Changelog](https://keepachangelog.com/fr/1.0.0/) et ce projet adhère à [Semantic Versioning](https://semver.org/lang/fr/).

---

## [0.7.0] - 2026-10-14

### Ajouté
- **Persistance des profils de classe (`~/.config/hyprsmart/profiles.json`)** :
  - Sauvegarde et restauration automatiques des empreintes visuelles des classes de fenêtres (`text_l`, `bg_l`, `text_density`, `bg_ratio`).
  - Lissage continu en moyenne mobile exponentielle (EMA) persisté sur disque de manière atomique lors des captures.
- **Préchargement universel au démarrage (`preload_all_windows`)** :
  - À chaque démarrage du démon, toutes les fenêtres ouvertes et mappées à travers l'ensemble des espaces de travail et moniteurs reçoivent instantanément leur niveau de transparence optimal basé sur leur profil de classe et le fond d'écran sous-jacent.
  - L'utilisateur n'a plus besoin de cliquer ou focaliser manuellement chaque fenêtre pour déclencher son adaptation d'opacité.
  - Journalisation explicite dédiée avec l'étiquette `[PRELOAD]`.
- **Support du ciblage multi-écrans par fenêtre** :
  - Ajout du champ `monitor_id` dans la structure `Window` et résolution dynamique du moniteur et du fond d'écran associé dans `apply_window_decision`.
- **Suite de tests étendue (`test_preload_profiles.py`)** :
  - 31 tests unitaires validant la sérialisation/désérialisation JSON des profils et le préchargement transparent sans exécution de commandes `grim`.

---

## [0.6.1] - 2026-10-14

### Modifié & Amélioré
- **Recalibration adaptative du contraste (`compute.py`)** :
  - Découplage de la conformité WCAG sur la médiane représentative du fond d'écran et du plancher de lisibilité minimal ($\ge 2.0$) sur les percentiles extrêmes (`p85`/`p95`).
  - Permet aux fenêtres sombres (IDE, terminaux, chat) de s'établir naturellement à une transparence visible et agréable ($\alpha \approx 0.65 - 0.75$) sans rester bloquées à 0.95/1.0.
- **Extraction précise de la luminance du texte (`win_col.py`)** :
  - Échantillonnage ciblé sur les pixels distincts de l'arrière-plan ($|L - L_{bg}| > 0.05$) au 95ᵉ percentile, capturant la brillance réelle des glyphes de code et éléments textuels plutôt que le noir d'arrière-plan ou les bordures atténuées.
- **Réactivité instantanée des événements (`handle.py`)** :
  - Raccourcissement drastique des délais de debouncing pour les changements de focus (`activewindowv2`: 0.05s) et les déplacements (`movewindowv2`: 0.08s).
  - Garantie que les fenêtres nouvellement gérées reçoivent immédiatement leur niveau de transparence sans être bloquées par un diffing initial.
  - Nettoyage automatique des fenêtres fermées dans `MANAGED_WINDOWS` sur `closewindow`.
- **Isolation stricte de la configuration dans la suite de tests (`test_video_detect.py`)** :
  - Utilisation d'un `TemporaryDirectory` et réinitialisation du singleton `_CURRENT_CONFIG` pour empêcher les tests de modifier le fichier de configuration réel `~/.config/hyprsmart/config.yaml`.

---

## [0.6.0] - 2026-10-14

### Ajouté
- **Dé-mélange optique direct (`unblend_luminance` dans `win_col.py`)** :
  - Inversion analytique exacte de l'alpha compositing : $L_{pure} = \text{clamp}((L_{captured} - (1 - \alpha) \cdot L_{backdrop}) / \alpha, 0.0, 1.0)$.
  - Suppression totale du clignotement transitoire (flash à 1.0) : la fenêtre transparente est capturée telle quelle et ses couleurs originelles sont restaurées par calcul.
  - Détection immédiate des changements de contenu (ex: passage d'un site sombre à une page web blanche) dès que `windowtitlev2` se stabilise.
- **Profils génériques de classe avec moyenne mobile (`CLASS_PROFILES`)** :
  - Actualisation continue de l'empreinte visuelle de chaque classe d'application via EMA ($70\%$ historique, $30\%$ observation).
  - Régularisation adaptative bayésienne lors du dé-mélange si $\alpha$ est faible pour immuniser le calcul contre le bruit.
- **Verrou réentrant (`RLock`) dans `cache.py`** :
  - Remplacement de `Lock` par `RLock` éliminant tout risque d'auto-deadlock sur les appels imbriqués de cache.
- **Suite de tests unitaire étendue** : 29 tests validant l'inversion optique synthétique, le lissage EMA des classes et la non-régression du moteur.

---

## [0.5.0] - 2026-10-14

### Ajouté
- **Ordonnanceur glissant d'événements (`DebouncedScheduler`)** :
  - Remplacement du throttle fixe par un trailing debounce par clé annulant les timers antérieurs lors de l'arrivée de nouveaux événements.
  - Délais adaptatifs pour laisser le temps aux interfaces de s'initialiser (`openwindow`: 0.70s, `windowtitlev2`: 0.35s, `activewindowv2`: 0.15s).
- **Anti-contamination de transparence des snapshots** :
  - Restauration transitoire de l'opacité à 1.0 (20 ms) avant la capture physique `grim` lorsqu'une fenêtre déjà transparente doit être re-capturée.
  - Évite la pollution des couleurs de la fenêtre par le fond d'écran sous-jacent et les dérives en boucle fermée.
- **Cache hiérarchique avec repli dynamique par classe (`CLASS_CACHE`)** :
  - Apprentissage automatique et dynamique des profils visuels par `window_class` lors de la première capture (aucun code en dur).
  - Élimine 99% des re-captures lors des frappes au clavier ou changements de titre dans les terminaux et éditeurs.
  - Extension de la durée de vie du cache d'instance à 30 minutes (au lieu de 30 secondes).
- **Diffing d'opacité ($\Delta \alpha < 0.03$)** :
  - Court-circuit des dispatches IPC `hyprctl` superflus lorsque l'opacité calculée est déjà appropriée pour le fond d'écran.
  - Suppression des micro-saccades et allègement substantiel de la charge processeur et du compositeur.
- **Suite de tests étendue** : 24 tests unitaires couvrant l'apprentissage de classe, l'annulation de l'ordonnanceur et le diffing d'opacité.

---

## [0.4.0] - 2026-10-14

### Ajouté
- **Détecteur multi-signaux de vidéo (`video_detect.py`)** :
  - Combinaison pondérée de 4 signaux indépendants : invalidation de veille Wayland (`idle_inhibit` $+0.35$), flux audio PipeWire/PulseAudio (`audio_active` $+0.35$), caractéristiques visuelles de scène (`visual_video` $+0.25$) et plein écran (`fullscreen` $+0.15$).
  - Résolution de l'arbre généalogique des processus `/proc/<pid>/status` pour associer les sous-processus audio (ex: Firefox Content Process) à la fenêtre principale.
  - Détection insensible aux faux positifs (Spotify musique seule $S=0.35 < 0.55$) et faux négatifs (vidéo muette $S=0.60 \ge 0.55$).
  - Clamping direct de l'opacité à `video_opacity` (par défaut `1.0`) pour préserver les scènes sombres et l'intégrité visuelle.
- **Gestionnaire dynamique de configuration CLI (`hyprsmart settings`)** :
  - Sous-commande `hyprsmart settings` pour lister tous les réglages et leurs descriptions.
  - Sous-commande `hyprsmart settings <clé> <valeur>` avec validation de type/bornes et sauvegarde persistante dans `config.yaml`.
  - Commande IPC `set_setting` sur `control.sock` permettant la mise à jour à chaud de la mémoire du démon et le recalcul immédiat.
- **Suite de tests étendue** : 19 tests unitaires automatisés couvrant les profils vidéo, audio seul, plein écran, et la validation des réglages.

### Corrigé
- **Format de coordonnées pour `grim`** : Troncature/arrondi entier des coordonnées géométriques dans `capture_window` évitant l'erreur `invalid geometry` de grim lors de l'utilisation de flottants.

---

## [0.3.0] - 2026-10-14

### Ajouté
- **Analyse d'énergie des contours du fond d'écran ($E_{wall}$)** :
  - Opérateur de Sobel 2D en pur NumPy (`compute_sobel_energy`) calculant le gradient spatial haute-fréquence.
  - Mise en cache conjointe de la luminance et de la carte de gradient dans `WALLPAPER_CACHE`.
  - Extension de `Backdrop` avec `p15`, `p85`, `median` et `edge_energy`.
- **Mesure de densité textuelle et dominante de fond ($D_{text}, R_{bg}$)** :
  - Dataclass `WindowVisuals` contenant `text_l`, `bg_l`, `text_density` et `bg_ratio`.
  - Calcul de la proportion de fond uni et détection des pixels de glyphes par gradient sur la capture de fenêtre.
- **Moteur de décision adaptatif (`compute.py`)** :
  - Assouplissement dynamique du contraste cible (jusqu'à 3.0 / 2.8) lorsque le fond d'écran est flouté ou calme ($E_{wall} \le 0.05$).
  - Utilisation des percentiles tronqués ($p15, p85$) pour débloquer la transparence naturelle sur les fenêtres sombres (TTY, VSCode) sans surréaction aux détails spéculaires isolés.
- **Tests unitaires enrichis** : 10 tests automatisés validant Sobel, les terminaux sur fond calme vs texturé, et le déballage rétrocompatible de `WindowVisuals`.

---

## [0.2.0] - 2026-10-13

### Ajouté
- **Interface en ligne de commande (CLI)** complète avec sous-commandes :
  - `start` : Démarrage du démon en arrière-plan détaché (avec option `-f/--foreground`).
  - `stop` : Arrêt gracieux du démon et restauration automatique de l'opacité originale des fenêtres.
  - `reload` : Rechargement à chaud de la configuration YAML et purge des caches.
  - `status` : Affichage de l'état du démon (PID, socket de contrôle, écrans connectés, mapping de wallpapers).
  - `monitor --id <id> --use-wall <path>` : Association persistante d'un fond d'écran par moniteur avec mise à jour en direct.
  - `what-is-it-doing` : Consultation et streaming en direct des logs (`-w/--watch`, `-n/--lines`).
- **Serveur de contrôle IPC** : Écoute sur UNIX Domain Socket (`$XDG_RUNTIME_DIR/hyprsmart/control.sock`) pour la communication CLI $\leftrightarrow$ Démon.
- **Gestionnaire de configuration** : Module `config.py` gérant `~/.config/hyprsmart/config.yaml`.
- **Mise en cache de luminance des wallpapers** : `WALLPAPER_CACHE` indexé par `(chemin, largeur, hauteur, mtime)` évitant les recalculs Lanczos/WCAG répétitifs.
- **Suite de tests unitaires** : 7 tests automatisés (`unittest`) couvrant le découpage matriciel, le contraste WCAG, la résolution de configuration et l'IPC socket.
- **Guide des agents et rapports** : `AGENT.md` et système de rapports de session dans `wiki/reports/`.

### Modifié
- **Correction des coordonnées 2D dans `backdrop.py`** : Découpage matriciel NumPy corrigé en `lum[y0:y1, x0:x1]`.
- **Bornage sécurisé des fenêtres** : Remplacement de `max()` par `min()` pour borner la zone analysée et renvoyer un état neutre si la fenêtre est hors écran.
- **Tolérance aux pannes du socket Hyprland** : Reconnexion automatique avec temporisation lors du rechargement de Hyprland (`.socket2.sock`).
- **Sortie non bufferisée** : `PYTHONUNBUFFERED=1` et `line_buffering=True` pour un affichage instantané des logs.

### Corrigé
- **KeyError 'title'** : Prise en charge sécurisée des cas où aucune fenêtre n'est active dans Hyprland (`hyprctl activewindow -j` retournant `{}`).

---

## [0.1.0] - 2026-10-13

### Ajouté
- Prototype initial (POC) basé sur l'analyse de contraste relatif sRGB (norme WCAG 2.x).
- Écoute des événements Hyprland via le socket UNIX événementiel.
- Première version du cache mémoire de fenêtres (`cache.py`).
- Capture de fenêtre via `grim` et extraction des couleurs dominantes/extrêmes.
