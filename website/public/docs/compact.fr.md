# Compaction

## Contexte : Pourquoi avons-nous besoin de la compaction ?

Imaginez la fenêtre de contexte du LLM comme un **sac à dos à capacité limitée** 🎒. À chaque tour de conversation, chaque résultat d'appel d'outil ajoute quelque chose dans le sac à dos. Au fur et à mesure que la conversation avance, le sac se remplit de plus en plus...

```mermaid
graph LR
    A[La conversation commence] --> B[Les messages s'accumulent]
    B --> C[Le sac à dos est presque plein !]
    C --> D{Que faire ?}
    D -->|Ne rien faire| E[La conversation se brise]
    D -->|Compacter| F[Continuer à discuter tranquillement]
```

Que se passe-t-il quand le sac à dos est plein ?

- 🚫 **Conversation interrompue** - Impossible de continuer l'échange
- 📉 **Dégradation de la qualité** - L'IA commence à « oublier »
- ❌ **Erreurs API** - Échec complet

**La compaction** est la magie qui vous aide à « ranger votre sac à dos » ✨ — en compressant les anciens éléments dans une petite boîte (résumé), libérant de la place pour les nouvelles choses !

## Qu'est-ce que la compaction ?

La compaction, c'est comme rédiger un **compte-rendu de réunion** : condenser une longue discussion en points clés, tout en laissant le contenu récent de la conversation intact.

```mermaid
graph TB
    subgraph Avant compaction
        A1[Message 1 : Bonjour]
        A2[Message 2 : Aide-moi à écrire du code]
        A3[Message 3 : Résultat de l'appel d'outil...très long]
        A4[Message 4 : Fais quelques modifications]
        A5[Message 5 : Ajuste encore]
        A6[Message 6 : Parfait !]
        A7[Message 7 : Nouvelle exigence]
    end

    subgraph Après compaction
        B1[📦 Résumé compacté : Précédemment aidé l'utilisateur à écrire et affiner du code]
        B2[Message 6 : Parfait !]
        B3[Message 7 : Nouvelle exigence]
    end

    A1 --> B1
    A2 --> B1
    A3 --> B1
    A4 --> B1
    A5 --> B1
    A6 --> B2
    A7 --> B3
```

Après compaction, les requêtes suivantes utilisent :

- 📦 **Résumé compacté** (remplaçant les anciens messages)
- 💬 **Messages récents** (conservés tels quels)

Le résumé compacté est persisté, vous n'avez donc pas à craindre de le perdre !

> Le mécanisme de compaction est inspiré d'[OpenClaw](https://github.com/openclaw/openclaw) et implémenté par [ReMe](https://github.com/agentscope-ai/ReMe).

## Configuration

### Variables d'environnement

| Variable d'environnement               | Défaut   | Description                                                                      |
| -------------------------------------- | -------- | -------------------------------------------------------------------------------- |
| `COPAW_MEMORY_COMPACT_THRESHOLD`       | `100000` | Seuil de tokens qui déclenche la compaction automatique (ligne d'avertissement)  |
| `COPAW_MEMORY_COMPACT_KEEP_RECENT`     | `3`      | Nombre de messages récents à conserver après compaction                          |
| `COPAW_MEMORY_COMPACT_RATIO`           | `0.7`    | Ratio de seuil pour déclencher la compaction (relatif à la fenêtre de contexte)  |

## Quand la compaction se déclenche-t-elle ?

CoPaw offre deux modes de compaction : **automatique** et **manuel** 🚗

### 1. 🤖 Compaction automatique (quand on approche du seuil de contexte)

CoPaw agit comme un majordome attentionné, vérifiant combien d'espace reste dans le « sac à dos » avant chaque tour de conversation. Lorsque le nombre de tokens des messages compactables dépasse le seuil, il range automatiquement pour vous !

**Diagramme de la structure de mémoire :**

```mermaid
graph LR
    subgraph Structure de mémoire
        A[🔒 Prompt système] --> B[📚 Messages compactables]
        B --> C[💬 Messages récents]
    end

    B -->|Dépasse le seuil ?| D{Vérification}
    D -->|Oui| E[Déclencher la compaction !]
    D -->|Non| F[Continuer la conversation]
```

| Zone                          | Description                    | Traitement                                                                                |
| ----------------------------- | ------------------------------ | ----------------------------------------------------------------------------------------- |
| 🔒 **Prompt système**         | Le « guide de persona » de l'IA | Toujours conservé, jamais compacté                                                       |
| 📚 **Messages compactables**  | Journal de conversation historique | Nombre de tokens calculé ; compacté en résumé quand le seuil est dépassé             |
| 💬 **Messages récents**       | Derniers N messages             | Conservés tels quels (N configuré par `KEEP_RECENT`)                                     |

### 2. 🎮 Compaction manuelle (commande /compact)

Parfois vous voulez proactivement « vider votre sac à dos » ? Pas de problème ! Envoyez la formule magique :

```bash
/compact
```

Après exécution, vous verrez une réponse comme celle-ci :

```text
**Compaction terminée !**

- Messages compactés : 12
**Résumé compressé :**
<contenu du résumé compacté>
- Tâche de résumé démarrée en arrière-plan
```

Détail de la réponse :

- 📊 **Messages compactés** - Combien de messages ont été compactés
- 📝 **Résumé compressé** - Le contenu du résumé généré
- ⏳ **Tâche de résumé** - Une tâche en arrière-plan démarre également pour stocker le résumé dans la mémoire à long terme

## Contenu de la compaction : Que contient le résumé ?

Le résumé compacté ressemble à un **document de passation de projet**, contenant toutes les informations clés nécessaires pour continuer le travail :

```mermaid
graph TB
    A[Résumé compacté] --> B[🎯 Objectifs]
    A --> C[⚙️ Contraintes & Préférences]
    A --> D[📈 Avancement]
    A --> E[🔑 Décisions clés]
    A --> F[➡️ Prochaines étapes]
    A --> G[📌 Contexte clé]
```

| Section                          | Contenu                                   | Exemple                                                  |
| -------------------------------- | ----------------------------------------- | -------------------------------------------------------- |
| 🎯 **Objectifs**                 | Ce que l'utilisateur veut accomplir       | « Construire un système de connexion utilisateur »       |
| ⚙️ **Contraintes & Préférences** | Exigences mentionnées par l'utilisateur   | « Utiliser TypeScript, sans framework »                  |
| 📈 **Avancement**                | Tâches terminées / en cours / bloquées    | « API de connexion terminée, API d'inscription en cours » |
| 🔑 **Décisions clés**            | Décisions prises et leur raisonnement     | « Choix de JWT plutôt que Sessions pour la sans-état »   |
| ➡️ **Prochaines étapes**         | Quoi faire ensuite                        | « Implémenter la fonctionnalité de réinitialisation du mot de passe » |
| 📌 **Contexte clé**              | Données nécessaires pour continuer        | « Le fichier principal est à src/auth.ts »               |

> 💡 **Conseil** : La compaction préserve les chemins de fichiers exacts, les noms de fonctions et les messages d'erreur, garantissant que l'IA ne « perd pas la mémoire » et que les transitions de contexte se font en douceur !
