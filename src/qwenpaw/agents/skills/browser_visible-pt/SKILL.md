---
name: browser_visible
description: "Use esta skill quando o usuário precisar controlar o modo de inicialização do navegador para browser_use. Por padrão, o browser_use inicia o Chrome/Chromium local usando CDP gerenciado; `headed` controla se a janela é visível, e `private_mode` controla se o CDP é desativado em favor do Playwright."
metadata:
  builtin_skill_version: "1.2"
  qwenpaw:
    emoji: "🖥️"
    requires: {}
---

# Modos de Inicialização do Navegador

O `browser_use.start` possui apenas dois modos de inicialização:

- Padrão: CDP gerenciado
- `private_mode=true`: gerenciado pelo Playwright

Significado dos parâmetros:

- `headed`: se deve exibir a janela do navegador
- `private_mode`: se deve desativar o CDP e usar o Playwright em vez disso

Os dois parâmetros são independentes e podem ser combinados livremente.

## Uso Comum

Inicialização padrão:
```json
{"action": "start"}
```

Abrir uma janela visível:
```json
{"action": "start", "headed": true}
```

Sem CDP:
```json
{"action": "start", "private_mode": true}
```

Janela visível + sem CDP:
```json
{"action": "start", "headed": true, "private_mode": true}
```

## Quando Usar `private_mode`

Defina `private_mode=true` apenas quando o usuário solicitar explicitamente uma das seguintes opções:

- Não quer que o navegador seja gerenciado via CDP
- Quer usar o Playwright em vez disso
- Quer reduzir a possibilidade de outras ferramentas locais se conectarem via CDP

Caso contrário, apenas defina `headed=true` conforme necessário.

## Observações

- O padrão é CDP gerenciado
- O modo de inicialização é inteiramente determinado pelos parâmetros da chamada
- O CDP gerenciado requer Chrome / Chromium / Edge instalado localmente
- `private_mode=true` não significa absolutamente indetectável — simplesmente alterna para o gerenciamento pelo Playwright
- Quando o usuário opera manualmente o navegador visível, o temporizador de inatividade pode não ser reiniciado
- `private_mode` é um parâmetro explícito para cada chamada `start` e não persiste
- Se um navegador já estiver em execução, você deve executar `stop` e depois `start` novamente para alternar os modos de inicialização ou a visibilidade da janela
- O modo visível ocupa a área de trabalho e requer um ambiente gráfico; pode não funcionar em servidores ou ambientes sem interface gráfica
