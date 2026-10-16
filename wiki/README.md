# HyprSmart Wiki & Documentation Technique

Bienvenue dans la base de connaissances et de documentation de **HyprSmart** (*Adaptive intelligence for Hyprland*).

Ce wiki centralise les fondements mathématiques, les choix d'architecture logicielle, les comptes-rendus de sessions et les archives historiques du projet.

---

## 1. Organisation du Wiki

Le wiki est structuré en deux grands espaces vivants et un espace d'archivage :

```
wiki/
├── under-the-hood/       # Concepts mathématiques, physiques et algorithmiques
│   ├── archives/         # Architectures dépréciées et notes d'évolution
│   └── README.md         # Sommaire des 9 piliers techniques
├── reports/              # Rapports de session et journal de bord de l'agent IA
│   └── README.md         # Index chronologique et thématique des interventions
└── README.md             # Ce document (index général)
```

---

## 2. Concepts Fondamentaux ([`under-the-hood/`](under-the-hood/README.md))

Explorez la mécanique interne et les démonstrations physiques qui éliminent le besoin de modèles d'IA lourds au profit d'un moteur déterministe sRGB :

1. [**01. Luminance Relative sRGB & Contraste WCAG 2.x**](under-the-hood/01_wcag_relative_luminance.md)  
   *Linéarisation sRGB, pondérations CIE 1931, modélisation optique du mélange alpha et solveur à double contrainte.*
2. [**02. Gradients Spatiaux & Détection de Contours (Sobel)**](under-the-hood/02_spatial_gradient_and_edge_detection.md)  
   *Convolutions 2D, estimation de l'encombrement visuel (*clutter*) et assouplissement adaptatif sur fond uni.*
3. [**03. Analyse du Contenu des Fenêtres**](under-the-hood/03_window_content_analysis.md)  
   *Quantification rapide 12-bits par décalage, extraction du fond dominant et détection de densité textuelle.*
4. [**04. Échantillonnage du Fond d'Écran & Mise en Cache**](under-the-hood/04_wallpaper_sampling_and_caching.md)  
   *Découpe géométrique multi-écrans (*cover mode*), interpolation Lanczos et cache mémoire invalidé par mtime.*
5. [**05. IPC Wayland, Threading & Architecture Système**](under-the-hood/05_wayland_ipc_and_threading.md)  
   *Sockets UNIX Hyprland (`.socket2.sock`), pipeline asynchrone producteur-consommateur et restauration d'opacité.*
6. [**06. Détection Multi-Signaux de Vidéo**](under-the-hood/06_multi_signal_video_detection.md)  
   *Inhibition de mise en veille Wayland, flux audio PipeWire, géométrie plein écran et clamp d'opacité multimédia.*
7. [**07. Caching Dynamique, Exécution Différée & Snapshots**](under-the-hood/07_dynamic_caching_and_deferred_execution.md)  
   *Ordonnanceur glissant (*trailing debounce*), cache mémoire L1/L2, diffing d'opacité et snapshotting sans flash.*
8. [**08. Dé-mélange Optique & Profils de Classe Persistants**](under-the-hood/08_optical_unblending_and_class_profiles.md)  
   *Inversion mathématique du blending alpha ($L_{\text{pure}}$), persistance `profiles.json` et préchargement universel.*
9. [**09. Réévaluation Progressive & Profils Dynamiques Émergents**](under-the-hood/09_progressive_reevaluation_and_dynamic_profiles.md)  
   *Surveillance cadencée annulable (11 ticks, arrêt à 8 stables), court-circuit pixel $32 \times 32$, bascule de polarité et filtre anti-wobble / anti-hunting.*

Consultez également les [**Archives**](under-the-hood/archives/README.md) pour découvrir les technologies explorées puis retirées (ex: le prototype initial Vision-LLM).

---

## 3. Rapports de Session ([`reports/`](reports/README.md))

Conformément à la charte [`AGENT.md`](../AGENT.md), chaque intervention technique donne lieu à un rapport détaillé et daté retraçant :
- Le contexte et le besoin exprimé par l'utilisateur,
- Les diagnostics techniques et les causes racines identifiées,
- Les solutions algorithmiques retenues et leur implémentation,
- Les résultats des suites de tests unitaires et les fichiers modifiés.

Consultez [**`wiki/reports/README.md`**](reports/README.md) pour parcourir l'historique de navigation des 20+ sessions de développement.
