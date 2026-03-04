# Skills

**Skills** : plusieurs sont intégrées, et vous pouvez ajouter des Skills personnalisées ou en importer depuis le Skills Hub.

Deux façons de gérer les Skills :

- **Console** — Utilisez la [Console](./console) sous **Agent → Skills**
- **Répertoire de travail** — Suivez les étapes ci-dessous pour modifier les fichiers directement

> Si vous êtes nouveau avec les canaux, le heartbeat ou cron, lisez d'abord l'[Introduction](./intro).

L'application charge les Skills depuis le dossier `skills` du répertoire de travail (par défaut
`~/.copaw/active_skills/`) : tout sous-répertoire contenant un `SKILL.md` est chargé comme une
Skill ; aucune inscription supplémentaire requise.

---

## Vue d'ensemble des Skills intégrées

Les Skills suivantes sont intégrées. Elles sont synchronisées avec le répertoire de travail
selon les besoins ; vous pouvez les activer ou les désactiver dans la Console ou via la config.

| Skill                        | Description                                                                                                                                                                                                          | Source                                                         |
| ---------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------- |
| **cron**                     | Tâches planifiées. Créez, listez, mettez en pause, reprenez ou supprimez des tâches via `copaw cron` ou **Contrôle → Tâches cron** dans la Console ; exécutez selon un planning et envoyez les résultats à un canal. | Intégrée                                                       |
| **file_reader**              | Lire et résumer des fichiers texte (.txt, .md, .json, .csv, .log, .py, etc.). PDF et Office sont gérés par les Skills ci-dessous.                                                                                    | Intégrée                                                       |
| **dingtalk_channel_connect** | Aide à l'intégration du canal DingTalk : guide à travers la console développeur, les champs clés, la recherche des identifiants (`Client ID` / `Client Secret`) et les étapes manuelles requises.                    | Intégrée                                                       |
| **himalaya**                 | Gérer les emails via CLI (IMAP/SMTP). Utilisez `himalaya` pour lister, lire, rechercher et organiser les emails depuis le terminal ; supporte plusieurs comptes et pièces jointes.                                   | https://github.com/openclaw/openclaw/tree/main/skills/himalaya |
| **news**                     | Récupérer et résumer les dernières actualités depuis les sites configurés ; les catégories incluent politique, finance, société, monde, tech, sports, divertissement.                                                | Intégrée                                                       |
| **pdf**                      | Opérations PDF : lire, extraire texte/tableaux, fusionner/diviser, faire pivoter, ajouter un filigrane, créer, remplir des formulaires, chiffrer/déchiffrer, OCR, etc.                                               | https://github.com/anthropics/skills/tree/main/skills/pdf      |
| **docx**                     | Créer, lire et modifier des documents Word (.docx), incluant table des matières, en-têtes/pieds de page, tableaux, images, suivi des modifications, commentaires.                                                    | https://github.com/anthropics/skills/tree/main/skills/docx     |
| **pptx**                     | Créer, lire et modifier des présentations PowerPoint (.pptx), incluant modèles, dispositions, notes, commentaires.                                                                                                   | https://github.com/anthropics/skills/tree/main/skills/pptx     |
| **xlsx**                     | Lire, modifier et créer des feuilles de calcul (.xlsx, .xlsm, .csv, .tsv), nettoyer la mise en forme, les formules et l'analyse de données.                                                                          | https://github.com/anthropics/skills/tree/main/skills/xlsx     |
| **browser_visible**          | Lancer une vraie fenêtre de navigateur visible (headful) pour les démos, le débogage ou les scénarios nécessitant une interaction humaine (ex. connexion, CAPTCHA).                                                  | Intégrée                                                       |

---

## Gérer les Skills dans la Console

Dans la [Console](./console), allez dans **Agent → Skills** pour :

- Voir toutes les Skills chargées et leur état d'activation ;
- **Activer ou désactiver** une Skill avec un bouton bascule ;
- **Créer** une Skill personnalisée en entrant un nom et un contenu (pas besoin de créer un répertoire) ;
- **Modifier** le nom ou le contenu d'une Skill existante.

Les modifications sont synchronisées avec le répertoire de travail et affectent l'agent. Pratique si vous préférez ne pas modifier les fichiers directement.

---

## Skill intégrée : Cron (tâches planifiées)

Lors de la première exécution, la Skill **Cron** est synchronisée du package vers
`~/.copaw/active_skills/cron/`. Elle fournit « exécuter selon un planning et envoyer les résultats à un canal. » Vous gérez les tâches avec le [CLI](./cli) (`copaw cron`) ou dans la Console sous **Contrôle → Tâches cron** ; pas besoin de modifier les fichiers de Skill.

Opérations courantes :

- Créer une tâche : `copaw cron create --type agent --name "xxx" --cron "0 9 * * *" ...`
- Lister les tâches : `copaw cron list`
- Vérifier l'état : `copaw cron state <job_id>`

---

## Importer des Skills

Vous pouvez importer des Skills depuis ces sources URL dans la Console :

- `https://skills.sh/...`
- `https://clawhub.ai/...`
- `https://skillsmp.com/...`
- `https://github.com/...`

### Étapes

1. Ouvrez la [Console](./console) → **Agent → Skills**, cliquez sur **Importer des Skills**.

   ![skill](https://img.alicdn.com/imgextra/i2/O1CN01gQN4gv1HCj5HVBeq1_!!6000000000722-2-tps-3410-1978.png)

2. Collez une URL de Skill dans la fenêtre contextuelle (voir l'**exemple d'acquisition d'URL** ci-dessous pour la méthode d'acquisition).

   ![url](https://img.alicdn.com/imgextra/i1/O1CN01YSoLHy1dZ5yWnMM3N_!!6000000003749-2-tps-3410-1978.png)

3. Confirmez et attendez que l'import se termine.

   ![click](https://img.alicdn.com/imgextra/i4/O1CN013idFsl1CiGHBEIWx2_!!6000000000114-2-tps-3410-1978.png)

4. Après un import réussi, les nouvelles Skills ajoutées apparaissent dans la liste des Skills.

   ![check](https://img.alicdn.com/imgextra/i1/O1CN014LNdGd1wFNcq6JWbY_!!6000000006278-2-tps-3410-1978.png)

### Exemples d'acquisition d'URL

1. Utilisez `skills.sh` comme exemple (le même flux d'acquisition d'URL s'applique à `clawhub.ai` et `skillsmp.com`) : ouvrez `https://skills.sh/`.
2. Choisissez la Skill dont vous avez besoin (par exemple, `find-skills`).

   ![find](https://img.alicdn.com/imgextra/i4/O1CN015bgbAR1ph8JbtTsIY_!!6000000005391-2-tps-3410-2064.png)

3. Copiez l'URL depuis la barre d'adresse en haut ; c'est l'URL de la Skill utilisée pour l'import.

   ![url](https://img.alicdn.com/imgextra/i2/O1CN01d1l5kO1wgrODXukNV_!!6000000006338-2-tps-3410-2064.png)

4. Pour importer des Skills depuis GitHub, ouvrez une page qui contient `SKILL.md` (par exemple, `skill-creator` dans le dépôt skills d'anthropics), puis copiez l'URL depuis la barre d'adresse en haut.

   ![github](https://img.alicdn.com/imgextra/i2/O1CN0117GbZa1lLN24GNpqI_!!6000000004802-2-tps-3410-2064.png)

### Notes

- Si une Skill avec le même nom existe déjà, l'import n'écrase pas par défaut. Vérifiez d'abord celle existante dans la liste.
- Si l'import échoue, vérifiez d'abord la complétude de l'URL, les domaines supportés et l'accès réseau sortant. Si le réseau est instable ou si GitHub limite les requêtes, ajoutez `GITHUB_TOKEN` dans Console → Paramètres → Environnements. Voir la documentation GitHub : [Gérer vos tokens d'accès personnel](https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/managing-your-personal-access-tokens).

---

## Skills personnalisées (dans le répertoire de travail)

Pour ajouter vos propres instructions ou capacités via le système de fichiers, ajoutez une Skill personnalisée sous le répertoire `customized_skills`.

### Étapes

1. Créez un répertoire sous `~/.copaw/customized_skills/`, ex. `ma_skill`.
2. Ajoutez un fichier `SKILL.md` dans ce répertoire. Rédigez du Markdown qui décrit la capacité pour l'agent. Vous pouvez optionnellement utiliser un front matter YAML en haut pour `name`, `description` et `metadata` (pour l'agent ou la Console).

### Exemple de structure de répertoire

```
~/.copaw/
  active_skills/        # Skills activées (fusionnées depuis intégrées + personnalisées)
    cron/
      SKILL.md
    ma_skill/
      SKILL.md
  customized_skills/    # Skills personnalisées créées par l'utilisateur (ajouter ici)
    ma_skill/
      SKILL.md
```

### Exemple de SKILL.md

```markdown
---
name: ma_skill
description: Ma capacité personnalisée
---

# Utilisation

Cette Skill est utilisée pour…
```

Au démarrage, l'application fusionne les Skills intégrées avec les Skills personnalisées de `~/.copaw/customized_skills/` dans `~/.copaw/active_skills/` ; les Skills personnalisées ont la priorité en cas de collision de noms. Vos répertoires personnalisés ne sont jamais écrasés ; les Skills intégrées ne sont copiées dans `active_skills` que lorsqu'elles sont manquantes.

---

## Pages associées

- [Introduction](./intro) — Ce que le projet peut faire
- [Console](./console) — Gérer les Skills et les canaux dans la Console
- [Canaux](./channels) — Connecter DingTalk, Feishu, iMessage, Discord, QQ
- [Heartbeat](./heartbeat) — Bilan / digest planifié
- [CLI](./cli) — Commandes cron en détail
- [Configuration & répertoire de travail](./config) — Répertoire de travail et config
