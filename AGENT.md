# AGENT.md — Guide d'intervention pour les Agents IA sur HyprSmart

Ce document définit les standards d'ingénierie, l'architecture du projet, les conventions de code et les processus opérationnels que tout agent IA intervenant sur le dépôt **HyprSmart** doit impérativement respecter.

---

## 1. Règles Absolues d'Intervention

> [!IMPORTANT]
> **À la fin de CHAQUE requête / session d'intervention, l'agent DOIT :**
> 
> 1. **Consigner un rapport de session** dans le dossier `wiki/reports/`.
>    - **Format du fichier** : `wiki/reports/YYYY-MM-DD_<theme_ou_action>.md`.
>    - **Contenu minimal** :
>      - Contexte & Demande utilisateur
>      - Analyse technique & constatations
>      - Modifications apportées & fichiers touchés
>      - Tests et vérifications exécutés
>      - Prochaines étapes suggérées
> 
> 2. **Effectuer un commit Git avec le flag `[ai]`** dans le message pour différencier clairement les interventions de l'agent de celles du développeur humain.
>    - **Convention de message** : `[ai] <type>: <description>` (ex: `[ai] docs: update AGENT.md and add session report` ou `[ai] fix(opacity): correct numpy coordinate slicing`).

---

## 2. Vision et Nature du Projet

### 2.1 Contexte & Problématique
Sous Hyprland (compositeur Wayland), l'activation de la transparence des fenêtres est esthétique mais pose des problèmes majeurs d'accessibilité et d'ergonomie :
- Perte de contraste en fonction des motifs et couleurs du fond d'écran sous-jacent.
- Dégradation de la lisibilité des textes, documents, codes sources et vidéos.
- Nécessité manuelle fastidieuse d'activer/désactiver la transparence via des raccourcis clavier (`toggleopaque`).

### 2.2 Objectif de HyprSmart
**HyprSmart** est un démon résident pour Hyprland qui ajuste dynamiquement et automatiquement l'opacité de chaque fenêtre active afin de maximiser la transparence sans jamais dégrader la lisibilité, en garantissant un ratio de contraste minimal conforme aux normes WCAG 2.x ($CR \ge 4.5$).

### 2.3 Évolution du Projet
1. **Approche historique (v1 - `old/` & `dataset/`)** : Inférence multimodale locale via Ollama (`qwen3.5:0.8b`). L'IA analysait une capture d'écran pour estimer la présence de vidéo, la densité de texte et de visuels. Dataset constitué dans `dataset/` (193 échantillons). Inconvénient : trop lourd, latence inadaptée au temps réel.
2. **Approche actuelle (`src/hyprsmart/`, branche `feat/rel-luminance`)** : Analyse déterministe temps réel ultra-rapide basée sur la luminance relative sRGB (WCAG) combinant quantification des couleurs de fenêtre, cartographie de luminance du fond d'écran et calcul direct d'opacité.

---

## 3. Analyse du Projet : État Actuel (POC Fonctionnel)

Le projet est aujourd'hui **fonctionnel mais au stade de Proof of Concept (POC)**. La chaîne globale produit un résultat tangible, mais souffre de plusieurs verrous architecturaux avant de prétendre à un statut d'outil de production/MVP.

### 3.1 Ce qui est validé et fonctionnel (POC)
- Connexion temps réel au socket UNIX événementiel de Hyprland (`.socket2.sock`).
- Système de debounce basique évitant le spam d'événements rapprochés.
- Capture d'écran ciblée de la géométrie de fenêtre via `grim`.
- Quantification des couleurs dominantes (fond) et extrêmes (texte) avec calcul de luminance WCAG.
- Algorithme de recherche de l'opacité minimale (`decide_opacity`).
- Application en direct de l'opacité via les commandes `hyprctl`.
- Première couche de cache en mémoire (`cache.py`) avec TTL de 30 secondes basé sur l'adresse et le titre de fenêtre.

### 3.2 Limites et fragilités du POC actuel

| Domaine | Problème constaté | Impact / Risque |
| :--- | :--- | :--- |
| **Wallpaper** | Chemin en dur (`/home/char-c/Pictures/Wallpapers/...gif`) dans `handle.py`. | Ne fonctionne sur aucune autre machine sans ce fichier précis. |
| **Performance** | `load_wallpaper()` est rappelé à chaque événement, même lors d'un cache hit ! | Décodage image / calcul LANCZOS / WCAG répétés, pic CPU inutile. |
| **Indexation 2D** | Dans `backdrop.py` : `lum[x0:x1, y0:y1]` au lieu de `[y0:y1, x0:x1]`, et `x1 = max(...)` au lieu de `min(...)`. | Décalage spatial de la zone d'écran analysée ; risque de crash si coordonnées hors bornes. |
| **Multi-fenêtres** | Suppose que le wallpaper est toujours visible derrière la fenêtre active. | Si d'autres fenêtres opaques sont sous la fenêtre active (z-order), l'analyse du wallpaper est erronée. |
| **Multi-moniteur** | Échelle HiDPI (`scale`) et changements dynamiques d'écrans non synchronisés. | Décalage des coordonnées grim / dimensions du fond d'écran. |
| **Résilience socket** | `socket.py` crashe si une ligne n'a pas `>>` ou si Hyprland redémarre (`hyprctl reload`). | Arrêt du démon sans tentative de reconnexion automatique. |
| **Cycle de vie** | Pas de gestion des signaux d'arrêt (`SIGINT`, `SIGTERM`). | Les fenêtres restent avec leur opacité modifiée à l'extinction du démon sans restauration. |
| **Configuration** | Aucun fichier de configuration ni arguments CLI. | Impossibilité de personnaliser les seuils de contraste, opacité min/max, ou délais. |
| **Qualité / Tests** | Aucun test unitaire ni mock du compositeur. | Régressions faciles lors des refactorings mathématiques. |

---

## 4. Architecture de la Base de Code

```
hyprsmart/
├── dataset/                  # Jeux de données d'échantillons annotés (captures + metadata.json)
├── old/                      # Archives de la v1 (Ollama, datacollect, scripts préliminaires)
├── src/
│   └── hyprsmart/
│       ├── __init__.py       # Point d'entrée principal (hyprsmart:main)
│       ├── daemon/           # Orchestration des événements & threads
│       │   ├── __init__.py
│       │   ├── cache.py      # Cache mémoire des métadonnées de fenêtres (TTL 30s)
│       │   ├── handle.py     # Debounce, files de traitement et workers
│       │   └── socket.py     # Client socket UNIX Hyprland (.socket2.sock)
│       ├── opacity/          # Moteur mathématique de contraste & WCAG
│       │   ├── __init__.py
│       │   ├── backdrop.py   # Rendu wallpaper & échantillonnage de luminance
│       │   ├── compute.py    # Détermination de l'opacité selon le ratio WCAG
│       │   └── win_col.py    # Détection des couleurs fenêtre (fond dominant & texte)
│       └── primitive/        # Wrappers système de bas niveau
│           ├── __init__.py
│           ├── get_mon.py    # État des moniteurs (hyprctl monitors -j)
│           ├── get_win.py    # Fenêtre active et liste clients (hyprctl -j)
│           └── window.py     # Dataclass Window, grim, hyprctl dispatch opacity
├── wiki/
│   └── reports/              # RAPPORTS DE SESSION OBLIGATOIRES (1 par requête)
├── AGENT.md                  # Ce guide
├── pyproject.toml            # Configuration du projet Python (uv)
└── uv.lock                   # Lockfile uv
```

---

## 5. Feuille de Route : Du POC au MVP Stabilisé

Pour faire évoluer ce POC vers une version stable et publiable, les chantiers prioritaires sont :

1. **Phase 1 : Nettoyage & Correction des Bugs Critiques**
   - Corriger le slicing et le clamping des coordonnées dans `backdrop.py` (`lum[y0:y1, x0:x1]` avec `min(...)`).
   - Mettre en cache la matrice de luminance du wallpaper pour ne pas recharger le fichier à chaque événement.
   - Sécuriser le parsing des lignes du socket dans `socket.py` (`split(">>", 1)` avec vérification).

2. **Phase 2 : Configuration & Détection du Wallpaper**
   - Externaliser la configuration (fichier `~/.config/hyprsmart/config.toml`).
   - Implémenter des adaptateurs pour détecter le fond d'écran actif (`hyprpaper`, `swww`, `waypaper`, ou capture directe du background via `grim`).

3. **Phase 3 : Robustesse & Ergonomie Daemon**
   - Reconnexion automatique du socket UNIX si le serveur se ferme.
   - Interception de `SIGINT`/`SIGTERM` pour réinitialiser l'opacité de toutes les fenêtres à 1.0 (ou leur valeur par défaut).
   - Ajout d'une suite de tests unitaires (pytest) pour le calcul de contraste et les fonctions pures.

---

## 6. Commandes et Environnement

- **Lancement** :
  ```bash
  uv run hyprsmart
  ```
- **Vérification d'import** :
  ```bash
  uv run python -c "import hyprsmart; print('OK')"
  ```
- **Ajout de paquets** :
  ```bash
  uv add <nom-du-paquet>
  ```
- **Validation Git** :
  ```bash
  git status
  git commit -m "[ai] <message>"
  ```
