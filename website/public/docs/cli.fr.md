# CLI

`copaw` est l'outil en ligne de commande pour CoPaw. Cette page est organisée de
« démarrage rapide » à « gestion avancée » — lisez de haut en bas si
vous débutez, ou accédez directement à la section dont vous avez besoin.

> Vous ne savez pas ce que signifient « canaux », « heartbeat » ou « cron » ? Voir d'abord
> l'[Introduction](./intro).

---

## Pour commencer

Ce sont les commandes que vous utiliserez dès le premier jour.

### copaw init

Configuration initiale. Vous guide à travers la configuration de manière interactive.

```bash
copaw init              # Configuration interactive (recommandée pour la première fois)
copaw init --defaults   # Non interactif, utilise toutes les valeurs par défaut (idéal pour les scripts)
copaw init --force      # Écraser les fichiers de config existants
```

**Ce que couvre le flux interactif (dans l'ordre) :**

1. **Heartbeat** — intervalle (ex. `30m`), cible (`main` / `last`), heures actives optionnelles.
2. **Afficher les détails des outils** — si les détails des appels d'outils apparaissent dans les messages du canal.
3. **Langue** — `zh` ou `en` pour les fichiers de persona de l'agent (SOUL.md, etc.).
4. **Canaux** — configurer optionnellement iMessage / Discord / DingTalk / Feishu / QQ / Console.
5. **Fournisseur LLM** — sélectionner le fournisseur, entrer la clé API, choisir le modèle (**obligatoire**).
6. **Skills** — activer tout / rien / sélection personnalisée.
7. **Variables d'environnement** — ajouter optionnellement des paires clé-valeur pour les outils.
8. **HEARTBEAT.md** — modifier la liste de contrôle heartbeat dans votre éditeur par défaut.

### copaw app

Démarrer le serveur CoPaw. Tout le reste — canaux, tâches cron, l'interface Console — dépend de cela.

```bash
copaw app                             # Démarrer sur 127.0.0.1:8088
copaw app --host 0.0.0.0 --port 9090 # Adresse personnalisée
copaw app --reload                    # Rechargement automatique lors de changements de code (dev)
copaw app --workers 4                 # Mode multi-worker
copaw app --log-level debug           # Journalisation détaillée
```

| Option        | Défaut      | Description                                                               |
| ------------- | ----------- | ------------------------------------------------------------------------- |
| `--host`      | `127.0.0.1` | Hôte de liaison                                                           |
| `--port`      | `8088`      | Port de liaison                                                           |
| `--reload`    | désactivé   | Rechargement automatique lors de changements de fichiers (dev uniquement) |
| `--workers`   | `1`         | Nombre de processus worker                                                |
| `--log-level` | `info`      | `critical` / `error` / `warning` / `info` / `debug` / `trace`             |

### Console

Une fois `copaw app` en cours d'exécution, ouvrez `http://127.0.0.1:8088/` dans votre navigateur pour
accéder à la **Console** — une interface web pour le chat, les canaux, cron, les Skills, les modèles,
et plus encore. Voir [Console](./console) pour une visite complète.

Si le frontend n'a pas été compilé, l'URL racine renvoie `{"message": "Hello World"}`
mais l'API fonctionne toujours.

**Pour compiler le frontend :** dans le répertoire `console/` du projet, exécutez
`npm ci && npm run build` (sortie dans `console/dist/`). Les images Docker et les paquets pip
incluent déjà la Console.

---

## Modèles & variables d'environnement

Avant d'utiliser CoPaw, vous devez configurer au moins un fournisseur LLM. Les variables d'environnement
alimentent de nombreux outils intégrés (ex. recherche web).

### copaw models

Gérer les fournisseurs LLM et le modèle actif.

| Commande                               | Ce qu'elle fait                                                            |
| -------------------------------------- | -------------------------------------------------------------------------- |
| `copaw models list`                    | Afficher tous les fournisseurs, le statut de la clé API et le modèle actif |
| `copaw models config`                  | Configuration interactive complète : clés API → modèle actif               |
| `copaw models config-key [provider]`   | Configurer la clé API d'un seul fournisseur                                |
| `copaw models set-llm`                 | Changer le modèle actif (clés API inchangées)                              |
| `copaw models download <repo_id>`      | Télécharger un modèle local (llama.cpp / MLX)                              |
| `copaw models local`                   | Lister les modèles locaux téléchargés                                      |
| `copaw models remove-local <model_id>` | Supprimer un modèle local téléchargé                                       |
| `copaw models ollama-pull <model>`     | Télécharger un modèle Ollama                                               |
| `copaw models ollama-list`             | Lister les modèles Ollama                                                  |
| `copaw models ollama-remove <model>`   | Supprimer un modèle Ollama                                                 |

```bash
copaw models list                    # Voir ce qui est configuré
copaw models config                  # Configuration interactive complète
copaw models config-key modelscope   # Définir uniquement la clé API de ModelScope
copaw models config-key dashscope    # Définir uniquement la clé API de DashScope
copaw models config-key custom       # Définir un fournisseur personnalisé (URL de base + clé)
copaw models set-llm                 # Changer uniquement le modèle actif
```

#### Modèles locaux

CoPaw peut également exécuter des modèles localement via llama.cpp ou MLX — aucune clé API requise.
Installez d'abord le backend : `pip install 'copaw[llamacpp]'` ou
`pip install 'copaw[mlx]'`.

```bash
# Télécharger un modèle (sélectionne automatiquement Q4_K_M GGUF)
copaw models download Qwen/Qwen3-4B-GGUF

# Télécharger un modèle MLX
copaw models download Qwen/Qwen3-4B --backend mlx

# Télécharger depuis ModelScope
copaw models download Qwen/Qwen2-0.5B-Instruct-GGUF --source modelscope

# Lister les modèles téléchargés
copaw models local
copaw models local --backend mlx

# Supprimer un modèle téléchargé
copaw models remove-local <model_id>
copaw models remove-local <model_id> --yes   # sans confirmation
```

| Option      | Court | Défaut        | Description                                                                                |
| ----------- | ----- | ------------- | ------------------------------------------------------------------------------------------ |
| `--backend` | `-b`  | `llamacpp`    | Backend cible (`llamacpp` ou `mlx`)                                                        |
| `--source`  | `-s`  | `huggingface` | Source de téléchargement (`huggingface` ou `modelscope`)                                   |
| `--file`    | `-f`  | _(auto)_      | Nom de fichier spécifique. Si omis, sélectionné automatiquement (préfère Q4_K_M pour GGUF) |

#### Modèles Ollama

CoPaw s'intègre avec Ollama pour exécuter des modèles localement. Les modèles sont chargés dynamiquement depuis votre daemon Ollama — installez d'abord Ollama depuis [ollama.com](https://ollama.com).

Installez le SDK Ollama : `pip install 'copaw[ollama]'` (ou relancez l'installateur avec `--extras ollama`)

```bash
# Télécharger un modèle Ollama
copaw models ollama-pull mistral:7b
copaw models ollama-pull qwen3:8b

# Lister les modèles Ollama
copaw models ollama-list

# Supprimer un modèle Ollama
copaw models ollama-remove mistral:7b
copaw models ollama-remove qwen3:8b --yes   # sans confirmation

# Utiliser dans le flux config (détecte automatiquement les modèles Ollama)
copaw models config           # Sélectionner Ollama → Choisir dans la liste des modèles
copaw models set-llm          # Basculer vers un autre modèle Ollama
```

**Différences clés par rapport aux modèles locaux :**

- Les modèles viennent du daemon Ollama (pas téléchargés par CoPaw)
- Utilisez `ollama-pull` / `ollama-remove` au lieu de `download` / `remove-local`
- La liste des modèles se met à jour dynamiquement quand vous ajoutez/supprimez via Ollama CLI ou CoPaw

> **Note :** Vous êtes responsable de vous assurer que la clé API est valide. CoPaw ne
> vérifie pas l'exactitude de la clé. Voir [Config — Fournisseurs LLM](./config#llm-providers).

### copaw env

Gérer les variables d'environnement utilisées par les outils et Skills au runtime.

| Commande                  | Ce qu'elle fait                         |
| ------------------------- | --------------------------------------- |
| `copaw env list`          | Lister toutes les variables configurées |
| `copaw env set KEY VALUE` | Définir ou mettre à jour une variable   |
| `copaw env delete KEY`    | Supprimer une variable                  |

```bash
copaw env list
copaw env set TAVILY_API_KEY "tvly-xxxxxxxx"
copaw env set GITHUB_TOKEN "ghp_xxxxxxxx"
copaw env delete TAVILY_API_KEY
```

> **Note :** CoPaw ne fait que stocker et charger ces valeurs ; vous êtes responsable de
> vous assurer qu'elles sont correctes. Voir
> [Config — Variables d'environnement](./config#environment-variables).

---

## Canaux

Connecter CoPaw aux plateformes de messagerie.

### copaw channels

Gérer la configuration des canaux (iMessage, Discord, DingTalk, Feishu, QQ,
Console, etc.). **Note :** Utilisez `config` pour la configuration interactive (pas de sous-commande `configure`) ;
utilisez `remove` pour désinstaller les canaux personnalisés (pas d'`uninstall`).

| Commande                       | Ce qu'elle fait                                                                                                                               |
| ------------------------------ | --------------------------------------------------------------------------------------------------------------------------------------------- |
| `copaw channels list`          | Afficher tous les canaux et leur statut (secrets masqués)                                                                                     |
| `copaw channels install <key>` | Installer un canal dans `custom_channels/` : créer un stub ou utiliser `--path`/`--url`                                                       |
| `copaw channels add <key>`     | Installer et ajouter à la config ; les canaux intégrés obtiennent uniquement une entrée de config ; supporte `--path`/`--url`                 |
| `copaw channels remove <key>`  | Supprimer un canal personnalisé de `custom_channels/` (les intégrés ne peuvent pas être supprimés) ; `--keep-config` garde l'entrée de config |
| `copaw channels config`        | Activer/désactiver les canaux et renseigner les identifiants de manière interactive                                                           |

```bash
copaw channels list                    # Voir le statut actuel
copaw channels install my_channel      # Créer un stub de canal personnalisé
copaw channels install my_channel --path ./my_channel.py
copaw channels add dingtalk            # Ajouter DingTalk à la config
copaw channels remove my_channel       # Supprimer le canal personnalisé (et de la config par défaut)
copaw channels remove my_channel --keep-config   # Supprimer le module uniquement, garder l'entrée de config
copaw channels config                 # Configuration interactive
```

Le flux `config` interactif vous permet de choisir un canal, de l'activer/désactiver et de saisir les identifiants. Il boucle jusqu'à ce que vous choisissiez « Sauvegarder et quitter ».

| Canal        | Champs à renseigner                                           |
| ------------ | ------------------------------------------------------------- |
| **iMessage** | Préfixe bot, chemin de base de données, intervalle de sondage |
| **Discord**  | Préfixe bot, Token du Bot, proxy HTTP, auth proxy             |
| **DingTalk** | Préfixe bot, Client ID, Client Secret                         |
| **Feishu**   | Préfixe bot, App ID, App Secret                               |
| **QQ**       | Préfixe bot, App ID, Client Secret                            |
| **Console**  | Préfixe bot                                                   |

> Pour la configuration des identifiants spécifiques à chaque plateforme, voir [Canaux](./channels).

---

## Cron (tâches planifiées)

Créez des tâches qui s'exécutent selon un planning — « tous les jours à 9h », « toutes les 2 heures
interroger CoPaw et envoyer la réponse ». **Nécessite que `copaw app` soit en cours d'exécution.**

### copaw cron

| Commande                     | Ce qu'elle fait                                                         |
| ---------------------------- | ----------------------------------------------------------------------- |
| `copaw cron list`            | Lister toutes les tâches                                                |
| `copaw cron get <job_id>`    | Afficher les spécifications d'une tâche                                 |
| `copaw cron state <job_id>`  | Afficher l'état runtime (prochaine exécution, dernière exécution, etc.) |
| `copaw cron create ...`      | Créer une tâche                                                         |
| `copaw cron delete <job_id>` | Supprimer une tâche                                                     |
| `copaw cron pause <job_id>`  | Mettre en pause une tâche                                               |
| `copaw cron resume <job_id>` | Reprendre une tâche en pause                                            |
| `copaw cron run <job_id>`    | Exécuter une fois immédiatement                                         |

### Créer des tâches

**Option 1 — Arguments CLI (tâches simples)**

Deux types de tâches :

- **text** — envoyer un message fixe à un canal selon un planning.
- **agent** — interroger CoPaw selon un planning et livrer la réponse.

```bash
# Texte : envoyer "Bonjour !" sur DingTalk tous les jours à 9:00
copaw cron create \
  --type text \
  --name "Quotidien 9h" \
  --cron "0 9 * * *" \
  --channel dingtalk \
  --target-user "votre_user_id" \
  --target-session "session_id" \
  --text "Bonjour !"

# Agent : toutes les 2 heures, interroger CoPaw et transmettre la réponse
copaw cron create \
  --type agent \
  --name "Vérifier les tâches" \
  --cron "0 */2 * * *" \
  --channel dingtalk \
  --target-user "votre_user_id" \
  --target-session "session_id" \
  --text "Quelles sont mes tâches ?"
```

Obligatoires : `--type`, `--name`, `--cron`, `--channel`, `--target-user`,
`--target-session`, `--text`.

**Option 2 — Fichier JSON (complexe ou par lot)**

```bash
copaw cron create -f job_spec.json
```

La structure JSON correspond à la sortie de `copaw cron get <job_id>`.

### Options supplémentaires

| Option                       | Défaut  | Description                                          |
| ---------------------------- | ------- | ---------------------------------------------------- |
| `--timezone`                 | `UTC`   | Fuseau horaire pour le planning cron                 |
| `--enabled` / `--no-enabled` | activé  | Créer activé ou désactivé                            |
| `--mode`                     | `final` | `stream` (incrémental) ou `final` (réponse complète) |
| `--base-url`                 | auto    | Remplacer l'URL de base de l'API                     |

### Aide-mémoire des expressions cron

Cinq champs : **minute heure jour mois jour_semaine** (pas de secondes).

| Expression     | Signification            |
| -------------- | ------------------------ |
| `0 9 * * *`    | Tous les jours à 9:00    |
| `0 */2 * * *`  | Toutes les 2 heures pile |
| `30 8 * * 1-5` | En semaine à 8:30        |
| `0 0 * * 0`    | Dimanche à minuit        |
| `*/15 * * * *` | Toutes les 15 minutes    |

---

## Chats (sessions)

Gérer les sessions de chat via l'API. **Nécessite que `copaw app` soit en cours d'exécution.**

### copaw chats

| Commande                               | Ce qu'elle fait                                                            |
| -------------------------------------- | -------------------------------------------------------------------------- |
| `copaw chats list`                     | Lister toutes les sessions (supporte les filtres `--user-id`, `--channel`) |
| `copaw chats get <id>`                 | Voir les détails d'une session et l'historique des messages                |
| `copaw chats create ...`               | Créer une nouvelle session                                                 |
| `copaw chats update <id> --name "..."` | Renommer une session                                                       |
| `copaw chats delete <id>`              | Supprimer une session                                                      |

```bash
copaw chats list
copaw chats list --user-id alice --channel dingtalk
copaw chats get 823845fe-dd13-43c2-ab8b-d05870602fd8
copaw chats create --session-id "discord:alice" --user-id alice --name "Mon Chat"
copaw chats create -f chat.json
copaw chats update <chat_id> --name "Renommé"
copaw chats delete <chat_id>
```

---

## Skills

Étendre les capacités de CoPaw avec des Skills (lecture PDF, recherche web, etc.).

### copaw skills

| Commande              | Ce qu'elle fait                                                                     |
| --------------------- | ----------------------------------------------------------------------------------- |
| `copaw skills list`   | Afficher toutes les Skills et leur statut activé/désactivé                          |
| `copaw skills config` | Activer/désactiver les Skills de manière interactive (interface par cases à cocher) |

```bash
copaw skills list     # Voir ce qui est disponible
copaw skills config   # Activer/désactiver les Skills interactivement
```

Dans l'interface interactive : ↑/↓ pour naviguer, Espace pour basculer, Entrée pour confirmer.
Un aperçu des modifications est affiché avant application.

> Pour les détails des Skills intégrées et la création de Skills personnalisées, voir [Skills](./skills).

---

## Maintenance

### copaw clean

Supprimer tout ce qui se trouve sous le répertoire de travail (par défaut `~/.copaw`).

```bash
copaw clean             # Confirmation interactive
copaw clean --yes       # Sans confirmation
copaw clean --dry-run   # Lister uniquement ce qui serait supprimé
```

---

## Options globales

Chaque sous-commande `copaw` hérite de :

| Option          | Défaut      | Description                                                      |
| --------------- | ----------- | ---------------------------------------------------------------- |
| `--host`        | `127.0.0.1` | Hôte API (détecté automatiquement depuis le dernier `copaw app`) |
| `--port`        | `8088`      | Port API (détecté automatiquement depuis le dernier `copaw app`) |
| `-h` / `--help` |             | Afficher le message d'aide                                       |

Si le serveur tourne sur une adresse non standard, passez ces options globalement :

```bash
copaw --host 0.0.0.0 --port 9090 cron list
```

## Répertoire de travail

Toute la config et les données se trouvent dans `~/.copaw` par défaut : `config.json`,
`HEARTBEAT.md`, `jobs.json`, `chats.json`, Skills, mémoire et fichiers de persona de l'agent.

| Variable            | Description                                     |
| ------------------- | ----------------------------------------------- |
| `COPAW_WORKING_DIR` | Remplacer le chemin du répertoire de travail    |
| `COPAW_CONFIG_FILE` | Remplacer le chemin du fichier de configuration |

Voir [Config & Répertoire de travail](./config) pour tous les détails.

---

## Vue d'ensemble des commandes

| Commande         | Sous-commandes                                                                                                                         | Serveur requis ? |
| ---------------- | -------------------------------------------------------------------------------------------------------------------------------------- | :--------------: |
| `copaw init`     | —                                                                                                                                      |       Non        |
| `copaw app`      | —                                                                                                                                      |  — (le démarre)  |
| `copaw models`   | `list` · `config` · `config-key` · `set-llm` · `download` · `local` · `remove-local` · `ollama-pull` · `ollama-list` · `ollama-remove` |       Non        |
| `copaw env`      | `list` · `set` · `delete`                                                                                                              |       Non        |
| `copaw channels` | `list` · `install` · `add` · `remove` · `config`                                                                                       |       Non        |
| `copaw cron`     | `list` · `get` · `state` · `create` · `delete` · `pause` · `resume` · `run`                                                            |     **Oui**      |
| `copaw chats`    | `list` · `get` · `create` · `update` · `delete`                                                                                        |     **Oui**      |
| `copaw skills`   | `list` · `config`                                                                                                                      |       Non        |
| `copaw clean`    | —                                                                                                                                      |       Non        |

---

## Pages associées

- [Introduction](./intro) — Ce que CoPaw peut faire
- [Console](./console) — Interface de gestion web
- [Canaux](./channels) — Configuration DingTalk, Feishu, iMessage, Discord, QQ
- [Heartbeat](./heartbeat) — Bilan / digest planifié
- [Skills](./skills) — Skills intégrées et personnalisées
- [Configuration & Répertoire de travail](./config) — Répertoire de travail et config.json
