---
name: news
description: "Busque as últimas notícias para o usuário em sites de notícias especificados. Fornece URLs autoritativas para política, finanças, sociedade, mundo, tecnologia, esportes e entretenimento. Use browser_use para abrir cada URL e snapshot para obter conteúdo, depois resuma para o usuário."
metadata:
  builtin_skill_version: "1.2"
  qwenpaw:
    emoji: "📰"
    requires: {}
---

# Referência de Notícias

Quando o usuário pedir "últimas notícias", "o que está nas notícias hoje" ou "notícias na categoria X", use a ferramenta **browser_use** com as categorias e URLs abaixo: abra a página, tire um snapshot, depois extraia manchetes e pontos-chave do conteúdo da página e responda ao usuário.

## Categorias e Fontes

| Categoria       | Fonte                          | URL |
|-----------------|--------------------------------|-----|
| **Política**    | People's Daily · CPC News      | https://cpc.people.com.cn/ |
| **Finanças**    | China Economic Net             | http://www.ce.cn/ |
| **Sociedade**   | China News · Sociedade         | https://www.chinanews.com/society/ |
| **Mundo**       | CGTN                           | https://www.cgtn.com/ |
| **Tecnologia**  | Science and Technology Daily   | https://www.stdaily.com/ |
| **Esportes**    | CCTV Sports                    | https://sports.cctv.com/ |
| **Entretenimento** | Sina Entertainment          | https://ent.sina.com.cn/ |

## Como Usar (browser_use)

1. **Esclareça a necessidade do usuário**: Determine qual categoria ou categorias (política / finanças / sociedade / mundo / tecnologia / esportes / entretenimento), ou escolha 1–2 para buscar.
2. **Escolha a URL**: Use a URL da tabela para essa categoria; para múltiplas categorias, repita os passos abaixo para cada URL.
3. **Abra a página**: Chame **browser_use** com:
   ```json
   {"action": "open", "url": "https://www.chinanews.com/society/"}
   ```
   Substitua `url` pela URL correspondente da tabela.
4. **Tire um snapshot**: Na mesma sessão, chame **browser_use** novamente:
   ```json
   {"action": "snapshot"}
   ```
   Extraia manchetes, datas e resumos do conteúdo retornado da página.
5. **Resuma a resposta**: Organize uma lista curta (manchete + uma ou duas frases + fonte) por tempo ou importância; se um site estiver inacessível ou der timeout, diga isso e sugira outra fonte.

## Notas

- A estrutura da página pode mudar quando os sites forem atualizados; se a extração falhar, diga isso e sugira que o usuário abra o link diretamente.
- Ao visitar múltiplas categorias, execute `open` para cada URL, depois `snapshot`, para evitar misturar conteúdo de páginas diferentes.
- Você pode incluir o link original na resposta para que o usuário possa abri-lo.
