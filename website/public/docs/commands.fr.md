# Commandes système

> **Expérimental** : Les commandes système ne couvrent pas encore tous les scénarios et cas limites ; leur utilisation peut entraîner des erreurs ou un comportement inattendu. Veuillez vous fier au comportement réel comme source de vérité.

Les **commandes système** sont des instructions spéciales préfixées par `/` qui vous permettent de contrôler directement l'état de la conversation sans attendre que l'IA interprète votre intention.

Cinq commandes sont actuellement supportées :

- **`/compact`** — Compresser la conversation actuelle, générer un résumé et sauvegarder les mémoires
- **`/new`** — Démarrer une nouvelle conversation, en sauvegardant les mémoires en arrière-plan
- **`/clear`** — Tout effacer complètement, sans rien sauvegarder
- **`/history`** — Voir l'historique de la conversation avec le détail de l'utilisation des tokens
- **`/compact_str`** — Voir le résumé compressé actuel (lecture seule)

> Si vous n'êtes pas encore familier avec des concepts comme « compaction » ou « mémoire à long terme », nous vous recommandons de lire d'abord l'[Introduction](./intro.fr.md).

---

## Comparaison des commandes

| Commande       | Nécessite d'attendre | Résumé compressé      | Mémoire à long terme    | Historique des messages  | Utilisation du contexte         |
| -------------- | -------------------- | --------------------- | ----------------------- | ------------------------ | ------------------------------- |
| `/compact`     | Oui                  | Génère un nouveau     | Sauvegardé en arrière-plan | Marqué comme compacté | -                               |
| `/new`         | Non                  | Effacé                | Sauvegardé en arrière-plan | Marqué comme compacté | -                               |
| `/clear`       | Non                  | Effacé                | Non sauvegardé          | Complètement effacé      | -                               |
| `/history`     | Non                  | -                     | -                       | Vue en lecture seule     | 📊 Détails tokens + Utilisation |
| `/compact_str` | Non                  | -                     | -                       | -                        | 📖 Voir le contenu du résumé    |

---

## /compact — Compresser la conversation actuelle

Déclenche manuellement la compaction de la conversation, condensant tous les messages actuels en un résumé (nécessite d'attendre), tout en sauvegardant dans la mémoire à long terme en arrière-plan.

```
/compact
```

Exemple de réponse :

```
**Compaction terminée !**

- Messages compactés : 12
**Résumé compressé :**
L'utilisateur a demandé de l'aide pour construire un système d'authentification utilisateur, l'implémentation de l'endpoint de connexion est terminée...
- Tâche de résumé démarrée en arrière-plan
```

> Contrairement à la compaction automatique, `/compact` compresse **tous** les messages actuels, pas seulement la partie dépassant le seuil.

---

## /new — Effacer le contexte et sauvegarder les mémoires

Efface immédiatement le contexte actuel et démarre une nouvelle conversation ; l'historique est sauvegardé dans la mémoire à long terme en arrière-plan.

```
/new
```

Exemple de réponse :

```
**Nouvelle conversation démarrée !**

- Tâche de résumé démarrée en arrière-plan
- Prêt pour une nouvelle conversation
```

---

## /clear — Effacer le contexte (sans sauvegarder les mémoires)

Efface immédiatement le contexte actuel, y compris l'historique des messages et les résumés compressés. Rien n'est sauvegardé dans la mémoire à long terme.

```
/clear
```

Exemple de réponse :

```
**Historique effacé !**

- Résumé compressé réinitialisé
- La mémoire est maintenant vide
```

> ⚠️ `/clear` est **irréversible** ! Contrairement à `/new`, le contenu effacé ne sera pas sauvegardé.

---

## /history — Voir l'historique de la conversation actuelle

Affiche la liste de tous les messages non compressés de la conversation actuelle, ainsi que les **informations détaillées sur l'utilisation du contexte**.

```
/history
```

Exemple de réponse :

```
**Historique de la conversation**

- Total des messages : 3
- Tokens estimés : 1256
- Longueur maximale d'entrée : 128000
- Utilisation du contexte : 0,98 %
- Tokens du résumé compressé : 128

[1] **user** (text_tokens=42)
    content: [text(tokens=42)]
    aperçu : Écris-moi une fonction Python...

[2] **assistant** (text_tokens=256)
    content: [text(tokens=256)]
    aperçu : Bien sûr, laisse-moi écrire une fonction pour toi...

[3] **user** (text_tokens=28)
    content: [text(tokens=28)]
    aperçu : Peux-tu ajouter la gestion des erreurs ?
```

> 💡 **Conseil** : Utilisez `/history` fréquemment pour surveiller votre utilisation du contexte. Lorsque `Utilisation du contexte` approche 100 %, cela indique que la conversation est sur le point de déclencher une compaction automatique. Vous pouvez utiliser proactivement `/compact` ou `/new` pour gérer le contexte avant que cela se produise.

---

## /compact_str — Voir le résumé compressé

Affiche le contenu du résumé compressé actuel.

```
/compact_str
```

Exemple de réponse (quand un résumé existe) :

```
**Résumé compressé**

L'utilisateur a demandé de l'aide pour construire un système d'authentification utilisateur, l'implémentation de l'endpoint de connexion est terminée...
```

Exemple de réponse (quand il n'y a pas de résumé) :

```
**Aucun résumé compressé**

- Aucun résumé n'a encore été généré
- Utilisez /compact ou attendez la compaction automatique
```

---

## Pages associées

- [Introduction](./intro.fr.md) — Ce que ce projet peut faire
- [Console](./console.fr.md) — Gérer l'état de l'agent dans la console
- [Configuration & Répertoire de travail](./config.fr.md) — Répertoire de travail & configuration
- [CLI](./cli.fr.md) — Référence de l'outil en ligne de commande
