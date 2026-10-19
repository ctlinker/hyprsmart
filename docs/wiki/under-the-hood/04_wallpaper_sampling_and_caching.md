# 04. Échantillonnage du Fond d'Écran & Mise en Cache

L'un des défis majeurs de HyprSmart est de connaître à chaque instant les propriétés visuelles précises de la portion du fond d'écran masquée par la fenêtre active, sans consommer de CPU ni de bande passante disque à répétition.

Ce document détaille les algorithmes de sous-échantillonnage, la géométrie de projection et la stratégie de cache implémentés dans `src/hyprsmart/opacity/backdrop.py`.

---

## 1. Sous-Échantillonnage et Rendu en Mode Cover

Un fond d'écran moderne en résolution 4K ($3840 \times 2160$) pèse plusieurs dizaines de mégaoctets et comporte plus de 8 millions de pixels. Manipuler une telle matrice à chaque déplacement ou redimensionnement de fenêtre engendrerait une latence inacceptable.

### Le facteur de réduction `DOWN = 4`
HyprSmart divise par $4$ les dimensions de l'écran :
$$\text{width}_{target} = \lfloor \text{monitor\_w} / 4 \rfloor, \quad \text{height}_{target} = \lfloor \text{monitor\_h} / 4 \rfloor$$

| Résolution écran | Dimensions analysées (`DOWN=4`) | Nombre de pixels | Mémoire par matrice (float32) |
| :--- | :--- | :--- | :--- |
| **Full HD** ($1920 \times 1080$) | $480 \times 270$ | $129\,600$ pixels | $\approx 518$ Ko |
| **QHD** ($2560 \times 1440$) | $640 \times 360$ | $230\,400$ pixels | $\approx 921$ Ko |
| **4K UHD** ($3840 \times 2160$) | $960 \times 540$ | $518\,400$ pixels | $\approx 2.0$ Mo |

La surface mémoire est divisée par **$16$**, permettant d'exécuter des convolutions et des calculs de percentiles en moins de **0.2 milliseconde**.

### Algorithme de redimensionnement en mode "Cover"
Comme les gestionnaires de fond d'écran (`hyprpaper`, `swww`), HyprSmart applique un cadrage centré sans déformation d'aspect :
1. Calcul du facteur d'échelle isotrope :
   $$s = \max\left(\frac{\text{width}_{target}}{\text{img.width}}, \; \frac{\text{height}_{target}}{\text{img.height}}\right)$$
2. Rééchantillonnage par interpolation de **Lanczos** (filtre sinc à haute fidélité).
3. Découpage centré (*crop*) pour s'ajuster exactement aux dimensions cibles.

---

## 2. Correspondance des Coordonnées Spatiales (Mapping 2D)

Lorsqu'une fenêtre se déplace sur le bureau Hyprland, ses coordonnées géométriques $(x, y, w, h)$ sont projetées sur la grille sous-échantillonnée du moniteur correspondant :

```
(mon.x, mon.y) ┌────────────────────────────────────────┐
               │              Moniteur                  │
               │      (win.x, win.y)                    │
               │          ┌──────────┐                  │
               │          │ Fenêtre  │ win.height       │
               │          │          │                  │
               │          └──────────┘                  │
               │            win.width                   │
               └────────────────────────────────────────┘
```

### Projection normalisée et bornage sécurisé :
$$x_0 = \max\left(0, \min\left(W, \left\lfloor \frac{win.x - mon.x}{\text{DOWN}} \right\rfloor \right)\right)$$
$$y_0 = \max\left(0, \min\left(H, \left\lfloor \frac{win.y - mon.y}{\text{DOWN}} \right\rfloor \right)\right)$$
$$x_1 = \max\left(0, \min\left(W, \left\lfloor \frac{win.x - mon.x + win.width}{\text{DOWN}} \right\rfloor \right)\right)$$
$$y_1 = \max\left(0, \min\left(H, \left\lfloor \frac{win.y - mon.y + win.height}{\text{DOWN}} \right\rfloor \right)\right)$$

### Convention des axes NumPy :
Dans un tableau NumPy 2D, le premier axe (axe 0) indexe les **lignes** (axe vertical $Y$) et le second axe (axe 1) indexe les **colonnes** (axe horizontal $X$) :
```python
region_lum = lum[y0:y1, x0:x1]
region_grad = grad[y0:y1, x0:x1]
```

Si la fenêtre est entièrement minimisée ou située hors écran ($x_1 \le x_0$ ou $y_1 \le y_0$), HyprSmart retourne immédiatement un objet `Backdrop` neutre par défaut pour prévenir toute exception mathématique sur tableau vide.

---

## 3. Stratégie de Mise en Cache Conjointe (Luminance & Contours)

Pour éviter de relire le fichier image et de réexécuter les convolutions à chaque événement, HyprSmart maintient un cache mémoire thread-safe :

```python
WALLPAPER_CACHE: dict[tuple[str, int, int, float], tuple[np.ndarray, np.ndarray]]
```

### Clé de cache composite :
Une entrée de cache est indexée par le quadruplet :
$$\text{Clé} = (\text{chemin\_absolu}, \; \text{monitor\_w}, \; \text{monitor\_h}, \; \text{mtime})$$

- **`mtime` (Modification Time)** : Horodatage POSIX de dernière modification du fichier image. Si le fond d'écran est modifié ou remplacé sur le disque, `mtime` change et le cache s'invalide automatiquement au prochain cycle.
- **Tuplet retourné** : `(matrice_luminance, matrice_gradient_sobel)`.
- **Invalidation manuelle** : La commande `hyprsmart reload` ou le changement d'écran via `hyprsmart monitor` invoque `clear_wallpaper_cache()` pour forcer un rechargement immédiat.
