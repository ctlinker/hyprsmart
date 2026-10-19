# Archives — Concepts et Architectures Dépréciés de HyprSmart

Ce dossier regroupe la documentation technique des architectures, algorithmes et technologies qui ont fait partie de HyprSmart par le passé mais qui ont été retirés ou remplacés.

---

## 1. Règle d'Archivage

> [!IMPORTANT]
> **Règle absolue pour tout contributeur ou agent IA** :
> Lorsqu'un concept, un modèle ou un composant algorithmique présent dans `wiki/under-the-hood/` est retiré de la base de code active, son document explicatif **ne doit jamais être purement supprimé**.
> 
> Il doit être déplacé dans ce dossier `archives/` avec :
> 1. La description technique détaillée de son fonctionnement historique.
> 2. Les raisons objectives de son abandon (performances, latence, complexité, robustesse).
> 3. La solution moderne qui lui a succédé dans HyprSmart.

---

## 2. Sommaire des Archives

| Fichier | Période | Technologie d'origine | Remplacé par |
| :--- | :--- | :--- | :--- |
| [**00_vision_llm_v1.md**](00_vision_llm_v1.md) | Prototype initial (v1) | Vision-LLM local (`ollama`, modèle `qwen3.5:0.8b`) | Vision déterministe sRGB WCAG 2.x & Sobel 2D |
