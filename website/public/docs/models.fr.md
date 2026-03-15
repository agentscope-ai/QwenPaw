# Modèles

Vous devez configurer un modèle avant de discuter avec CoPaw. Vous pouvez le faire dans **Console → Paramètres → Modèles**.

![Console models](https://img.alicdn.com/imgextra/i1/O1CN01zHAE1Z26w6jXl2xbr_!!6000000007725-2-tps-3802-1968.png)

CoPaw prend en charge plusieurs fournisseurs de LLM : les **fournisseurs cloud** (nécessitent une clé API, y compris Google Gemini), les **fournisseurs locaux** (llama.cpp / MLX), le **fournisseur Ollama**, le **fournisseur LM Studio**, et vous pouvez ajouter des **fournisseurs personnalisés**. Cette page explique comment configurer chaque type.

---

## Configurer les fournisseurs cloud

Les fournisseurs cloud (notamment ModelScope, DashScope, Aliyun Coding Plan, OpenAI, Azure OpenAI, Google Gemini et MiniMax) appellent des modèles distants via une API et nécessitent une **clé API**.

**Dans la console :**

1. Ouvrez la console et accédez à **Paramètres → Modèles**.
2. Trouvez la carte du fournisseur cloud cible (par ex. DashScope) et cliquez sur **Paramètres**. Saisissez votre **clé API** et cliquez sur **Enregistrer**.

   ![save](https://img.alicdn.com/imgextra/i1/O1CN01zHAE1Z26w6jXl2xbr_!!6000000007725-2-tps-3802-1968.png)

3. Après l'enregistrement, le statut de la carte en haut à droite devient **Disponible**. Dans la section **Configuration LLM** en haut, vous pouvez sélectionner ce fournisseur dans le menu déroulant **Fournisseur** et voir la liste des modèles dans le menu déroulant **Modèle**.

   ![choose](https://img.alicdn.com/imgextra/i2/O1CN01aYwWJ31gsjoGdycs5_!!6000000004198-2-tps-3802-1968.png)

4. Choisissez le modèle cible (par ex. qwen3.5-plus) et cliquez sur **Enregistrer**.

   ![save](https://img.alicdn.com/imgextra/i3/O1CN01oQTx2a1Qey37oM3Tw_!!6000000002002-2-tps-3802-1968.png)

5. La barre de configuration LLM affichera le fournisseur et le modèle actuels en haut à droite.

   ![model](https://img.alicdn.com/imgextra/i1/O1CN018wZ0C81MWweGbYL33_!!6000000001443-2-tps-3802-1968.png)

> Pour révoquer un fournisseur cloud, cliquez sur **Paramètres** sur sa carte, puis sur **Révoquer l'autorisation** et confirmez. Le statut du fournisseur passera à **Indisponible**.
>
> ![cancel](https://img.alicdn.com/imgextra/i2/O1CN01A8j1IR1n8fHGnio0q_!!6000000005045-2-tps-3802-1968.png)

## Fournisseur Google Gemini

Le fournisseur Google Gemini utilise l'API native Gemini de Google (via le SDK `google-genai`) pour accéder aux modèles Gemini. Les modèles préconfigurés incluent Gemini 3.1 Pro, Gemini 3 Flash, Gemini 3.1 Flash Lite, Gemini 2.5 Pro, Gemini 2.5 Flash, Gemini 2.5 Flash Lite et Gemini 2.0 Flash. Des modèles supplémentaires peuvent être découverts automatiquement via l'API.

**Prérequis :**

- Obtenez une clé API Gemini depuis [Google AI Studio](https://aistudio.google.com/apikey).

**Dans la console :**

1. Ouvrez la console et accédez à **Paramètres → Modèles**.
2. Trouvez la carte du fournisseur **Google Gemini** et cliquez sur **Paramètres**. Saisissez votre **clé API** et cliquez sur **Enregistrer**.
3. Après l'enregistrement, le statut de la carte devient **Disponible**. Le fournisseur prend en charge la **découverte de modèles** — cliquez sur **Modèles** pour découvrir automatiquement les modèles Gemini disponibles via l'API.
4. Dans la section **Configuration LLM** en haut, sélectionnez **Google Gemini** dans le menu déroulant **Fournisseur** et choisissez un modèle (par ex. `gemini-2.5-flash`), puis cliquez sur **Enregistrer**.

**Via le CLI :**

```bash
# Configurer la clé API
copaw models config-key gemini

# Définir Gemini comme LLM actif
copaw models set-llm
```

> **Conseil :** Les modèles Gemini dotés de capacités de réflexion (par ex. Gemini 3.1 Pro, Gemini 2.5 Pro, Gemini 2.5 Flash) prennent en charge le raisonnement étendu. CoPaw gère automatiquement les blocs de réflexion et les signatures de pensée de ces modèles.

## Fournisseurs locaux (llama.cpp / MLX)

Les fournisseurs locaux exécutent les modèles sur votre machine sans **clé API** ; les données restent sur l'appareil.

**Prérequis :**

- Installez le backend correspondant dans le même environnement que CoPaw :
  - llama.cpp : `pip install 'copaw[llamacpp]'`
  - MLX : `pip install 'copaw[mlx]'`

1. Sur la page Modèles, vous verrez les cartes pour llama.cpp et MLX.

   ![card](https://img.alicdn.com/imgextra/i3/O1CN01Xpbl8a1nJemcFr97p_!!6000000005069-2-tps-3802-1968.png)

2. Cliquez sur **Modèles** sur la carte du fournisseur local cible (par ex. llama.cpp), puis sur **Télécharger le modèle**.

   ![download](https://img.alicdn.com/imgextra/i3/O1CN01ML9Ce81kyvcoD92hG_!!6000000004753-2-tps-3802-1968.png)

3. Saisissez l'**ID du dépôt** et choisissez la **Source**, puis cliquez sur **Télécharger le modèle**.

   ![id](https://img.alicdn.com/imgextra/i3/O1CN01HaIQwC1qV3UHvsvgc_!!6000000005500-2-tps-3802-1968.png)

4. Le téléchargement va démarrer ; veuillez patienter jusqu'à la fin.

   ![wait](https://img.alicdn.com/imgextra/i2/O1CN018b8woI1yHmwOJB2V6_!!6000000006554-2-tps-3802-1968.png)

5. Une fois le téléchargement terminé, le statut de la carte du fournisseur local devient **Disponible**.

   ![avai](https://img.alicdn.com/imgextra/i4/O1CN01yazvrI25tWt9WqD8w_!!6000000007584-2-tps-3802-1968.png)

6. Dans la **Configuration LLM** en haut, sélectionnez le fournisseur local dans le menu déroulant **Fournisseur** et le modèle nouvellement ajouté dans le menu déroulant **Modèle**, puis cliquez sur **Enregistrer**.

   ![model](https://img.alicdn.com/imgextra/i1/O1CN015KoPYh1cCp6H4rkN9_!!6000000003565-2-tps-3802-1968.png)

7. La zone de configuration LLM affichera le fournisseur local et le nom du modèle sélectionné.

   ![see](https://img.alicdn.com/imgextra/i1/O1CN01Dce5Pt1GH1BBxJcjD_!!6000000000596-2-tps-3802-1968.png)

> Cliquez sur **Modèles** sur une carte de fournisseur local pour voir les noms de modèles, les tailles et les sources. Pour supprimer un modèle, cliquez sur l'**icône de corbeille** à droite du modèle et confirmez.
>
> ![delete](https://img.alicdn.com/imgextra/i4/O1CN01roGD1X1lKudZT51co_!!6000000004801-2-tps-3802-1968.png)

## Fournisseur Ollama

Le fournisseur Ollama utilise le **démon Ollama** installé sur votre machine. Les modèles sont gérés par Ollama ; CoPaw ne les télécharge pas directement, et la liste se synchronise avec Ollama.

**Prérequis :**

- Installez Ollama depuis [ollama.com](https://ollama.com).
- Installez le support Ollama dans l'environnement de CoPaw : `pip install 'copaw[ollama]'`.

1. Sur la page Modèles, vous verrez la carte du fournisseur Ollama.

2. Cliquez sur **Paramètres** en bas à droite. Sur la page de configuration Ollama, saisissez une **clé API** (n'importe quelle valeur convient, par ex. `ollama`). Cliquez sur **Enregistrer**.

   ![set](https://img.alicdn.com/imgextra/i1/O1CN01JhGTpy1FPQqDXSVo9_!!6000000000479-2-tps-3802-1968.png)

3. Cliquez sur **Modèles** en bas à droite. Si vous avez déjà récupéré des modèles avec Ollama, ils apparaîtront ici. Pour récupérer un nouveau modèle, cliquez sur **Télécharger le modèle**.

   ![download](https://img.alicdn.com/imgextra/i2/O1CN01CARKar1ilzCd0dIZ9_!!6000000004454-2-tps-3802-1968.png)

4. Saisissez le **nom du modèle**, puis cliquez sur **Télécharger le modèle**.

   ![download](https://img.alicdn.com/imgextra/i3/O1CN014JJgSv24of3xUkGch_!!6000000007438-2-tps-3802-1968.png)

5. Le modèle va se télécharger ; veuillez patienter jusqu'à la fin.

   ![wait](https://img.alicdn.com/imgextra/i3/O1CN01ptZICs25rEuMA4O7U_!!6000000007579-2-tps-3802-1968.png)

6. Une fois terminé, dans la **Configuration LLM** en haut, sélectionnez **Ollama** dans le menu déroulant **Fournisseur** et votre modèle dans le menu déroulant **Modèle**, puis cliquez sur **Enregistrer**.

   ![save](https://img.alicdn.com/imgextra/i3/O1CN01DEOqAH1ODMx4rUTLw_!!6000000001671-2-tps-3802-1968.png)

7. La zone de configuration LLM affichera le fournisseur Ollama et le nom du modèle sélectionné.

   ![name](https://img.alicdn.com/imgextra/i2/O1CN01955KEG1vtOcDcdedZ_!!6000000006230-2-tps-3802-1968.png)

> Si vous voyez `Ollama SDK not installed. Install with: pip install 'copaw[ollama]'`, assurez-vous qu'Ollama est installé depuis ollama.com et que vous avez exécuté `pip install 'copaw[ollama]'` dans l'environnement de CoPaw. Pour supprimer un modèle, cliquez sur **Modèles** sur la carte Ollama, puis sur l'**icône de corbeille** à côté du modèle et confirmez.
>
> ![delete](https://img.alicdn.com/imgextra/i1/O1CN01OvNNu21shXVzD14go_!!6000000005798-2-tps-3802-1968.png)
>
> **Utilisateurs Docker :** Si CoPaw s'exécute dans un conteneur Docker, `localhost` fait référence au conteneur — et non à votre machine hôte. Modifiez l'URL de base Ollama en `http://host.docker.internal:11434` (et ajoutez `--add-host=host.docker.internal:host-gateway` à votre commande `docker run`). Consultez la [section Docker du README](https://github.com/agentscope-ai/CoPaw#using-docker) pour plus de détails.

## Fournisseur LM Studio

Le fournisseur LM Studio se connecte au serveur compatible OpenAI intégré à l'application de bureau **LM Studio**. Les modèles sont gérés dans l'interface graphique de LM Studio ; CoPaw découvre automatiquement les modèles chargés via le point de terminaison `/v1/models`.

**Prérequis :**

- Installez LM Studio depuis [lmstudio.ai](https://lmstudio.ai).
- Dans LM Studio, chargez un modèle et démarrez le serveur local (par défaut : `http://localhost:1234`).

1. Sur la page Modèles, vous verrez la carte du fournisseur LM Studio.

2. Cliquez sur **Paramètres** en bas à droite. L'URL de base par défaut est `http://localhost:1234/v1`. Ajustez-la si vous avez modifié le port dans LM Studio. Cliquez sur **Enregistrer**.

3. Cliquez sur **Modèles** pour voir les modèles actuellement chargés dans LM Studio. Vous pouvez également ajouter manuellement un ID de modèle si nécessaire.

4. Dans la **Configuration LLM** en haut, sélectionnez **LM Studio** dans le menu déroulant **Fournisseur** et votre modèle dans le menu déroulant **Modèle**, puis cliquez sur **Enregistrer**.

> **Conseil :** LM Studio ne nécessite pas de clé API par défaut. Si vous avez activé l'authentification dans LM Studio, saisissez la clé dans le champ **Clé API**. Les modèles doivent être chargés dans l'interface graphique de LM Studio avant d'apparaître dans CoPaw.
>
> **Important — Longueur de contexte :** LM Studio charge les modèles avec une petite longueur de contexte par défaut (souvent 2048 ou 4096 tokens). Le prompt système de CoPaw (AGENTS.md + SOUL.md + PROFILE.md) peut facilement dépasser cette limite, provoquant une erreur du type _« Le nombre de tokens à conserver du prompt initial est supérieur à la longueur de contexte »_. Pour corriger cela, **déchargez le modèle dans LM Studio et rechargez-le avec une longueur de contexte plus grande** (16384 ou plus est recommandé). Vous pouvez le faire dans l'interface graphique de LM Studio (Paramètres du modèle → Longueur de contexte) ou via le CLI : `lms unload --all && lms load <model> -c 16384`.
>
> **Utilisateurs Docker :** Si CoPaw s'exécute dans un conteneur Docker, `localhost` fait référence au conteneur — et non à votre machine hôte. Modifiez l'URL de base de LM Studio en `http://host.docker.internal:1234/v1` (et ajoutez `--add-host=host.docker.internal:host-gateway` à votre commande `docker run`). Consultez la [section Docker du README](https://github.com/agentscope-ai/CoPaw#using-docker) pour plus de détails.

## Ajouter un fournisseur personnalisé

1. Sur la page Modèles, cliquez sur **Ajouter un fournisseur**.

   ![add](https://img.alicdn.com/imgextra/i2/O1CN018PFJmz1kUhUBwf4OL_!!6000000004687-2-tps-3802-1968.png)

2. Saisissez l'**ID du fournisseur** et le **nom d'affichage**, puis cliquez sur **Créer**.

   ![create](https://img.alicdn.com/imgextra/i3/O1CN01XuLvkT1wRHvNLHUaf_!!6000000006304-2-tps-3802-1968.png)

3. La nouvelle carte du fournisseur apparaîtra.

   ![card](https://img.alicdn.com/imgextra/i3/O1CN01BFghrw1ZFcfpyzIL7_!!6000000003165-2-tps-3802-1968.png)

4. Cliquez sur **Paramètres**, saisissez l'**URL de base** et la **clé API**, puis cliquez sur **Enregistrer**.

   ![save](https://img.alicdn.com/imgextra/i4/O1CN01R5ZTQ321ymyQ8psEY_!!6000000007054-2-tps-3802-1968.png)

5. La carte affichera l'URL de base et la clé API configurées, mais le statut restera **Indisponible** tant que vous n'aurez pas ajouté de modèle.

   ![model](https://img.alicdn.com/imgextra/i4/O1CN01qDDA1I1xd1gu7D8w2_!!6000000006465-2-tps-3802-1968.png)

6. Cliquez sur **Modèles**, saisissez l'**ID du modèle**, puis cliquez sur **Ajouter le modèle**.

   ![add](https://img.alicdn.com/imgextra/i2/O1CN01nG1FoA1KyJ4vcUYwo_!!6000000001232-2-tps-3802-1968.png)

7. Le fournisseur personnalisé s'affichera alors comme **Disponible**. Dans la **Configuration LLM** en haut, sélectionnez-le dans le menu déroulant **Fournisseur** et le nouveau modèle dans le menu déroulant **Modèle**, puis cliquez sur **Enregistrer**.

   ![model](https://img.alicdn.com/imgextra/i2/O1CN01EtQCWr1YpW63ox5QY_!!6000000003108-2-tps-3802-1968.png)

8. La zone de configuration LLM affichera l'ID du fournisseur personnalisé et le nom du modèle sélectionné.

   ![save](https://img.alicdn.com/imgextra/i2/O1CN01WPMjKq1bCzdC8RJvP_!!6000000003430-2-tps-3802-1968.png)

> Si la configuration échoue, vérifiez à nouveau l'**URL de base**, la **clé API** et l'**ID du modèle** (y compris la casse). Pour supprimer un fournisseur personnalisé, cliquez sur **Supprimer le fournisseur** sur sa carte et confirmez.
>
> ![delete](https://img.alicdn.com/imgextra/i3/O1CN0124kc9J1dv4zHYDWQg_!!6000000003797-2-tps-3802-1968.png)
