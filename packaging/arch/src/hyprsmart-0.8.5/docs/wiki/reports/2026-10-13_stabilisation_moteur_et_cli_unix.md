# Rapport de Session : Stabilisation du Moteur, CLI HyprSmart & Contrôle par Socket UNIX

- **Date** : 2026-10-13
- **Auteur** : Gemini (Agent IA Antigravity)
- **Branche active** : `feat/rel-luminance`
- **Statut** : Terminé avec succès

---

## 1. Contexte & Demande Utilisateur

L'utilisateur a demandé :
1. De corriger les erreurs et faiblesses techniques identifiées dans le POC.
2. D'introduire une commande de configuration du wallpaper par écran : `hyprsmart monitor --id <mon-id> --use-wall <WALL>`.
3. De concevoir une interface CLI complète (`hyprsmart start`, `hyprsmart stop`, `hyprsmart reload`).
4. De donner un avis technique argumenté sur l'utilisation de FastAPI vs d'autres mécanismes IPC.

---

## 2. Décision Architecturale : UNIX Domain Socket vs FastAPI

Après concertation et approbation de l'utilisateur, l'option **UNIX Domain Socket natif** (`$XDG_RUNTIME_DIR/hyprsmart/control.sock`) a été choisie plutôt que FastAPI pour les raisons suivantes :
- **Alignement avec Wayland / Hyprland** : Protocole léger, direct et standard pour les démons locaux de bureau.
- **Empreinte minimale** : Zéro dépendance supplémentaire (évite d'embarquer Uvicorn/FastAPI en mémoire), temps de réponse < 1 ms, sécurité basée sur les permissions de fichiers POSIX.

---

## 3. Réalisations & Corrections Apportées

### 3.1 Moteur Mathématique & Opacité (`opacity/backdrop.py`)
- **Correction du découpage matriciel** : Inversion des axes corrigée en `lum[y0:y1, x0:x1]` (lignes = Y, colonnes = X en NumPy).
- **Protection des bornes** : Utilisation de `min()` et validation des zones vides (fenêtres minimisées ou hors écran) pour éviter les crashs de percentiles.
- **Cache de luminance des fonds d'écran** : Implémentation de `get_cached_wallpaper_luminance(path, monitor_w, monitor_h)` qui met en cache la matrice de luminance calculée par écran (`(path, w, h, mtime)`). Élimine le décodage Lanczos et les calculs WCAG répétitifs à chaque événement.

### 3.2 Résilience du Démon (`daemon/socket.py` & `daemon/handle.py`)
- **Tolérance aux erreurs sur le socket Hyprland** : Parsing sécurisé des lignes événementielles sans crash si le délimiteur `>>` est manquant. Reconnexion automatique avec temporisation si Hyprland redémarre.
- **Gestion dynamique des fonds d'écran** : Suppression du chemin hardcodé au profit de la résolution dynamique via `config.py` et le nom/ID de l'écran actif.
- **Arrêt gracieux & restauration d'opacité** : Suivi des fenêtres modifiées (`MANAGED_WINDOWS`) et réinitialisation de leur opacité à 1.0 à l'extinction du démon.

### 3.3 Configuration & Persistance (`config.py`)
- Gestion du fichier de configuration `~/.config/hyprsmart/config.yaml`.
- Support de l'association d'un fond d'écran par ID d'écran (`0`, `1`) ou par nom (`eDP-1`, `DP-1`), avec wallpaper par défaut en fallback.

### 3.4 Serveur de Contrôle & Commandes CLI (`daemon/control_server.py` & `cli.py`)
- Serveur de contrôle IPC non-bloquant en écoute sur `$XDG_RUNTIME_DIR/hyprsmart/control.sock`.
- Commandes CLI implémentées :
  - `hyprsmart start [-f/--foreground]` : Démarre le démon en tâche de fond (détaché) ou au premier plan.
  - `hyprsmart stop` : Envoie l'ordre d'arrêt via socket (ou signal SIGTERM), restaure les fenêtres et nettoie le PID file.
  - `hyprsmart reload` : Recharge la configuration YAML et purge les caches de luminance à chaud.
  - `hyprsmart status` : Affiche l'état du démon (PID, socket, moniteurs détectés et wallpapers configurés).
  - `hyprsmart monitor --id <id> --use-wall <path>` : Associe un fond d'écran à un écran et notifie immédiatement le démon actif.

---

## 4. Tests et Vérifications

1. **Tests unitaires (`tests/test_opacity_and_config.py` & `tests/test_control_server.py`)** :
   - 6 tests unitaires exécutés via `uv run python -m unittest discover tests`.
   - Résultat : 100% succès en 0.125s (test du slicing matriciel, fallback hors écran, calcul de contraste, résolution de config et communication IPC round-trip).
2. **Tests d'intégration CLI** :
   - `hyprsmart monitor --id 0 --use-wall ...` -> Sauvegarde validée.
   - `hyprsmart start` -> Démon lancé en arrière-plan (PID vérifié).
   - `hyprsmart status` -> Affiche `Status: RUNNING` avec socket actif.
   - `hyprsmart reload` -> Acquittement et rechargement validés.
   - `hyprsmart stop` -> Processus arrêté proprement et PID libéré.

---

## 5. Fichiers Modifiés et Créés

- `src/hyprsmart/__init__.py` (point d'entrée)
- `src/hyprsmart/__main__.py` (nouveau)
- `src/hyprsmart/cli.py` (nouveau)
- `src/hyprsmart/config.py` (nouveau)
- `src/hyprsmart/daemon/control_server.py` (nouveau)
- `src/hyprsmart/daemon/handle.py` (corrigé)
- `src/hyprsmart/daemon/socket.py` (sécurisé)
- `src/hyprsmart/daemon/cache.py` (ajout `cache_clear`)
- `src/hyprsmart/daemon/__init__.py` (exports mis à jour)
- `src/hyprsmart/opacity/backdrop.py` (corrigé avec cache)
- `src/hyprsmart/opacity/__init__.py` (exports mis à jour)
- `src/hyprsmart/primitive/get_mon.py` (ajout `id` et `get_hyprland_monitors`)
- `src/hyprsmart/primitive/__init__.py` (exports mis à jour)
- `tests/test_opacity_and_config.py` (nouveau)
- `tests/test_control_server.py` (nouveau)
- `AGENT.md` (mis à jour)
- `wiki/reports/2026-10-13_stabilisation_moteur_et_cli_unix.md` (ce rapport)
