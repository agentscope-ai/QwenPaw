# Configuration & Répertoire de travail

Cette page couvre :

- **Répertoire de travail** — Où les données sont stockées
- **config.json** — Ce que signifie chaque champ et ses valeurs par défaut
- **Variables d'environnement** — Comment personnaliser les chemins

> Pas de code requis — modifiez simplement le JSON et c'est parti.

---

## Qu'est-ce que le répertoire de travail ?

Par défaut, toute la config et les données se trouvent dans un seul dossier — le **répertoire de travail** :

- **`~/.copaw`** (le dossier `.copaw` sous votre répertoire personnel)

Quand vous exécutez `copaw init`, ce répertoire est créé automatiquement. Voici ce que
vous y trouverez :

| Fichier / Répertoire | Objectif                                                               |
| -------------------- | ---------------------------------------------------------------------- |
| `config.json`        | Activation/désactivation des canaux et identifiants, paramètres heartbeat, langue, etc. |
| `HEARTBEAT.md`       | Contenu du prompt utilisé à chaque exécution du heartbeat              |
| `jobs.json`          | Liste des tâches cron (gérée via `copaw cron` ou API)                  |
| `chats.json`         | Liste des chats/sessions (mode stockage fichier)                       |
| `active_skills/`     | Skills actuellement actives et utilisées par l'agent                   |
| `customized_skills/` | Skills personnalisées créées par l'utilisateur                         |
| `memory/`            | Fichiers de mémoire de l'agent (gérés automatiquement)                 |
| `SOUL.md`            | _(obligatoire)_ Identité principale et principes comportementaux       |
| `AGENTS.md`          | _(obligatoire)_ Workflows détaillés, règles et directives              |

> **Conseil :** `SOUL.md` et `AGENTS.md` sont les fichiers Markdown minimaux requis
> pour le prompt système de l'agent. Sans eux, l'agent revient à un
> prompt générique « You are a helpful assistant ». Exécutez `copaw init` pour les copier automatiquement
> selon votre choix de langue (`zh` / `en`).

---

## Changer les chemins avec des variables d'environnement (optionnel)

Si vous ne voulez pas utiliser `~/.copaw`, vous pouvez remplacer le répertoire de travail ou
des noms de fichiers spécifiques :

| Variable                           | Défaut          | Signification                                                                               |
| ---------------------------------- | --------------- | ------------------------------------------------------------------------------------------- |
| `COPAW_WORKING_DIR`                | `~/.copaw`      | Répertoire de travail ; config, heartbeat, tâches, chats, Skills et mémoire s'y trouvent   |
| `COPAW_CONFIG_FILE`                | `config.json`   | Nom du fichier de config (relatif au répertoire de travail)                                 |
| `COPAW_HEARTBEAT_FILE`             | `HEARTBEAT.md`  | Nom du fichier de prompt heartbeat (relatif au répertoire de travail)                       |
| `COPAW_JOBS_FILE`                  | `jobs.json`     | Nom du fichier des tâches cron (relatif au répertoire de travail)                           |
| `COPAW_CHATS_FILE`                 | `chats.json`    | Nom du fichier des chats (relatif au répertoire de travail)                                 |
| `COPAW_LOG_LEVEL`                  | `info`          | Niveau de log de l'application (`debug`, `info`, `warning`, `error`, `critical`)            |
| `COPAW_MEMORY_COMPACT_THRESHOLD`   | `100000`        | Seuil de caractères pour déclencher la compaction de mémoire                                |
| `COPAW_MEMORY_COMPACT_KEEP_RECENT` | `3`             | Nombre de messages récents conservés après compaction                                       |
| `COPAW_MEMORY_COMPACT_RATIO`       | `0.7`           | Ratio de seuil pour déclencher la compaction (relatif à la fenêtre de contexte)             |
| `COPAW_CONSOLE_STATIC_DIR`         | _(auto-détecté)_ | Chemin vers les fichiers statiques du frontend de la console                               |

Exemple — utiliser un répertoire de travail différent pour ce shell :

```bash
export COPAW_WORKING_DIR=/home/moi/mon_copaw
copaw app
```

La config, HEARTBEAT, les tâches, la mémoire, etc. seront lus/écrits sous
`/home/moi/mon_copaw`.

---

## Que contient config.json ?

Ci-dessous se trouve la **structure complète** avec chaque champ, son type, sa valeur par défaut
et ce qu'il fait. Vous n'avez pas besoin de tout renseigner — les champs manquants
utilisent automatiquement les valeurs par défaut.

### Exemple complet

```json
{
  "channels": {
    "imessage": {
      "enabled": false,
      "bot_prefix": "",
      "db_path": "~/Library/Messages/chat.db",
      "poll_sec": 1.0
    },
    "discord": {
      "enabled": false,
      "bot_prefix": "",
      "bot_token": "",
      "http_proxy": "",
      "http_proxy_auth": ""
    },
    "dingtalk": {
      "enabled": false,
      "bot_prefix": "",
      "client_id": "",
      "client_secret": ""
    },
    "feishu": {
      "enabled": false,
      "bot_prefix": "",
      "app_id": "",
      "app_secret": "",
      "encrypt_key": "",
      "verification_token": "",
      "media_dir": "~/.copaw/media"
    },
    "qq": {
      "enabled": false,
      "bot_prefix": "",
      "app_id": "",
      "client_secret": ""
    },
    "console": {
      "enabled": true,
      "bot_prefix": ""
    }
  },
  "agents": {
    "defaults": {
      "heartbeat": {
        "every": "30m",
        "target": "main",
        "activeHours": null
      }
    },
    "running": {
      "max_iters": 50,
      "max_input_length": 131072
    },
    "language": "zh",
    "installed_md_files_language": "zh"
  },
  "last_api": {
    "host": "127.0.0.1",
    "port": 8088
  },
  "last_dispatch": null,
  "show_tool_details": true
}
```

### Référence champ par champ

#### `channels` — Configurations des canaux de messagerie

Chaque canal a une base commune et des champs spécifiques au canal.

**Champs communs (tous les canaux) :**

| Champ                  | Type   | Défaut  | Description                                                        |
| ---------------------- | ------ | ------- | ------------------------------------------------------------------ |
| `enabled`              | bool   | `false` | Si le canal est actif                                              |
| `bot_prefix`           | string | `""`    | Préfixe de commande optionnel (ex. `/paw`)                         |
| `filter_tool_messages` | bool   | `false` | Filtrer les messages d'appel/sortie d'outils de l'envoi (désactivé par défaut) |

**`channels.imessage`** — iMessage macOS

| Champ      | Type   | Défaut                       | Description                     |
| ---------- | ------ | ---------------------------- | ------------------------------- |
| `db_path`  | string | `~/Library/Messages/chat.db` | Chemin vers la base de données iMessage |
| `poll_sec` | float  | `1.0`                        | Intervalle de sondage en secondes |

**`channels.discord`** — Bot Discord

| Champ             | Type   | Défaut | Description                        |
| ----------------- | ------ | ------ | ---------------------------------- |
| `bot_token`       | string | `""`   | Token du bot Discord               |
| `http_proxy`      | string | `""`   | URL du proxy HTTP (utile en Chine) |
| `http_proxy_auth` | string | `""`   | Chaîne d'authentification du proxy |

**`channels.dingtalk`** — DingTalk (钉钉)

| Champ           | Type   | Défaut | Description                     |
| --------------- | ------ | ------ | ------------------------------- |
| `client_id`     | string | `""`   | Client ID de l'application DingTalk |
| `client_secret` | string | `""`   | Client Secret de l'application DingTalk |

**`channels.feishu`** — Feishu / Lark (飞书)

| Champ                | Type   | Défaut           | Description                          |
| -------------------- | ------ | ---------------- | ------------------------------------ |
| `app_id`             | string | `""`             | App ID Feishu                        |
| `app_secret`         | string | `""`             | App Secret Feishu                    |
| `encrypt_key`        | string | `""`             | Clé de chiffrement des événements (optionnel) |
| `verification_token` | string | `""`             | Token de vérification des événements (optionnel) |
| `media_dir`          | string | `~/.copaw/media` | Répertoire pour les fichiers médias reçus |

**`channels.qq`** — Bot QQ

| Champ           | Type   | Défaut | Description           |
| --------------- | ------ | ------ | --------------------- |
| `app_id`        | string | `""`   | App ID du Bot QQ      |
| `client_secret` | string | `""`   | Client Secret du Bot QQ |

**`channels.console`** — Console (E/S terminal)

| Champ     | Type | Défaut | Description                                                      |
| --------- | ---- | ------ | ---------------------------------------------------------------- |
| `enabled` | bool | `true` | Activé par défaut ; affiche les réponses de l'agent sur stdout   |

> **Conseil :** Le système surveille automatiquement les changements de `config.json` (toutes les 2 secondes).
> Si vous modifiez la config d'un canal pendant que l'application est en cours d'exécution, elle
> rechargera automatiquement ce canal — pas besoin de redémarrer.

---

#### `agents` — Paramètres de comportement de l'agent

| Champ                                | Type           | Défaut    | Description                                                                |
| ------------------------------------ | -------------- | --------- | -------------------------------------------------------------------------- |
| `agents.defaults.heartbeat`          | object \| null | Voir ci-dessous | Configuration du heartbeat                                            |
| `agents.running`                     | object         | Voir ci-dessous | Configuration du comportement runtime de l'agent                      |
| `agents.language`                    | string         | `"zh"`    | Langue pour les fichiers MD de l'agent (`"en"` ou `"zh"`)                  |
| `agents.installed_md_files_language` | string \| null | `null`    | Suivi de la langue des fichiers MD installés ; géré par `copaw init`       |

**`agents.running`** — Comportement runtime de l'agent

| Champ              | Type | Défaut          | Description                                                                                                                   |
| ------------------ | ---- | --------------- | ----------------------------------------------------------------------------------------------------------------------------- |
| `max_iters`        | int  | `50`            | Nombre maximum d'itérations de raisonnement-action pour l'agent ReAct (doit être ≥ 1)                                        |
| `max_input_length` | int  | `131072` (128K) | Longueur maximale d'entrée (tokens) pour la fenêtre de contexte du modèle. La compaction de mémoire se déclenche à 80% de cette valeur (doit être ≥ 1000) |

**`agents.defaults.heartbeat`** — Planification du heartbeat

| Champ         | Type           | Défaut   | Description                                                                                                          |
| ------------- | -------------- | -------- | -------------------------------------------------------------------------------------------------------------------- |
| `every`       | string         | `"30m"`  | Intervalle d'exécution. Supporte les combinaisons `Nh`, `Nm`, `Ns`, ex. `"1h"`, `"30m"`, `"2h30m"`, `"90s"`         |
| `target`      | string         | `"main"` | `"main"` = exécuter dans la session principale uniquement ; `"last"` = envoyer le résultat au dernier canal/utilisateur qui a envoyé un message |
| `activeHours` | object \| null | `null`   | Fenêtre temporelle optionnelle. Si définie, le heartbeat ne s'exécute que pendant cette période                      |

**`agents.defaults.heartbeat.activeHours`** (quand non null) :

| Champ   | Type   | Défaut    | Description                  |
| ------- | ------ | --------- | ---------------------------- |
| `start` | string | `"08:00"` | Heure de début (HH:MM, 24h)  |
| `end`   | string | `"22:00"` | Heure de fin (HH:MM, 24h)    |

> Voir [Heartbeat](./heartbeat) pour un guide détaillé.

---

#### `last_api` — Dernière adresse API utilisée

| Champ  | Type           | Défaut | Description                       |
| ------ | -------------- | ------ | --------------------------------- |
| `host` | string \| null | `null` | Dernier hôte utilisé par `copaw app` |
| `port` | int \| null    | `null` | Dernier port utilisé par `copaw app` |

Sauvegardé automatiquement à chaque exécution de `copaw app`. Les autres sous-commandes CLI
(comme `copaw cron`) l'utilisent pour savoir où envoyer les requêtes.

---

#### `last_dispatch` — Dernière cible de distribution de messages

| Champ        | Type   | Défaut | Description                                       |
| ------------ | ------ | ------ | ------------------------------------------------- |
| `channel`    | string | `""`   | Nom du canal (ex. `"discord"`, `"dingtalk"`)      |
| `user_id`    | string | `""`   | ID de l'utilisateur dans ce canal                 |
| `session_id` | string | `""`   | ID de session/conversation                        |

Mis à jour automatiquement quand un utilisateur envoie un message. Utilisé par le heartbeat quand
`target = "last"` — le résultat du heartbeat sera envoyé à ce canal/utilisateur/session.

---

#### `show_tool_details` — Visibilité de la sortie des outils

| Champ               | Type | Défaut | Description                                                                                                                        |
| ------------------- | ---- | ------ | ---------------------------------------------------------------------------------------------------------------------------------- |
| `show_tool_details` | bool | `true` | Quand `true`, les messages du canal incluent les détails complets des appels/résultats d'outils. Quand `false`, les détails sont masqués (affiche « ... »). |

---

## Fournisseurs LLM

CoPaw a besoin d'un fournisseur LLM pour fonctionner. Vous pouvez le configurer de trois façons :

- **`copaw init`** — assistant interactif, la façon la plus simple
- **Interface Console** — cliquez dans la page des paramètres au runtime
- **API** — `PUT /providers/{id}` et `PUT /providers/active_llm`

### Fournisseurs intégrés

| Fournisseur | ID           | URL de base par défaut                              | Préfixe de clé API |
| ----------- | ------------ | --------------------------------------------------- | ------------------ |
| ModelScope  | `modelscope` | `https://api-inference.modelscope.cn/v1`            | `ms`               |
| DashScope   | `dashscope`  | `https://dashscope.aliyuncs.com/compatible-mode/v1` | `sk`               |
| Personnalisé | `custom`    | _(vous le définissez)_                              | _(quelconque)_     |

Pour chaque fournisseur vous devez définir :

| Paramètre  | Description                                       |
| ---------- | ------------------------------------------------- |
| `base_url` | URL de base de l'API (pré-remplie pour les fournisseurs intégrés) |
| `api_key`  | Votre clé API                                     |

Puis choisissez quel fournisseur + modèle activer :

| Paramètre     | Description                                   |
| ------------- | --------------------------------------------- |
| `provider_id` | Quel fournisseur utiliser (ex. `dashscope`)   |
| `model`       | Quel modèle utiliser (ex. `qwen3-max`)        |

> **Conseil :** Exécutez `copaw init` et suivez les invites — il listera les modèles disponibles
> pour chaque fournisseur pour que vous puissiez en choisir un directement.
>
> **Note :** Vous êtes responsable de vous assurer que la clé API et l'URL de base sont valides.
> CoPaw ne vérifie pas si la clé est correcte ou a un quota suffisant —
> assurez-vous que le fournisseur et le modèle choisis sont accessibles.

---

## Variables d'environnement

Certains outils nécessitent des clés API supplémentaires (ex. `TAVILY_API_KEY` pour la recherche web). Vous pouvez
les gérer de trois façons :

- **`copaw init`** — demande « Configurer des variables d'environnement ? » lors de la configuration
- **Interface Console** — modifier dans la page des paramètres
- **API** — `GET/PUT/DELETE /envs`

Les variables définies sont auto-chargées au démarrage de l'application, donc tous les outils et processus enfants
peuvent les lire via `os.environ`.

> **Note :** Vous êtes responsable de vous assurer que les valeurs (ex. clés API tierces)
> sont valides. CoPaw ne fait que les stocker et les injecter — il ne vérifie pas
> leur exactitude.

---

## Skills

Les Skills étendent les capacités de l'agent. Elles se trouvent dans trois répertoires :

| Répertoire                    | Objectif                                                               |
| ----------------------------- | ---------------------------------------------------------------------- |
| Intégré (dans le code source) | Livré avec CoPaw — docx, pdf, pptx, xlsx, news, email, cron, etc.    |
| `~/.copaw/customized_skills/` | Skills créées par l'utilisateur                                        |
| `~/.copaw/active_skills/`     | Skills actuellement actives (synchronisées depuis intégrées + personnalisées) |

Chaque Skill est un répertoire avec un fichier `SKILL.md` (front matter YAML avec `name`
et `description`), et des sous-répertoires optionnels `references/` et `scripts/`.

Gérez les Skills via :

- `copaw init` (choisir tout / rien / personnalisé lors de la configuration)
- `copaw skills config` (bascule interactive)
- Points de terminaison API (`/skills/...`)

---

## Mémoire

CoPaw dispose d'une mémoire persistante inter-conversations : il compresse automatiquement le contexte et sauvegarde les informations clés dans des fichiers Markdown pour une rétention à long terme. Voir [Mémoire](./memory.fr.md) pour tous les détails.

Les fichiers de mémoire sont stockés dans deux emplacements :

| Fichier / Répertoire            | Objectif                                                                     |
| ------------------------------- | ---------------------------------------------------------------------------- |
| `~/.copaw/MEMORY.md`            | Informations clés durables (décisions, préférences, faits persistants)       |
| `~/.copaw/memory/YYYY-MM-DD.md` | Journaux quotidiens (notes, contexte runtime, résumés auto-générés)          |

### Configuration de l'embedding

La recherche mémoire repose sur des embeddings vectoriels pour la récupération sémantique. Configurez via ces variables d'environnement :

| Variable               | Description                           | Défaut                                              |
| ---------------------- | ------------------------------------- | --------------------------------------------------- |
| `EMBEDDING_API_KEY`    | Clé API pour le service d'embedding   | _(vide — recherche vectorielle désactivée si non définie)_ |
| `EMBEDDING_BASE_URL`   | URL du service d'embedding            | `https://dashscope.aliyuncs.com/compatible-mode/v1` |
| `EMBEDDING_MODEL_NAME` | Nom du modèle d'embedding             | `text-embedding-v4`                                 |
| `EMBEDDING_DIMENSIONS` | Dimensions vectorielles               | `1024`                                              |
| `FTS_ENABLED`          | Activer la recherche plein texte BM25 | `true`                                              |

> **Recommandé :** Définissez `EMBEDDING_API_KEY` et gardez `FTS_ENABLED=true` pour utiliser la récupération hybride vectorielle + BM25 pour de meilleurs résultats.

---

## Résumé

- Tout se trouve sous **`~/.copaw`** par défaut ; remplacez avec
  `COPAW_WORKING_DIR` (et les variables d'env associées) si nécessaire.
- Au quotidien vous modifiez **config.json** (canaux, heartbeat, langue) et
  **HEARTBEAT.md** (quoi demander à chaque tick heartbeat) ; gérez les tâches cron
  via CLI/API.
- La personnalité de l'agent est définie par les fichiers Markdown dans le répertoire de travail :
  **SOUL.md** + **AGENTS.md** (obligatoires).
- Les fournisseurs LLM sont configurés via `copaw init` ou l'interface console.
- Les modifications de config des canaux sont **auto-rechargées** sans redémarrage (sondage
  toutes les 2 secondes).
- Appelez l'API Agent : **POST** `/agent/process`, corps JSON, streaming SSE ;
  voir [Démarrage rapide — Vérifier l'installation](./quickstart#verify-install-optional) pour
  des exemples.

---

## Pages associées

- [Introduction](./intro) — Ce que le projet peut faire
- [Canaux](./channels) — Comment remplir les canaux dans la config
- [Heartbeat](./heartbeat) — Comment remplir le heartbeat dans la config

---

## Fichiers de prompt de l'agent en un coup d'œil

> Condensé depuis [Fichiers de prompt de l'agent](./agent_md_intro.fr.md) — voir la page complète pour les détails.
>
> La conception du prompt dans cette section est inspirée par [OpenClaw](https://github.com/openclaw/openclaw).

| Fichier          | Objectif principal                                           | Lecture/Écriture                                                                     | Contenu clé                                                                                                                              |
| ---------------- | ------------------------------------------------------------ | ------------------------------------------------------------------------------------ | ---------------------------------------------------------------------------------------------------------------------------------------- |
| **SOUL.md**      | Définit les **valeurs et principes comportementaux** de l'agent | Lecture seule (prédéfini par développeur/utilisateur)                              | Être véritablement utile ; avoir ses propres opinions ; essayer avant de demander ; respecter les limites de confidentialité              |
| **PROFILE.md**   | Enregistre l'**identité** et le **profil utilisateur** de l'agent | Lecture-écriture (auto-généré par BOOTSTRAP, puis modifiable manuellement ou via console) | Côté agent : nom, rôle, style, capacités ; Côté utilisateur : nom, fuseau horaire, préférences, contexte                          |
| **BOOTSTRAP.md** | Flux d'**intégration initial** pour les nouveaux agents      | Unique (s'auto-supprime après complétion ✂️)                                         | ① Auto-présentation → ② Apprendre sur l'utilisateur → ③ Écrire PROFILE.md → ④ Lire SOUL.md → ⑤ Auto-suppression                         |
| **AGENTS.md**    | **Manuel de fonctionnement complet** de l'agent              | Lecture seule (référence de fonctionnement principal)                                | Règles de lecture/écriture du système mémoire ; sécurité & permissions ; spécifications d'utilisation des outils ; déclencheurs heartbeat ; limites opérationnelles |
| **MEMORY.md**    | Stocke les **paramètres d'outils et leçons apprises** de l'agent | Lecture-écriture (maintenu par l'agent, aussi modifiable manuellement)             | Config & connexions SSH ; chemins/versions de l'environnement local ; personnalisation & préférences utilisateur                         |
| **HEARTBEAT.md** | Définit les **tâches de patrouille en arrière-plan** de l'agent | Lecture-écriture (fichier vide = ignorer heartbeat)                                | Vide → pas de patrouille ; écrire des tâches → exécution auto de la liste de contrôle aux intervalles configurés                         |

**Collaboration des fichiers :**

```
BOOTSTRAP.md (🐣 unique)
    ├── génère → PROFILE.md (🪪 qui suis-je)
    ├── guide la lecture → SOUL.md (🫀 mon âme)
    └── s'auto-supprime après complétion ✂️

AGENTS.md (📋 manuel quotidien)
    ├── lit/écrit → MEMORY.md (🧠 mémoire à long terme)
    ├── référence → HEARTBEAT.md (💓 patrouille périodique)
    └── référence → PROFILE.md (🪪 connaître l'utilisateur)
```

> **En une phrase :** SOUL définit le caractère, PROFILE mémorise les relations, BOOTSTRAP gère la naissance, AGENTS gouverne le comportement, MEMORY accumule l'expérience, HEARTBEAT reste vigilant.
