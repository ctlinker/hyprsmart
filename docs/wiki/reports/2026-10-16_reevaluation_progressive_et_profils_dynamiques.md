# Rapport de Session : Réévaluation Progressive Annulable & Profils Dynamiques Émergents

- **Date** : 2026-10-16
- **Version** : `0.8.0`
- **Branche** : `feat/progressive-change`
- **Auteur** : Agent IA Antigravity `[ai]`

---

## 1. Contexte & Demande Utilisateur

L'utilisateur a souhaité concevoir et implémenter sur la branche `feat/progressive-change` un mécanisme de **réévaluation progressive annulable** pour gérer les fenêtres dont le contenu évolue de manière asynchrone après un événement initial (ex: un navigateur chargeant un site web après que `<title>` a changé) :
- **Durée maximale par défaut** : `11` ticks d'une seconde (`reeval_max_ticks = 11`), configurable via `hyprsmart settings`.
- **Arrêt anticipé sur stabilité** : `8` ticks stables consécutifs par défaut (`reeval_stable_ticks = 8`, plage recommandée `7~10`), permettant de franchir les plateaux d'attente réseau/JS de 2 à 4 secondes sans s'arrêter prématurément sur un écran de chargement vide.
- **Émergence d'un profil dynamique par classe** : Mesure à chaque seconde de la variation visuelle ($\Delta V_t$) afin d'estimer la volatilité (`volatility`) et le temps de stabilisation (`settle_time`) propres à chaque classe d'application dans `~/.config/hyprsmart/profiles.json`.

---

## 2. Analyse Technique & Réalisations

### 2.1 Moteur de Réévaluation Progressive (`ProgressiveReevaluator` dans `handle.py`)
- Implémentation de [`ProgressiveSession`](../../src/hyprsmart/daemon/handle.py) et [`ProgressiveReevaluator`](../../src/hyprsmart/daemon/handle.py) orchestrés sur `DebouncedScheduler` :
  - À la réception de `openwindow`, `windowtitlev2` ou d'un `activewindowv2` sur une fenêtre non cachée (ou appartenant à une classe volatile), une session progressive démarre après la capture initiale $t_0$.
  - Chaque seconde (`reeval_interval = 1.0`), `step_tick` capture la fenêtre active et compare ses caractéristiques visuelles à celles du tick précédent via [`visual_delta`](../../src/hyprsmart/opacity/win_col.py) :
    $$\Delta V_t = \max\Big( |L_{\text{bg}}^{(t)} - L_{\text{bg}}^{(t-1)}|, \; |L_{\text{text}}^{(t)} - L_{\text{text}}^{(t-1)}|, \; |R_{\text{bg}}^{(t)} - R_{\text{bg}}^{(t-1)}|, \; |D_{\text{text}}^{(t)} - D_{\text{text}}^{(t-1)}| \Big)$$
  - **Si $\Delta V_t \ge 0.03$** : `stable_ticks` est réinitialisé à `0`, `last_change_tick` est mis à jour, et `apply_window_decision` recalcule et applique la nouvelle opacité si $|\Delta\alpha| \ge 0.03$.
  - **Si $\Delta V_t < 0.03$** : `stable_ticks` est incrémenté. Dès que `stable_ticks >= stable_ticks_target` (8 par défaut) ou `current_tick >= max_ticks` (11 par défaut), la session se termine et enregistre son observation.
  - **Annulation instantanée** : Tout changement de focus vers une autre fenêtre (`activewindowv2`), fermeture (`closewindow`), nouveau titre (`windowtitlev2`) ou détection d'un flux vidéo actif (`evaluate_video_score`) annule immédiatement la session en cours.

### 2.2 Optimisations & Garde-Fous
1. **Court-circuit d'identité pixel ($32 \times 32$)** :
   - [`_quick_thumbnail_array`](../../src/hyprsmart/daemon/handle.py) extrait une miniature $32 \times 32$ (`NEAREST`) en `int16`. Si la géométrie $(x, y, w, h)$ et les pixels sont identiques au tick précédent ($\max |I_t - I_{t-1}| < 1$), le tick est comptabilisé comme stable en $< 0.1\text{ ms}$ sans exécuter la quantification 12-bits, le filtre de Sobel ni le solveur WCAG.
2. **Contournement de régularisation sur inversion de polarité (`win_col.py`)** :
   - Dans [`unblend_luminance`](../../src/hyprsmart/opacity/win_col.py) et [`window_colors`](../../src/hyprsmart/opacity/win_col.py), si $|L_{\text{unblended}} - L_{\text{class\_ref}}| > 0.25$ (bascule franche d'un écran de chargement sombre vers un site web blanc ou inversement), la régularisation par le profil de classe est contournée pour garantir une adaptation immédiate à $100\%$.
3. **Protection de l'EMA de classe (`cache.py`)** :
   - Les ticks intermédiaires mettent à jour uniquement `WIN_CACHE` (`update_class=False`). Le profil persistant `CLASS_PROFILES` (`profiles.json`) n'est mis à jour qu'à la convergence de la session via [`record_class_probing_session`](../../src/hyprsmart/daemon/cache.py).
4. **Profil Dynamique Émergent & Budget Adaptatif (`get_adaptive_reeval_budget`)** :
   - Enrichissement de `WindowVisuals` et `profiles.json` avec `volatility`, `settle_time` et `sample_count`.
   - En phase d'apprentissage (`sample_count < 5`), le budget complet `(11, 8)` est toujours appliqué.
   - Une fois le profil mature (`sample_count >= 5`), les classes prouvées statiques (`volatility < 0.025`, `settle_time <= 1.0s`) réduisent automatiquement leur nombre de ticks requis, tandis que les classes volatiles (navigateurs) conservent la fenêtre complète.

### 2.3 Stabilisation des Modifications Indexées Précédentes
- Correction de `_sanitize_profile_visuals` dans `cache.py` qui plafonnait à tort `text_l` à `0.54` sur les terminaux sombres.
- Raffinement de la pondération `w_trim` dans `compute.py` pour préserver une transparence naturelle ($\alpha \le 0.75$) sur les fonds calmes tout en maintenant une protection stricte sur les fonds texturés.
- Ajustement de `visuals.bg_ratio <= 0.30` dans `video_detect.py`.

---

## 3. Modifications Apportées & Fichiers Touchés

- [`src/hyprsmart/config.py`](../../src/hyprsmart/config.py) : Ajout de `reeval_max_ticks` (`11`), `reeval_stable_ticks` (`8`), `reeval_interval` (`1.0`) et support du type `int` dans `update_setting`.
- [`src/hyprsmart/opacity/win_col.py`](../../src/hyprsmart/opacity/win_col.py) & [`src/hyprsmart/opacity/__init__.py`](../../src/hyprsmart/opacity/__init__.py) : Champs `volatility`, `settle_time`, `sample_count` sur `WindowVisuals`, fonction `visual_delta`, et contournement de régularisation sur inversion de polarité.
- [`src/hyprsmart/daemon/cache.py`](../../src/hyprsmart/daemon/cache.py) : Persistance JSON des métriques temporelles, `record_class_probing_session`, `get_adaptive_reeval_budget`, et correction de `_sanitize_profile_visuals`.
- [`src/hyprsmart/daemon/handle.py`](../../src/hyprsmart/daemon/handle.py) & [`src/hyprsmart/daemon/__init__.py`](../../src/hyprsmart/daemon/__init__.py) : Implémentation de `ProgressiveSession`, `ProgressiveReevaluator`, `_quick_thumbnail_array` et intégration dans le pipeline d'événements.
- [`src/hyprsmart/opacity/compute.py`](../../src/hyprsmart/opacity/compute.py) & [`src/hyprsmart/opacity/video_detect.py`](../../src/hyprsmart/opacity/video_detect.py) : Calibrage du solveur sur fond calme et du seuil `visual_video`.
- [`src/hyprsmart/cli.py`](../../src/hyprsmart/cli.py) : Exposition des nouveaux paramètres dans `status`.
- [`tests/test_progressive_reeval.py`](../../tests/test_progressive_reeval.py) : Nouveaux tests unitaires dédiés.
- [`wiki/under-the-hood/09_progressive_reevaluation_and_dynamic_profiles.md`](../under-the-hood/09_progressive_reevaluation_and_dynamic_profiles.md), [`wiki/under-the-hood/README.md`](../under-the-hood/README.md), [`README.md`](../../README.md), [`AGENT.md`](../../AGENT.md), [`CHANGELOG.md`](../../CHANGELOG.md), [`pyproject.toml`](../../pyproject.toml) (`0.8.0`).

---

## 4. Tests et Vérifications Exécutés

- Exécution de la suite complète : `.venv/bin/python -m unittest discover tests -v`
- **Résultat** : **36 / 36 tests réussis (`OK`)**, incluant :
  - Validation des bornes et types pour `reeval_max_ticks`, `reeval_stable_ticks` et `reeval_interval`.
  - Simulation complète d'un chargement de page web (écran sombre aux ticks 1–2 $\to$ bascule vers une page claire au tick 3 $\to$ court-circuit pixel et convergence après 8 ticks stables au tick 11).
  - Vérification du contournement de régularisation lors d'une inversion de polarité ($L_{\text{bg}} : 0.05 \to 0.95$).
  - Vérification de l'adaptation du budget de ticks entre classes statiques (`foot`) et volatiles (`firefox`).
  - Annulation immédiate de session sur changement de focus ou fermeture.

---

## 5. Prochaines Étapes Suggérées

1. **Observation en conditions réelles** via `hyprsmart what-is-it-doing -w` lors de la navigation sur des sites web variés (SPAs, chargements lents, changements de thèmes) pour affiner si besoin le seuil `PROGRESSIVE_DELTA_THRESHOLD` (`0.03`).
2. **Détection automatique du wallpaper** (`hyprpaper`, `swww`, `waypaper`) et prise en compte du **z-order** multi-fenêtres.
