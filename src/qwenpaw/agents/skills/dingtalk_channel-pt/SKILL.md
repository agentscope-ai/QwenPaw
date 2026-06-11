---
name: dingtalk_channel_connect
description: "Use um navegador com interface gráfica para completar automaticamente a integração de canal DingTalk para o QwenPaw. Aplicável quando o usuário mencionar DingTalk, console de desenvolvedor, Client ID, Client Secret, bot, modo Stream, vinculação ou configuração de canal. Suporta pausar quando uma página de login for detectada e retomar após o usuário efetuar login."
metadata:
  builtin_skill_version: "1.3"
  qwenpaw:
    emoji: "🤖"
    requires: {}
---

# Conexão Automática de Canal DingTalk (Navegador com Interface Gráfica)

Esta skill automatiza a criação de um aplicativo DingTalk e a vinculação de um canal QwenPaw usando um navegador com interface gráfica.

## Regras Obrigatórias

1. Deve ser iniciado no modo de navegador com interface gráfica:

```json
{"action": "start", "headed": true}
```

2. Deve pausar quando uma tela de login for encontrada:
   - Se a página exibir uma tela de login (ex.: prompt de login, login por QR code, login por telefone/senha), interrompa as operações automatizadas imediatamente.
   - Informe claramente ao usuário para fazer login manualmente primeiro, depois aguarde o usuário responder com "logado / continuar".
   - Não prossiga com as etapas seguintes até que o usuário confirme.

3. Qualquer alteração de configuração do aplicativo só entra em vigor após criar uma nova versão e publicar:
   - Após configurar informações relacionadas ao bot, **você deve publicar o bot**.
   - Seja criando um novo aplicativo ou modificando informações do aplicativo (nome, descrição, ícone, configuração do bot, etc.), você **deve realizar "criar nova versão + publicar"** ao final.
   - Não afirme que a configuração está ativa se a publicação não foi concluída.

## Confirmação Prévia à Execução (Obrigatório Fazer Primeiro)

Antes de iniciar os cliques automatizados, inicie uma "confirmação de configuração" com o usuário, informando-o claramente sobre os campos personalizáveis, especificações de imagem e valores padrão. Use a seguinte confirmação estruturada:

1. Permita que o usuário personalize os seguintes campos:
   - Nome do aplicativo
   - Descrição do aplicativo
   - URL de imagem ou caminho local para ícone do bot
   - URL de imagem ou caminho local para imagem de prévia de mensagem do bot

2. Indique claramente as especificações de imagem (de forma proeminente):
   - Ícone do bot: somente JPG/PNG, `240*240px` ou maior, proporção `1:1`, menos de `2MB`, sem cantos arredondados.
   - Imagem de prévia de mensagem do bot: formato `png/jpeg/jpg`, no máximo `2MB`.

3. Indique claramente os valores padrão (usados automaticamente se o usuário não especificar):
   - Nome do aplicativo: `QwenPaw`
   - Descrição do aplicativo: `Your personal assistant`
   - Ícone do bot: `https://img.alicdn.com/imgextra/i4/O1CN01M0iyHF1FVNzM9qjC0_!!6000000000492-2-tps-254-254.png`
   - Imagem de prévia de mensagem do bot: `https://img.alicdn.com/imgextra/i4/O1CN01M0iyHF1FVNzM9qjC0_!!6000000000492-2-tps-254-254.png`

4. Se o usuário não fornecer valores personalizados, você deve primeiro responder explicitamente:
   - "Todas as configurações padrão serão usadas (QwenPaw / Your personal assistant / imagens padrão). Prosseguindo agora."

## Estratégia de Upload de Imagem (Link e caminho local são suportados)

1. Se o usuário fornecer um caminho local, use-o diretamente para upload.
2. Se o usuário fornecer um link de imagem, baixe-o para um arquivo temporário local primeiro, depois faça o upload.
3. A sequência de ações de upload deve ser:
   - Primeiro clique na entrada de upload da página (para disparar o seletor de arquivos)
   - Depois chame `file_upload` com o array de caminhos locais (`paths_json`)
4. Se o upload falhar devido a incompatibilidade com as especificações de imagem (dimensões, proporção, tamanho, formato):
   - Pause a automação imediatamente
   - Peça claramente ao usuário que faça o upload manualmente de uma imagem compatível
   - Após o usuário confirmar "enviado / continuar", retome a partir da etapa atual

### Dicas Práticas de Upload

1. O `paths_json` do `file_upload` deve ser um "array de strings JSON" — observe o escape:

```json
{
  "action": "file_upload",
  "paths_json": "[\"xxx.png\"]",
  "frame_selector": "iframe[src*=\"/fe/app?isHideOuterFrame=true\"]"
}
```

2. Se a página estiver dentro de um iframe, prefira incluir `frame_selector`; caso contrário, o controle de upload pode não ser encontrado ou o seletor pode não ser disparado.

3. Você deve clicar na entrada de upload antes de chamar `file_upload`; chamá-lo diretamente resultará em:
   - `No chooser. Click upload then file_upload.`

4. Características estruturais comuns da área de ícone do bot que podem ser usadas para localizar elementos (exemplos; podem aparecer como rótulos de UI em chinês no console DingTalk):
   - `text: "* 机器人图标"` (Ícone do Bot)
   - `button: "使用应用图标"` (Usar Ícone do App)
   - `button: "avatar"` (geralmente contém `img "avatar"` internamente)

5. Quando o snapshot mostrar tanto "使用应用图标" ("Usar Ícone do App") quanto "avatar", prefira clicar no botão `avatar` para disparar o upload, depois chame `file_upload`.

## Fluxo de Automação

### Etapa 1: Abrir o Console de Desenvolvedor DingTalk

1. Inicie o navegador no modo com interface gráfica (`headed: true`)
2. Navegue para `https://open-dev.dingtalk.com/`
3. Chame `snapshot` para verificar se login é necessário

Se login for necessário, pause com a seguinte mensagem:

> Login no Console de Desenvolvedor DingTalk é necessário. Pausei as operações automatizadas. Por favor, conclua o login no navegador aberto. Responda "continuar" quando terminar e eu retomarei a partir da página atual.

### Etapa 2: Criar um Aplicativo Empresarial Interno

Após o usuário confirmar o login, continue:

1. Navegue até o caminho de criação:
   - Desenvolvimento de Aplicativos -> Aplicativos Empresariais Internos -> Aplicativos DingTalk -> Criar Aplicativo
2. Preencha as informações do aplicativo (prefira valores personalizados do usuário, caso contrário use os padrões):
   - Nome do aplicativo: padrão `QwenPaw`
   - Descrição do aplicativo: padrão `Your personal assistant`
3. Salve e crie o aplicativo

Se o texto ou estrutura da página não corresponder ao esperado, execute novamente `snapshot` e reposicione os elementos com base na semântica do texto visível.

### Etapa 3: Adicionar Capacidade de Bot e Publicar

1. Clique em **Adicionar Capacidade de Aplicativo** em **Capacidades do Aplicativo**, encontre **Bot** e adicione-o
2. Ative o botão de alternância no lado direito de **Configuração do Bot**
3. Preencha **Nome do Bot**, **Resumo do Bot** e **Descrição do Bot**
4. Faça upload do **Ícone do Bot** (imagem personalizada do usuário ou padrão):
   - Clique na imagem abaixo do rótulo do ícone do bot
   - URL da imagem padrão: `https://img.alicdn.com/imgextra/i4/O1CN01M0iyHF1FVNzM9qjC0_!!6000000000492-2-tps-254-254.png`
   - Se for um link, baixe localmente primeiro, depois faça o upload
   - Se a imagem não atender às especificações, pause e peça ao usuário para fazer o upload manualmente de uma imagem compatível antes de continuar
5. Faça upload da **Imagem de Prévia de Mensagem do Bot** (imagem personalizada do usuário ou padrão):
   - Clique na imagem abaixo do rótulo da imagem de prévia de mensagem do bot
   - URL da imagem padrão: `https://img.alicdn.com/imgextra/i4/O1CN01M0iyHF1FVNzM9qjC0_!!6000000000492-2-tps-254-254.png`
   - Se for um link, baixe localmente primeiro, depois faça o upload
   - Se a imagem não atender às especificações, pause e peça ao usuário para fazer o upload manualmente de uma imagem compatível antes de continuar
6. Confirme que o modo de recebimento de mensagens está definido como `Modo Stream` (a UI em chinês pode exibir `Stream 模式`)
7. Selecione **Publicar**; um diálogo de confirmação adicional aparecerá — selecione publicar. Observação: **você deve publicar o bot** antes de prosseguir para a próxima etapa

### Etapa 4: Criar Versão e Publicar

1. Navegue para `Lançamento do Aplicativo -> Gerenciamento e Lançamento de Versões`
2. Crie uma nova versão (obrigatório após cada alteração de configuração)
3. Preencha a descrição da versão; defina o escopo de visibilidade do aplicativo para todos os funcionários
4. Siga as instruções da página para concluir a publicação; um novo diálogo aparecerá — selecione confirmar publicação
5. Somente após ver o status de publicação bem-sucedida você pode prosseguir com as etapas subsequentes ou dizer ao usuário "a configuração está agora ativa"

### Etapa 5: Obter Credenciais

1. Navegue para `Informações Básicas -> Credenciais e Informações Básicas`
2. Informe ao usuário que o `Client ID` (AppKey) e o `Client Secret` (AppSecret) estão nesta página. Não faça alterações proativamente; oriente o usuário a vinculá-los por conta própria

## Métodos de Vinculação QwenPaw

Após obter as credenciais, oriente o usuário a escolher um dos seguintes métodos:

1. Configuração pelo frontend do console:
   - No console QwenPaw, vá para `Controle -> Canais -> DingTalk`
   - Insira o `Client ID` e o `Client Secret`

2. Método de arquivo de configuração:

```json
"dingtalk": {
  "enabled": true,
  "bot_prefix": "[BOT]",
  "client_id": "Seu Client ID",
  "client_secret": "Seu Client Secret"
}
```

Caminho: `~/.qwenpaw/config.json`, no campo `channels.dingtalk`.

### Requisitos de Entrega de Credenciais (Obrigatório)

1. O agente é responsável apenas por orientar o usuário até a página de credenciais, obter e exibir o `Client ID` e o `Client Secret` real.
2. O agente não deve modificar proativamente a configuração do `console` ou o `~/.qwenpaw/config.json`.
3. Você deve instruir o usuário a preencher as credenciais manualmente usando um dos dois métodos:
   - Frontend do console: `Controle -> Canais -> DingTalk`
   - Arquivo de configuração: edite o campo `channels.dingtalk` no `~/.qwenpaw/config.json`

## Padrão de Uso da Ferramenta de Navegador

Execute na seguinte ordem por padrão:

1. `start` com `headed: true`
2. `open`
3. `snapshot`
4. `click` / `type` / `select_option` / `press_key` conforme necessário
5. `snapshot` frequente após transições de página
6. `stop` ao terminar

## Estratégia de Estabilidade e Recuperação

- Prefira usar o `ref` do `snapshot` mais recente; use `selector` apenas quando necessário.
- Após cada clique crítico ou navegação, use uma espera curta (`wait_for`) e execute `snapshot` novamente imediatamente.
- Se a sessão expirar ou login for necessário novamente durante o fluxo, pause novamente e aguarde o usuário fazer login antes de continuar a partir da etapa atual.
- Se a automação for bloqueada por permissões de tenant ou aprovação de administrador, descreva claramente o bloqueio e peça ao usuário que conclua essa etapa manualmente antes de retomar.
