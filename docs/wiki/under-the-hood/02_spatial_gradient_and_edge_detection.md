# 02. Gradients Spatiaux & Détection de Contours (Sobel)

La luminance moyenne seule ne suffit pas à prédire la lisibilité humaine : un texte blanc sur fond noir semi-transparent reste lisible sur un ciel bleu pur, mais devient illisible sur une photo de branchages très texturés de même luminosité moyenne. 

Ce document détaille l'utilisation des **filtres de gradient spatial** (opérateur de Sobel 2D) pour quantifier l'encombrement visuel (*visual clutter*).

---

## 1. Définition Mathématique du Contour

En traitement d'image, un **contour** (*edge*) correspond à une variation abrupte de luminosité dans l'espace.
Mathématiquement, le contour est modélisé par le **gradient spatial 2D** de la fonction de luminance $I(x, y)$ :

$$\nabla I(x, y) = \left( \frac{\partial I}{\partial x}, \; \frac{\partial I}{\partial y} \right)$$

L'amplitude (ou magnitude) du gradient mesure la force du contour :
$$G(x, y) = \sqrt{ \left(\frac{\partial I}{\partial x}\right)^2 + \left(\frac{\partial I}{\partial y}\right)^2 }$$

- **Zone plate ou floue** : $\nabla I \approx (0, 0) \implies G \approx 0.0$.
- **Caractère typographique / bordure nette** : saut important de luminosité $\implies G \gg 0.1$.

---

## 2. L'Opérateur de Sobel 2D

Dans le domaine discret (grille de pixels), la dérivée est approchée par une convolution avec des noyaux $3 \times 3$ :

$$K_x = \frac{1}{8} \begin{bmatrix} -1 & 0 & 1 \\ -2 & 0 & 2 \\ -1 & 0 & 1 \end{bmatrix}, \quad K_y = \frac{1}{8} \begin{bmatrix} -1 & -2 & -1 \\ 0 & 0 & 0 \\ 1 & 2 & 1 \end{bmatrix}$$

Le noyau de Sobel présente l'avantage de combiner une **dérivation directionnelle** avec un **lissage gaussien perpendiculaire**, ce qui le rend résistant au bruit numérique.

### Implémentation NumPy vectorisée dans `backdrop.py`
Pour une vitesse maximale, HyprSmart effectue cette opération par découpage matriciel sans boucle `for` :
```python
gx = (
    (lum[:-2, 2:] + 2.0 * lum[1:-1, 2:] + lum[2:, 2:])
    - (lum[:-2, :-2] + 2.0 * lum[1:-1, :-2] + lum[2:, :-2])
) / 8.0

gy = (
    (lum[2:, :-2] + 2.0 * lum[2:, 1:-1] + lum[2:, 2:])
    - (lum[:-2, :-2] + 2.0 * lum[:-2, 1:-1] + lum[:-2, 2:])
) / 8.0

sobel_mag = np.sqrt(gx**2 + gy**2)
```

### Prise en compte des motifs fins (Différences Finies Adjacentes)
Le noyau de Sobel compare les colonnes $x+1$ et $x-1$ (écart de 2 pixels). Pour éviter tout effet de repliement de spectre (*aliasing*) sur des motifs alternés de 1 pixel (ex: damier fin), HyprSmart combine Sobel avec la différence absolue des pixels adjacents :
$$\text{mag} = \max(\text{sobel\_mag}, \text{fd})$$

---

## 3. Théorie Psychovisuelle de l'Encombrement (*Visual Clutter*)

### Pourquoi le texte transparent souffre-t-il sur certains fonds ?
Le cortex visuel primaire humain décompose les scènes en bandes de **fréquences spatiales**.
- Les glyphes d'un texte (lettres, code source) sont constitués de **très hautes fréquences spatiales** (traits fins, angles droits, courbes serrées).
- Si le fond d'écran situé derrière est **flouté ou doux** (effet `blur` de Hyprland), il ne contient aucune haute fréquence spatiale. L'œil n'éprouve aucune difficulté à séparer les lettres du fond, même avec un contraste modéré.
- Si le fond d'écran comporte des **contours nets et contrastés** (feuilles d'arbres, briques, écritures), les contours du fond entrent en collision directe avec les traits des lettres (*contour crowding*), détruisant la lisibilité.

---

## 4. Modulation Déterministe du Contraste Cible

HyprSmart calcule l'énergie moyenne des contours de la zone du fond d'écran située sous la fenêtre :
$$E_{wall} = \text{mean}(G_{region}) \in [0.0, 1.0]$$

Le ratio de contraste cible $CR_{eff}$ est alors ajusté dynamiquement :
$$CR_{eff} = \max\left(3.0, \; CR_{base} - \left(1.0 - \frac{E_{wall}}{0.12}\right) \times 1.5\right)$$

| Énergie des contours $E_{wall}$ | Type d'arrière-plan | Seuil de contraste $CR_{eff}$ | Opacité résultante typique |
| :--- | :--- | :--- | :--- |
| $\le 0.03$ | Fond uni, dégradé doux ou flou fort | **$3.0:1$** (WCAG AA large) | Forte transparence ($\alpha \approx 0.65 - 0.75$) |
| $0.03 < E_{wall} < 0.10$ | Fond photographique standard | **$3.5:1 - 4.0:1$** | Transparence modérée ($\alpha \approx 0.80 - 0.85$) |
| $\ge 0.12$ | Motifs très nets, damiers, feuillages | **$4.5:1$** (WCAG AA strict) | Quasi-opaque ($\alpha \approx 0.95 - 1.0$) |

### Élimination des artefacts spéculaires isolés (Percentiles tronqués $p15/p85$)
Sur un fond à faible énergie ($E_{wall} < 0.08$), un unique pixel clair (un reflet ou une étoile isolée) ne doit pas condamner toute la fenêtre à être opaque. HyprSmart teste alors l'intervalle interquartile tronqué ($p15, p85$) au lieu du $p5/p95$ absolu.
