# Rapport de Session : Détection Multi-Signaux de Vidéo & Commande `hyprsmart settings`

**Date** : 14 Octobre 2026  
**Branche** : `feat/video-detection`  
**Version** : `0.4.0`  
**Auteur / Agent** : Antigravity `[ai]`

---

## 1. Contexte & Demande Utilisateur

L'utilisateur a validé l'idée d'un détecteur vidéo multi-niveaux et a demandé :
1. L'implémentation de la détection de lecture vidéo afin d'éviter la transparence sur les fenêtres affichant des scènes vidéo/films (évite de laver les couleurs et de dégrader les scènes sombres).
2. L'introduction d'un paramètre `video_opacity` et d'une commande CLI `hyprsmart settings <clé> <valeur>` permettant de modifier dynamiquement les réglages du démon.
3. Le respect continu des conventions d'ingénierie : mise à jour de `CHANGELOG.md`, bump de version SemVer, documentation sous `wiki/under-the-hood/`, rapport de session et commit avec flag `[ai]`.

---

## 2. Analyse Technique & Architecture Développée

### 2.1 Détecteur Multi-Signaux Déterministe (`video_detect.py`)
Pour détecter les flux vidéo de manière fiable sans IA lourde, 4 signaux complémentaires sont interrogés :
- **`idle_inhibit` (Poids 0.35)** : Extraction du protocole Wayland idle-inhibitor via l'IPC Hyprland (`win.inhibiting_idle`). Actif sur Firefox, Chromium, MPV, VLC en cours de lecture.
- **`audio_active` (Poids 0.35)** : Requête PipeWire/PulseAudio via `pactl --format=json list sink-inputs`. Vérification des flux actifs non-corked/non-mutés et résolution de l'arbre des processus `/proc/<pid>/status` (`PPid`) pour relier les moteurs de rendu enfants au PID de la fenêtre.
- **`visual_video` (Poids 0.25)** : Analyse du profil visuel (`bg_ratio < 0.40` et `text_density < 0.20`), typique d'une scène photographique ou cinématographique continue sans aplat de couleur ni abondance de glyphes.
- **`fullscreen` (Poids 0.15)** : Mode plein écran extrait de Hyprland (`win.fullscreen`).

**Règle de décision** :
$$\text{is\_video} = (S_{video} \ge 0.55)$$
- Les vidéos avec audio (ex: YouTube) atteignent un score $\ge 0.70$ (détectées).
- Les vidéos muettes atteignent $0.60$ (détectées).
- La musique seule (Spotify) plafonne à $0.35$ (non-vidéo, transparence normale préservée).

### 2.2 Commande `hyprsmart settings`
- `hyprsmart settings` : Affiche l'ensemble des paramètres actuels avec leur description.
- `hyprsmart settings <clé> <valeur>` : Valide le type et les bornes autorisées, enregistre dans `~/.config/hyprsmart/config.yaml` et notifie le démon actif via le socket UNIX `control.sock` (`cmd: set_setting`) pour recalculer immédiatement la fenêtre active.

### 2.3 Correctif Géométrie `grim`
Les coordonnées flottantes issues de Hyprland (`x=409.0, y=67.0`) provoquaient un rejet par `grim -g` (`invalid geometry`). Un formatage entier explicite `int(round(...))` a résolu le problème.

---

## 3. Fichiers Modifiés & Créés

- **`src/hyprsmart/primitive/window.py`** :
  - Dataclass `Window` enrichie avec `pid`, `inhibiting_idle`, `fullscreen`, `window_class`.
  - Formatage entier dans `capture_window` pour la compatibilité `grim`.
- **`src/hyprsmart/opacity/video_detect.py` [NOUVEAU]** :
  - Détecteur multi-signaux, parseur PipeWire et parcours de parenté `/proc`.
- **`src/hyprsmart/opacity/__init__.py`** :
  - Export de `evaluate_video_score`, `get_active_audio_pids`, `is_pid_emitting_audio`.
- **`src/hyprsmart/config.py`** :
  - Ajout de `video_opacity: float = 1.0`.
  - Dictionnaire `SETTINGS_METADATA` et fonction de validation `update_setting`.
- **`src/hyprsmart/daemon/handle.py`** :
  - Intégration de l'évaluation vidéo dans `cache_hit_worker` et `luminance_worker` pour appliquer directement `video_opacity`.
- **`src/hyprsmart/cli.py`** :
  - Prise en charge de la commande IPC `set_setting` dans le serveur de contrôle.
  - Implémentation de la commande `hyprsmart settings [clé] [valeur]`.
- **`tests/test_video_detect.py` [NOUVEAU]** :
  - 9 nouveaux tests unitaires pour la matrice de score vidéo et la validation des réglages.
- **`wiki/under-the-hood/06_multi_signal_video_detection.md` [NOUVEAU]** :
  - Documentation approfondie de la théorie et des poids de détection vidéo.
- **`wiki/under-the-hood/README.md`** :
  - Référencement du nouveau concept 06.
- **`AGENT.md`** :
  - Mise à jour de la feuille de route et ajout de `hyprsmart settings` aux commandes.
- **`CHANGELOG.md` & `pyproject.toml`** :
  - Bilan de version et bump en `0.4.0`.

---

## 4. Tests et Vérifications

1. **Tests unitaires automatisés** :
   ```bash
   uv run python -m unittest discover tests
   ```
   *Résultat* : 19 tests exécutés et validés avec succès en 0.12s.
2. **Tests CLI Live** :
   - `uv run hyprsmart settings` -> Affichage de la table des réglages.
   - `uv run hyprsmart settings video_opacity 0.98` -> Sauvegarde YAML et notification IPC au démon.
   - `uv run hyprsmart settings video_opacity 1.5` -> Erreur de validation de borne supérieure.
   - `uv run hyprsmart what-is-it-doing -n 10` -> Confirmation des logs de décision en direct :
     `[DECIDE] alpha: 1.00 (text_dens=0.10, bg_ratio=0.83, wall_edge=0.028) for 0x5630fb6418c0`.

---

## 5. Prochaines Étapes Suggérées

1. Fusionner la branche `feat/video-detection` dans `dev`.
2. Implémenter la détection automatique du fond d'écran actif (via `hyprpaper`, `swww` ou `waypaper`) pour dispenser de l'association manuelle `hyprsmart monitor`.
3. Gestion des fenêtres superposées (z-order) pour les dispositions flottantes.
