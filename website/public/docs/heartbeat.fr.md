# Heartbeat

Dans CoPaw, le **heartbeat** signifie : à intervalle fixe, poser à CoPaw les
« questions » que vous avez écrites dans un fichier, et envoyer optionnellement la réponse de CoPaw vers
**le canal où vous avez discuté en dernier**. Idéal pour les « bilans réguliers, digest quotidiens, rappels planifiés » — CoPaw s'exécute sans que vous envoyiez de message.

Si vous n'avez pas lu l'[Introduction](./intro), parcourez rapidement les « termes » qui s'y trouvent
(heartbeat, canaux) en premier.

---

## Comment fonctionne le heartbeat

1. Vous avez un fichier **HEARTBEAT.md** (par défaut dans le répertoire de travail
   `~/.copaw/`). Son contenu est **ce qu'il faut demander à CoPaw à chaque fois** (un
   bloc de texte ; CoPaw le voit comme un message utilisateur).
2. Le système s'exécute selon votre **intervalle** (ex. toutes les 30 minutes) : lit
   HEARTBEAT.md → envoie cela comme message utilisateur → CoPaw répond.
3. **Si la réponse est envoyée à un canal** est contrôlé par **target** dans
   la config :
   - **main** — Exécute CoPaw uniquement ; n'envoie la réponse nulle part (ex. pour
     les bilans locaux ou les journaux).
   - **last** — Envoie la réponse de CoPaw vers **le canal/session où vous avez
     parlé à CoPaw en dernier** (ex. si vous avez utilisé DingTalk en dernier, la
     réponse du heartbeat va à DingTalk).

Vous pouvez également définir des **heures actives** : le heartbeat ne s'exécute que dans cette fenêtre temporelle chaque
jour (ex. 08:00–22:00).

---

## Étape 1 : Rédiger HEARTBEAT.md

Chemin par défaut : `~/.copaw/HEARTBEAT.md`. Contenu = « ce qu'il faut demander à chaque fois. »
Texte brut ou Markdown ; tout est envoyé comme un seul message utilisateur.

Exemple (personnalisez à votre guise) :

```markdown
# Liste de contrôle heartbeat

- Scanner la boîte de réception pour les emails urgents
- Vérifier le calendrier pour les 2 prochaines heures
- Revoir les tâches bloquées
- Bilan léger si inactif depuis 8h
```

Si vous avez exécuté `copaw init` sans `--defaults`, vous avez été invité à modifier
HEARTBEAT.md ; votre éditeur par défaut s'ouvrait. Vous pouvez également modifier le fichier à tout moment ;
la prochaine exécution du heartbeat utilisera le nouveau contenu.

---

## Étape 2 : Configurer le heartbeat dans config.json

**L'intervalle, la cible et les heures actives** sont dans `config.json` (généralement
`~/.copaw/config.json`), sous `agents.defaults.heartbeat` :

| Champ       | Signification                                               | Exemple                                              |
| ----------- | ----------------------------------------------------------- | ---------------------------------------------------- |
| every       | Fréquence d'exécution                                       | `"30m"`, `"1h"`, `"2h30m"`, `"90s"`                  |
| target      | Où envoyer la réponse                                       | `"main"` = ne pas envoyer ; `"last"` = dernier canal |
| activeHours | Optionnel ; ne s'exécute que dans cette fenêtre chaque jour | `{ "start": "08:00", "end": "22:00" }`               |

Exemple (toutes les 30 min, pas de canal) :

```json
"agents": {
  "defaults": {
    "heartbeat": {
      "every": "30m",
      "target": "main"
    }
  }
}
```

Exemple (envoyer au dernier canal, toutes les heures, seulement 08:00–22:00) :

```json
"agents": {
  "defaults": {
    "heartbeat": {
      "every": "1h",
      "target": "last",
      "activeHours": { "start": "08:00", "end": "22:00" }
    }
  }
}
```

Sauvegardez la config ; si le serveur est en cours d'exécution, les nouveaux paramètres prennent effet (certaines
configurations peuvent nécessiter un redémarrage).

---

## Heartbeat vs tâches cron

|                   | Heartbeat                                   | Tâches cron                                                    |
| ----------------- | ------------------------------------------- | -------------------------------------------------------------- |
| **Nombre**        | Un fichier de prompt (HEARTBEAT.md)         | Autant que nécessaire                                          |
| **Planification** | Un intervalle global                        | Chaque tâche a sa propre planification                         |
| **Livraison**     | Optionnel : envoyer au dernier canal ou non | Chaque tâche spécifie son propre canal et utilisateur          |
| **Idéal pour**    | Un bilan / digest fixe                      | Plusieurs tâches à différentes heures avec différents contenus |

> Besoin d'« envoyer Bonjour à 9h » ou d'« interroger les tâches toutes les 2h et envoyer à DingTalk » ? Utilisez [CLI](./cli) `copaw cron create` (tâches cron), pas le heartbeat.

---

## Pages associées

- [Introduction](./intro) — Ce que le projet peut faire
- [Canaux](./channels) — Connecter un canal d'abord pour que target=last ait un endroit où envoyer
- [CLI](./cli) — Configurer le heartbeat lors de l'init, gérer les tâches cron
- [Configuration & répertoire de travail](./config) — config.json et répertoire de travail
