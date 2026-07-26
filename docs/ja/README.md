<!-- Language: [English](../en/README.md) · [한국어](../ko/README.md) · **日本語** -->

# AV 3.0 Blueprint Lab — ドキュメント (日本語)

**言語:** [English](../en/README.md) · [한국어](../ko/README.md) · **日本語**

このディレクトリには AV 3.0 Blueprint Lab の日本語ドキュメント一式が含まれます。
プロジェクトの概要と最短のインストール手順は
[リポジトリの README](../../README.md) から始めてください。

## 12 個のモジュール

本ラボは、NVIDIA + AWS の **Physical AI データパイプライン**を 12 個の SageMaker
Studio ノートブック（M0–M11）で実践するハンズオンです：

| モジュール | 内容 | インスタンス |
|---|---|---|
| **M0** | パイプライン概要 — 全体パイプラインを各モジュールに対応づけ（計算なし） | CPU `t3.medium` |
| **M1** | データ探索 — 実際の **nuScenes-mini** センサーデータの取り込みと探索、シーン選択 | CPU `t3.medium` |
| **M2** | Cosmos Reason キャプション — サンプルクリップの VLM キャプション | GPU `g5.12xlarge` |
| **M3** | Cosmos Curator — **NeMo Curator** による動画キュレーション（分割・変換・フィルタ・重複除去） | GPU `g5.12xlarge` |
| **M4** | Cosmos Transfer — 実クリップの天候・条件オーグメンテーション | GPU（`g6.24xlarge` で検証済み） |
| **M5** | Cosmos Predict — 合成シナリオ（video2world）生成 | GPU |
| **M6** | Alpamayo VLA — **Alpamayo-1.5-10B** による視覚-言語-行動推論と軌道予測 | GPU |
| **M7** | AlpaSim クローズドループ評価 — 本物のクローズドループ方策評価結果を可視化 | CPU `t3.medium`（+ GPU EC2） |
| **M8** | OpenSearch セマンティック検索 — キャプション埋め込みに対する k-NN 検索 | CPU `t3.medium` |
| **M9** | HyperPod 分散学習 — 実際の 2 ノード `torch.distributed` DDP ジョブ | CPU `t3.medium`（+ ジョブノード） |
| **M10** | Nerfstudio 3D 再構成 — NeRF / 3D Gaussian Splatting（オプション/デモ） | GPU `g5.xlarge` |
| **M11** | パイプライン自動化 — 実際の SageMaker Pipeline（Caption→Curate→Augment） | CPU `t3.medium`（+ 処理ジョブ） |

推奨経路：**M0 → M1 → M2 → M3**、その後は合成データ（M4/M5）、方策+シミュレーション
（M6/M7）、検索（M8）、本番パターン（M9/M11）へ分岐。

## 読む順番

**ラボをセットアップする管理者の場合:**
1. [PREREQUISITES.md](PREREQUISITES.md) — アカウント、トークン、クォータ、ゲート付きライセンス。
2. [ADMIN_GUIDE.md](ADMIN_GUIDE.md) — 日程ごとのセットアップ手順（デプロイ、データ/モデル
   のステージング、参加者プロビジョニング、監視、後片付け）。
3. [DATA_CONTRACT.md](DATA_CONTRACT.md) — モジュール間の S3 データコントラクト（リファレンス）。

**参加者の場合:**
1. [PRE_LEARNING_GUIDE.md](PRE_LEARNING_GUIDE.md) — イベント前に読む概念。
2. [PARTICIPANT_GUIDE.md](PARTICIPANT_GUIDE.md) — 当日のクリック単位の手順。

**モジュール別の詳細:**
- [COSMOS_M4_M5.md](COSMOS_M4_M5.md) — Cosmos Transfer（M4）& Predict（M5）。
- [ALPAMAYO_M6.md](ALPAMAYO_M6.md) — Alpamayo VLA（M6）。
- [ALPASIM_M7.md](ALPASIM_M7.md) — AlpaSim クローズドループ評価（M7）。
- [HYPERPOD_M9.md](HYPERPOD_M9.md) — 分散学習（M9）。
- [PIPELINE_M11.md](PIPELINE_M11.md) — SageMaker Pipelines（M11）。

**M7 GPU / SSM 手順（上級）:**
- [M7_MANUAL_TEST_RUNBOOK.md](M7_MANUAL_TEST_RUNBOOK.md) — 管理者：GPU EC2 ホストで
  本物の AlpaSim リファレンス評価を実行。
- [M7_PARTICIPANT_SSM_RUNBOOK.md](M7_PARTICIPANT_SSM_RUNBOOK.md) — 参加者：SSM 経由で
  本物の AlpaSim を自分で実行するオプション経路。
