<p align="center">
  <img src="logo.png" alt="DataPaw" width="320">
</p>

<p align="center">
  <strong>QwenPaw 向けデータ分析プラグイン</strong>
</p>

<p align="center">
  <a href="#"><img src="https://img.shields.io/badge/License-Apache%202.0-blue.svg" alt="License" /></a>
  <a href="https://www.python.org/downloads/"><img src="https://img.shields.io/badge/Python-3.10%2B-blue.svg" alt="Python" /></a>
  <a href="#"><img src="https://img.shields.io/badge/version-0.1.0-green.svg" alt="Version" /></a>
</p>

<p align="center">
  <a href="README.md">English</a> | <a href="README_zh.md">中文</a> | <b>日本語</b> | <a href="README_ru.md">Русский</a>
</p>

---

DataPaw は QwenPaw 向けのデータ分析プラグインです。**12 個の BI 系 agent skill**（異常検知、ディメンション drilldown、要因分解、時間要因寄与、適応閾値、HTML レポート生成、それらをつなぐプランニング / ルーティング skill）を同梱しており、agent はローカルファイルに対して BI 課題をエンドツーエンドで進められます：ロード → クレンジング → 分析 → drilldown → レポート出力。

主な利用シーン：

- **多段階の BI 分析** —— 各ステップに合った skill を agent が自動で選び、最後に構造化されたレポートを出力します。
- **指標の異常要因分析** —— 指標に変動があった際、適応閾値 → 異常検知 → 時間要因分解 → ディメンション drilldown が同梱 skill として連続実行され、HTML レポートで完結します。
- **ローカルファイルワークフロー** —— CSV / Excel / Parquet をチャットでアップロード、絶対パスを貼り付け、または agent workspace に直接配置の 3 通りで投入できます。分析は `execute_shell_command` で一気通貫に走ります。

内部的には、多段階分析は必ず **DAG タスクグラフ**として構造化されます。各ステップは名前付きノードで、agent が 1 ノードずつ進め、進捗は session に永続化されるため、いつでも中断・再開が可能です。DAG 状態は SSE で観測でき、REST API で編集できます。**タスクパネル フロントエンド**（DAG 可視化 + ノード編集 UI）は同じプラグイン内で開発中です —— 下記 [フロントエンド ロードマップ](#フロントエンド-ロードマップ)を参照してください。

DataPaw はあなたの環境内で完結して動作します。データは外部に出ません。

## クイックスタート

### 前提条件

| 項目 | 要件 |
|---|---|
| **QwenPaw バージョン** | **≥ v1.1.7** |
| **Python** | 3.10 ~ 3.13 |
| **LLM プロバイダ** | QwenPaw 側で設定済み（DataPaw はアクティブモデルを継承） |

> QwenPaw が v1.1.7 未満の場合はアップグレードしてください：`pip install --upgrade "qwenpaw>=1.1.7"`。

### 1. DataPaw プラグインをインストール

**Console 経由（推奨）：**

1. QwenPaw を起動（`qwenpaw app`）し、http://127.0.0.1:8088/ を開きます。
2. 左サイドバーの Settings 配下にある「Plugin Manager」をクリックし、「Install Plugin」を選択。
3. `datapaw/` フォルダをインストールダイアログにドラッグするか、ZIP ファイルを選択します（DataPaw は QwenPaw の `plugins/bundle/datapaw/` に同梱されています）。
4. インストール完了を待ちます。

**CLI 経由：**

```bash
qwenpaw plugin install /path/to/datapaw
```

> インストール後、ブラウザを強制リフレッシュ（`Cmd+Shift+R` / `Ctrl+Shift+R`）し、agent ドロップダウンに新しい「DataPaw」項目を反映させてください。

### 2. 設定

#### LLM モデル

console の **Settings → Models** で LLM プロバイダと API キーを設定します。DataPaw はアクティブモデルをそのまま継承するため、個別の設定は不要です。[QwenPaw Models ドキュメント](https://qwenpaw.agentscope.io/docs/models)を参照してください。

#### データの渡し方

DataPaw はデータ取得ツールを同梱していません。データを分析に渡す方法は便利な順に 3 つあります：

- **チャットでファイルをアップロード** —— console のファイルアップロードは agent workspace の `media/` / `file_store/` 配下に置かれ、agent から直接読み取れます。
- **絶対パスを貼り付け** —— メッセージ内にパスを書きます（例：`/Users/me/Downloads/data.csv`）。agent が `read_file` / `execute_shell_command` 経由で開きます。
- **workspace にファイルを配置** —— CSV / Excel / Parquet を `~/.qwenpaw/workspaces/datapaw/` に直接コピーし、相対パスで参照します。

分析の中間データ、チャート、レポートはすべて `~/.qwenpaw/workspaces/datapaw/artifacts/<session_id>/<graph_id>/<node_id>/` 配下に集約されます。詳細は下記 [Artifact レイアウト](#artifact-レイアウト)を参照してください。

### 3. 使ってみる

チャットページの agent ドロップダウンから **DataPaw** を選び、次のようなリクエストを試してください：

```
2025 年 12 月の商品 X の日別アクセストレンドを分析し、HTML レポートを出力してください。
```

期待される動作：

- agent が `analysis-plan-builder` を呼んで分析プランを起こします。
- agent はプランを 1 ノードずつ進めます：各ノードは `pending → ready → in_progress → done` の順に遷移します。
- 最終ノードが `bi-report-generation` を呼び、artifacts ルート配下に HTML ファイルを生成します。

## 同梱 Skills

DataPaw の価値は同梱の skill 群にあります。12 個すべてが起動時に agent workspace に自動インストールされ、有効化されます。

### フロー skill（つなぎ役）

| Skill | agent が呼ぶタイミング |
|---|---|
| `data-intent-router` | ユーザーの各ターン冒頭でリクエストを分類し、対応するパイプラインへルーティング。 |
| `analysis-plan-builder` | オープンエンドな分析要求を、確認可能な構造化プランに変換。 |
| `runtime-guide` | 実行時の作法：再利用、エラーハンドリング、プラン途中修正、自己チェック。 |

### 分析 skill

| Skill | 機能 |
|---|---|
| `bi-metric-analysis` | 単一指標 / スコープのエンドツーエンドパイプライン：指標観測 + 異常検知 + ディメンション drilldown。 |
| `bi-anomaly-detection` | 時系列データに対する閾値ベースの異常点検出。 |
| `bi-adaptive-threshold` | データ自身の自然変動から異常 / 影響度の閾値を導出（ハードコーディング不要）。 |
| `bi-attribution-analysis` | 指標変動に対するディメンション別寄与度。加算型と加重平均型の両指標に対応。 |
| `bi-dimension-drilldown` | 階層的 drilldown により、変動を駆動するディメンションを特定。 |
| `bi-time-impact-attribution` | 期間比較の変動を構造変動 / トレンド変動 / イベント影響に分解。 |
| `bi-new-dimension-analysis` | 新規出現のディメンション値（新チャネル / SKU / 機能など）を検出し、影響を評価。 |
| `bi-semantic-layer-guide` | 指標 / ディメンションのセマンティック層が用意されている場合の利用作法。 |

### レポート

| Skill | 機能 |
|---|---|
| `bi-report-generation` | 分析結論と artifact をまとめ、読みやすい HTML レポートを生成。 |

各 skill は `SKILL.md`（モデルカード）に加え、必要に応じて補助スクリプトと参考ドキュメントを `skills/<name>/` 配下に同梱しています。SKILL.md は agent がオンデマンドで読み取るため、ユーザー側で操作する必要はありません。

## 利用例

**日次トレンド分析 + HTML レポート**

> 2025 年 12 月の商品 X の日別アクセストレンドを分析し、異常検知と下落要因分析を行い、HTML レポートを出力してください。

DataPaw はまず `analysis-plan-builder` で DAG を計画し、依存順に `bi-anomaly-detection` → `bi-attribution-analysis` → `bi-report-generation` を駆動し、最終的に artifacts ルート配下に `report.html` を生成します。

**ワンショットの簡単な質問**

> `sessions.csv` のセッション時間の中央値はいくつですか？

十分に単純な問いの場合、DataPaw は `create_plan` をスキップし、`execute_shell_command` で直接計算して回答します。

## フロントエンド ロードマップ

本リリースは DataPaw プラグインの **backend** のみを含みます：agent、skills、DAG タスクグラフ、REST API、SSE イベント。

**DataPaw フロントエンド** —— DAG 可視化、ノードクリックでの編集、パネル内ファイルプレビュー、fetch_data 結果のレンダリング —— は、同じプラグインの一部として鋭意開発中です。後続バージョンで `plugins/bundle/datapaw/` から backend と一緒に公開予定です。

フロントエンドが揃うまでは、チャット agent 経由で DataPaw を完全に利用できます。DAG 状態と artifact は、下記の SSE イベントストリームと REST エンドポイントから観測可能です。

## タスクグラフと API

多段階分析は DAG として構造化され、session に永続化され、REST + SSE で観測可能です。

### REST エンドポイント（`/api/tasks/...` にマウント）

| Method | Path | 用途 |
|---|---|---|
| `GET`  | `/{session_id}` | 現在の DAG + 履歴サマリ + artifact サマリ |
| `GET`  | `/{session_id}/dag` | アクティブなグラフの完全な DAG |
| `GET`  | `/{session_id}/sop` | 現在のグラフを YAML 出力 |
| `PUT`  | `/{session_id}/sop` | 新規 SOP YAML をアップロード（agent へ `[sop_replaced]` 通知をキュー） |
| `PUT`  | `/{session_id}/dag` | DAG をパッチ（`[dag_merged]` 通知をキュー） |
| `GET`  | `/{session_id}/history/{plan_id}` | アーカイブ済みグラフを参照 |
| `GET`  | `/{session_id}/files{,/preview,/download}` | artifact の一覧 / プレビュー / ダウンロード |

書き込みエンドポイントは `_check_not_running` により agent 実行中の競合書き込みをブロックします。スキーマは `core/routers/tasks.py` を参照してください。

## アーキテクチャ

DataPaw は QwenPaw のプラグインシステム経由で統合されます。host ソースは一切変更せず、すべて起動時に挿入されます。

```
plugins/bundle/datapaw/
├── plugin.json                # manifest
├── plugin.py                  # backend エントリ：startup / shutdown フック登録
├── constants.py               # 共有定数 + sys.path ブートストラップ
├── agents_setup.py            # 内蔵 agent プロファイル + workspace + skills を書き込む
├── hooks.py                   # ランタイム patch：smart agent factory、channel SSE、unload クリーンアップ
├── prompts/MASTER.md          # ランタイム機構プロンプト（DAG / plan ツール / artifact ルール）
├── agents/datapaw/{zh,en}/    # 言語別 SOUL.md + PROFILE.md
├── skills/                    # 12 個の同梱 BI skill
└── core/                      # 中核実装
    ├── agents/base.py         # DataPawAgent（QwenPawAgent を継承）
    ├── orchestration/         # TaskGraph / RuntimeStateManager / hint / events
    ├── routers/tasks.py       # /api/tasks/* ルータ
    └── path_context.py        # サンドボックス視点 ↔ host パスの変換層
```

システムプロンプトは 3 層構成で組み立てられます：

1. host 標準の `AGENTS.md` / `SOUL.md` / `PROFILE.md`（host の per-agent プロンプト規約）。
2. プラグインの `MASTER.md` —— DAG ランタイムルールと plan ツール説明を host 三点セットの後に追加。
3. 動的な `<datapaw-analysis-environment>` ヒント。現在のリクエストの workspace パス、artifacts ルート、実行作法を提示。

## Artifact レイアウト

すべての分析出力は agent workspace 配下に、session / graph / node の 3 層で分離されます：

```
~/.qwenpaw/workspaces/datapaw/artifacts/
└── <session_id>/
    └── <graph_id>/
        └── <node_id>/
            ├── data.csv
            ├── chart.png
            └── report.html
```

`finish_subtask(files=...)` には相対パス（`artifacts/` プレフィックスなし）を渡し、ランタイムが `PathContext.resolve_artifact_path` 経由で host 絶対パスに解決します。

## 謝辞

- [QwenPaw](https://github.com/agentscope-ai/QwenPaw) と [agentscope](https://github.com/modelscope/agentscope) を基盤としています。
