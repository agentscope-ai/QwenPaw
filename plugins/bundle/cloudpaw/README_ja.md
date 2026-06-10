<p align="center">
  <img src="https://raw.githubusercontent.com/agentscope-ai/QwenPaw/main/plugins/bundle/cloudpaw/docs/cloudpaw.png" alt="CloudPaw" width="360" />
</p>

<p align="center">
  <strong>QwenPaw 向けクラウド機能拡張プラグイン</strong>
</p>

<p align="center">
  <a href="https://github.com/agentscope-ai/CloudPaw/blob/main/LICENSE"><img src="https://img.shields.io/badge/License-Apache%202.0-blue.svg" alt="License" /></a>
  <a href="https://www.python.org/downloads/"><img src="https://img.shields.io/badge/Python-3.10%2B-blue.svg" alt="Python" /></a>
  <a href="#"><img src="https://img.shields.io/badge/version-0.0.3-green.svg" alt="Version" /></a>
</p>

<p align="center">
  <a href="README.md">English</a> | <a href="README_zh.md">中文</a> | <b>日本語</b> | <a href="README_ru.md">Русский</a>
</p>

---

CloudPaw は QwenPaw のクラウド機能拡張プラグインで、**QwenPaw + Aliyun CLI** を組み合わせ、**IaC** を深く統合しています。単なるチャットボットではなく、クラウドネイティブな実行エンジンを備えたインテリジェントアシスタントです。

自然言語でニーズを説明するだけで、CloudPaw がリソースの作成からアプリケーションのデプロイまで全プロセスを自動化します。例えば：

- **一言でアプリをデプロイ**：CloudPaw に「個人サイトを作って」と伝えれば、ECS インスタンスの作成、セキュリティグループの設定、アプリケーションのデプロイを自動で行い、アクセス可能な URL を返します。
- **個人サイトの迅速な公開**：希望するコンテンツとスタイルを説明すれば、CloudPaw がコードを生成し、クラウドにデプロイし、パブリックエンドポイントをバインドします。
- **API サービスの迅速な公開**：インターフェース定義を指定すれば、CloudPaw がコード生成からコンテナビルド、サービス公開までのパイプライン全体を処理します。

CloudPaw はお客様自身の環境で完全に動作し、データの安全性と管理権を確保します。

## クイックスタート

### 前提条件

| 項目 | 要件 |
|------|------|
| **QwenPaw バージョン** | **≥ v1.1.7** |
| **Python** | 3.10 ~ 3.13 |
| **Alibaba Cloud アカウント** | クラウド操作に Access Key が必要 |

> QwenPaw のインストールについては [QwenPaw クイックスタート](https://qwenpaw.agentscope.io/docs/quickstart) を参照してください。QwenPaw のバージョンが v1.1.7 未満の場合は、まずアップグレードしてください：`pip install --upgrade qwenpaw>=1.1.7`。

### 1. CloudPaw プラグインのインストール

**コンソール経由（推奨）：**

1. QwenPaw を起動（`qwenpaw app`）し、http://127.0.0.1:8088/ を開く
2. 左サイドバーの「プラグインマネージャー」（設定グループ内）をクリックし、「プラグインをインストール」をクリック
3. 以下のいずれかの方法でインストール：
   - プラグインダウンロード URL を入力：`https://qwenpaw-download.oss-ap-southeast-1.aliyuncs.com/files/plugins/cloudpaw/cloudpaw-0.0.3.zip`
   - `cloudpaw/` フォルダをインストールダイアログにドラッグするか、ZIP ファイルを選択（CloudPaw は QwenPaw v1.1.7+ の `plugins/bundle/cloudpaw/` にバンドル済み）
4. インストール完了を待つ

**CLI 経由：**

```bash
qwenpaw plugin install /path/to/cloudpaw
# または URL 経由でインストール
qwenpaw plugin install https://qwenpaw-download.oss-ap-southeast-1.aliyuncs.com/files/plugins/cloudpaw/cloudpaw-0.0.3.zip
```

> **⚠️ 重要：インストール後、ブラウザを強制リフレッシュする必要があります**（`Ctrl+Shift+R` / `Cmd+Shift+R`）。CloudPaw のカスタム UI コンポーネント（提案選択、PRD 管理など）はページをリフレッシュするまで表示されません。インストール後に機能が不足している場合は、まずリフレッシュをお試しください。

### 2. 設定

CloudPaw をインストールした後、以下の設定を完了してください：

#### ① QwenPaw モデル

コンソールの「設定」→「モデル」で LLM プロバイダーと API Key を設定します。[QwenPaw モデル設定ドキュメント](https://qwenpaw.agentscope.io/docs/models) を参照してください。

#### ② Alibaba Cloud 認証情報

コンソールの「環境変数」で設定（CloudPaw がプレースホルダーエントリを自動作成）：

- `ALIBABA_CLOUD_ACCESS_KEY_ID` — Access Key ID
- `ALIBABA_CLOUD_ACCESS_KEY_SECRET` — Access Key Secret
- `ALIBABA_CLOUD_REGION_ID` — リージョン ID（デフォルト `cn-hangzhou`）

システム環境変数や CLI でも設定可能です。Access Key の取得方法については [Alibaba Cloud ドキュメント](https://help.aliyun.com/document_detail/116401.html) を参照してください。フル権限を持つプライマリアカウントの Access Key の使用を推奨します。

#### ③ iac-code モデル設定

CloudPaw は IaC テンプレート生成に [iac-code](https://github.com/aliyun/iac-code)（≥ 0.1.2）を使用しています。**手動でのモデル設定は不要です** — CloudPaw が QwenPaw のアクティブモデルを自動的に iac-code に同期します。

CloudPaw プラグインの起動時に `~/.iac-code/settings.yml` に `llm_source: qwenpaw` を書き込みます。これにより iac-code は QwenPaw のアクティブモデルからモデル設定（プロバイダー、API キー、モデル名など）を直接読み取ります。QwenPaw で動作するモデルを設定済みであれば（手順 ①）、iac-code は同じモデルを自動的に使用します — 追加の設定は不要です。

**手動オーバーライド：** iac-code に QwenPaw とは異なるモデルを使用させたい場合は、`IAC_CODE_PROVIDER` 環境変数を設定してください（QwenPaw の環境変数ページまたはシステム環境変数経由）。この変数が存在する場合、CloudPaw は自動注入をスキップし、iac-code は手動設定を使用します。詳細は [iac-code LLM 設定ドキュメント](https://aliyun.github.io/iac-code/docs/configuration/llm-providers) を参照してください。

### 3. 使用開始

チャットページの Agent ドロップダウンから「CloudPaw-Master」を選択して開始します。

> **⚠️ リスク警告：使用前にお読みください**
>
> 1. **リソースリスク**：本サービスは完全なアカウントアクセス権を持つ Alibaba Cloud 管理者認証情報を必要とします。操作によりアカウント内のリソースが作成、変更、または削除される可能性があります。
> 2. **セキュリティアドバイス**：慎重に操作し、既存のリソースを監視してください。使用前に**重要なデータをバックアップ**し、リソースの状態と請求を定期的に確認してください。
> 3. **免責事項**：本サービスは完全に AI 駆動です。AI はエラーや不正確な結果を生成する可能性があります。AI の操作を確認・承認する責任はお客様にあり、最終結果についてもお客様が責任を負います。AI の操作に起因する損失について、当方は責任を負いません。
> 4. **費用について**：クラウドリソースの作成と使用には対応するクラウドサービス料金が発生します。請求を監視し、リソースの使用を適切に計画してください。

## アーキテクチャ

CloudPaw は QwenPaw ネイティブプラグインシステムを通じて統合されます。

```
QwenPaw/
└── plugins/
    └── bundle/
        └── cloudpaw/           # CloudPaw プラグイン（フロントエンド＆バックエンド）
            ├── plugin.json     # プラグインマニフェスト
            ├── plugin.py       # バックエンドエントリーポイント
            ├── requirements.txt # Python 依存関係（iac-code, httpx-sse）
            ├── ui/             # フロントエンドプラグイン（カスタムツールコールレンダラー）
            ├── skills/         # スキル定義
            ├── tools/          # ツール実装
            ├── modules/        # モジュール
            ├── agents/         # Agent プロンプトと設定
            └── prompts/        # プロンプト定義
```

## 機能

- **IaC デプロイオーケストレーション**：[iac-code](https://github.com/aliyun/iac-code) エンジンによる ROS/Terraform テンプレート生成で Alibaba Cloud リソースデプロイを自動化
- **リソース提案選択**：専用フロントエンドレンダリングによるインタラクティブな複数提案の比較と選択（`proposal_choice` ツール）
- **PRD 管理フロントエンド拡張**：QwenPaw Mission Mode の PRD 管理用カスタムフロントエンドレンダリング（`manage_prd` ツール）
- **マルチ Agent 協調**：QwenPaw Mission Mode を通じて複数の Agent を編成し、複雑なデプロイタスクを実行
- **Alibaba Cloud Skills リモート Agent 統合**：A2A プロトコルを通じて Alibaba Cloud Skills Hub のリモート Agent に接続・呼び出し、リアルタイムストリーミング表示
- **自動依存関係セットアップ**：プラグイン起動時に `iac-code` と Alibaba Cloud CLI を自動インストール

## Alibaba Cloud Skills リモート Agent 統合

CloudPaw は **A2A（Agent-to-Agent）プロトコル** を通じて **Alibaba Cloud Skills Hub** のリモート Agent に接続・呼び出しが可能で、クロス Agent 協調を実現します。

> **注意**：A2A 機能は現在 CloudPaw プラグイン内でのみサポートされ、Alibaba Cloud Skills Hub にホストされている Agent に限定されます。他の A2A Agent への接続は互換性の問題が発生する可能性があります。

### 使用方法

CloudPaw はリモート A2A Agent を呼び出す **2つの方法** を提供します。両方とも LLM により処理され、`a2a_call` ツールを通じて実行されます：

#### 方法 1：`/a2a` コマンドによるクイックコール

チャットボックスで `/a2a` コマンドを使用してリモート Agent にメッセージを送信：

```
/a2a <エイリアス> <メッセージ>
```

例：

```
/a2a my-agent Node.js アプリを ECS にデプロイするにはどうすればいいですか？
```

コマンドは LLM が理解できる指示に自動変換され、`a2a_call` ツールが呼び出されます。

#### 方法 2：自然言語による呼び出し

自然言語でニーズを説明するだけで、LLM が自動的にリモート Agent を呼び出すべきかを判断し、`a2a_call` ツールを通じて実行します：

```
my-agent に Flask アプリを Alibaba Cloud に素早くデプロイする方法を聞いてください
```

このモードでは、LLM がユーザーの意図を理解し、適切なリモート Agent を自動的に選択します。マルチターン会話やコンテキストが必要なシナリオに最適です。

#### 登録済み Agent の一覧表示

引数なしで `/a2a` と入力すると、すべての登録済みリモート A2A Agent とその接続状態が一覧表示されます。インストール済みスキルを表示する `/skills` コマンドと同様です。

### 注意事項

- A2A 機能は現在 CloudPaw プラグイン内でのみサポートされ、Alibaba Cloud Skills Hub にホストされている Agent に限定されます。他の A2A Agent への接続は互換性の問題が発生する可能性があります。
- リモート Agent を呼び出す際、メッセージ内容はリモートサーバーに送信されます — データセキュリティにご注意ください
- 同時にアクティブにできる A2A コールは 1 つのみです

## マルチ Agent アーキテクチャ

CloudPaw は QwenPaw の **Mission Mode** を通じてマルチ Agent 協調を実現します。ユーザーはマスター Agent と対話し、マスター Agent が自動的に要件を PRD（製品要求仕様書）に分解し、ストーリー優先度に基づいて専門サブ Agent にタスクを委任します。

| Agent | 責任 |
|---|---|
| **CloudPaw-Master** | オーケストレーション：ユーザー対話、要件明確化、PRD 生成、タスク委任、結果集約 |
| **CloudPaw-Executor** | 汎用実行：コード作成、アプリデプロイ、環境設定、CLI 操作 |
| **CloudPaw-Verifier** | 統合検証：クラウドリソース状態、アプリ機能、アクセシビリティ、セキュリティコンプライアンス |
| **iac-code**（外部 ACP Agent） | IaC エンジン：ACP プロトコルを通じて非同期呼び出し、ROS/Terraform テンプレート生成、コスト見積もり、スタック管理 |

## 使用例

**個人ホームページをクラウドにデプロイ**

> 個人ホームページを作成してクラウドにデプロイしてください。ページには自己紹介、スキル、プロジェクト経験、連絡先情報を含め、個人情報はすべてプレースホルダーを使用してください。スタイルはクリーンでミニマル、モバイルとデスクトップにレスポンシブ対応にしてください。Alibaba Cloud ECS を使用してデプロイしてください。

**API サービスをクラウドに迅速に公開**

> API サービスをクラウドに素早くデプロイしてください。デフォルトで /health と /hello のエンドポイントを提供し、呼び出し可能な URL とリクエスト例を教えてください。設定はできるだけシンプルで分かりやすくしてください。

## 謝辞

- [iac-code](https://github.com/aliyun/iac-code) — Alibaba Cloud 向け AI Infrastructure as Code アシスタント
