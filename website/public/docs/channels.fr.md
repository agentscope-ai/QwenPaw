# Canaux

Un **canal** est l'endroit où vous parlez à CoPaw : connectez DingTalk et il répond
dans DingTalk ; pareil pour QQ, etc. Si ce terme vous est nouveau, voir l'[Introduction](./intro).

Deux façons de configurer les canaux :

- **Console** (recommandé) — Dans la [Console](./console) sous **Contrôle → Canaux**, cliquez sur une carte de canal, activez-le et renseignez les identifiants dans le panneau. Les modifications prennent effet à la sauvegarde.
- **Modifier `config.json` directement** — Par défaut `~/.copaw/config.json` (créé par `copaw init`), définissez `enabled: true` et renseignez les identifiants de cette plateforme. Sauvegarder déclenche un rechargement sans redémarrer l'application.

Tous les canaux partagent deux champs :

- **enabled** — Activer ou désactiver le canal.
- **bot_prefix** — Préfixe pour les réponses du bot (ex. `[BOT]`) pour les repérer facilement.
- **filter_tool_messages** — (optionnel, par défaut `false`) Filtrer les messages d'appel et de sortie d'outils pour ne pas les envoyer aux utilisateurs. Définissez à `true` pour masquer les détails d'exécution des outils.

Voici comment obtenir les identifiants et remplir la config pour chaque canal.

---

## DingTalk (recommandé)

### Créer une application DingTalk

Tutoriel vidéo :

![Video tutorial](https://cloud.video.taobao.com/vod/Fs7JecGIcHdL-np4AS7cXaLoywTDNj7BpiO7_Hb2_cA.mp4)

Étape par étape :

1. Ouvrez le [Portail développeur DingTalk](https://open-dev.dingtalk.com/)

2. Créez une **application d'entreprise interne**

   ![internal enterprise app](https://img.alicdn.com/imgextra/i1/O1CN01KLtwvu1rt9weVn8in_!!6000000005688-2-tps-2809-1585.png)

3. Ajoutez la capacité **「Robot」**

   ![add robot](https://img.alicdn.com/imgextra/i2/O1CN01AboPsn1XGQ84utCG8_!!6000000002896-2-tps-2814-1581.png)

4. Définissez le mode de réception de messages sur **Stream** puis publiez

   ![robot](https://img.alicdn.com/imgextra/i3/O1CN01KwmNZ61GwhDhKxgSv_!!6000000000687-2-tps-2814-1581.png)

   ![Stream](https://img.alicdn.com/imgextra/i2/O1CN01tk8QW11NqvXYqcoPH_!!6000000001622-2-tps-2809-1590.png)

5. Créez une nouvelle version à publier, remplissez les informations de base et sauvegardez

   ![new version](https://img.alicdn.com/imgextra/i3/O1CN01lRCPuf1PQwIeFL4AL_!!6000000001836-2-tps-2818-1590.png)

   ![save](https://img.alicdn.com/imgextra/i1/O1CN01vrzbIA1Qey2x8Jbua_!!6000000002002-2-tps-2809-1585.png)

6. Dans les détails de l'application, copiez :

   - **Client ID** (AppKey)
   - **Client Secret** (AppSecret)

   ![client](https://img.alicdn.com/imgextra/i3/O1CN01JsRrwx1hJImLfM7O1_!!6000000004256-2-tps-2809-1585.png)

7. (Optionnel) **Ajoutez l'IP de votre serveur à la liste blanche** — cela est nécessaire pour les fonctionnalités qui appellent l'API ouverte DingTalk (ex. téléchargement d'images et fichiers envoyés par les utilisateurs). Allez dans **"Sécurité & Conformité → Liste blanche IP"** dans les paramètres de votre application et ajoutez l'IP publique de la machine exécutant CoPaw. Vous pouvez trouver votre IP publique en exécutant `curl ifconfig.me` dans un terminal. Si l'IP n'est pas sur la liste blanche, les téléchargements d'images et de fichiers échoueront avec une erreur `Forbidden.AccessDenied.IpNotInWhiteList`.

### Lier l'application

Vous pouvez la configurer soit dans le frontend de la Console soit en modifiant `~/.copaw/config.json`.

**Méthode 1** : Configurer dans le frontend de la Console

Allez dans "Contrôle→Canaux", trouvez **DingTalk**, cliquez dessus, et entrez le **Client ID** et le **Client Secret** que vous venez d'obtenir.

![console](https://img.alicdn.com/imgextra/i3/O1CN01i07tt61rzZUSMo5SI_!!6000000005702-2-tps-3643-1897.png)

**Méthode 2** : Modifier `~/.copaw/config.json`

Dans `config.json`, trouvez `channels.dingtalk` et renseignez les informations correspondantes, par exemple :

```json
"dingtalk": {
  "enabled": true,
  "bot_prefix": "[BOT]",
  "client_id": "votre Client ID",
  "client_secret": "votre Client Secret",
  "filter_tool_messages": false
}
```

- Définissez `filter_tool_messages: true` si vous souhaitez masquer les détails d'exécution des outils dans le chat.

Sauvegardez le fichier ; si l'application est déjà en cours d'exécution, le canal rechargera. Sinon exécutez
`copaw app`.

### Trouver l'application créée

Tutoriel vidéo :

![Video tutorial](https://cloud.video.taobao.com/vod/Ppt7rLy5tvuMFXDLks8Y2hDYV9hAfoZ78Y8mC0wUn1g.mp4)

Étape par étape :

1. Dans DingTalk, appuyez sur la **zone de recherche** dans l'onglet **[Messages]**

![Search box](https://img.alicdn.com/imgextra/i4/O1CN01qVVqyx1Mh1MLdOq2X_!!6000000001465-2-tps-2809-2236.png)

2. Recherchez le **nom du bot** que vous venez de créer ; trouvez le bot sous **[Fonctions]**

![Bot](https://img.alicdn.com/imgextra/i3/O1CN01AzxSlR2AJPjY6xfOU_!!6000000008182-2-tps-2809-2236.png)

3. Appuyez pour ouvrir le chat

![Chat](https://img.alicdn.com/imgextra/i4/O1CN01ut70CJ1pXyOO5sg7P_!!6000000005371-2-tps-2032-1614.png)

> Vous pouvez ajouter le bot à un chat de groupe via **Paramètres du groupe → Bots → Ajouter un robot dans DingTalk**. Si vous créez un chat de groupe depuis votre conversation individuelle avec le bot, les réponses du bot ne seront pas déclenchées.

---

## Feishu (Lark)

Le canal Feishu reçoit les messages via **connexion longue WebSocket** (pas d'IP publique ou webhook nécessaire). L'envoi utilise l'API ouverte Feishu. Il supporte le texte, les images et les fichiers dans les deux sens. Pour les chats de groupe, `chat_id` et `message_id` sont inclus dans les métadonnées du message de requête pour la déduplication et le contexte en aval.

### Créer une application Feishu et obtenir les identifiants

1. Ouvrez la [Plateforme ouverte Feishu](https://open.feishu.cn/app) et créez une application d'entreprise

![Feishu](https://img.alicdn.com/imgextra/i4/O1CN01pb7WtO1Zvl6rlQllk_!!6000000003257-2-tps-4082-2126.png)

![Build](https://img.alicdn.com/imgextra/i4/O1CN018o4NsY1Q0fC22LtRv_!!6000000001914-2-tps-4082-2126.png)

2. Dans **Identifiants & Informations de base**, copiez **App ID** et **App Secret**

![ID & Secret](https://img.alicdn.com/imgextra/i2/O1CN01XISo4K2A9nPrMUT4f_!!6000000008161-2-tps-4082-2126.png)

3. Renseignez **App ID** et **App Secret** dans `config.json` (voir "Remplir config.json" ci-dessous) et sauvegardez

4. Exécutez **`copaw app`** pour démarrer CoPAW

5. Retournez dans la console Feishu, activez **Bot** sous **Ajouter des fonctionnalités**

![Bot](https://img.alicdn.com/imgextra/i3/O1CN01kqWyqE1mM7IAlSf8k_!!6000000004939-2-tps-4082-2126.png)

6. Sous **Permissions & Portées**, sélectionnez **Import/export de portées par lot** et collez le JSON suivant :

```json
{
  "scopes": {
    "tenant": [
      "aily:file:read",
      "aily:file:write",
      "aily:message:read",
      "aily:message:write",
      "corehr:file:download",
      "im:chat",
      "im:message",
      "im:message.group_msg",
      "im:message.p2p_msg:readonly",
      "im:message.reactions:read",
      "im:resource",
      "contact:user.base:readonly"
    ],
    "user": []
  }
}
```

![Import/Export](https://img.alicdn.com/imgextra/i1/O1CN01mrXvWI1tiHm1tm9BE_!!6000000005935-2-tps-4082-2126.png)

![JSON](https://img.alicdn.com/imgextra/i4/O1CN01YJPgEg20OmDC1SfEa_!!6000000006840-2-tps-4082-2126.png)

![Confirm](https://img.alicdn.com/imgextra/i3/O1CN01J37Aq41GH1B7NgLYi_!!6000000000596-2-tps-4082-2126.png)

![Confirm](https://img.alicdn.com/imgextra/i1/O1CN01N0ZPMt1LM7fi35WAn_!!6000000001284-2-tps-4082-2126.png)

7. Sous **Événements & Callbacks**, cliquez sur **Configuration des événements**, et choisissez **Recevoir les événements via connexion persistante** comme mode d'abonnement (pas d'IP publique nécessaire)

> **Note :** Suivez cet ordre : Configurer App ID/Secret → démarrer `copaw app` → puis configurer la connexion longue dans la console Feishu. Si des erreurs persistent, essayez d'arrêter le service copaw et de redémarrer `copaw app`.

![WebSocket](https://img.alicdn.com/imgextra/i3/O1CN01XdU7hK1fVY8gIDhZK_!!6000000004012-2-tps-4082-2126.png)

8. Sélectionnez **Ajouter des événements**, recherchez **Message reçu**, et abonnez-vous à **Message reçu v2.0**

![Receive](https://img.alicdn.com/imgextra/i1/O1CN01EE4iZf1CnIdDDeli6_!!6000000000125-2-tps-4082-2126.png)

![Click](https://img.alicdn.com/imgextra/i2/O1CN01PlzsFU1JhWx9EcuPc_!!6000000001060-2-tps-4082-2126.png)

![Result](https://img.alicdn.com/imgextra/i2/O1CN01fiMjkp24mN51TyWcI_!!6000000007433-2-tps-4082-2126.png)

9. Sous **Versions de l'application** → **Gestion des versions & Publication**, **Créez une version**, renseignez les informations de base, **Sauvegardez** et **Publiez**

![Create](https://img.alicdn.com/imgextra/i3/O1CN01mzOHs11cdO4MnZMcX_!!6000000003623-2-tps-4082-2126.png)

![Info](https://img.alicdn.com/imgextra/i1/O1CN01y1SkZP24hKiufZpb5_!!6000000007422-2-tps-4082-2126.png)

![Save](https://img.alicdn.com/imgextra/i2/O1CN01o1Wq3n2AD0BkIVidL_!!6000000008168-2-tps-4082-2126.png)

![pub](https://img.alicdn.com/imgextra/i1/O1CN01dcWI7F1PmSuniDLJx_!!6000000001883-2-tps-4082-2126.png)

### Remplir config.json

Trouvez `channels.feishu` (par défaut dans `~/.copaw/config.json`) dans `config.json`. Seuls **App ID** et **App Secret** sont obligatoires (copiez depuis la console Feishu sous Identifiants & informations de base) :

```json
"feishu": {
  "enabled": true,
  "bot_prefix": "[BOT]",
  "app_id": "cli_xxxxx",
  "app_secret": "votre App Secret"
}
```

Les autres champs (encrypt_key, verification_token, media_dir) sont optionnels ; en mode WebSocket vous pouvez les omettre (les valeurs par défaut s'appliquent). Puis `pip install lark-oapi` et exécutez `copaw app`. Si votre environnement utilise un proxy SOCKS, installez également `python-socks` (par exemple, `pip install python-socks`), sinon vous pourriez voir : `python-socks is required to use a SOCKS proxy`.

> **Note :** Vous pouvez également renseigner **App ID** et **App Secret** dans l'interface Console, mais vous devez redémarrer le service copaw avant de continuer avec la configuration de la connexion longue.
> ![console](https://img.alicdn.com/imgextra/i1/O1CN01JInbHT1ei5MdfkMGv_!!6000000003904-2-tps-4082-2126.png)

### Permissions bot recommandées

Le JSON de l'étape 6 accorde les permissions suivantes (identité application) pour la messagerie et les fichiers :

| Nom de la permission                               | ID de permission               | Type            | Notes               |
| -------------------------------------------------- | ------------------------------ | --------------- | ------------------- |
| Obtenir un fichier                                 | aily:file:read                 | Application     | -                   |
| Téléverser un fichier                              | aily:file:write                | Application     | -                   |
| Obtenir un message                                 | aily:message:read              | Application     | -                   |
| Envoyer un message                                 | aily:message:write             | Application     | -                   |
| Télécharger un fichier                             | corehr:file:download           | Application     | -                   |
| Obtenir/mettre à jour les infos du groupe          | im:chat                        | Application     | -                   |
| Obtenir/envoyer des messages chat et groupe        | im:message                     | Application     | -                   |
| Obtenir tous les messages de groupe (sensible)     | im:message.group_msg           | Application     | -                   |
| Lire les DM utilisateur-bot                        | im:message.p2p_msg:readonly    | Application     | -                   |
| Voir les réactions aux messages                    | im:message.reactions:read      | Application     | -                   |
| Obtenir/téléverser des ressources image et fichier | im:resource                    | Application     | -                   |
| **Lire les contacts en tant qu'application**       | **contact:user.base:readonly** | **Application** | **Voir ci-dessous** |

> **Nom d'affichage de l'utilisateur (recommandé) :** Pour afficher les **pseudonymes des utilisateurs** dans les sessions et les journaux (ex. "张三#1d1a" au lieu de "unknown#1d1a"), activez la permission de lecture des contacts **Lire les contacts en tant qu'application** (`contact:user.base:readonly`). Sans celle-ci, Feishu ne renvoie que les champs d'identité (ex. open_id) et pas le nom de l'utilisateur, donc CoPAW ne peut pas résoudre les pseudonymes. Après activation, publiez ou mettez à jour la version de l'application pour que la permission prenne effet.

### Ajouter le bot aux favoris

1. Dans **l'Espace de travail**, appuyez sur **Ajouter** aux **Favoris**

![Add favorite](https://img.alicdn.com/imgextra/i2/O1CN01G32zCo1gKqUyJH8H7_!!6000000004124-2-tps-2614-1488.png)

2. Recherchez le nom du bot que vous avez créé et appuyez sur **Ajouter**

![Add](https://img.alicdn.com/imgextra/i3/O1CN01paAwW31XhRUuRq7vi_!!6000000002955-2-tps-3781-2154.png)

3. Le bot apparaîtra dans vos favoris ; appuyez dessus pour ouvrir le chat

![Added](https://img.alicdn.com/imgextra/i4/O1CN012n7SOT1D07imvq7LY_!!6000000000153-2-tps-2614-1488.png)

![Chat](https://img.alicdn.com/imgextra/i2/O1CN01upVEJw1zKMmYtP9PP_!!6000000006695-2-tps-2614-1488.png)

---

## iMessage (macOS uniquement)

> ⚠️ Le canal iMessage est **macOS uniquement**. Il repose sur l'application Messages locale et la base de données iMessage, il ne peut donc pas fonctionner sous Linux ou Windows.

L'application sonde la base de données iMessage locale à la recherche de nouveaux messages et envoie des réponses en votre nom.

### Prérequis

- Assurez-vous que **Messages** est connecté sur ce Mac (ouvrez l'application Messages et connectez-vous
  avec votre Apple ID dans les Paramètres système).
- Installez **imsg** (utilisé pour accéder à la base de données iMessage) :
  ```bash
  brew install steipete/tap/imsg
  ```
- Le chemin par défaut de la base de données iMessage est `~/Library/Messages/chat.db`. Utilisez-le sauf si vous avez déplacé la base de données.
- L'application nécessite **Accès complet au disque** (Paramètres système → Confidentialité & Sécurité → Accès complet au disque) pour lire `chat.db`.
- Tout reste sur votre machine ; aucune donnée n'est envoyée ailleurs.

### Remplir config.json

```json
"imessage": {
  "enabled": true,
  "bot_prefix": "[BOT]",
  "db_path": "~/Library/Messages/chat.db",
  "poll_sec": 1.0
}
```

- **db_path** — Chemin vers la base de données iMessage
- **poll_sec** — Intervalle de sondage en secondes (1 est correct)

---

## Discord

### Obtenir un Token de Bot

1. Ouvrez le [Portail développeur Discord](https://discord.com/developers/applications)

![Discord Developer Portal](https://img.alicdn.com/imgextra/i2/O1CN01oV68yZ1sb7y3nGoQN_!!6000000005784-2-tps-4066-2118.png)

2. Créez une nouvelle application (ou sélectionnez-en une existante)

![Create application](https://img.alicdn.com/imgextra/i2/O1CN01eA9lA71kMukVCWR4y_!!6000000004670-2-tps-3726-1943.png)

3. Allez dans **Bot** dans la barre latérale gauche, créez un bot et copiez le **Token**

![Token](https://img.alicdn.com/imgextra/i1/O1CN01iuPiUe1lJzqEiIu23_!!6000000004799-2-tps-2814-1462.png)

4. Faites défiler vers le bas, activez **Message Content Intent** et **Send Messages** pour le bot, puis sauvegardez

![Permissions](https://img.alicdn.com/imgextra/i4/O1CN01EXH4w51FSdbxYKLG9_!!6000000000486-2-tps-4066-2118.png)

5. Dans **OAuth2 → URL Generator**, activez `bot`, accordez **Send Messages**, et générez le lien d'invitation

![Bot](https://img.alicdn.com/imgextra/i2/O1CN01B2oXx71KVS7kjKSEm_!!6000000001169-2-tps-4066-2118.png)

![Send Messages](https://img.alicdn.com/imgextra/i3/O1CN01DlU9oi1QYYVBPoUIA_!!6000000001988-2-tps-4066-2118.png)

![Link](https://img.alicdn.com/imgextra/i2/O1CN01ljhh1j1OZLxb2mAkO_!!6000000001719-2-tps-4066-2118.png)

6. Ouvrez le lien dans votre navigateur ; il redirigera vers Discord. Ajoutez le bot à votre serveur

![Server](https://img.alicdn.com/imgextra/i2/O1CN01QlcQPI1KzgGTWtZnb_!!6000000001235-2-tps-2798-1822.png)

![Server](https://img.alicdn.com/imgextra/i4/O1CN01ihF0dW1xC0Jw8uwm6_!!6000000006406-2-tps-2798-1822.png)

7. Vous pouvez voir que le bot est maintenant dans votre serveur

![Bot in server](https://img.alicdn.com/imgextra/i4/O1CN01IDPCke1S1EvIIqtX9_!!6000000002186-2-tps-2798-1822.png)

### Configurer le Bot

Vous pouvez configurer via l'interface Console ou en modifiant `~/.copaw/config.json`.

**Méthode 1 :** Configurer dans la Console

Allez dans **Contrôle → Canaux**, cliquez sur **Discord**, et entrez le **Token du Bot** que vous avez obtenu.

![Console](https://img.alicdn.com/imgextra/i4/O1CN019GKk901VE0od1PU9t_!!6000000002620-2-tps-4084-2126.png)

**Méthode 2 :** Modifier `~/.copaw/config.json`

Trouvez `channels.discord` dans `config.json` et renseignez les champs, par exemple :

```json
"discord": {
  "enabled": true,
  "bot_prefix": "[BOT]",
  "bot_token": "votre Token du Bot",
  "http_proxy": "",
  "http_proxy_auth": ""
}
```

Si vous avez besoin d'un proxy (ex. pour des restrictions réseau) :

- **http_proxy** — ex. `http://127.0.0.1:7890`
- **http_proxy_auth** — `utilisateur:mot_de_passe` si le proxy nécessite une authentification, sinon laissez vide

---

## QQ

### Obtenir les identifiants du bot QQ

1. Ouvrez la [Plateforme développeur QQ](https://q.qq.com/)

![Platform](https://img.alicdn.com/imgextra/i4/O1CN01OjCvUf1oT6ZDWpEk5_!!6000000005225-2-tps-4082-2126.png)

2. Créez une **application bot** et cliquez pour ouvrir la page de modification

![bot](https://img.alicdn.com/imgextra/i3/O1CN01xBbXWa1pSTdioYFdg_!!6000000005359-2-tps-4082-2126.png)

![confirm](https://img.alicdn.com/imgextra/i3/O1CN01zt7w0V1Ij4fjcm5MS_!!6000000000928-2-tps-4082-2126.png)

3. Allez dans **Configuration des callbacks** → activez **Événements de messages C2C** sous **Événements de messages directs**, et **Événement At pour les messages de groupe** sous **Événements de groupe**, puis confirmez

![c2c](https://img.alicdn.com/imgextra/i4/O1CN01HDSoX91iOAbTVULZf_!!6000000004402-2-tps-4082-2126.png)

![at](https://img.alicdn.com/imgextra/i4/O1CN01UJn1AK1UKatKkjMv4_!!6000000002499-2-tps-4082-2126.png)

4. Dans **Configuration sandbox** → **Liste des messages**, cliquez sur **Ajouter un membre** et ajoutez **vous-même**

![1](https://img.alicdn.com/imgextra/i4/O1CN01BSdkXl1ckG0dC7vH9_!!6000000003638-2-tps-4082-2126.png)

![1](https://img.alicdn.com/imgextra/i4/O1CN01LGYUMe1la1hmtcuyY_!!6000000004834-2-tps-4082-2126.png)

5. Dans **Paramètres développeur**, obtenez **AppID** et **AppSecret** (ClientSecret) et renseignez-les dans la config (voir ci-dessous). Ajoutez l'**IP de votre serveur à la liste blanche** — seules les IP sur liste blanche peuvent appeler l'API ouverte hors sandbox.

![1](https://img.alicdn.com/imgextra/i4/O1CN012UQWI21cnvBAUcz54_!!6000000003646-2-tps-4082-2126.png)

6. Dans la config sandbox, scannez le code QR avec QQ pour ajouter le bot à votre liste de messages

![1](https://img.alicdn.com/imgextra/i3/O1CN01r1OvPy1kcwc30w32K_!!6000000004705-2-tps-4082-2126.png)

### Remplir config.json

Dans `config.json`, trouvez `channels.qq` et définissez `app_id` et `client_secret` avec les
valeurs ci-dessus :

```json
"qq": {
  "enabled": true,
  "bot_prefix": "[BOT]",
  "app_id": "votre AppID",
  "client_secret": "votre AppSecret"
}
```

Vous fournissez **AppID** et **AppSecret** comme deux champs séparés ; ne les concaténez pas
en un seul token.

Vous pouvez également les renseigner dans l'interface Console.

![1](https://img.alicdn.com/imgextra/i1/O1CN013zS1dF1hLal9IM4rc_!!6000000004261-2-tps-4082-2126.png)

---

## Annexe

### Vue d'ensemble de la configuration

| Canal    | Clé config | Champs principaux                                                         |
| -------- | ---------- | ------------------------------------------------------------------------- |
| DingTalk | dingtalk   | client_id, client_secret                                                  |
| Feishu   | feishu     | app_id, app_secret ; optionnel encrypt_key, verification_token, media_dir |
| iMessage | imessage   | db_path, poll_sec (macOS uniquement)                                      |
| Discord  | discord    | bot_token ; optionnel http_proxy, http_proxy_auth                         |
| QQ       | qq         | app_id, client_secret                                                     |

Les détails des champs et la structure se trouvent dans les tableaux ci-dessus et dans [Config & répertoire de travail](./config).

### Support des messages multimodaux

Le support pour la **réception** (utilisateur → bot) et l'**envoi** (bot → utilisateur) de texte, image,
vidéo, audio et fichier varie selon le canal.
**✓** = supporté. **🚧** = en construction (réalisable mais pas encore fait). **✗** = non supporté (pas possible sur ce canal).

| Canal    | Reçoit texte | Reçoit image | Reçoit vidéo | Reçoit audio | Reçoit fichier | Envoie texte | Envoie image | Envoie vidéo | Envoie audio | Envoie fichier |
| -------- | ------------ | ------------ | ------------ | ------------ | -------------- | ------------ | ------------ | ------------ | ------------ | -------------- |
| DingTalk | ✓            | ✓            | ✓            | ✓            | ✓              | ✓            | ✓            | ✓            | ✓            | ✓              |
| Feishu   | ✓            | ✓            | ✓            | ✓            | ✓              | ✓            | ✓            | ✓            | ✓            | ✓              |
| Discord  | ✓            | ✓            | ✓            | ✓            | ✓              | ✓            | 🚧           | 🚧           | 🚧           | 🚧             |
| iMessage | ✓            | ✗            | ✗            | ✗            | ✗              | ✓            | ✗            | ✗            | ✗            | ✗              |
| QQ       | ✓            | 🚧           | 🚧           | 🚧           | 🚧             | ✓            | 🚧           | 🚧           | 🚧           | 🚧             |

Notes :

- **DingTalk** : Reçoit le texte enrichi et un seul fichier (downloadCode) ; envoie
  image / voix / vidéo / fichier via le webhook de session.
- **Feishu** : Connexion longue WebSocket pour la réception ; API ouverte pour l'envoi.
  Texte / image / fichier supportés dans les deux sens ; les métadonnées du message incluent
  `feishu_chat_id` et `feishu_message_id` pour le contexte de groupe et la déduplication.
- **Discord** : Les pièces jointes sont analysées comme image / vidéo / audio / fichier pour
  l'agent ; l'envoi de vrais médias est 🚧 (actuellement lien uniquement dans la réponse).
- **iMessage** : imsg + sondage de base de données ; texte uniquement ; les pièces jointes sont ✗ (pas
  possible sur ce canal).
- **QQ** : La réception des pièces jointes comme multimodal et l'envoi de vrais médias sont 🚧 ;
  actuellement texte + lien uniquement.

### Changer la config via HTTP

Avec l'application en cours d'exécution, vous pouvez lire et mettre à jour la config du canal ; les modifications sont écrites dans
`config.json` et appliquées automatiquement :

- `GET /config/channels` — Lister tous les canaux
- `PUT /config/channels` — Remplacer tout
- `GET /config/channels/{channel_name}` — Obtenir un canal (ex. `dingtalk`, `imessage`)
- `PUT /config/channels/{channel_name}` — Mettre à jour un canal

---

## Étendre les canaux

Pour ajouter une nouvelle plateforme (ex. WeCom, Slack), implémentez une sous-classe de **BaseChannel** ; le code principal reste inchangé.

### Flux de données et file d'attente

- **ChannelManager** maintient une file d'attente par canal qui l'utilise. Quand un message arrive, le canal appelle **`self._enqueue(payload)`** (injecté par le manager au démarrage) ; la boucle consumer du manager appelle ensuite **`channel.consume_one(payload)`**.
- La classe de base implémente un **`consume_one` par défaut** : transformer le payload en `AgentRequest`, exécuter `_process`, appeler `send_message_content` pour chaque message complété, et `_on_consume_error` en cas d'échec. La plupart des canaux n'ont besoin d'implémenter que « entrant → requête » et « réponse → sortant » ; ils ne remplacent pas `consume_one`.

### La sous-classe doit implémenter

| Méthode                                                 | Objectif                                                                                                                                                                        |
| ------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `build_agent_request_from_native(self, native_payload)` | Convertir le message natif du canal en `AgentRequest` (en utilisant le runtime `Message` / `TextContent` / `ImageContent` etc.) et définir `request.channel_meta` pour l'envoi. |
| `from_env` / `from_config`                              | Construire l'instance depuis l'environnement ou la config.                                                                                                                      |
| `async start()` / `async stop()`                        | Cycle de vie (connexion, abonnement, nettoyage).                                                                                                                                |
| `async send(self, to_handle, text, meta=None)`          | Envoyer un texte (et des pièces jointes optionnelles).                                                                                                                          |

### Ce que la classe de base fournit

- **Flux de consommation** : `_payload_to_request`, `get_to_handle_from_request` (par défaut `user_id`), `get_on_reply_sent_args`, `_before_consume_process` (ex. sauvegarder receive_id), `_on_consume_error` (par défaut : `send_content_parts`), et optionnel **`refresh_webhook_or_token`** (no-op ; à remplacer quand le canal doit rafraîchir les tokens).
- **Helpers** : `resolve_session_id`, `build_agent_request_from_user_content`, `_message_to_content_parts`, `send_message_content`, `send_content_parts`, `to_handle_from_target`.

Remplacez **`consume_one`** uniquement quand le flux diffère (ex. impression console, debounce). Remplacez **`get_to_handle_from_request`** / **`get_on_reply_sent_args`** quand la cible d'envoi ou les args de callback diffèrent.

### Exemple : canal minimal (texte uniquement)

Pour les canaux texte uniquement utilisant la file du manager, vous n'avez pas besoin d'implémenter `consume_one` ; la base par défaut suffit :

```python
# my_channel.py
from agentscope_runtime.engine.schemas.agent_schemas import TextContent, ContentType
from copaw.app.channels.base import BaseChannel
from copaw.app.channels.schema import ChannelType

class MyChannel(BaseChannel):
    channel: ChannelType = "my_channel"

    def __init__(self, process, enabled=True, bot_prefix="", **kwargs):
        super().__init__(process, on_reply_sent=kwargs.get("on_reply_sent"))
        self.enabled = enabled
        self.bot_prefix = bot_prefix

    @classmethod
    def from_config(cls, process, config, on_reply_sent=None, show_tool_details=True):
        return cls(process=process, enabled=getattr(config, "enabled", True),
                   bot_prefix=getattr(config, "bot_prefix", ""), on_reply_sent=on_reply_sent)

    @classmethod
    def from_env(cls, process, on_reply_sent=None):
        return cls(process=process, on_reply_sent=on_reply_sent)

    def build_agent_request_from_native(self, native_payload):
        payload = native_payload if isinstance(native_payload, dict) else {}
        channel_id = payload.get("channel_id") or self.channel
        sender_id = payload.get("sender_id") or ""
        meta = payload.get("meta") or {}
        session_id = self.resolve_session_id(sender_id, meta)
        text = payload.get("text", "")
        content_parts = [TextContent(type=ContentType.TEXT, text=text)]
        request = self.build_agent_request_from_user_content(
            channel_id=channel_id, sender_id=sender_id, session_id=session_id,
            content_parts=content_parts, channel_meta=meta,
        )
        request.channel_meta = meta
        return request

    async def start(self):
        pass

    async def stop(self):
        pass

    async def send(self, to_handle, text, meta=None):
        # Appeler votre API HTTP etc. pour envoyer
        pass
```

Quand vous recevez un message, construisez un dict natif et mettez en file d'attente (`_enqueue` est injecté par le manager) :

```python
native = {
    "channel_id": "my_channel",
    "sender_id": "user_123",
    "text": "Bonjour",
    "meta": {},
}
self._enqueue(native)
```

### Exemple : multimodal (texte + image / vidéo / audio / fichier)

Dans `build_agent_request_from_native`, analysez les pièces jointes en contenu runtime et appelez `build_agent_request_from_user_content` :

```python
from agentscope_runtime.engine.schemas.agent_schemas import (
    TextContent, ImageContent, VideoContent, AudioContent, FileContent, ContentType,
)

def build_agent_request_from_native(self, native_payload):
    payload = native_payload if isinstance(native_payload, dict) else {}
    channel_id = payload.get("channel_id") or self.channel
    sender_id = payload.get("sender_id") or ""
    meta = payload.get("meta") or {}
    session_id = self.resolve_session_id(sender_id, meta)
    content_parts = []
    if payload.get("text"):
        content_parts.append(TextContent(type=ContentType.TEXT, text=payload["text"]))
    for att in payload.get("attachments") or []:
        t = (att.get("type") or "file").lower()
        url = att.get("url") or ""
        if not url:
            continue
        if t == "image":
            content_parts.append(ImageContent(type=ContentType.IMAGE, image_url=url))
        elif t == "video":
            content_parts.append(VideoContent(type=ContentType.VIDEO, video_url=url))
        elif t == "audio":
            content_parts.append(AudioContent(type=ContentType.AUDIO, data=url))
        else:
            content_parts.append(FileContent(type=ContentType.FILE, file_url=url))
    if not content_parts:
        content_parts = [TextContent(type=ContentType.TEXT, text="")]
    request = self.build_agent_request_from_user_content(
        channel_id=channel_id, sender_id=sender_id, session_id=session_id,
        content_parts=content_parts, channel_meta=meta,
    )
    request.channel_meta = meta
    return request
```

### Répertoire des canaux personnalisés et CLI

- **Répertoire** : Les canaux sous le répertoire de travail dans `custom_channels/` (par défaut `~/.copaw/custom_channels/`) sont chargés au runtime. Le manager scanne les fichiers `.py` et les paquets (sous-répertoires avec `__init__.py`), charge les sous-classes `BaseChannel` et les enregistre par l'attribut `channel` de la classe.
- **Installer** : `copaw channels install <key>` crée un template `<key>.py` dans `custom_channels/` à modifier, ou utilisez `--path <chemin local>` / `--url <URL>` pour copier un module de canal depuis le disque ou le web. `copaw channels add <key>` fait de même et ajoute également une entrée par défaut à la config (avec optionnel `--path`/`--url`).
- **Supprimer** : `copaw channels remove <key>` supprime le module de ce canal depuis `custom_channels/` (canaux personnalisés uniquement ; les intégrés ne peuvent pas être supprimés). Par défaut, il supprime également la clé de `channels` dans `config.json` ; utilisez `--keep-config` pour laisser la config inchangée.
- **Config** : `ChannelConfig` utilise `extra="allow"`, donc n'importe quelle clé de canal peut apparaître sous `channels` dans `config.json`. Utilisez `copaw channels config` pour la configuration interactive ou modifiez la config manuellement.

---

## Pages associées

- [Introduction](./intro) — Ce que le projet peut faire
- [Démarrage rapide](./quickstart) — Installation et première exécution
- [Heartbeat](./heartbeat) — Bilan / digest planifié
- [CLI](./cli) — init, app, cron, clean
- [Configuration & répertoire de travail](./config) — config.json et répertoire de travail
