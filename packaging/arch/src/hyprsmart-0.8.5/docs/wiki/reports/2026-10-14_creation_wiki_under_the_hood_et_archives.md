# Rapport de Session : Création de `wiki/under-the-hood/` et des Archives

- **Date** : 2026-10-14
- **Auteur** : Gemini (Agent IA Antigravity)
- **Branche active** : `feat/edge-density`
- **Version actuelle** : `0.3.0`
- **Statut** : Terminé avec succès

---

## 1. Contexte & Demande Utilisateur

L'utilisateur a demandé :
1. De créer et peupler un dossier `wiki/under-the-hood/` expliquant les concepts fondamentaux qui rendent HyprSmart possible.
2. D'établir une règle d'archivage stricte : si un composant ou un concept est retiré ou remplacé, son document ne doit pas être supprimé mais déplacé dans `wiki/under-the-hood/archives/`.

---

## 2. Réalisations Documentaires

### 2.1 Documentation des Concepts Actifs (`wiki/under-the-hood/`)
Cinq documents approfondis ont été créés, détaillant les piliers mathématiques, optiques, algorithmiques et système du projet :

1. [**`README.md`**](file:///home/char-c/Projects/hyprsmart/hyprsmart/wiki/under-the-hood/README.md) : Vue d'ensemble du pipeline en diagramme Mermaid, index des concepts et règle d'archivage.
2. [**`01_wcag_relative_luminance.md`**](file:///home/char-c/Projects/hyprsmart/hyprsmart/wiki/under-the-hood/01_wcag_relative_luminance.md) : Délinéarisation gamma sRGB, coefficients photométriques CIE 1931 ($0.2126 R + 0.7152 G + 0.0722 B$), formule du contraste WCAG ($+0.05$ de réflexion parasite) et modélisation du mélange alpha.
3. [**`02_spatial_gradient_and_edge_detection.md`**](file:///home/char-c/Projects/hyprsmart/hyprsmart/wiki/under-the-hood/02_spatial_gradient_and_edge_detection.md) : Opérateur de convolution Sobel 2D en pur NumPy, différences finies adjacentes, théorie psychovisuelle de l'encombrement (*visual clutter*), modulation du contraste cible ($CR_{eff}$) et percentiles tronqués $p15/p85$.
4. [**`03_window_content_analysis.md`**](file:///home/char-c/Projects/hyprsmart/hyprsmart/wiki/under-the-hood/03_window_content_analysis.md) : Réduction d'échelle ($512 \times 512$), quantification 12-bits par décalage de bits (`rgb >> 4`), détection du fond dominant, extraction du texte (percentiles extrêmes) et mesure de la densité textuelle ($D_{text}$).
5. [**`04_wallpaper_sampling_and_caching.md`**](file:///home/char-c/Projects/hyprsmart/hyprsmart/wiki/under-the-hood/04_wallpaper_sampling_and_caching.md) : Sous-échantillonnage `DOWN = 4`, redimensionnement Lanczos en mode *cover*, projection géométrique des coordonnées Hyprland vers NumPy (`lum[y, x]`), et cache conjoint luminance/gradient basé sur `mtime`.
6. [**`05_wayland_ipc_and_threading.md`**](file:///home/char-c/Projects/hyprsmart/hyprsmart/wiki/under-the-hood/05_wayland_ipc_and_threading.md) : Sockets UNIX Hyprland (`.socket2.sock`), filtrage par debounce, architecture multi-threadée producteur-consommateur (`CAPTURE_QUEUE`, `LUMINANCE_QUEUE`, `CACHE_HIT_QUEUE`), serveur de contrôle IPC (`control.sock`) et restauration d'opacité à l'arrêt (`SIGINT`/`SIGTERM`).

### 2.2 Dossier d'Archivage (`wiki/under-the-hood/archives/`)
- [**`README.md`**](file:///home/char-c/Projects/hyprsmart/hyprsmart/wiki/under-the-hood/archives/README.md) : Politique d'archivage formelle pour les futurs contributeurs et agents IA.
- [**`00_vision_llm_v1.md`**](file:///home/char-c/Projects/hyprsmart/hyprsmart/wiki/under-the-hood/archives/00_vision_llm_v1.md) : Archive technique de la v1 (inférence Vision-LLM via Ollama `qwen3.5:0.8b`, prédictions YAML et constitution du dataset de 193 échantillons), expliquant pourquoi cette approche a été abandonnée au profit du déterministe (latence de 2s vs 2ms, mémoire, stabilité).

### 2.3 Règle Pérennisée dans `AGENT.md`
- Ajout de la **Règle 4** dans la section 1 de `AGENT.md` imposant la maintenance de `wiki/under-the-hood/` et l'interdiction de supprimer des concepts (obligation de déplacement dans `archives/`).

---

## 3. Validation & Traçabilité

- Suite de tests unitaires exécutée : 10 tests passés avec succès.
- Commit Git réalisé avec le préfixe conventionnel `[ai]`.
