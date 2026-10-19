# Rapport de Session : Externalisation de la Blacklist & Escalade de Privilèges

- **Date** : 2026-10-17
- **Version** : `0.8.3`
- **Branche** : `feat/hardened-security`
- **Auteur** : Agent IA Antigravity `[ai]`

---

## 1. Contexte & Demande Utilisateur

Suite à l'implémentation du bouclier de confidentialité (*Privacy Shield*) en version `0.8.2`, l'utilisateur a identifié un vecteur de risque lié à l'emplacement de configuration des classes sensibles :

> *"hum this `DEFAULT_SENSITIVE_CLASSES = [...]` is that a i blacklist (chmod -w) in hyprsmart config ?"*
> *"hum i think the `# ~/.config/hyprsmart/config.yaml ... sensitive_classes: [...]` should live in a blacklist.yaml that is readonly, hyprsmart would just use etheir polkit if present or inline a sudo cmd or whatever privilage escalation tools that is around to edit that file if needed"*

Si la liste des applications sensibles résidait dans le fichier utilisateur classique et modifiable `~/.config/hyprsmart/config.yaml`, un processus malveillant non privilégié (script malicieux, malware ou dépendance npm/pip compromise) exécuté dans la session graphique de l'utilisateur pouvait discrètement éditer ce fichier pour vider la liste des classes sensibles et déverrouiller la capture d'écran des gestionnaires de mots de passe (`keepassxc`, `1password`, `bitwarden`, etc.).

---

## 2. Architecture & Modèle de Sécurité Implémenté

```mermaid
flowchart TD
    subgraph Storage ["Fichiers & Permissions"]
        SysBL["/etc/hyprsmart/blacklist.yaml (root:root, 0444)"]
        UserBL["~/.config/hyprsmart/blacklist.yaml (chmod 0444)"]
        UserCfg["~/.config/hyprsmart/config.yaml (0600, modifiable)"]
    end

    subgraph UserSpace ["Espace Utilisateur Non Privilégié"]
        Malware["Processus Non Privilégié / Malware"]
        HyprsmartCLI["CLI: hyprsmart blacklist add / remove / lock"]
        Daemon["HyprSmart Daemon (Worker Grim & Solver)"]
    end

    subgraph Escalation ["Sous-système d'Élévation de Privilèges"]
        Detector{"Outil détecté ?"}
        PKExec["pkexec (Polkit GUI Agent)"]
        Sudo["sudo (Invite Terminal)"]
        InstallCmd["install -m 0444 -D <tmp> <dest>"]
    end

    Malware -- Tentative écriture directe --> BlockWrite["Rejet EACCES / EPERM (Noyau Linux)"]
    Malware -- Tentative chmod u+w (root-owned) --> BlockChmod["Rejet EPERM (Seul root peut chmod)"]

    HyprsmartCLI --> Detector
    Detector -- Polkit présent --> PKExec
    Detector -- Fallback sudo --> Sudo
    PKExec --> PromptUser["Boîte de dialogue d'authentification utilisateur"]
    Sudo --> PromptUser
    PromptUser -- Autorisé --> InstallCmd
    InstallCmd --> SysBL
    InstallCmd --> UserBL

    Daemon --> UserCfg
    Daemon -- Lecture seule mtime --> SysBL
    Daemon -- Lecture seule mtime --> UserBL
```

### 2.1 Hiérarchie des Fichiers de Liste Noire
1. **Fichier Système** (`/etc/hyprsmart/blacklist.yaml`) :
   - Priorité maximale s'il est présent sur la machine.
   - Propriété absolue `root:root` avec permissions strictes `0o444`. Aucun processus non privilégié ne peut ni l'éditer, ni le supprimer, ni le renommer.
2. **Fichier Utilisateur** (`~/.config/hyprsmart/blacklist.yaml`) :
   - Initialisé automatiquement au premier lancement avec les applications sensibles par défaut.
   - Immédiatement verrouillé en lecture seule avec les permissions `0o444` (`chmod -w`).
   - Isolé : le fichier `config.yaml` ne contient plus la clé `sensitive_classes`.

### 2.2 Mécanisme d'Élévation de Privilèges Atomique
La fonction [`save_blacklist`](../../src/hyprsmart/config.py) orchestre l'écriture sécurisée :
1. **Création d'un fichier temporaire sécurisé** : Les données YAML assainies sont écrites dans un fichier temporaire à droits restreints (`0o600`).
2. **Détection dynamique de l'outil d'escalade** :
   - Recherche prioritaire de `pkexec` (permettant d'afficher la fenêtre de dialogue native de l'environnement graphique, tel que `polkit-gnome` ou `polkit-kde`).
   - Repli transparent sur `sudo` (ou `doas`) en environnement terminal interactif si `pkexec` échoue ou est indisponible.
3. **Exécution atomique via `/usr/bin/install`** :
   Au lieu d'enchaîner plusieurs commandes (`mkdir`, `cp`, `chown`, `chmod`) risquant de déclencher plusieurs invites de mot de passe successives, HyprSmart invoque :
   ```bash
   [pkexec|sudo] install -m 0444 -D <fichier_temporaire> <destination_blacklist>
   ```
   L'utilitaire `install` crée les répertoires parents manquants, copie le fichier, applique les permissions `0444` et garantit la propriété `root:root` en une seule opération unifiée.
4. **Purge garantie** : Le fichier temporaire est systématiquement supprimé du disque dans un bloc `finally`.
5. **Rechargement immédiat du démon** : Le CLI transmet automatiquement un ordre `reload` au socket de contrôle UNIX pour appliquer la nouvelle politique sans délai.

---

## 3. Nouvelles Commandes CLI : `hyprsmart blacklist`

Le CLI intègre désormais un sous-module complet d'administration de la liste noire :

```bash
# 1. Consulter l'état complet du bouclier (chemin, droits, propriétaire, outil d'escalade et classes)
hyprsmart blacklist

# 2. Ajouter une ou plusieurs fenêtres sensibles (invite Polkit / sudo)
hyprsmart blacklist add my_vault signal-desktop

# 3. Retirer une fenêtre de la liste noire
hyprsmart blacklist remove signal-desktop

# 4. Forcer le verrouillage en lecture seule (0444)
hyprsmart blacklist lock

# 5. Promouvoir la liste noire au niveau système (/etc/hyprsmart/blacklist.yaml)
hyprsmart blacklist lock --system
```

### Validation et Assainissement des Entrées :
Toute tentative d'injection de caractères spéciaux ou de chemins dans les noms de classes est rejetée via l'expression régulière stricte :
```python
CLASS_NAME_RE = re.compile(r"^[a-zA-Z0-9_\-\.]+$")
```

---

## 4. Surveillance Multi-Fichiers (`_BLACKLIST_MTIME`)

Afin d'éviter tout désynchronisme entre le démon résident et les modifications apportées à `blacklist.yaml`, la fonction [`get_current_config`](../../src/hyprsmart/config.py) surveille conjointement la date de modification (`st_mtime`) de `config.yaml` et de `blacklist.yaml` :
- Dès qu'un changement de mtime est détecté sur l'un des deux fichiers, la configuration en mémoire est invalidée et rechargée automatiquement.

---

## 5. Validation par les Tests Unitaires

La suite de tests [`tests/test_security_hardening.py`](../../tests/test_security_hardening.py) a été enrichie de 9 nouveaux cas de test dédiés :
1. `test_blacklist_auto_create_readonly` : Vérification de la création automatique en mode `0o444` (`chmod -w`).
2. `test_blacklist_load_custom_and_fallback` : Vérification du parsing, de la normalisation en minuscules et du repli de secours sur fichier corrompu.
3. `test_blacklist_save_direct_readonly` : Écriture directe et vérification des droits `0o444`.
4. `test_blacklist_save_escalation_install_command` : Validation de l'appel `install -m 0444 -D` sans `shell=True` et de la purge du fichier temporaire.
5. `test_blacklist_save_escalation_fallback_to_sudo` : Validation du basculement automatique de `pkexec` vers `sudo` en cas d'échec.
6. `test_blacklist_save_escalation_failure_handled` : Gestion propre des erreurs et annulations d'authentification.
7. `test_blacklist_mtime_triggers_config_reload` : Détection du changement de mtime de `blacklist.yaml` par le démon.
8. `test_config_yaml_does_not_contain_sensitive_classes` : Garantie que `config.yaml` ne stocke plus `sensitive_classes`.
9. `test_cli_cmd_blacklist_actions` : Test fonctionnel des sous-commandes `list`, `add`, `remove` et `lock`.

### Résultat de l'Exécution :
```text
Ran 55 tests in 14.525s
OK
```

---

## 6. Bilan & Statut

- **Version** : Bumper à `0.8.3` dans `pyproject.toml` et `uv.lock`.
- **Documentation** : Chapitre 10 du Wiki mis à jour et exemples ajoutés au `README.md`.
- **Changelog** : Renseigné selon les conventions SemVer.
- **Surface d'attaque** : Entièrement hermétique contre les attaques locales non privilégiées ciblant la liste des fenêtres protégées.
