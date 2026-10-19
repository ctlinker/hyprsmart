# Archive : Inférence Multimodale par Vision-LLM (v1)

- **Statut** : Archivé / Remplacé
- **Période active** : Version initiale (v1, présente dans le dossier `old/`)
- **Remplacé par** : Analyse déterministe par luminance relative WCAG 2.x et gradients spatiaux Sobel 2D (`src/hyprsmart/opacity/`)

---

## 1. Description du Concept Initial

Dans sa première mouture (v1), HyprSmart tentait de déterminer l'opacité idéale d'une fenêtre en faisant appel à un **modèle de langage visuel multimodal (VLM)** exécuté localement via le serveur **Ollama**.

### Implémentation historique (`old/opacity.py`) :
Lorsqu'une fenêtre était activée, une capture d'écran était transmise au modèle `qwen3.5:0.8b` avec une consigne structurée pour prédire les propriétés de l'image au format YAML :

```python
response = ollama.chat(
    model="qwen3.5:0.8b",
    stream=False,
    think=False,
    messages=[{
        "role": "user",
        "content": """
        Analyze this window screenshot.

        Return YAML with:
        ```yaml
        video: boolean
        text_density: number from 0 to 1
        visual_density: number from 0 to 1
        contrast: number from 0 to 1
        ```
        """,
        "images": [img_byte],
    }],
)
```

Le résultat était ensuite analysé par une fonction heuristique :
```python
def decide_opacity(state: VisualState) -> float:
    if state.video:
        return 1.0
    if state.text_density > 0.7:
        return 1.0
    if state.visual_density > 0.8:
        return 0.95
    return 0.85
```

---

## 2. Le Dataset d'Entraînement / Évaluation (`dataset/`)

Pour évaluer la fiabilité des réponses du modèle, un pipeline de collecte avait été mis en place (`old/daemon/datacollect.py`), générant 193 échantillons dans le dossier `dataset/`.

Chaque échantillon contient :
- `image.png` : La capture d'écran brute de la fenêtre au moment de l'événement.
- `metadata.json` : Horodatage, dimensions, titre de la fenêtre, et la prédiction brute émise par le modèle.

---

## 3. Raisons de l'Abandon et Remplacement

Bien que séduisante sur le plan conceptuel, cette approche par Vision-LLM s'est heurtée à des limites rédhibitoires pour un démon de bureau temps réel :

1. **Latence d'inférence prohibitive** :
   - Même un petit modèle de 0.8 milliard de paramètres mettait entre **800 ms et 2500 ms** pour analyser une seule capture d'écran sur GPU/NPU, et plusieurs secondes sur CPU.
   - Cette latence provoquait des saccades et des retards inacceptables lors du changement de focus entre fenêtres.
2. **Consommation mémoire et énergétique excessive** :
   - Maintenir un runtime d'inférence LLM résident en VRAM/RAM monopolisait entre 1 et 2 Go de mémoire pour une tâche qui ne relève au fond que de l'optique et de la géométrie 2D.
3. **Instabilité et non-déterminisme** :
   - Les modèles génératifs souffraient occasionnellement d'hallucinations de format (blocs Markdown mal fermés, valeurs aberrantes hors de l'intervalle $[0, 1]$).
4. **Indifférence au fond d'écran réel** :
   - Le modèle analysait la fenêtre isolée, sans aucune connaissance de l'image de fond d'écran située en dessous sur le moniteur.

---

## 4. La Solution Moderne (v2 & v3 Déterministe)

Le remplacement complet du VLM par des formules déterministes (linéarisation sRGB WCAG 2.x, convolution Sobel 2D et quantification 12-bits) a permis :
- De réduire le temps de calcul à **moins de 2 millisecondes** (soit un gain de vitesse de $\times 500$).
- De supprimer toute dépendance à un serveur Ollama externe ou à un GPU dédié.
- D'obtenir un comportement 100% prédictible, stable et reproductible.
