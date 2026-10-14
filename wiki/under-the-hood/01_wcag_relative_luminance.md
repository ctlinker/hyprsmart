# 01. Luminance Relative sRGB & Contraste WCAG 2.x

La première brique fondamentale de HyprSmart repose sur le calcul physique de la **luminance relative** et du **ratio de contraste WCAG**.

---

## 1. Pourquoi les valeurs RGB brutes ne suffisent pas

Un pixel RGB encodé en 8 bits par canal $(R, G, B) \in [0, 255]^3$ ne représente pas une intensité lumineuse directement exploitable pour estimer la lisibilité :
1. **Sensibilité spectrale de l'œil humain** : La rétine humaine possède trois types de cônes avec des sensibilités très inégales aux longueurs d'onde. Nous sommes immensément plus sensibles à la lumière verte qu'à la lumière bleue. Ainsi, un vert pur $(0, 255, 0)$ paraît beaucoup plus éblouissant qu'un bleu pur $(0, 0, 255)$ de même valeur numérique.
2. **Non-linéarité sRGB (Gamma)** : Les écrans et les formats d'images appliquent une courbe de transfert de gamma pour compresser l'espace colorimétrique. Une valeur $128$ n'émet pas 50% de la lumière physique d'une valeur $255$, mais seulement environ 21%.

---

## 2. Délinéarisation sRGB (Gamma Expansion)

Pour retrouver la quantité réelle de photons émise par un pixel, HyprSmart applique la formule officielle de délinéarisation sRGB recommandée par le W3C (norme WCAG 2.1) :

Soit $c = \frac{V_{channel}}{255.0} \in [0.0, 1.0]$ pour chacun des trois canaux $(R, G, B)$ :

$$c_{lin} = \begin{cases} \frac{c}{12.92} & \text{si } c \le 0.04045 \\ \left(\frac{c + 0.055}{1.055}\right)^{2.4} & \text{si } c > 0.04045 \end{cases}$$

Dans `src/hyprsmart/opacity/backdrop.py`, cette transformation est vectorisée en NumPy :
```python
c = rgb / 255.0
lin = np.where(
    c <= 0.04045,
    c / 12.92,
    ((c + 0.055) / 1.055) ** 2.4,
)
```

---

## 3. Calcul de la Luminance Relative $L$

Une fois les canaux linéaires $R_{lin}, G_{lin}, B_{lin}$ obtenus, on calcule la luminance relative $L \in [0.0, 1.0]$ selon les coefficients photométriques standards CIE 1931 :

$$L = 0.2126 \cdot R_{lin} + 0.7152 \cdot G_{lin} + 0.0722 \cdot B_{lin}$$

- Le vert représente **71.52%** de la sensation de brillance perçue.
- Le rouge représente **21.26%**.
- Le bleu ne représente que **7.22%**.

Une valeur $L = 0.0$ correspond au noir parfait, et $L = 1.0$ au blanc le plus lumineux.

---

## 4. La Formule du Ratio de Contraste WCAG 2.x

La norme WCAG définit le ratio de contraste $CR$ entre deux luminances relatives $L_1$ et $L_2$ (avec $L_1 \ge L_2$) par :

$$CR = \frac{L_1 + 0.05}{L_2 + 0.05}$$

### D'où vient la constante $+0.05$ ?
Cette valeur constante simule la **réflexion parasite de la lumière ambiante** sur la vitre de l'écran (*ambient flare*). Même dans une pièce sombre, le noir absolu d'un moniteur n'est jamais parfait en raison des reflets.
- Le ratio varie de $1.0:1$ (aucun contraste, couleurs identiques) à $21.0:1$ (noir pur sur blanc pur).
- Le standard WCAG AA exige un minimum de **4.5:1** pour le texte normal, et **3.0:1** pour le grand texte ou les éléments d'interface à fort contraste.

---

## 5. Modélisation Optique de la Transparence (Alpha Blending)

Quand une fenêtre possède une opacité $\alpha \in [0.0, 1.0]$, son arrière-plan physique $L_{bg}$ se mélange par transparence avec le fond d'écran $L_{wall}$ situé derrière elle.

La luminance perçue derrière le texte devient :
$$L_{perçu}(\alpha) = \alpha \cdot L_{bg} + (1.0 - \alpha) \cdot L_{wall}$$

### La condition d'acceptation de HyprSmart :
Pour garantir que le texte de la fenêtre reste parfaitement lisible, HyprSmart recherche la plus petite valeur d'$\alpha$ telle que :

$$CR(L_{text}, L_{perçu}(\alpha)) \ge CR_{cible}$$

Cette formule permet de calculer mathématiquement l'opacité sans aucune approximation ni modèle d'intelligence artificielle.
