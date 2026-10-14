# Journal des Modifications (CHANGELOG)

Toutes les modifications notables apportées à ce projet sont consignées dans ce fichier.
Le format est basé sur [Keep a Changelog](https://keepachangelog.com/fr/1.0.0/) et ce projet adhère à [Semantic Versioning](https://semver.org/lang/fr/).

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
