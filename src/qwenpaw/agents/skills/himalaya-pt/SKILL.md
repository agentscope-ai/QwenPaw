---
name: himalaya
description: "CLI para gerenciar e-mails via IMAP/SMTP. Use `himalaya` para listar, ler, escrever, responder, encaminhar, pesquisar e organizar e-mails pelo terminal. Suporta múltiplas contas e composição de mensagens com MML (MIME Meta Language)."
homepage: https://github.com/pimalaya/himalaya
metadata:
  builtin_skill_version: "1.3"
  qwenpaw:
    emoji: "📧"
    requires:
      bins:
        - himalaya
    install:
      - id: brew
        kind: brew
        formula: himalaya
        bins:
          - himalaya
        label: "Instalar Himalaya (brew)"
---
# Himalaya Email CLI

Himalaya é um cliente de e-mail CLI que permite gerenciar e-mails pelo terminal usando backends IMAP, SMTP, Notmuch ou Sendmail.

## Referências

- `references/configuration.md` (configuração do arquivo de config + autenticação IMAP/SMTP)

## Pré-requisitos

1. **Himalaya CLI** - o binário `himalaya` deve estar disponível no `PATH`. Verifique com `himalaya --version`.
   - **Recomendado: v1.2.0 ou mais recente.** Versões mais antigas podem falhar com alguns servidores IMAP; v1.2.0+ inclui correções relacionadas.
2. Um arquivo de configuração em `~/.config/himalaya/config.toml`
3. Credenciais IMAP/SMTP configuradas (senha armazenada com segurança)

## Configuração

Execute o assistente interativo para configurar uma conta (substitua `default` por qualquer nome desejado, ex.: `gmail`, `trabalho`):

```bash
himalaya account configure default
```

Ou crie `~/.config/himalaya/config.toml` manualmente:

```toml
[accounts.personal]
email = "voce@exemplo.com"
display-name = "Seu Nome"
default = true

backend.type = "imap"
backend.host = "imap.exemplo.com"
backend.port = 993
backend.encryption.type = "tls"
backend.login = "voce@exemplo.com"
backend.auth.type = "password"
backend.auth.cmd = "pass show email/imap"  # ou use keyring

message.send.backend.type = "smtp"
message.send.backend.host = "smtp.exemplo.com"
message.send.backend.port = 587
message.send.backend.encryption.type = "start-tls"
message.send.backend.login = "voce@exemplo.com"
message.send.backend.auth.type = "password"
message.send.backend.auth.cmd = "pass show email/smtp"
```

Se você estiver usando conta de e-mail 163, adicione `backend.extensions.id.send-after-auth = true` no arquivo de config para garantir o funcionamento correto.

## Operações Comuns

### Listar Pastas

```bash
himalaya folder list
```

### Listar E-mails

Listar e-mails na CAIXA DE ENTRADA (padrão):

```bash
himalaya envelope list
```

Listar e-mails em uma pasta específica:

```bash
himalaya envelope list --folder "Enviados"
```

Listar com paginação:

```bash
himalaya envelope list --page 1 --page-size 20
```

Se encontrar erros, tente:

```bash
himalaya envelope list -f INBOX -s 1
```

### Pesquisar E-mails

```bash
himalaya envelope list from joao@exemplo.com subject reuniao
```

### Ler um E-mail

Ler e-mail por ID (mostra texto simples):

```bash
himalaya message read 42
```

Exportar MIME bruto:

```bash
himalaya message export 42 --full
```

### Enviar / Compor E-mails

**Abordagem recomendada:** Use o pipeline `template write | template send` para e-mails simples.

**Enviar um e-mail simples:**

```bash
export EDITOR=cat
himalaya template write \
  -H "To: destinatario@exemplo.com" \
  -H "Subject: Assunto do E-mail" \
  "Conteúdo do corpo do e-mail" | himalaya template send
```

**Enviar com múltiplos cabeçalhos:**

```bash
export EDITOR=cat
himalaya template write \
  -H "To: destinatario@exemplo.com" \
  -H "Cc: cc@exemplo.com" \
  -H "Subject: Assunto do E-mail" \
  "Conteúdo do corpo do e-mail" | himalaya template send
```

**Enviar com anexos (usando Python):**

Para e-mails com anexos, use os módulos `smtplib` e `email.mime` do Python:

```python
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders

msg = MIMEMultipart()
msg['From'] = 'remetente@163.com'
msg['To'] = 'destinatario@exemplo.com'
msg['Subject'] = 'E-mail com anexo'

msg.attach(MIMEText('Corpo do e-mail', 'plain'))

# Adicionar anexo
with open('/caminho/para/arquivo.pdf', 'rb') as f:
    part = MIMEBase('application', 'octet-stream')
    part.set_payload(f.read())
    encoders.encode_base64(part)
    part.add_header('Content-Disposition', 'attachment; filename="arquivo.pdf"')
    msg.attach(part)

server = smtplib.SMTP_SSL('smtp.163.com', 465)
server.login('remetente@163.com', 'senha')
server.send_message(msg)
server.quit()
```

**⚠️ Limitações de anexos MML:** O comando `template send` com formato MML pode falhar com "cannot parse MML message: empty body" ao usar multipart/anexos. Este é um problema conhecido no himalaya v1.1.0. Use a abordagem Python para anexos.

**⚠️ Evite `message write` para automação:** O comando `himalaya message write` requer seleção interativa via TUI (Editar/Descartar/Sair) e travará em ambientes não-interativos.

**⚠️ Limitações do `message send`:** O `himalaya message send <email_bruto>` direto pode falhar com "cannot send message without a recipient" devido a problemas de análise de cabeçalho. Use `template send` em vez disso.

**Requisito de configuração:** Certifique-se de que `message.send.save-to-folder` esteja definido em config.toml para evitar erros "Folder not exist":

```toml
[accounts.163]
# ... outra config ...
message.send.save-to-folder = "Sent"
```

Para contas de e-mail 163, crie a pasta Sent primeiro se não existir:

```bash
himalaya folder create Sent
```

### Mover/Copiar E-mails

Mover para pasta:

```bash
himalaya message move 42 "Arquivo"
```

Copiar para pasta:

```bash
himalaya message copy 42 "Importante"
```

### Excluir um E-mail

```bash
himalaya message delete 42
```

### Gerenciar Flags

Adicionar flag:

```bash
himalaya flag add 42 --flag seen
```

Remover flag:

```bash
himalaya flag remove 42 --flag seen
```

## Múltiplas Contas

Listar contas:

```bash
himalaya account list
```

Usar uma conta específica:

```bash
himalaya --account trabalho envelope list
```

## Anexos

Salvar anexos de uma mensagem:

```bash
himalaya attachment download 42
```

Salvar em diretório específico:

```bash
himalaya attachment download 42 --dir ~/Downloads
```

## Formatos de Saída

A maioria dos comandos suporta `--output` para saída estruturada:

```bash
himalaya envelope list --output json
himalaya envelope list --output plain
```

## Depuração

Ativar log de depuração:

```bash
RUST_LOG=debug himalaya envelope list
```

Rastreamento completo com backtrace:

```bash
RUST_LOG=trace RUST_BACKTRACE=1 himalaya envelope list
```

## Dicas

- Use `himalaya --help` ou `himalaya <comando> --help` para uso detalhado.
- Os IDs de mensagem são relativos à pasta atual; liste novamente após trocar de pasta.
- Para compor e-mails ricos com anexos, use sintaxe MML (veja `references/message-composition.md`).
- Armazene senhas com segurança usando `pass`, keyring do sistema ou um comando que retorne a senha.
- **Para automação:** Sempre use o pipeline `template write | template send` com `export EDITOR=cat`.
- **Usuários de e-mail 163:** Defina `backend.extensions.id.send-after-auth = true` e `message.send.save-to-folder = "Sent"` na configuração.
- **Nomes de pastas:** Use nomes de pastas em inglês (ex.: "Sent" em vez de "已发送") para melhor compatibilidade.
