# MCP

**MCP (Model Context Protocol)** permet à CoPaw de se connecter à des serveurs MCP externes et d'utiliser leurs outils. Vous pouvez ajouter des clients MCP via la Console pour étendre les capacités de CoPaw.

---

## Prérequis

Si vous utilisez `npx` pour exécuter des serveurs MCP, assurez-vous d'avoir :

- **Node.js** version 18 ou supérieure ([télécharger](https://nodejs.org/))

Vérifiez votre version de Node.js :

```bash
node --version
```

---

## Ajouter des clients MCP dans la Console

1. Ouvrez la Console et allez dans **Agent → MCP**
2. Cliquez sur le bouton **+ Créer**
3. Collez votre configuration de client MCP au format JSON
4. Cliquez sur **Créer** pour importer

---

## Formats de configuration

CoPaw supporte trois formats JSON pour importer des clients MCP :

### Format 1 : Format mcpServers standard (Recommandé)

```json
{
  "mcpServers": {
    "nom-client": {
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-filesystem"],
      "env": {
        "API_KEY": "votre-cle-api-ici"
      }
    }
  }
}
```

### Format 2 : Format clé-valeur direct

```json
{
  "nom-client": {
    "command": "npx",
    "args": ["-y", "@modelcontextprotocol/server-filesystem"],
    "env": {
      "API_KEY": "votre-cle-api-ici"
    }
  }
}
```

### Format 3 : Format client unique

```json
{
  "key": "nom-client",
  "name": "Mon Client MCP",
  "command": "npx",
  "args": ["-y", "@modelcontextprotocol/server-filesystem"],
  "env": {
    "API_KEY": "votre-cle-api-ici"
  }
}
```

---

## Exemple : Serveur MCP Filesystem

```json
{
  "mcpServers": {
    "filesystem": {
      "command": "npx",
      "args": [
        "-y",
        "@modelcontextprotocol/server-filesystem",
        "/Users/username/Documents"
      ]
    }
  }
}
```

> Remplacez `/Users/username/Documents` par le chemin du répertoire auquel vous souhaitez que l'agent accède.

---

## Gérer les clients MCP

Une fois importés, vous pouvez :

- **Voir tous les clients** — Voir tous les clients MCP sous forme de cartes sur la page MCP
- **Activer / Désactiver** — Basculer les clients sans les supprimer
- **Modifier la configuration** — Cliquer sur une carte pour voir et modifier la configuration JSON
- **Supprimer des clients** — Supprimer les clients MCP dont vous n'avez plus besoin
