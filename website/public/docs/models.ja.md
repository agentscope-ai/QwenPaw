# モデル

CoPaw でチャットする前にモデルを設定する必要があります。**コンソール → 設定 → モデル** から設定できます。

![Console models](https://img.alicdn.com/imgextra/i1/O1CN01zHAE1Z26w6jXl2xbr_!!6000000007725-2-tps-3802-1968.png)

CoPaw は複数の LLM プロバイダーに対応しています：**クラウドプロバイダー**（API キーが必要、Google Gemini を含む）、**ローカルプロバイダー**（llama.cpp / MLX）、**Ollama プロバイダー**、**LM Studio プロバイダー**、および**カスタムプロバイダー**の追加が可能です。このページでは各タイプの設定方法を説明します。

---

## クラウドプロバイダーの設定

クラウドプロバイダー（ModelScope、DashScope、Aliyun Coding Plan、OpenAI、Azure OpenAI、Google Gemini、MiniMax を含む）はリモートモデルを API 経由で呼び出し、**API キー** が必要です。

**コンソールでの操作：**

1. コンソールを開き、**設定 → モデル** に移動します。
2. 対象のクラウドプロバイダーカード（例：DashScope）を見つけ、**設定** をクリックします。**API キー** を入力し、**保存** をクリックします。

   ![save](https://img.alicdn.com/imgextra/i1/O1CN01zHAE1Z26w6jXl2xbr_!!6000000007725-2-tps-3802-1968.png)

3. 保存後、カード右上のステータスが **利用可能** になります。上部の **LLM 設定** セクションで、**プロバイダー** ドロップダウンからこのプロバイダーを選択し、**モデル** ドロップダウンでモデル一覧を確認できます。

   ![choose](https://img.alicdn.com/imgextra/i2/O1CN01aYwWJ31gsjoGdycs5_!!6000000004198-2-tps-3802-1968.png)

4. 対象のモデル（例：qwen3.5-plus）を選択し、**保存** をクリックします。

   ![save](https://img.alicdn.com/imgextra/i3/O1CN01oQTx2a1Qey37oM3Tw_!!6000000002002-2-tps-3802-1968.png)

5. LLM 設定バーの右上に、現在のプロバイダーとモデルが表示されます。

   ![model](https://img.alicdn.com/imgextra/i1/O1CN018wZ0C81MWweGbYL33_!!6000000001443-2-tps-3802-1968.png)

> クラウドプロバイダーの認証を取り消すには、そのカードの **設定** をクリックし、**認証の取り消し** を選択して確認します。プロバイダーのステータスが **利用不可** に変わります。
>
> ![cancel](https://img.alicdn.com/imgextra/i2/O1CN01A8j1IR1n8fHGnio0q_!!6000000005045-2-tps-3802-1968.png)

## Google Gemini プロバイダー

Google Gemini プロバイダーは、Google のネイティブ Gemini API（`google-genai` SDK 経由）を使用して Gemini モデルにアクセスします。事前設定されたモデルには、Gemini 3.1 Pro、Gemini 3 Flash、Gemini 3.1 Flash Lite、Gemini 2.5 Pro、Gemini 2.5 Flash、Gemini 2.5 Flash Lite、Gemini 2.0 Flash が含まれます。追加のモデルは API から自動検出できます。

**前提条件：**

- [Google AI Studio](https://aistudio.google.com/apikey) から Gemini API キーを取得。

**コンソールでの操作：**

1. コンソールを開き、**設定 → モデル** に移動します。
2. **Google Gemini** プロバイダーカードを見つけ、**設定** をクリックします。**API キー** を入力し、**保存** をクリックします。
3. 保存後、カードのステータスが **利用可能** になります。このプロバイダーは **モデル検出** に対応しています — **モデル** をクリックすると、API から利用可能な Gemini モデルを自動検出します。
4. 上部の **LLM 設定** セクションで、**プロバイダー** ドロップダウンから **Google Gemini** を選択し、モデル（例：`gemini-2.5-flash`）を選んで、**保存** をクリックします。

**CLI での操作：**

```bash
# API キーの設定
copaw models config-key gemini

# Gemini をアクティブな LLM に設定
copaw models set-llm
```

> **ヒント：** 思考機能を持つ Gemini モデル（例：Gemini 3.1 Pro、Gemini 2.5 Pro、Gemini 2.5 Flash）は拡張推論に対応しています。CoPaw はこれらのモデルからの思考ブロックと思考シグネチャを自動的に処理します。

## ローカルプロバイダー（llama.cpp / MLX）

ローカルプロバイダーはお使いのマシン上でモデルを実行し、**API キーは不要** です。データはデバイス上に保持されます。

**前提条件：**

- CoPaw と同じ環境に対応するバックエンドをインストール：
  - llama.cpp: `pip install 'copaw[llamacpp]'`
  - MLX: `pip install 'copaw[mlx]'`

1. モデルページに llama.cpp と MLX のカードが表示されます。

   ![card](https://img.alicdn.com/imgextra/i3/O1CN01Xpbl8a1nJemcFr97p_!!6000000005069-2-tps-3802-1968.png)

2. 対象のローカルプロバイダーカード（例：llama.cpp）の **モデル** をクリックし、次に **モデルをダウンロード** をクリックします。

   ![download](https://img.alicdn.com/imgextra/i3/O1CN01ML9Ce81kyvcoD92hG_!!6000000004753-2-tps-3802-1968.png)

3. **リポジトリ ID** を入力し、**ソース** を選択して、**モデルをダウンロード** をクリックします。

   ![id](https://img.alicdn.com/imgextra/i3/O1CN01HaIQwC1qV3UHvsvgc_!!6000000005500-2-tps-3802-1968.png)

4. ダウンロードが開始されます。完了するまでお待ちください。

   ![wait](https://img.alicdn.com/imgextra/i2/O1CN018b8woI1yHmwOJB2V6_!!6000000006554-2-tps-3802-1968.png)

5. ダウンロードが完了すると、ローカルプロバイダーカードのステータスが **利用可能** になります。

   ![avai](https://img.alicdn.com/imgextra/i4/O1CN01yazvrI25tWt9WqD8w_!!6000000007584-2-tps-3802-1968.png)

6. 上部の **LLM 設定** で、**プロバイダー** ドロップダウンからローカルプロバイダーを選択し、**モデル** ドロップダウンから新しく追加したモデルを選択して、**保存** をクリックします。

   ![model](https://img.alicdn.com/imgextra/i1/O1CN015KoPYh1cCp6H4rkN9_!!6000000003565-2-tps-3802-1968.png)

7. LLM 設定エリアにローカルプロバイダーと選択したモデル名が表示されます。

   ![see](https://img.alicdn.com/imgextra/i1/O1CN01Dce5Pt1GH1BBxJcjD_!!6000000000596-2-tps-3802-1968.png)

> ローカルプロバイダーカードの **モデル** をクリックすると、モデル名、サイズ、ソースを確認できます。モデルを削除するには、そのモデルの右側にある **ゴミ箱アイコン** をクリックして確認します。
>
> ![delete](https://img.alicdn.com/imgextra/i4/O1CN01roGD1X1lKudZT51co_!!6000000004801-2-tps-3802-1968.png)

## Ollama プロバイダー

Ollama プロバイダーは、お使いのマシンにインストールされた **Ollama デーモン** を使用します。モデルは Ollama が管理し、CoPaw は直接ダウンロードしません。モデル一覧は Ollama と同期されます。

**前提条件：**

- [ollama.com](https://ollama.com) から Ollama をインストール。
- CoPaw の環境に Ollama サポートをインストール：`pip install 'copaw[ollama]'`

1. モデルページに Ollama プロバイダーカードが表示されます。

2. 右下の **設定** をクリックします。Ollama 設定ページで **API キー** を入力します（任意の値で構いません。例：`ollama`）。**保存** をクリックします。

   ![set](https://img.alicdn.com/imgextra/i1/O1CN01JhGTpy1FPQqDXSVo9_!!6000000000479-2-tps-3802-1968.png)

3. 右下の **モデル** をクリックします。Ollama で既にモデルをプルしている場合、ここに表示されます。新しいモデルをプルするには、**モデルをダウンロード** をクリックします。

   ![download](https://img.alicdn.com/imgextra/i2/O1CN01CARKar1ilzCd0dIZ9_!!6000000004454-2-tps-3802-1968.png)

4. **モデル名** を入力し、**モデルをダウンロード** をクリックします。

   ![download](https://img.alicdn.com/imgextra/i3/O1CN014JJgSv24of3xUkGch_!!6000000007438-2-tps-3802-1968.png)

5. モデルのダウンロードが開始されます。完了するまでお待ちください。

   ![wait](https://img.alicdn.com/imgextra/i3/O1CN01ptZICs25rEuMA4O7U_!!6000000007579-2-tps-3802-1968.png)

6. 完了後、上部の **LLM 設定** で、**プロバイダー** ドロップダウンから **Ollama** を選択し、**モデル** ドロップダウンからモデルを選択して、**保存** をクリックします。

   ![save](https://img.alicdn.com/imgextra/i3/O1CN01DEOqAH1ODMx4rUTLw_!!6000000001671-2-tps-3802-1968.png)

7. LLM 設定エリアに Ollama プロバイダーと選択したモデル名が表示されます。

   ![name](https://img.alicdn.com/imgextra/i2/O1CN01955KEG1vtOcDcdedZ_!!6000000006230-2-tps-3802-1968.png)

> `Ollama SDK not installed. Install with: pip install 'copaw[ollama]'` と表示される場合は、ollama.com から Ollama がインストールされていること、および CoPaw の環境で `pip install 'copaw[ollama]'` を実行済みであることを確認してください。モデルを削除するには、Ollama カードの **モデル** をクリックし、モデルの横の **ゴミ箱アイコン** をクリックして確認します。
>
> ![delete](https://img.alicdn.com/imgextra/i1/O1CN01OvNNu21shXVzD14go_!!6000000005798-2-tps-3802-1968.png)
>
> **Docker ユーザーの方へ：** CoPaw が Docker コンテナ内で実行されている場合、`localhost` はホストマシンではなくコンテナを指します。Ollama のベース URL を `http://host.docker.internal:11434` に変更してください（`docker run` コマンドに `--add-host=host.docker.internal:host-gateway` を追加してください）。詳細は [README の Docker セクション](https://github.com/agentscope-ai/CoPaw#using-docker) をご覧ください。

## LM Studio プロバイダー

LM Studio プロバイダーは、**LM Studio** デスクトップアプリケーションに内蔵された OpenAI 互換サーバーに接続します。モデルは LM Studio の GUI で管理され、CoPaw は `/v1/models` エンドポイントを介して読み込まれたモデルを自動的に検出します。

**前提条件：**

- [lmstudio.ai](https://lmstudio.ai) から LM Studio をインストール。
- LM Studio でモデルを読み込み、ローカルサーバーを起動（デフォルト：`http://localhost:1234`）。

1. モデルページに LM Studio プロバイダーカードが表示されます。

2. 右下の **設定** をクリックします。デフォルトのベース URL は `http://localhost:1234/v1` です。LM Studio でポートを変更した場合は調整してください。**保存** をクリックします。

3. **モデル** をクリックすると、LM Studio に現在読み込まれているモデルが表示されます。必要に応じてモデル ID を手動で追加することもできます。

4. 上部の **LLM 設定** で、**プロバイダー** ドロップダウンから **LM Studio** を選択し、**モデル** ドロップダウンからモデルを選択して、**保存** をクリックします。

> **ヒント：** LM Studio はデフォルトで API キーを必要としません。LM Studio で認証を有効にしている場合は、**API キー** フィールドにキーを入力してください。モデルは LM Studio の GUI で読み込まれていないと CoPaw に表示されません。
>
> **重要 — コンテキスト長：** LM Studio はデフォルトで小さなコンテキスト長（多くの場合 2048 または 4096 トークン）でモデルを読み込みます。CoPaw のシステムプロンプト（AGENTS.md + SOUL.md + PROFILE.md）はこの制限を容易に超える可能性があり、_「初期プロンプトから保持するトークン数がコンテキスト長を超えています」_ というエラーが発生することがあります。これを修正するには、**LM Studio でモデルをアンロードし、より大きなコンテキスト長で再読み込み** してください（16384 以上を推奨）。LM Studio の GUI（モデル設定 → コンテキスト長）または CLI で実行できます：`lms unload --all && lms load <model> -c 16384`
>
> **Docker ユーザーの方へ：** CoPaw が Docker コンテナ内で実行されている場合、`localhost` はホストマシンではなくコンテナを指します。LM Studio のベース URL を `http://host.docker.internal:1234/v1` に変更してください（`docker run` コマンドに `--add-host=host.docker.internal:host-gateway` を追加してください）。詳細は [README の Docker セクション](https://github.com/agentscope-ai/CoPaw#using-docker) をご覧ください。

## カスタムプロバイダーの追加

1. モデルページで **プロバイダーを追加** をクリックします。

   ![add](https://img.alicdn.com/imgextra/i2/O1CN018PFJmz1kUhUBwf4OL_!!6000000004687-2-tps-3802-1968.png)

2. **プロバイダー ID** と **表示名** を入力し、**作成** をクリックします。

   ![create](https://img.alicdn.com/imgextra/i3/O1CN01XuLvkT1wRHvNLHUaf_!!6000000006304-2-tps-3802-1968.png)

3. 新しいプロバイダーカードが表示されます。

   ![card](https://img.alicdn.com/imgextra/i3/O1CN01BFghrw1ZFcfpyzIL7_!!6000000003165-2-tps-3802-1968.png)

4. **設定** をクリックし、**ベース URL** と **API キー** を入力して、**保存** をクリックします。

   ![save](https://img.alicdn.com/imgextra/i4/O1CN01R5ZTQ321ymyQ8psEY_!!6000000007054-2-tps-3802-1968.png)

5. カードに設定されたベース URL と API キーが表示されますが、モデルを追加するまでステータスは **利用不可** のままです。

   ![model](https://img.alicdn.com/imgextra/i4/O1CN01qDDA1I1xd1gu7D8w2_!!6000000006465-2-tps-3802-1968.png)

6. **モデル** をクリックし、**モデル ID** を入力して、**モデルを追加** をクリックします。

   ![add](https://img.alicdn.com/imgextra/i2/O1CN01nG1FoA1KyJ4vcUYwo_!!6000000001232-2-tps-3802-1968.png)

7. カスタムプロバイダーが **利用可能** と表示されます。上部の **LLM 設定** で、**プロバイダー** ドロップダウンから選択し、**モデル** ドロップダウンから新しいモデルを選択して、**保存** をクリックします。

   ![model](https://img.alicdn.com/imgextra/i2/O1CN01EtQCWr1YpW63ox5QY_!!6000000003108-2-tps-3802-1968.png)

8. LLM 設定エリアにカスタムプロバイダー ID と選択したモデル名が表示されます。

   ![save](https://img.alicdn.com/imgextra/i2/O1CN01WPMjKq1bCzdC8RJvP_!!6000000003430-2-tps-3802-1968.png)

> 設定に失敗した場合は、**ベース URL**、**API キー**、**モデル ID**（大文字小文字を含む）を再確認してください。カスタムプロバイダーを削除するには、そのカードの **プロバイダーを削除** をクリックして確認します。
>
> ![delete](https://img.alicdn.com/imgextra/i3/O1CN0124kc9J1dv4zHYDWQg_!!6000000003797-2-tps-3802-1968.png)
