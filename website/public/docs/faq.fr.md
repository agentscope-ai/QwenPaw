# FAQ

Cette page regroupe les questions les plus fréquemment posées par la communauté.
Cliquez sur une question pour afficher la réponse.

---

### CoPaw vs OpenClaw : Comparaison des fonctionnalités

Veuillez consulter la page [Comparaison](/docs/comparison) pour une comparaison détaillée des fonctionnalités.

### Comment installer CoPaw

CoPaw supporte plusieurs méthodes d'installation. Voir
[Démarrage rapide](https://copaw.agentscope.io/docs/quickstart) pour les détails :

1. Installateur en une ligne (configure Python automatiquement)

```
# macOS / Linux :
curl -fsSL https://copaw.agentscope.io/install.sh | bash
# Windows (PowerShell) :
irm https://copaw.agentscope.io/install.ps1 | iex
# Pour les dernières instructions, référez-vous à la documentation et préférez pip si nécessaire.
```

2. Installer avec pip

Version Python requise : >= 3.10, < 3.14

```
pip install copaw
```

3. Installer avec Docker

Si Docker est installé, exécutez les commandes suivantes puis ouvrez
`http://127.0.0.1:8088/` dans votre navigateur :

```
docker pull agentscope/copaw:latest
docker run -p 8088:8088 -v copaw-data:/app/working agentscope/copaw:latest
```

### Comment mettre à jour CoPaw

Pour mettre à jour CoPaw, utilisez la méthode correspondant à votre type d'installation :

1. Si installé via le script en une ligne, relancez l'installateur pour mettre à jour.

2. Si installé via pip, exécutez :

```
pip install --upgrade copaw
```

3. Si installé depuis les sources, récupérez le dernier code et réinstallez :

```
cd CoPaw
git pull origin main
pip install -e .
```

4. Si vous utilisez Docker, tirez la dernière image et redémarrez le conteneur :

```
docker pull agentscope/copaw:latest
docker run -p 8088:8088 -v copaw-data:/app/working agentscope/copaw:latest
```

Après la mise à jour, redémarrez le service avec `copaw app`.

### Comment initialiser et démarrer le service CoPaw

Initialisation rapide recommandée :

```bash
copaw init --defaults
```

Démarrer le service :

```bash
copaw app
```

L'URL par défaut de la Console est `http://127.0.0.1:8088/`. Après l'initialisation rapide, vous pouvez
ouvrir la Console et personnaliser les paramètres. Voir
[Démarrage rapide](https://copaw.agentscope.io/docs/quickstart).

### Dépôt open source

CoPaw est open source. Dépôt officiel :
`https://github.com/agentscope-ai/CoPaw`

### Où consulter les détails de la dernière mise à jour de version

Vous pouvez consulter les changements de version dans les
[Releases](https://github.com/agentscope-ai/CoPaw/releases) de CoPaw sur GitHub.

### Comment configurer les modèles

Dans la Console, allez dans **Paramètres -> Modèles**. Voir
[Console -> Modèles](https://copaw.agentscope.io/docs/console#models) pour
les détails.

- Modèles cloud : renseignez la clé API du fournisseur (ModelScope, DashScope ou personnalisé), puis
  choisissez le modèle actif.
- Modèles locaux : supporte `llama.cpp`, `MLX` et Ollama. Après le téléchargement, sélectionnez
  le modèle actif sur la même page.

Vous pouvez également utiliser les commandes CLI `copaw models` pour la configuration, le téléchargement et
le changement. Voir
[CLI -> Modèles et Variables d'environnement -> copaw models](https://copaw.agentscope.io/docs/cli#copaw-models).

### Comment gérer les Skills

Allez dans **Agent -> Skills** dans la Console. Vous pouvez activer/désactiver les Skills, créer
des Skills personnalisées et importer des Skills depuis le Skills Hub. Voir
[Skills](https://copaw.agentscope.io/docs/skills).

### Comment configurer MCP

Allez dans **Agent -> MCP** dans la Console. Vous pouvez activer/désactiver/supprimer/créer des clients MCP
là-bas. Voir [MCP](https://copaw.agentscope.io/docs/mcp).

### Erreur courante

1. Motif d'erreur : `You didn't provide an API key`

Détail de l'erreur :

```
Error: Unknown agent error: AuthenticationError: Error code: 401 - {'error': {'message': "You didn't provide an API key. You need to provide your API key in an Authorization header using Bearer auth (i.e. Authorization: Bearer YOUR_KEY). ", 'type': 'invalid_request_error', 'param': None, 'code': None}, 'request_id': 'xxx'}
```

Cause 1 : la clé API du modèle n'est pas configurée. Obtenez une clé API et configurez-la dans
**Console -> Paramètres -> Modèles**.

Cause 2 : la clé est configurée mais échoue quand même. Dans la plupart des cas, l'un des
champs de configuration est incorrect (par exemple `base_url`, `api key` ou le nom du modèle).

CoPaw supporte les clés API obtenues via le Plan Codage DashScope. Si ça échoue encore,
veuillez vérifier :

- si `base_url` est correct ;
- si la clé API est copiée complètement (pas d'espaces supplémentaires) ;
- si le nom du modèle correspond exactement à la valeur du fournisseur (sensible à la casse).

Référence pour le bon flux d'obtention de clé :
https://help.aliyun.com/zh/model-studio/coding-plan-quickstart#2531c37fd64f9

---

### Comment obtenir du support en cas d'erreurs

Pour accélérer le dépannage et les corrections, veuillez créer une issue dans le dépôt GitHub de CoPaw
et inclure les informations complètes sur l'erreur :
https://github.com/agentscope-ai/CoPaw/issues

Dans de nombreuses erreurs de la Console, un chemin de fichier d'erreur détaillé est inclus. Par exemple :

Error: Unknown agent error: AuthenticationError: Error code: 401 - {'error': {'message': "You didn't provide an API key. You need to provide your API key in an Authorization header using Bearer auth (i.e. Authorization: Bearer YOUR_KEY). ", 'type': 'invalid_request_error', 'param': None, 'code': None}, 'request_id': 'xxx'}(Details: /var/folders/.../copaw_query_error_qzbx1mv1.json)

Veuillez télécharger ce fichier (par exemple
`/var/folders/.../copaw_query_error_qzbx1mv1.json`) avec votre fournisseur de modèle actuel, le nom du modèle et la version exacte de CoPaw.
