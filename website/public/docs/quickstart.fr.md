# Démarrage rapide

Cette section décrit cinq façons d'exécuter CoPAW :

- **Option A — Installation en une ligne (recommandée)** : exécuter sur votre machine sans configuration Python requise.
- **Option B — Installation pip** : si vous préférez gérer Python vous-même.
- **Option C — ModelScope Studio** : déploiement cloud en un clic, aucune installation locale requise.
- **Option D — Docker** : utiliser les images officielles de Docker Hub (ACR également disponible pour les utilisateurs en Chine) ; les tags incluent `latest` (stable) et `pre` (pré-version PyPI).
- **Option E — Alibaba Cloud ECS** : déploiement en un clic sur Alibaba Cloud, sans installation locale.

> 📖 Lisez d'abord l'[Introduction](./intro) ; après l'installation, voir la [Console](./console).

> 💡 **Après l'installation & le démarrage** : Avant de configurer les canaux, vous pouvez ouvrir la [Console](./console) (`http://127.0.0.1:8088/`) pour discuter avec CoPAW et configurer l'agent. Lorsque vous êtes prêt à discuter dans DingTalk, Feishu, QQ, etc., rendez-vous dans [Canaux](./channels) pour ajouter un canal.

---

## Option A : Installation en une ligne (recommandée)

Python n'est pas requis — l'installateur gère tout automatiquement en utilisant [uv](https://docs.astral.sh/uv/).

### Étape 1 : Installer

**macOS / Linux :**

```bash
curl -fsSL https://copaw.agentscope.io/install.sh | bash
```

Ouvrez ensuite un nouveau terminal (ou `source ~/.zshrc` / `source ~/.bashrc`).

**Windows (PowerShell) :**

```powershell
irm https://copaw.agentscope.io/install.ps1 | iex
```

Ouvrez ensuite un nouveau terminal (l'installateur ajoute CoPaw à votre PATH automatiquement).

Vous pouvez également passer des options :

**macOS / Linux :**

```bash
# Installer une version spécifique
curl -fsSL ... | bash -s -- --version 0.0.2

# Installer depuis les sources (dev/tests)
curl -fsSL ... | bash -s -- --from-source

# Avec support des modèles locaux (voir la documentation Modèles locaux)
bash install.sh --extras llamacpp    # llama.cpp (multiplateforme)
bash install.sh --extras mlx         # MLX (Apple Silicon)
bash install.sh --extras ollama      # Ollama (multiplateforme, nécessite le service Ollama)
```

**Windows (PowerShell) :**

```powershell
# Installer une version spécifique
.\install.ps1 -Version 0.0.2

# Installer depuis les sources (dev/tests)
.\install.ps1 -FromSource

# Avec support des modèles locaux (voir la documentation Modèles locaux)
.\install.ps1 -Extras llamacpp      # llama.cpp (multiplateforme)
.\install.ps1 -Extras mlx           # MLX
.\install.ps1 -Extras ollama        # Ollama
```

Pour mettre à jour, relancez simplement la commande d'installation. Pour désinstaller, exécutez `copaw uninstall`.

### Étape 2 : Initialiser

Générez `config.json` et `HEARTBEAT.md` dans le répertoire de travail (par défaut
`~/.copaw`). Deux options :

- **Utiliser les valeurs par défaut** (sans invite ; idéal pour démarrer rapidement, puis modifier
  la config plus tard) :
  ```bash
  copaw init --defaults
  ```
- **Interactif** (invite pour l'intervalle heartbeat, la cible, les heures actives et
  la configuration optionnelle des canaux et Skills) :
  ```bash
  copaw init
  ```
  Voir [CLI - Pour commencer](./cli#getting-started).

Pour écraser la config existante, utilisez `copaw init --force` (vous serez invité à confirmer).
Après l'init, si aucun canal n'est encore activé, suivez [Canaux](./channels) pour ajouter
DingTalk, Feishu, QQ, etc.

### Étape 3 : Démarrer le serveur

```bash
copaw app
```

Le serveur écoute sur `127.0.0.1:8088` par défaut. Si vous avez déjà
configuré un canal, CoPaw répondra là-bas ; sinon vous pouvez en ajouter un après
cette étape via [Canaux](./channels).

---

## Option B : Installation pip

Si vous préférez gérer Python vous-même (nécessite Python >= 3.10, < 3.14) :

```bash
pip install copaw
```

Optionnel : créez et activez d'abord un virtualenv (`python -m venv .venv`, puis
`source .venv/bin/activate` sur Linux/macOS ou `.venv\Scripts\Activate.ps1` sur Windows). Cela installe la commande `copaw`.

Puis suivez [Étape 2 : Initialiser](#étape-2--initialiser) et [Étape 3 : Démarrer le serveur](#étape-3--démarrer-le-serveur) ci-dessus.

---

## Option C : Configuration en un clic ModelScope Studio (sans installation)

Si vous préférez ne pas installer Python localement, vous pouvez déployer CoPaw sur le cloud ModelScope Studio :

1. D'abord, inscrivez-vous et connectez-vous sur [ModelScope](https://modelscope.cn/register?back=%2Fhome) ;
2. Ouvrez le [CoPaw Studio](https://modelscope.cn/studios/fork?target=AgentScope/CoPaw) et complétez la configuration en un clic.

**Important** : Définissez votre Studio comme **non public**, sinon d'autres personnes pourraient contrôler votre CoPaw.

---

## Option D : Docker

Les images sont sur **Docker Hub** (`agentscope/copaw`). Tags d'image : `latest` (stable) ; `pre` (pré-version PyPI). Également disponible sur Alibaba Cloud ACR pour les utilisateurs en Chine : `agentscope-registry.ap-southeast-1.cr.aliyuncs.com/agentscope/copaw` (mêmes tags).

Tirer et exécuter :

```bash
docker pull agentscope/copaw:latest
docker run -p 8088:8088 -v copaw-data:/app/working agentscope/copaw:latest
```

Ouvrez ensuite **http://127.0.0.1:8088/** dans votre navigateur pour la Console. La config, la mémoire et les Skills sont stockées dans le volume `copaw-data`. Pour passer des clés API, ajoutez `-e DASHSCOPE_API_KEY=xxx` ou `--env-file .env` à `docker run`.

---

## Option E : Déployer sur Alibaba Cloud ECS

Pour exécuter CoPaw sur Alibaba Cloud, utilisez le déploiement ECS en un clic :

1. Ouvrez le [lien de déploiement CoPaw sur Alibaba Cloud (ECS)](https://computenest.console.aliyun.com/service/instance/create/cn-hangzhou?type=user&ServiceId=service-1ed84201799f40879884) et renseignez les paramètres comme indiqué ;
2. Confirmez le coût et créez l'instance ; une fois le déploiement terminé, vous pouvez obtenir l'URL d'accès et commencer à utiliser le service.

Pour des instructions étape par étape, voir [Alibaba Cloud Developer : Déployez votre assistant IA en 3 minutes](https://developer.aliyun.com/article/1713682).

---

## Vérifier l'installation (optionnel)

Après le démarrage du serveur, vous pouvez appeler l'API Agent pour confirmer la configuration.
Point de terminaison : **POST** `/api/agent/process`, corps JSON, streaming SSE. Exemple mono-tour :

```bash
curl -N -X POST "http://localhost:8088/api/agent/process" \
  -H "Content-Type: application/json" \
  -d '{"input":[{"role":"user","content":[{"type":"text","text":"Bonjour"}]}],"session_id":"session123"}'
```

Utilisez le même `session_id` pour le multi-tour.

---

## Que faire ensuite

- **Discuter avec CoPAW** — [Canaux](./channels) : connecter un canal
  (DingTalk ou Feishu est un bon premier choix), créer l'application, remplir la config, puis envoyer un message
  dans cette application.
- **Exécuter un « bilan » ou digest planifié** — [Heartbeat](./heartbeat) : modifier
  HEARTBEAT.md et définir l'intervalle et la cible dans la config.
- **Plus de commandes** — [CLI](./cli) (init interactif, tâches cron, nettoyage),
  [Skills](./skills).
- **Changer le répertoire de travail ou le chemin de config** — [Config & répertoire de travail](./config).
