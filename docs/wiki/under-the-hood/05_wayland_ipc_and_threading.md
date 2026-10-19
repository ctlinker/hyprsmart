# 05. IPC Wayland, Threading & Architecture Système

Pour fonctionner comme un démon invisible, performant et parfaitement intégré à l'environnement de bureau, HyprSmart s'appuie sur les mécanismes système du compositeur **Hyprland** (Wayland) et une architecture multi-threadée par files de messages.

Ce document décrit le cycle de vie des événements, la séparation des tâches et le serveur de contrôle IPC.

---

## 1. Intégration Système avec Hyprland

Hyprland expose deux sockets UNIX locaux dans l'arborescence `$XDG_RUNTIME_DIR/hypr/$HYPRLAND_INSTANCE_SIGNATURE/` :
1. **`.socket2.sock` (Flux d'événements)** : Socket en lecture seule diffusant en continu tous les événements internes du compositeur (`activewindowv2`, `windowtitlev2`, `openwindow`, `workspace`, etc.) sous forme de lignes texte formatées :
   ```
   activewindowv2>>0x5630fc98e320,Creation Of Agent File
   ```
2. **`.socket.sock` (Commandes / Dispatcher)** : Socket de contrôle permettant d'exécuter des commandes de gestion de fenêtres sans passer par un serveur intermédiaire (également invoqué via l'utilitaire `hyprctl`).

### Résilience et reconnexion automatique (`src/hyprsmart/daemon/socket.py`)
Si le compositeur est rechargé par l'utilisateur (`hyprctl reload`) ou redémarré, la connexion socket est rompue. HyprSmart intercepte la fermeture du flux et tente automatiquement de se reconnecter toutes les secondes avec résolution dynamique de l'instance courante, évitant tout arrêt intempestif du démon.

---

## 2. Débruitage et Temporisation des Événements (Debounce)

Lors de la saisie au clavier dans un navigateur ou un terminal, le titre de la fenêtre peut changer plusieurs dizaines de fois par seconde (ex: compteurs, indicateurs de saisie).

### Mécanisme de filtrage :
- **`debounce_ev(kind)`** : Rejette tout événement du même type survenant à un intervalle inférieur à `debounce_interval` (défaut : $0.1$ s).
- **`EVENT_DELAYS`** : Applique un léger différé avant capture selon la nature de l'événement pour laisser le compositeur et l'application terminer leur cycle de rendu :
  - `activewindowv2` : 0.3 s (changement de focus)
  - `windowtitlev2` : 0.4 s (mise à jour du titre)
  - `openwindow` : 1.5 s (création initiale de la fenêtre graphique)

---

## 3. Architecture Multi-Threadée (Producteur - Consommateur)

Pour ne jamais bloquer la boucle d'écoute du socket Wayland, le traitement est délégué à trois files d'attente thread-safe (`queue.Queue`) animées par des workers dédiés :

```
             ┌─────────────────────────────┐
             │ Écouteur Socket .socket2.sock │
             └──────────────┬──────────────┘
                            │ (Déclenchement d'événement)
                            ▼
                    ┌───────────────┐
                    │  Cache Hit ?  │
                    └───┬───────┬───┘
               Oui      │       │     Non
         ┌──────────────┘       └──────────────┐
         ▼                                     ▼
 ┌─────────────────┐                  ┌─────────────────┐
 │ CACHE_HIT_QUEUE │                  │  CAPTURE_QUEUE  │
 └────────┬────────┘                  └────────┬────────┘
          │ (Calcul direct sans capture)        │ (Worker grim)
          │                                     ▼
          │                            ┌─────────────────┐
          │                            │ LUMINANCE_QUEUE │
          │                            └────────┬────────┘
          │                                     │ (Worker analyse)
          └─────────────────┬───────────────────┘
                            ▼
              ┌───────────────────────────┐
              │ Moteur Contraste & Opacité│
              └─────────────┬─────────────┘
                            ▼
              ┌───────────────────────────┐
              │  hyprctl dispatch opacity │
              └───────────────────────────┘
```

1. **`capture_worker`** : Exécute `grim -g "<x>,<y> <w>x<h>" -` pour extraire les octets PNG de la géométrie de fenêtre active, puis transmet le tampon à `LUMINANCE_QUEUE`.
2. **`luminance_worker`** : Analyse la vignette PNG (`window_colors`), enregistre les métriques dans le cache de fenêtre, extrait le fond d'écran correspondant, résout l'opacité et envoie la commande à Hyprland.
3. **`cache_hit_worker`** : Si la fenêtre est déjà connue et n'a pas changé de titre depuis moins de 30 secondes, l'étape de capture d'écran est entièrement sautée. Le calcul de transparence s'exécute directement en mémoire vive en moins de $0.3$ ms.

---

## 4. Serveur de Contrôle IPC (`control.sock`)

HyprSmart héberge son propre serveur de communication inter-processus via un socket UNIX dédié :
$$\text{Socket Path} = \$XDG\_RUNTIME\_DIR/\text{hyprsmart/control.sock}$$

### Protocole JSON par ligne
Toute commande envoyée par le CLI (`hyprsmart start`, `stop`, `reload`, `status`, `monitor`) est sérialisée en JSON terminé par un saut de ligne `\n` :
- `{"cmd": "ping"}` $\rightarrow$ `{"status": "ok", "message": "pong"}`
- `{"cmd": "status"}` $\rightarrow$ État du démon, PID, moniteurs et wallpapers.
- `{"cmd": "reload"}` $\rightarrow$ Recharge la configuration YAML et purge les caches de luminance.
- `{"cmd": "set_monitor_wall", "monitor": "0", "wallpaper": "..."}` $\rightarrow$ Mise à jour du wallpaper à chaud.
- `{"cmd": "stop"}` $\rightarrow$ Arrêt propre du démon.

---

## 5. Arrêt Gracieux et Restauration d'Opacité

Un démon d'accessibilité ne doit jamais laisser l'environnement graphique dans un état dégradé à sa fermeture.

1. **Suivi des fenêtres modifiées (`MANAGED_WINDOWS`)** : Chaque fenêtre dont l'opacité est modifiée par HyprSmart voit son adresse enregistrée dans un ensemble protégé par verrou (`threading.Lock`).
2. **Interception des signaux POSIX** : Le démon intercepte `SIGINT` (Ctrl+C) et `SIGTERM` (arrêt système ou commande `hyprsmart stop`).
3. **Restauration universelle (`restore_all_managed_windows`)** : Avant de terminer son processus, HyprSmart réinitialise l'opacité active et inactive de toutes les fenêtres gérées à `1.0` via `hyprctl dispatch` et supprime son fichier de verrouillage PID.
