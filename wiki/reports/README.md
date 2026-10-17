# Index des Rapports de Session

Ce dossier rassemble les comptes-rendus systématiques des interventions de développement menées sur **HyprSmart**, conformément aux directives de gouvernance définies dans [`AGENT.md`](../../AGENT.md).

---

## 1. Sommaire Thématique par Jalon

### Jalon v0.8.x — Réévaluation Progressive, Anti-Wobble & Durcissement Sécurité
- [**2026-10-17 — Optimisations de performances, réduction CPU & efficacité screencopy (`v0.8.4`)**](2026-10-17_optimisations_performances_et_reduction_cpu.md)  
  *Accélération de grim (-l 0 -s 1, gain 20x), table de correspondance sRGB LUT (gain 6x), élagage des tempêtes windowtitlev2 et suppression du polling statique.*
- [**2026-10-17 — Fusion vers `dev` du durcissement de sécurité & blacklist externe (`v0.8.3`)**](2026-10-17_fusion_dev_durcissement_securite.md)  
  *Intégration de `feat/hardened-security` dans `dev`, bouclier de confidentialité, SO_PEERCRED, bornage des files et blacklist en lecture seule (55 tests réussis).*
- [**2026-10-17 — Externalisation de la blacklist en lecture seule & escalade de privilèges (`v0.8.3`)**](2026-10-17_externalisation_blacklist_et_escalade_privileges.md)  
  *Séparation de `sensitive_classes` dans `blacklist.yaml` (`0o444`), escalade Polkit/sudo atomique via `install -m 0444 -D` et commande CLI `hyprsmart blacklist`.*
- [**2026-10-17 — Durcissement sécurité, surface d'attaque & bouclier de confidentialité (`v0.8.2`)**](2026-10-17_durcissement_securite_et_bouclier_confidentialite.md)  
  *Bouclier de confidentialité pour fenêtres sensibles, authentification SO_PEERCRED, bornage des files à 8 éléments, validation regex des adresses et droits stricts 0o700/0o600.*
- [**2026-10-16 — Fusion vers `dev` de la réévaluation progressive (`v0.8.1`)**](2026-10-16_fusion_dev_reevaluation_progressive.md)  
  *Intégration de `feat/progressive-change` dans `dev`, résolution des divergences et validation intégrale des 38 tests.*
- [**2026-10-16 — Stabilisation anti-wobble & anti-hunting (`v0.8.1`)**](2026-10-16_stabilisation_anti_wobble_reevaluation_progressive.md)  
  *Amortissement exponentiel des micro-sauts d'opacité, atténuation du bruit spatial de texture ($0.50 \times$) et recuit thermique du seuil temporel.*
- [**2026-10-16 — Réévaluation progressive annulable & profils dynamiques émergents (`v0.8.0`)**](2026-10-16_reevaluation_progressive_et_profils_dynamiques.md)  
  *Boucle de 11 ticks avec arrêt à 8 stables, court-circuit pixel $32 \times 32$, bascule franche de polarité et métriques `volatility` / `settle_time` dans `profiles.json`.*
- [**2026-10-16 — Prise de connaissance & audit technique du projet**](2026-10-16_prise_de_connaissance_et_audit_projet.md)  
  *Rapport d'audit global, revue d'architecture, analyse des modifications indexées pour le mode trace développeur et calibrage optique.*

### Jalon v0.7.x — Persistance des Profils & Préchargement au Démarrage
- [**2026-10-14 — Calibrage du contraste cible à 6.0 (Sweet Spot)**](2026-10-14_calibrage_contraste_cible_6.md)  
  *Ajustement ergonomique de la valeur par défaut pour maximiser l'effet esthétique de transparence sans perte de lisibilité.*
- [**2026-10-14 — Fusion vers `dev` et refonte visuelle du README**](2026-10-14_fusion_dev_et_refonte_readme.md)  
  *Intégration du logo HyprSmart, badges, diagrammes Mermaid et documentation unifiée.*
- [**2026-10-14 — Persistance des profils de classe & préchargement universel (`v0.7.0`)**](2026-10-14_profils_persistants_et_prechargement_demarrage.md)  
  *Fichier `~/.config/hyprsmart/profiles.json`, support multi-écrans et adaptation instantanée de toutes les fenêtres au démarrage du démon.*

### Jalon v0.5.x – v0.6.x — Dé-mélange Optique, Caching & Événements
- [**2026-10-14 — Recalibration adaptative du contraste & réactivité événementielle (`v0.6.1`)**](2026-10-14_recalibration_contraste_et_reactivite.md)  
  *Régularisation structurelle, protection de l'espace négatif et réactivité sur focus/mouvement.*
- [**2026-10-14 — Dé-mélange optique (Unblending) & profils génériques (`v0.6.0`)**](2026-10-14_demelange_optique_et_profils_generiques.md)  
  *Déconvolution mathématique de l'alpha compositing pour capturer les couleurs réelles des fenêtres déjà transparentes.*
- [**2026-10-14 — Caching dynamique, exécution différée & préservation des snapshots (`v0.5.0`)**](2026-10-14_caching_dynamique_et_execution_differee.md)  
  *Ordonnanceur `DebouncedScheduler` avec trailing execution, hiérarchie de cache et diffing d'opacité sans clignotement.*

### Jalon v0.4.x — Détection Multimédia & Gestion des Paramètres CLI
- [**2026-10-14 — Fusion sur `dev` & étude d'architecture pour la détection vidéo**](2026-10-14_fusion_dev_et_proposition_detection_video.md)  
  *Étude de faisabilité multi-signaux : Wayland idle-inhibit, PipeWire audio, plein écran et heuristiques visuelles.*
- [**2026-10-14 — Détection multi-signaux de vidéo & commande `hyprsmart settings` (`v0.4.0`)**](2026-10-14_detection_video_multi_signaux_et_cli_settings.md)  
  *Gestionnaire interactif CLI des paramètres avec persistance YAML et clamp d'opacité pour vidéos.*

### Jalon v0.1.x – v0.3.x — Fondations, Algorithmes Sobel & Contrôle IPC
- [**2026-10-14 — Implémentation des contours Sobel & de la densité textuelle**](2026-10-14_implementation_contours_et_densite_textuelle.md)  
  *Calcul d'énergie de gradient 2D sur le fond d'écran et estimation du taux d'espace négatif.*
- [**2026-10-14 — Fusion sur `dev` & création de la branche `feat/edge-density`**](2026-10-14_merge_dev_et_creation_branche_edge_density.md)  
  *Validation des jalons de relative luminance et initialisation de l'analyse spatiale.*
- [**2026-10-14 — Création de `wiki/under-the-hood/` & politique d'archivage**](2026-10-14_creation_wiki_under_the_hood_et_archives.md)  
  *Structuration de la documentation vivante et archivage du prototype Vision-LLM v1.*
- [**2026-10-13 — Stabilisation du moteur, CLI HyprSmart & contrôle par socket UNIX**](2026-10-13_stabilisation_moteur_et_cli_unix.md)  
  *Commandes `start`, `stop`, `reload`, `status`, et serveur IPC UNIX de contrôle.*
- [**2026-10-13 — Commande CLI `what-is-it-doing` & flux de logs**](2026-10-13_commande_what_is_it_doing_et_logs.md)  
  *Visualisation temps réel de l'état du démon et journalisation explicite.*
- [**2026-10-13 — Création de `CHANGELOG.md` & recherche sur la décision déterministe**](2026-10-13_changelog_et_reflexion_decision_deterministe.md)  
  *Abandon du Vision-LLM local au profit de la formule WCAG 2.1 déterministe.*
- [**2026-10-13 — Intégration de la règle de commit `[ai]` & diagnostic du POC**](2026-10-13_analyse_poc_et_regle_commit.md)  
  *Adoption des conventional commits préfixés par `[ai]` et diagnostic de latence.*
- [**2026-10-13 — Prise de connaissance initiale & création d'`AGENT.md`**](2026-10-13_initialisation_agent_md.md)  
  *Formalisation de la charte de pair-programming et des conventions de contribution.*
