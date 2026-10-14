# 03. Analyse du Contenu des Fenêtres

Pour ajuster l'opacité sans introduire de latence perceptible, HyprSmart doit être capable d'extraire les propriétés visuelles clés d'une fenêtre (couleur dominante de fond, luminosité du texte, densité des glyphes) en **moins de 5 millisecondes**, sans modèle de deep learning ni OCR lourd.

Ce document décrit les techniques de quantification rapide et d'analyse spatiale mises en œuvre dans `src/hyprsmart/opacity/win_col.py`.

---

## 1. Réduction d'Échelle (Thumbnailing)

La capture d'écran brute d'une fenêtre haute définition (ex: $1920 \times 1080$ ou $3840 \times 2160$) représente plusieurs millions de pixels.
- Le flux d'octets PNG capturé via `grim` est décodé par Pillow.
- L'image est immédiatement redimensionnée en une vignette de $512 \times 512$ pixels maximum via `img.thumbnail()`.
- Cette réduction divise la complexité algorithmique par un facteur de $10$ à $40$ tout en préservant fidèlement la distribution statistique des couleurs et des bordures de texte.

---

## 2. Détection du Fond par Quantification 12-bits (Bit-Shifting)

### Le piège de l'histogramme RGB direct
Un espace 24-bits classique comporte $256^3 \approx 16.7$ millions de couleurs possibles. Si l'on cherche simplement la valeur de pixel la plus fréquente (`mode`), le moindre dégradé subtil, bruit de rendu ou anti-aliasing disperse les pixels sur des milliers de valeurs légèrement différentes (ex: `#1e1e1e` vs `#1f1e1e`), empêchant de détecter le vrai fond uni.

### La quantification par troncature de bits
HyprSmart tronque les 4 bits de poids faible de chaque canal RGB (`rgb >> 4`), réduisant chaque composante de 256 à 16 niveaux :

$$q_{channel} = \lfloor V_{channel} / 16 \rfloor \in [0, 15]$$

Le nombre total de couleurs possibles est réduit à $16^3 = 4096$ casiers (*bins*).

### Empaquetage entier 12-bits (Bit-Packing)
Les trois composantes quantifiées sont combinées en un seul entier 32-bits par décalage logique :
```python
q = (rgb >> 4).reshape(-1, 3).astype(np.int32)
packed = (q[:, 0] << 8) | (q[:, 1] << 4) | q[:, 2]
```

### Extraction de la couleur de fond dominante
L'histogramme est ensuite calculé instantanément par `np.unique` :
```python
vals, counts = np.unique(packed, return_counts=True)
top_idx = counts.argmax()
top = vals[top_idx]
bg_ratio = float(counts[top_idx] / len(packed))
```
La couleur dominante est convertie en son centre de casier :
$$\text{RGB}_{bg} = \left( (top \gg 8) \times 16 + 8, \; (top \gg 4 \& 15) \times 16 + 8, \; (top \& 15) \times 16 + 8 \right)$$
Puis sa luminance relative $L_{bg}$ est calculée par la formule WCAG.

---

## 3. Extraction de la Luminance du Texte ($L_{text}$)

Le texte et les éléments interactifs d'une interface graphique sont par définition conçus pour contraster avec le fond :
- Si le fond est sombre ($L_{bg} < 0.5$) : le texte se trouve dans les **hauts percentiles** de luminance.
- Si le fond est clair ($L_{bg} \ge 0.5$) : le texte se trouve dans les **bas percentiles**.

Pour éliminer d'éventuels pixels d'artefacts isolés (curseur clignotant blanc sur fond clair, ou pixel mort noir sur fond sombre), HyprSmart extrait :
$$L_{text} = \begin{cases} \text{percentile}(99\%, L) & \text{si } L_{bg} < 0.5 \\ \text{percentile}(1\%, L) & \text{si } L_{bg} \ge 0.5 \end{cases}$$

---

## 4. Mesure de la Densité Textuelle ($D_{text}$)

Un terminal avec 3 lignes de commande et un éditeur VSCode affichant un fichier dense ne demandent pas le même compromis de lisibilité.

HyprSmart applique le filtre de gradient de Sobel sur la carte de luminance de la fenêtre pour compter la proportion de pixels situés sur des contours :
```python
grad = compute_sobel_energy(lum)
text_density = float(np.mean(grad > 0.08))
```

### Interprétation de la densité textuelle :
- **$D_{text} < 0.15$** : Espace négatif très majoritaire (terminal peu chargé, page de démarrage d'éditeur, document aéré).
- **$0.15 \le D_{text} \le 0.35$** : Code source avec coloration syntaxique standard, page web textuelle.
- **$D_{text} > 0.35$** : Interface très dense, tableau compact, ou image/vidéo avec forte variété spatiale.

---

## 5. Synthèse : La Dataclass `WindowVisuals`

Le résultat de cette analyse est encapsulé dans l'objet immuable `WindowVisuals` :
```python
@dataclass
class WindowVisuals:
    text_l: float        # Luminance du texte / éléments au premier plan [0, 1]
    bg_l: float          # Luminance du fond dominant [0, 1]
    text_density: float  # Taux d'occupation des contours textuels [0, 1]
    bg_ratio: float      # Pourcentage de surface couvert par le fond uni [0, 1]
```

Cet objet permet au moteur de décision de distinguer immédiatement un terminal noir quasi-vide ($R_{bg} = 0.85, D_{text} = 0.09$) d'une vidéo plein écran ou d'un navigateur web chargé, et d'adapter en conséquence l'agressivité de la transparence.
