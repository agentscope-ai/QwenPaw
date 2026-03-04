# Console

La **Console** est l'interface web intégrée de CoPaw. Après avoir exécuté `copaw app`,
ouvrez `http://127.0.0.1:8088/` dans votre navigateur pour entrer dans la Console.

**Dans la Console, vous pouvez :**

- Discuter avec CoPaw en temps réel
- Activer/désactiver les canaux de messagerie
- Voir et gérer toutes les sessions de chat
- Gérer les tâches planifiées
- Modifier les fichiers de persona et de comportement de CoPaw
- Activer/désactiver les Skills pour étendre les capacités de CoPaw
- Gérer les clients MCP
- Modifier la configuration runtime
- Configurer les fournisseurs LLM et sélectionner les modèles actifs
- Gérer les variables d'environnement nécessaires aux outils

La barre latérale à gauche regroupe les fonctionnalités en **Chat**, **Contrôle**, **Agent**,
et **Paramètres**. Cliquez sur un élément pour changer de page. Les sections ci-dessous
parcourent chaque fonctionnalité dans l'ordre.

> **Vous ne voyez pas la Console ?** Assurez-vous que le frontend a été compilé. Voir
> [CLI](./cli).

---

## Chat

> Barre latérale : **Chat → Chat**

C'est ici que vous parlez à CoPaw. C'est la page par défaut à l'ouverture de la Console.

![Chat](https://img.alicdn.com/imgextra/i4/O1CN01iuGyNc1mNwsUU5NQI_!!6000000004943-2-tps-3822-2070.png)

**Envoyer un message :**
Tapez dans la zone de saisie en bas, puis appuyez sur **Entrée** ou cliquez sur le
bouton d'envoi (↑). CoPaw répond en temps réel.

**Créer une nouvelle session :**
Cliquez sur le bouton **+ Nouvelle conversation** en haut de la barre latérale de chat pour démarrer une nouvelle
conversation. Chaque session conserve un historique séparé.

**Changer de session :**
Cliquez sur un nom de session dans la barre latérale de chat pour charger son historique.

**Supprimer une session :**
Cliquez sur le bouton **···** sur un élément de session, puis cliquez sur l'icône **corbeille**.

---

## Canaux

> Barre latérale : **Contrôle → Canaux**

Gérer les canaux pour DingTalk, Feishu, Discord, QQ,
iMessage et Console.

![Channels](https://img.alicdn.com/imgextra/i4/O1CN01tUJBg121ZbBnC5fjx_!!6000000006999-2-tps-3822-2070.png)

**Activer un canal :**

1. Cliquez sur la carte du canal que vous souhaitez configurer.
2. Un panneau de paramètres glisse depuis la droite. Activez **Activer**.

   ![Channel Configuration](https://img.alicdn.com/imgextra/i1/O1CN01dbZiw21S5MUOUFJ06_!!6000000002195-2-tps-3822-2070.png)

3. Renseignez les identifiants requis (les champs varient selon le canal) :

   | Canal        | Champs obligatoires                                                            |
   | ------------ | ------------------------------------------------------------------------------ |
   | **DingTalk** | Client ID, Client Secret                                                       |
   | **Feishu**   | App ID, App Secret _(Encrypt Key / Verification Token / Media Dir optionnels)_ |
   | **Discord**  | Bot Token, Proxy HTTP, Auth Proxy                                              |
   | **QQ**       | App ID, Client Secret                                                          |
   | **iMessage** | Chemin de la base de données, Intervalle de sondage                            |
   | **Console**  | _(bascule uniquement)_                                                         |

4. Cliquez sur **Sauvegarder**. Les modifications prennent effet en quelques secondes, sans redémarrage.

**Désactiver un canal :**
Ouvrez le même panneau, désactivez **Activer**, puis cliquez sur **Sauvegarder**.

> Pour les détails de configuration des identifiants, voir [Canaux](./channels).

---

## Sessions

> Barre latérale : **Contrôle → Sessions**

Voir, filtrer et nettoyer les sessions de chat sur tous les canaux.

![Sessions](https://img.alicdn.com/imgextra/i2/O1CN0142DXNW1NkyOX07sJ7_!!6000000001609-2-tps-3822-2070.png)

**Trouver des sessions :**
Utilisez la zone de recherche pour filtrer par utilisateur, ou utilisez le menu déroulant pour filtrer par
canal. Le tableau se met à jour immédiatement.

**Renommer une session :**
Cliquez sur **Modifier** sur une ligne → changez le nom → cliquez sur **Sauvegarder**.

**Supprimer une session :**
Cliquez sur **Supprimer** sur une ligne → confirmer.

**Suppression par lot :**
Sélectionnez des lignes → cliquez sur **Suppression par lot** → confirmer.

---

## Tâches cron

> Barre latérale : **Contrôle → Tâches cron**

Créer et gérer des tâches planifiées que CoPaw exécute automatiquement selon un planning.

![Cron Jobs](https://img.alicdn.com/imgextra/i3/O1CN01JET1Aw1C9SAvXuIpk_!!6000000000038-2-tps-3822-2070.png)

**Créer une nouvelle tâche :**

1. Cliquez sur **+ Créer une tâche**.

   ![Create Cron Job](https://img.alicdn.com/imgextra/i2/O1CN01jFAcIZ1wCAqyxDGKX_!!6000000006271-2-tps-3822-2070.png)

2. Renseignez chaque section :
   - **Informations de base** — ID de tâche (ex. `job-001`) et nom de tâche (ex. "Résumé quotidien").
   - **Planning** — Expression cron (ex. `0 9 * * *` = 9h00 tous les jours) et
     fuseau horaire
   - **Type & contenu de tâche** — **Texte** (message fixe) ou **Agent** (interroger
     CoPaw et transmettre la réponse), puis le contenu
   - **Livraison** — Canal cible (Console, DingTalk, etc.), utilisateur cible & ID de session, et
     mode (**Stream** = temps réel, **Final** = une réponse complète)
   - **Avancé** — Concurrence maximale, délai d'expiration, délai de rattrapage
3. Cliquez sur **Sauvegarder**.

**Modifier une tâche :**
Cliquez sur **Modifier** sur une ligne → modifier les champs → **Sauvegarder**.

**Activer/désactiver une tâche :**
Basculez l'interrupteur dans la ligne.

**Exécuter une fois immédiatement :**
Cliquez sur **Exécuter maintenant** → confirmer.

**Supprimer une tâche :**
Cliquez sur **Supprimer** → confirmer.

---

## Espace de travail

> Barre latérale : **Agent → Espace de travail**

Modifier les fichiers qui définissent la persona et le comportement de CoPaw, tels que `SOUL.md`,
`AGENTS.md` et `HEARTBEAT.md`, directement dans le navigateur.

![Workspace](https://img.alicdn.com/imgextra/i3/O1CN01APrwdP1NqT9CKJMFt_!!6000000001621-2-tps-3822-2070.png)

**Modifier des fichiers :**

1. Cliquez sur un fichier dans la liste (ex. `SOUL.md`).
2. L'éditeur affiche le contenu du fichier. Effectuez vos modifications.
3. Cliquez sur **Sauvegarder** pour appliquer, ou **Réinitialiser** pour annuler et recharger.

**Voir la mémoire quotidienne :**
Si `MEMORY.md` existe, cliquez sur la flèche **▶** pour développer les entrées par date.
Cliquez sur une date pour voir ou modifier la mémoire de ce jour.

**Télécharger l'espace de travail :**
Cliquez sur **Télécharger** (⬇) pour exporter l'espace de travail entier en `.zip`.

**Téléverser/restaurer l'espace de travail :**
Cliquez sur **Téléverser** (⬆) → choisissez un `.zip` (max 100 Mo). Les fichiers d'espace de travail existants
seront remplacés. Utile pour la migration et la restauration de sauvegarde.

---

## Skills

> Barre latérale : **Agent → Skills**

Gérer les Skills qui étendent les capacités de CoPaw (par exemple : lecture PDF,
création de documents Word, récupération d'actualités).

![Skills](https://img.alicdn.com/imgextra/i1/O1CN01ZF4kVc1Yz8PlPdiM6_!!6000000003129-2-tps-3822-2070.png)

**Activer une Skill :**
Cliquez sur **Activer** en bas d'une carte de Skill. Elle prend effet immédiatement.

**Voir les détails d'une Skill :**
Cliquez sur une carte de Skill pour ouvrir sa description complète.

**Désactiver une Skill :**
Cliquez sur **Désactiver**. Elle prend effet immédiatement également.

**Importer depuis le Skills Hub :**

1. Cliquez sur **Importer une Skill**.
2. Entrez une URL de Skill, puis cliquez sur importer.
3. Attendez que l'import se termine. La Skill apparaît comme activée.

![Import Skill](https://img.alicdn.com/imgextra/i4/O1CN01LLVYzH28gCCjby41K_!!6000000007961-2-tps-3822-2070.png)

**Créer une Skill personnalisée :**

1. Cliquez sur **Créer une Skill**.
2. Entrez un nom de Skill (ex. `requete_meteo`) et le contenu de la Skill en Markdown
   (doit inclure `name` et `description`).
3. Cliquez sur **Sauvegarder**. La nouvelle Skill apparaît immédiatement.

![Create Skill](https://img.alicdn.com/imgextra/i3/O1CN01hW0eLY1go9qeiPrUF_!!6000000004188-2-tps-3822-2070.png)

**Supprimer une Skill personnalisée :**
Désactivez d'abord la Skill, puis cliquez sur l'icône **🗑** sur sa carte et confirmez.

> Pour les détails des Skills intégrées, l'import depuis le Skills Hub et la création de Skills personnalisées, voir
> [Skills](./skills).

---

## MCP

> Barre latérale : **Agent → MCP**

Activez/désactivez/supprimez les clients **MCP** ici, ou créez-en de nouveaux.

![MCP](https://img.alicdn.com/imgextra/i4/O1CN01ANXnQQ1IfPVO6bEbY_!!6000000000920-2-tps-3786-1980.png)

**Créer un client**
Cliquez sur **Créer un client** en haut à droite, renseignez les informations requises, puis cliquez sur **Créer**. Le nouveau client MCP apparaît dans la liste.

---

## Configuration runtime

> Barre latérale : **Agent → Configuration runtime**

![Runtime Config](https://img.alicdn.com/imgextra/i3/O1CN01mhPcqC1KzgGYJQgkW_!!6000000001235-2-tps-3786-1980.png)

Ajustez **Itérations max** et **Longueur d'entrée max** ici ; cliquez sur **Sauvegarder** après modification.

---

## Modèles

> Barre latérale : **Paramètres → Modèles**

Configurez les fournisseurs LLM et choisissez le modèle utilisé par CoPaw. CoPaw supporte à la fois
les fournisseurs cloud (clé API requise) et les fournisseurs locaux (sans clé API).

![Models](https://img.alicdn.com/imgextra/i2/O1CN01Kd3lg91HdkS5SaLoF_!!6000000000781-2-tps-3822-2070.png)

### Fournisseurs cloud

**Configurer un fournisseur :**

1. Cliquez sur **Paramètres** sur une carte de fournisseur (ModelScope, DashScope).
2. Entrez votre **Clé API**.
3. Cliquez sur **Sauvegarder**. Le statut de la carte devient « Autorisé ».
4. Pour ajouter un fournisseur personnalisé, cliquez sur **Ajouter un fournisseur**.
5. Entrez l'ID du fournisseur, le nom d'affichage et les champs requis, puis cliquez sur **Créer**.
6. Ouvrez **Paramètres** pour le fournisseur créé, renseignez les champs requis, puis
   **Sauvegarder**. Le statut devient « Autorisé ».

**Révoquer l'autorisation :**
Ouvrez le dialogue de paramètres du fournisseur et cliquez sur **Révoquer l'autorisation**. Les données de la clé API
sont effacées. Si ce fournisseur est actuellement actif, la sélection du modèle est également effacée.

### Fournisseurs locaux (llama.cpp / MLX)

Les fournisseurs locaux affichent un tag violet **Local**. Installez d'abord les dépendances backend
(`pip install 'copaw[llamacpp]'` ou `pip install 'copaw[mlx]'`).

**Télécharger un modèle :**

1. Cliquez sur **Gérer les modèles** sur une carte de fournisseur local.
2. Cliquez sur **Télécharger un modèle**, puis renseignez :
   - **Repo ID** (obligatoire) — ex. `Qwen/Qwen3-4B-GGUF`
   - **Nom du fichier** (optionnel) — laissez vide pour la sélection automatique
   - **Source** — Hugging Face (par défaut) ou ModelScope
3. Cliquez sur **Télécharger** et attendez la fin.

**Voir et supprimer des modèles :**
Les modèles téléchargés sont listés avec la taille du fichier, le badge source (**HF** / **MS**),
et le bouton de suppression.

### Fournisseur Ollama

Le fournisseur Ollama s'intègre avec votre daemon Ollama local et charge
dynamiquement les modèles depuis celui-ci.

**Prérequis :**

- Installez Ollama depuis [ollama.com](https://ollama.com)
- Installez le SDK Ollama : `pip install 'copaw[ollama]'` (ou relancez l'installateur avec `--extras ollama`)

**Télécharger un modèle :**

1. Cliquez sur **Paramètres** sur la carte du fournisseur Ollama.
2. Dans **Clé API**, entrez une valeur (par exemple `ollama`), puis cliquez sur **Sauvegarder**.
3. Cliquez sur **Gérer les modèles** sur la carte Ollama, cliquez sur **Télécharger un modèle**, et
   entrez un nom de modèle (ex. `mistral:7b`, `qwen3:8b`).
4. Cliquez sur **Télécharger le modèle** et attendez la fin.

**Annuler un téléchargement :**
Pendant le téléchargement, cliquez sur **✕** à côté de l'indicateur de progression pour annuler.

**Voir et supprimer des modèles :**
Les modèles téléchargés sont listés avec la taille et le bouton de suppression. La liste se met à jour
automatiquement quand des modèles sont ajoutés/supprimés via Ollama CLI ou la Console.

**Différences par rapport aux fournisseurs locaux :**

- Les modèles viennent du daemon Ollama (pas téléchargés directement par CoPaw)
- La liste des modèles est auto-synchronisée avec Ollama
- Exemples de modèles populaires : `mistral:7b`, `qwen3:8b`

> Vous pouvez également gérer les modèles Ollama via CLI : `copaw models ollama-pull`,
> `copaw models ollama-list`, `copaw models ollama-remove`. Voir
> [CLI](./cli#ollama-models).

### Choisir le modèle actif

1. Dans la section **Config LLM**, sélectionnez un **Fournisseur** dans le menu déroulant
   (seuls les fournisseurs autorisés ou les fournisseurs locaux avec des modèles téléchargés apparaissent).
2. Sélectionnez un **Modèle** dans le menu déroulant des modèles.
3. Cliquez sur **Sauvegarder**.

> **Note :** La validité de la clé API cloud est votre responsabilité. CoPaw ne
> vérifie pas l'exactitude de la clé.
>
> Pour les détails du fournisseur, voir [Config — Fournisseurs LLM](./config#fournisseurs-llm).

---

## Variables d'environnement

> Barre latérale : **Paramètres → Variables d'environnement**

Gérer les variables d'environnement runtime nécessaires aux outils et Skills de CoPaw
(par exemple, `TAVILY_API_KEY`).

![Environments](https://img.alicdn.com/imgextra/i1/O1CN01jNMeBA1nMP9tQdTmU_!!6000000005075-2-tps-3822-2070.png)

**Ajouter une variable :**

1. Cliquez sur **+ Ajouter une variable**.
2. Entrez le nom de la variable (ex. `TAVILY_API_KEY`) et la valeur.
3. Cliquez sur **Sauvegarder**.

**Modifier une variable :**
Changez le champ **Valeur**, puis cliquez sur **Sauvegarder**.
(Les noms de variables sont en lecture seule après sauvegarde ; pour renommer, supprimez et recréez.)

**Supprimer une variable :**
Cliquez sur l'icône **🗑** sur une ligne, puis confirmez si demandé.

**Suppression par lot :**
Sélectionnez des lignes → cliquez sur **Supprimer** dans la barre d'outils → confirmer.

> **Note :** La validité des variables est votre responsabilité. CoPaw ne fait que stocker et
> charger les valeurs.
>
> Voir [Config — Variables d'environnement](./config#variables-denvironnement) pour plus d'infos.

---

## Référence rapide

| Page                      | Chemin barre latérale                  | Ce que vous pouvez faire                                                  |
| ------------------------- | -------------------------------------- | ------------------------------------------------------------------------- |
| Chat                      | Chat → Chat                            | Discuter avec CoPaw, gérer les sessions                                   |
| Canaux                    | Contrôle → Canaux                      | Activer/désactiver les canaux, configurer les identifiants                |
| Sessions                  | Contrôle → Sessions                    | Filtrer, renommer, supprimer des sessions                                 |
| Tâches cron               | Contrôle → Tâches cron                 | Créer/modifier/supprimer des tâches, exécuter immédiatement               |
| Espace de travail         | Agent → Espace de travail              | Modifier les fichiers de persona, voir la mémoire, télécharger/téléverser |
| Skills                    | Agent → Skills                         | Activer/désactiver/créer/supprimer des Skills                             |
| MCP                       | Agent → MCP                            | Activer/désactiver/créer/supprimer des clients MCP                        |
| Configuration runtime     | Agent → Configuration runtime          | Modifier la configuration runtime                                         |
| Modèles                   | Paramètres → Modèles                   | Configurer les fournisseurs, gérer local/Ollama, choisir le modèle        |
| Variables d'environnement | Paramètres → Variables d'environnement | Ajouter/modifier/supprimer des variables d'environnement                  |

---

## Pages associées

- [Configuration & Répertoire de travail](./config) — Champs de config, fournisseurs, variables d'env
- [Canaux](./channels) — Configuration et identifiants par canal
- [Skills](./skills) — Skills intégrées et personnalisées
- [Heartbeat](./heartbeat) — Configuration du heartbeat
- [CLI](./cli) — Référence en ligne de commande
