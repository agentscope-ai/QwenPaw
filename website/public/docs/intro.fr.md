# Introduction

Cette page décrit ce qu'est CoPaw, ce qu'il peut faire et comment démarrer en
suivant la documentation.

---

## Qu'est-ce que CoPaw ?

CoPaw est un **assistant personnel** qui s'exécute dans votre propre environnement.

- **Chat multicanal** — Communiquez avec lui via DingTalk, Feishu, QQ, Discord, iMessage et plus encore.
- **Exécution planifiée** — Exécutez des tâches automatiquement selon le calendrier que vous configurez.
- **Piloté par des Skills — les possibilités sont infinies** — Les skills intégrées comprennent cron (tâches planifiées), PDF et formulaires, gestion de Word/Excel/PPT, digest d'actualités, lecture de fichiers, et plus encore ; ajoutez des skills personnalisées comme décrit dans [Skills](./skills).
- **Toutes les données restent locales** — Aucun hébergement tiers.

CoPaw est développé par l'[équipe AgentScope](https://github.com/agentscope-ai) sur
[AgentScope](https://github.com/agentscope-ai/agentscope),
[AgentScope Runtime](https://github.com/agentscope-ai/agentscope-runtime) et
[ReMe](https://github.com/agentscope-ai/ReMe).

---

## Comment utiliser CoPaw ?

Vous utilisez CoPaw de deux façons principales :

1. **Discuter dans vos applications de messagerie**
   Envoyez des messages dans DingTalk, Feishu, QQ, Discord ou iMessage (Mac uniquement) ; CoPaw répond
   dans la même application et peut rechercher des informations, gérer des tâches, répondre à des questions —
   selon les Skills activées. Une instance CoPaw peut être connectée à
   plusieurs applications ; elle répond dans le canal où vous avez parlé en dernier.

2. **S'exécuter selon un calendrier**
   Sans envoyer de message à chaque fois, CoPaw peut s'exécuter à des heures définies :
   - Envoyer un message fixe à un canal (ex. « Bonjour » sur DingTalk à 9h) ;
   - Poser une question à CoPaw et envoyer la réponse à un canal (ex. toutes les 2 heures,
     demander « Quelles sont mes tâches ? » et publier la réponse sur DingTalk) ;
   - Exécuter un « bilan » ou digest : poser à CoPaw un ensemble de questions que vous avez
     rédigées et envoyer la réponse au dernier canal utilisé.

Après l'installation, la connexion d'au moins un canal et le démarrage du serveur, vous pouvez
discuter avec CoPaw dans DingTalk, Feishu, QQ, etc. et utiliser les messages planifiés et les bilans ;
ce qu'il fait réellement dépend des Skills que vous activez.

---

## Termes que vous verrez dans la documentation

- **Canal** — L'endroit où vous parlez à CoPaw (DingTalk, Feishu, QQ, Discord, iMessage, etc.).
  Configurez chacun dans [Canaux](./channels).
- **Heartbeat** — À intervalle fixe, poser à CoPaw un bloc de texte que vous avez rédigé et
  envoyer optionnellement la réponse au dernier canal utilisé. Voir
  [Heartbeat](./heartbeat).
- **Tâches cron** — Tâches planifiées (envoyer X à 9h, demander Y toutes les 2h, etc.), gérées
  via [CLI](./cli) ou l'API.

Chaque terme est expliqué en détail dans son chapitre.

---

## Ordre suggéré

1. **[Démarrage rapide](./quickstart)** — Faites tourner le serveur en trois commandes.
2. **[Console](./console)** — Une fois le serveur démarré, **avant de configurer les canaux**,
   vous pouvez utiliser la Console (ouvrez l'URL racine dans votre navigateur) pour
   discuter avec CoPaw et configurer l'agent. Cela vous permet de voir comment CoPaw fonctionne.
3. **Configurer et utiliser selon vos besoins** :
   - [Canaux](./channels) — Connectez DingTalk / Feishu / QQ / Discord / iMessage pour
     discuter avec CoPaw dans ces applications ;
   - [Heartbeat](./heartbeat) — Configurez un bilan planifié ou un digest (optionnel) ;
   - [CLI](./cli) — Initialisation, tâches cron, nettoyage du répertoire de travail, etc. ;
   - [Skills](./skills) — Comprendre et étendre les capacités de CoPaw ;
   - [Configuration et répertoire de travail](./config) — Répertoire de travail et fichier de configuration.
