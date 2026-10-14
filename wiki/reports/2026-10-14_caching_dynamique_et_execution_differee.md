# Rapport de Session : Caching Dynamique, Exécution Différée & Préservation des Snapshots

**Date** : 14 Octobre 2026  
**Branche** : `feat/caching-and-deferred-execution`  
**Version** : `0.5.0`  
**Auteur / Agent** : Antigravity `[ai]`

---

## 1. Contexte & Demande Utilisateur

L'utilisateur a mis en avant deux volets interdépendants indispensables pour rendre HyprSmart pleinement fluide et utilisable au quotidien :
1. **L'exécution différée (`deferred execution`)** : Certains événements (création de fenêtre, mise à jour de titre) nécessitent d'attendre que l'interface applicative soit réellement prête et peinte avant capture, évitant de capturer un écran vide ou un splash screen.
2. **La préservation des snapshots (anti-contamination de transparence)** : Si une fenêtre est déjà devenue transparente, `grim` capture le mélange optique de la fenêtre et du fond d'écran, ce qui contamine le profil colorimétrique lors des recalculs futurs.
3. **Le diffing d'opacité** : Déterminer si la transparence actuelle est déjà appropriée pour le fond d'écran avant de déclencher des opérations lourdes ou d'envoyer des commandes de dispatch `hyprctl`.

---

## 2. Analyse & Solutions Implémentées

### 2.1 Ordonnanceur Glissant (`DebouncedScheduler`)
- Remplacement du throttle fixe par un **trailing debounce** par clé (`SCHEDULER.schedule(key, delay, fn)`).
- Tout nouvel événement arrivant avant l'expiration du délai annule le timer précédent (`existing.cancel()`).
- Délais calibrés :
  - `activewindowv2` : 150 ms (réactivité au changement de fenêtre).
  - `windowtitlev2` : 350 ms (attend la fin des frappes au clavier ou du chargement de page).
  - `openwindow` : 700 ms (laisse le temps aux applications lourdes ou Electron de dessiner leur UI).

### 2.2 Anti-Contamination Optique des Snapshots
- Dans `capture_worker` : si la fenêtre a été rendue transparente par HyprSmart (`get_applied_alpha(addr) < 0.99`), l'opacité est temporairement rétablie à 1.0 pendant 20 ms.
- `grim` capture ainsi l'image 100% pure de l'application sans aucune transparence traversante du fond d'écran.
- L'opacité calculée est ensuite appliquée, éliminant tout risque de dérive ou boucle de rétroaction.

### 2.3 Cache Hiérarchique & Apprentissage Dynamique par Classe
- **Niveau 1 (`WIN_CACHE`)** : Instance exacte `address:title`, avec durée de vie portée à **30 minutes** (au lieu de 30 secondes).
- **Niveau 2 (`CLASS_CACHE`)** : Apprentissage dynamique par `window_class` dès la première capture de toute application (zéro configuration codée en dur).
- Lors d'un changement de titre (frappe dans bash/fish, ouverture d'un buffer nvim), le cache d'instance échoue mais le cache de classe fournit immédiatement le profil visuel en mémoire sans prise de capture.

### 2.4 Diffing d'Opacité ($\Delta \alpha < 0.03$)
- Dans `apply_window_decision` : calcul de la variation $|\alpha_{ideal} - \alpha_{current}|$.
- Si $\Delta \alpha < 0.03$, le dispatch IPC `hyprctl` est court-circuité.
- Élimination des micro-scintillements et allègement considérable de la charge CPU et du compositeur.

---

## 3. Fichiers Modifiés & Créés

- **`src/hyprsmart/daemon/cache.py`** :
  - Ajout de `CLASS_CACHE`, `record_applied_state`, `get_applied_alpha`.
  - Extension du TTL à 1800 s et repli dynamique automatique sur la classe.
- **`src/hyprsmart/daemon/handle.py`** :
  - Implémentation de `DebouncedScheduler`.
  - Intégration de la restauration à 1.0 avant capture dans `capture_worker`.
  - Factorisation de la décision dans `apply_window_decision` avec diffing d'opacité ($\Delta \alpha < 0.03$).
- **`tests/test_caching_and_defer.py` [NOUVEAU]** :
  - 5 tests unitaires validant le repli de classe, le tracking d'opacité, le trailing debounce et le diffing d'opacité.
- **`wiki/under-the-hood/07_dynamic_caching_and_deferred_execution.md` [NOUVEAU]** :
  - Documentation théorique détaillée des 4 concepts.
- **`wiki/under-the-hood/README.md`** :
  - Référencement du concept 07.
- **`AGENT.md`** :
  - Mise à jour de la feuille de route.
- **`CHANGELOG.md` & `pyproject.toml`** :
  - Bilan de version et passage à la version `0.5.0`.

---

## 4. Tests et Vérifications

1. **Suite de tests automatisés** :
   ```bash
   uv run python -m unittest discover tests
   ```
   *Résultat* : 24 tests exécutés et validés avec succès en 1.33s.
2. **Vérification du démon en cours d'exécution** :
   - Démarrage et rechargement réussis sous Hyprland.
   - Logs en direct confirmant la prise en compte des décisions d'opacité et des caches.

---

## 5. Prochaines Étapes Suggérées

1. Fusionner la branche `feat/caching-and-deferred-execution` dans `dev`.
2. Détection automatique du fond d'écran actif (via `hyprpaper`, `swww` ou `waypaper`).
3. Prise en charge des fenêtres flottantes / gestion du z-order.
