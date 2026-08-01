<!-- Language: [English](../en/README.md) · [한국어](../ko/README.md) · **日本語** -->

# AV 3.0 Blueprint Lab

**ドキュメント言語:** [English](../en/README.md) · [한국어](../ko/README.md) · **日本語**

[Building an End-to-End Physical AI Data Pipeline for Autonomous Vehicle 3.0 on AWS with NVIDIA](https://aws.amazon.com/blogs/industries/building-an-end-to-end-physical-ai-data-pipeline-for-autonomous-vehicle-3-0-on-aws-with-nvidia/) をハンズオンで実行するための、セルフサービス型 AWS プラットフォームです。参加者は **12 個の Jupyter ノートブックモジュール（M0〜M11）**に取り組み、自動運転車データパイプラインの全体像 — データ探索、動画キャプション生成（Cosmos Reason）、データキュレーション（Cosmos Curator）、合成データ拡張（Cosmos Transfer & Predict）、Vision-Language-Action 推論（Alpamayo）、クローズドループシミュレーション（AlpaSim）、セマンティック検索、分散学習、3D 再構成、本番パイプライン自動化 — を通して学びます。

このプラットフォームは、管理者ダッシュボードと参加者ダッシュボード、マルチユーザー SageMaker Studio のプロビジョニング、自動コスト管理を備えた**単一の AWS CDK スタック**としてデプロイされます。誰でも**自分自身の AWS アカウント**にデプロイできます。

> このリポジトリが提供するのは**ワークショップのコードとドキュメントのみ**です。サードパーティのモデルおよびデータセット（NVIDIA Cosmos/Alpamayo、nuScenes、NuRec）をオーケストレーションしますが、それらはご自身で**各自のライセンス**に従ってダウンロードするものであり、一部は**商用利用不可**です。[NOTICE](../../NOTICE) を参照してください。

---

## 12 のモジュール

| モジュール | 内容 | 推奨インスタンス |
|---|---|---|
| **M0** | パイプライン概要 — エンドツーエンドのパイプラインを各モジュールにマッピング（コンピュートなし） | `ml.t3.medium`（CPU） |
| **M1** | データ探索 — 実際の **nuScenes-mini** センサーデータの取り込みと探索、シーンの選択 | `ml.t3.medium`（CPU） |
| **M2** | Cosmos Reason キャプション生成 — サンプリングしたクリップの VLM キャプション | `ml.g5.12xlarge`（GPU） |
| **M3** | Cosmos Curator — **NeMo Curator** による動画キュレーション（分割、トランスコード、フィルタ、重複排除） | `ml.g5.12xlarge`（GPU） |
| **M4** | Cosmos Transfer — 実クリップの天候・条件拡張 | GPU（`ml.g6.24xlarge` で検証済み） |
| **M5** | Cosmos Predict — 合成シナリオ（video2world）生成 | GPU（`ml.g6.24xlarge` で検証済み） |
| **M6** | Alpamayo VLA — **Alpamayo-1.5-10B** による Vision-Language-Action 推論 + 軌道生成 | GPU（`ml.g6.24xlarge` で検証済み） |
| **M7** | AlpaSim クローズドループ評価 — 本物のクローズドループポリシー評価を可視化 | `ml.t3.medium`（CPU）+ GPU EC2 |
| **M8** | OpenSearch セマンティック検索 — キャプション埋め込みに対する k-NN 検索 | `ml.t3.medium`（CPU） |
| **M9** | HyperPod 分散学習 — 本物の 2 ノード `torch.distributed` DDP ジョブ | `ml.t3.medium`（CPU）+ ジョブノード |
| **M10** | Nerfstudio 3D 再構成 — NeRF / 3D Gaussian Splatting（オプション/デモ） | `ml.g5.xlarge`（GPU） |
| **M11** | パイプライン自動化 — 本物の SageMaker Pipeline（Caption→Curate→Augment） | `ml.t3.medium`（CPU）+ 処理ジョブ |

推奨の進め方: **M0 → M1 → M2 → M3** の順に進み、その後は合成データ（M4/M5）、ポリシー + シミュレーション（M6/M7）、検索（M8）、本番パターン（M9/M11）へと分岐します。表示されているインスタンスはダッシュボードのデフォルト値であり、各 GPU モジュールには代替インスタンスも用意されています（例: `ml.g5.12xlarge` のキャパシティが不足している場合の `ml.g6.12xlarge`）。

上記の AWS ブログ記事で説明されている **8 ステージのパイプライン**に各モジュールがどう対応するかは、[参加者向け事前学習ガイド § 2「8 ステージのパイプライン（とモジュールの対応関係）」](PRE_LEARNING_GUIDE.md#the-8-stage-pipeline)を参照してください。

---

## インストール前のプレビュー

デプロイする前に、このラボが何を生成するのか見てみたいですか？

**実行済みノートブックの結果。** [`examples/notebooks-with-outputs.tar.gz`](../../examples/notebooks-with-outputs.tar.gz) には、12 個のモジュールノートブック（M0〜M11）が実際の実行後の**出力セル付き**で含まれています — グラフ、生成された動画のメタデータ、メトリクス、ログ。ダウンロードして任意の Jupyter ビューアーで開けば、**インストールも実行もせずに**各モジュールの実際の結果を確認できます。（アカウント固有の識別子はプレースホルダーに置き換えてあります。）

---

## どのドキュメントを読むべきか

完全なガイドは **`docs/<lang>/`** 配下に **English / 한국어 / 日本語** で用意されています（以下のリンクはこの言語ディレクトリ内のドキュメントを指します。ページ上部の言語スイッチャーで言語を切り替えられます）:

| あなたは… | 読むもの（順番に） |
|---|---|
| **管理者 — ラボのセットアップ** | [PREREQUISITES](PREREQUISITES.md) → [ADMIN_GUIDE](ADMIN_GUIDE.md) → [DATA_CONTRACT](DATA_CONTRACT.md) |
| **参加者** | [PRE_LEARNING_GUIDE](PRE_LEARNING_GUIDE.md) → [PARTICIPANT_GUIDE](PARTICIPANT_GUIDE.md) |
| **モジュール別の詳細解説** | [COSMOS_M4_M5](COSMOS_M4_M5.md) · [ALPAMAYO_M6](ALPAMAYO_M6.md) · [ALPASIM_M7](ALPASIM_M7.md) · [HYPERPOD_M9](HYPERPOD_M9.md) · [PIPELINE_M11](PIPELINE_M11.md) |
| **M7 GPU / SSM（応用）** | [M7_MANUAL_TEST_RUNBOOK](M7_MANUAL_TEST_RUNBOOK.md)（管理者向け） · [M7_PARTICIPANT_SSM_RUNBOOK](M7_PARTICIPANT_SSM_RUNBOOK.md)（参加者向け） |

---

## 前提条件

| 要件 | バージョン | 備考 |
|---|---|---|
| AWS アカウント | — | SageMaker、S3、DynamoDB、Cognito、CloudFront へのアクセス権を持つこと |
| AWS CLI | v2.x | 設定済みであること（`aws sts get-caller-identity`） |
| Node.js | 18+ | CDK CLI + フロントエンドビルド |
| Python | 3.12+ | CDK インフラストラクチャコード |
| AWS CDK | 2.x | `npm install -g aws-cdk` |
| jq | — | デプロイスクリプト内での JSON パース |
| Hugging Face トークン | — | **管理者のみ** — ゲート付きモデル（M2/M4/M5/M6）を事前キャッシュし、M7 のリファレンス評価を実行します。**参加者に HF トークンは不要です。** [docs/ja/PREREQUISITES.md](PREREQUISITES.md) を参照してください。 |
| NGC API キー | — | **管理者のみ、M7 のみ** — AlpaSim NuRec レンダラーイメージ用。 |

### サービスクォータ（早めに申請 — 24〜48 時間のリードタイム）

GPU **Studio JupyterLab App** のクォータは、新規アカウントではデフォルトで低い値または **0** になっています。ワークショップの前に増加申請してください。M9/M11 用には別途**ジョブ**クォータもあり、見落としがちなので注意してください。完全な表と CLI コマンドは **[docs/ja/ADMIN_GUIDE.md](ADMIN_GUIDE.md)** および **[docs/ja/PREREQUISITES.md](PREREQUISITES.md)** にあります。

現在の値を確認する:
```bash
aws service-quotas list-service-quotas \
  --service-code sagemaker --region "${AWS_REGION:-us-west-2}" \
  --query 'Quotas[?contains(QuotaName, `Studio JupyterLab Apps`) || contains(QuotaName, `for training job`) || contains(QuotaName, `for processing job`)].{Name:QuotaName,Value:Value,Code:QuotaCode}' \
  --output table
```

---

## クイックスタート

すべてのコマンドは、アカウントとリージョンを環境から導出します。ハードコードされている値はありません。

```bash
# 1. クローン
git clone <repository-url> av3.0-blueprint-lab
cd av3.0-blueprint-lab

# 2. 必須の環境変数
export ADMIN_EMAIL="<admin-email>"           # 例: you@example.com
export AWS_REGION="us-west-2"                 # デフォルト。「リージョンの選択」を参照
export HF_TOKEN="hf_..."                      # 管理者の Hugging Face 読み取りトークン
# 任意だが推奨: 管理者ダッシュボードへのアクセスを自分の IP/CIDR に制限する
export ADMIN_IP_ALLOWLIST="203.0.113.0/24"    # デフォルト 0.0.0.0/0 = WAF は全開放

# 2b. Hugging Face 上でゲート付きモデル/データセットのライセンスに同意する（ステップ 6 の前に）。
#     huggingface.co にログインし、各ゲート付きリポジトリで "Agree and access repository" を
#     クリックする — 完全なリストは docs/ja/PREREQUISITES.md にあります。

# 3. CDK のブートストラップ（アカウント + リージョンごとに 1 回）
cd infra && python3 -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt
npx cdk bootstrap "aws://$(aws sts get-caller-identity --query Account --output text)/$AWS_REGION"
cd ..

# 4. インフラストラクチャ + ダッシュボードのデプロイ（約 25 分）
./scripts/deploy.sh

# 5. 最初の Cognito 管理者ユーザーを作成
#    （deploy.sh が、あなたのプール ID を含む正確なコマンドを出力します。ユーザー名は必ずメールアドレスにすること）
aws cognito-idp admin-create-user \
    --user-pool-id <cognito-pool-id> \
    --username "$ADMIN_EMAIL" \
    --user-attributes Name=email,Value="$ADMIN_EMAIL" Name=email_verified,Value=true \
    --temporary-password 'TempPass1!' \
    --region "$AWS_REGION"

# 6. NVIDIA モデルを S3 に事前キャッシュ（バックグラウンド、30〜60 分）
./scripts/cache_models.sh
#    M4/M5/M6 は追加でオフライン HF キャッシュが、M6 はデモクリップが、M7 は
#    一度きりの GPU-EC2 リファレンス評価が必要です — docs/ja/ADMIN_GUIDE.md §6 および
#    モジュール別の詳細解説（COSMOS_M4_M5、ALPAMAYO_M6、ALPASIM_M7）を参照してください。

# 7. nuScenes-mini データセットを S3 にステージング（M1 / M3 / M10 で必須）
./scripts/stage_nuscenes.sh
#    公開の AWS Open Data ミラーから取得します（ログイン不要。nuScenes の利用規約が適用されます）。

# 8. ノートブックテンプレート + ヘルパースクリプトを共有バケットにアップロード
ACCOUNT=$(aws sts get-caller-identity --query Account --output text)
aws s3 sync notebooks/ "s3://av30lab-shared-data-$ACCOUNT/notebook-templates/" --region "$AWS_REGION"
aws s3 sync scripts/   "s3://av30lab-shared-data-$ACCOUNT/notebook-templates/scripts/" --region "$AWS_REGION"
```

その後、`deploy.sh` が出力した **Admin Dashboard URL** を開き、ステップ 5 のメールアドレス + 仮パスワードでログインし、テストユーザーをプロビジョニングして、**Participant Dashboard Link** を開いてパイプラインマップを確認します。日ごとの完全なランブック — スモークテスト、一括プロビジョニング、モニタリング、撤去 — は **[docs/ja/ADMIN_GUIDE.md](ADMIN_GUIDE.md)** にあります。

---

## アーキテクチャ

```
        CloudFront (2x)  ─────────  Admin Dashboard  |  User Dashboard
              │                              │
        S3 static (admin)               S3 static (user)
              │
        API Gateway + Lambda  ── create_user, delete_user, bulk_provision,
              │                    list_sessions, terminate_session,
              │                    change_instance, get_costs, update_progress, …
   ┌──────────┼───────────────────────────────┐
 Cognito   DynamoDB                    SageMaker Studio Domain
 (auth)    (sessions,                  └─ per-user profile + JupyterLab space
            progress)                        │
                                       S3 shared-data bucket
                                        (model-cache / datasets / hf-cache /
                                         notebook-templates / m7-reference)
```

- **ネットワーク:** プライベートサブネット、NAT Gateway、S3/SageMaker 用の VPC エンドポイントを備えた VPC。
- **ストレージ:** KMS 暗号化 S3（共有データ + ユーザーごとのワークスペース）、事前キャッシュされたモデル。
- **コンピュート:** 自動セットアップ用のライフサイクル設定を持つ SageMaker Studio ドメイン。
- **認証:** 管理プレーン用のオプションの **WAF IP 許可リスト**を備えた Cognito ユーザープール。
- **API:** ユーザー管理、セッション、進捗管理のための Lambda ベースの REST API。
- **モニタリング:** CloudWatch アラーム、SNS 通知、日次の予算アラート。
- **フロントエンド:** CloudFront 上の React SPA（管理者ダッシュボード + ユーザーパイプラインマップ）。

---

## プロジェクト構成

```
av3.0-blueprint-lab/
├── infra/                  # AWS CDK app (Python): stack, constructs, Lambdas
│   ├── app.py  cdk.json  requirements.txt
│   ├── stacks/av30_stack.py
│   ├── av30_constructs/    # network, storage, database, sagemaker, auth, api, dashboards, monitoring
│   └── lambda/             # create_user, delete_user, bulk_provision, change_instance, get_costs, update_progress, …
├── notebooks/              # 12 workshop notebooks M0–M11
├── web/
│   ├── admin/              # Admin dashboard (React + Vite)
│   └── user/               # Participant pipeline map (React + Vite)
├── scripts/                # deploy.sh, teardown.sh, cache_models.sh, stage_nuscenes.sh,
│                           # setup_*.sh, alpasim_ec2_setup.sh, grab_gpu_instance.py, …
├── docs/{en,ko,ja}/        # Full trilingual documentation set
├── LICENSE                 # MIT-0 (workshop code)
├── NOTICE                  # third-party model/dataset licenses (incl. non-commercial)
└── README.md               # this file
```

---

## コストとクリーンアップ

| シナリオ | コスト | 備考 |
|---|---|---|
| アイドル状態（インフラのみ） | 約 $80/月 | NAT Gateway、VPC エンドポイント、DynamoDB、CloudFront |
| GPU モジュール | 時間課金 | `ml.g5.xlarge` 約 $1.41/時（M10）、`ml.g5.12xlarge` 約 $6.68/時（M2/M3）、`ml.p4d.24xlarge` 約 $37.69/時（M4/M5/M6） |
| M7 AlpaSim（EC2 上） | 約 $30 の一度きり（管理者） | `g6e.12xlarge` でのリファレンス評価。任意で参加者が自身で実行する場合は約 $10.5/時/ホスト |
| 1 週間フル（混在） | 約 $400〜600+ | p4d モジュールとユーザー数が支配的 |

**コスト管理:** 日次予算アラーム（SNS → `<admin-email>`）、Sessions タブからの管理者による強制終了、アイドル状態のアプリのライフサイクルによる自動停止（約 180 分）。**撤去:** `scripts/teardown.sh`（デフォルトはドライラン。`--yes`、`--user <id>`、`--destroy`）は、ユーザーごとのアプリ/スペース/プロファイルを削除し、孤立した OpenSearch Serverless コレクションを一掃し、タグ付けされた GPU EC2 ホストを終了します。イベント終了後は、**管理者の HF トークンを失効させ、NGC キーをローテーション**してください。詳細は [docs/ja/ADMIN_GUIDE.md](ADMIN_GUIDE.md) にあります。

---

## リージョンの選択

デフォルト: **us-west-2（オレゴン）** — GPU キャパシティが最も豊富で、`ml.p5.48xlarge` が利用可能です。デプロイ前に `export AWS_REGION=...` で変更できます。

| リージョン | p4d.24xlarge | p5.48xlarge | g5.12xlarge | 備考 |
|---|---|---|---|---|
| us-west-2（オレゴン） | ✅ | ✅ | ✅ | **デフォルト** |
| us-east-1（バージニア） | ✅ | ✅ | ✅ | 代替 |
| ap-northeast-2（ソウル） | ✅ | ❌ | ✅ | p5 のフォールバックなし |

S3 モデルキャッシュのパスはリージョンローカルです。リージョンを変更した後は `cache_models.sh` を再実行してください。

---

## ライセンス

このリポジトリ内の**ワークショップコード**（CDK インフラ、Lambda、ノートブック、ダッシュボード、スクリプト）は **MIT-0** ライセンスの下で提供されます — [LICENSE](../../LICENSE) を参照してください。

ノートブックがダウンロードする**モデルおよびデータセット**は、そのライセンスの対象**ではなく**、ここでは**再配布されません**。それぞれが独自の規約を保持しています — 特に **Alpamayo-1.5-10B（M6/M7）は商用利用不可（研究/評価目的のみ）**であり、**nuScenes** も商用利用不可です。適用されるすべてのライセンスを確認し、遵守してください。完全なリストは [NOTICE](../../NOTICE) を参照してください。
