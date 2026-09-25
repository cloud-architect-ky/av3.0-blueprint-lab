<!-- Language: [English](../en/README.md) · **한국어** · [日本語](../ja/README.md) -->

# AV 3.0 Blueprint Lab

**문서 언어:** [English](../en/README.md) · **한국어** · [日本語](../ja/README.md)

[NVIDIA와 함께 AWS에서 자율주행 3.0을 위한 End-to-End Physical AI 데이터 파이프라인 구축하기](https://aws.amazon.com/ko/blogs/tech/building-an-end-to-end-physical-ai-data-pipeline-for-autonomous-vehicle-3-0-on-aws-with-nvidia/)를 직접 실행해 볼 수 있는 셀프
서비스 AWS 플랫폼입니다. 참가자는 자율주행 데이터 파이프라인 전체를 다루는
**13개의 Jupyter 노트북 모듈(M0–M12)**을 차례로 진행합니다 — 데이터 탐색,
비디오 캡셔닝(Cosmos Reason), 데이터 큐레이션(Cosmos Curator), 합성 데이터
증강(Cosmos Transfer & Predict), 비전-언어-행동 추론(Alpamayo),
폐루프 시뮬레이션(AlpaSim), 시맨틱 검색, 분산 학습, 3D 재구성, 프로덕션
파이프라인 자동화까지 포함합니다.

이 플랫폼은 관리자 + 참가자 대시보드, 다중 사용자 SageMaker Studio 프로비저닝,
자동 비용 제어를 갖춘 **단일 AWS CDK 스택**으로 배포됩니다. 누구나 **자신의 AWS
계정**에 직접 배포할 수 있습니다.

> 이 저장소는 **워크숍 코드와 문서만** 제공합니다. 여기서는 직접 다운로드해야 하는
> 서드파티 모델 및 데이터셋(NVIDIA Cosmos/Alpamayo, nuScenes, NuRec)을
> 오케스트레이션할 뿐이며, 이들은 **각자의 라이선스** 하에 제공됩니다 — 일부는
> **비상업용**입니다. [NOTICE](../../NOTICE)를 참고하세요.

---

## 13개 모듈 (M0~M12)

| 모듈 | 블로그 스테이지 | 하는 일 | 권장 인스턴스 |
|---|---|---|---|
| **M0** | — | 파이프라인 개요 — 엔드투엔드 파이프라인을 각 모듈에 매핑(컴퓨트 없음) | `ml.t3.medium` (CPU) |
| **M1** | 1–2 | 데이터 탐색 — 실제 **nuScenes-mini** 센서 데이터 수집 및 탐색, 씬 선택 | `ml.t3.medium` (CPU) |
| **M2** | 3 | Cosmos Reason 캡셔닝 — 샘플링된 클립의 VLM 캡션 생성 | `ml.g5.12xlarge` (GPU) |
| **M3** | 3 | Cosmos Curator — **NeMo Curator** 비디오 큐레이션(분할, 트랜스코딩, 모션 필터링) | `ml.g5.12xlarge` (GPU) |
| **M4** | 4 | OpenSearch 시맨틱 검색 — 캡션 임베딩에 대한 k-NN 검색 | `ml.t3.medium` (CPU) |
| **M5** | 5 | Cosmos Transfer — 실제 클립에 날씨/조건 증강 | GPU (`ml.g5.12xlarge`) |
| **M6** | 5 (ext) | Cosmos Predict — 합성 시나리오(video2world) 생성 | GPU (`ml.g5.12xlarge`) |
| **M7** | 6 | Nerfstudio 3D 재구성 — NeRF / 3D Gaussian Splatting(선택/데모) | `ml.g5.xlarge` (GPU) |
| **M8** | 7 | Cosmos Reason LoRA SFT — nuScenes **사람 라벨**로 파라미터 효율 파인튜닝 | GPU (`ml.g5.12xlarge`, 4× 24 GB에서 네이티브 해상도 실측) |
| **M9** | 7 | Alpamayo VLA — **Alpamayo-1.5-10B** 비전-언어-행동 추론 + 궤적 | GPU (`ml.g5.12xlarge`) |
| **M10** | 8 | AlpaSim 폐루프 평가 — 진정한 폐루프 정책 평가 시각화 | `ml.t3.medium` (CPU) + GPU EC2 |
| **M11** | — (ext) | 파이프라인 자동화 — 실제 SageMaker Pipeline(Caption→Curate→Augment) | `ml.t3.medium` (CPU) + 프로세싱 작업 |
| **M12** | — (ext) | HyperPod 분산 학습 — 실제 2노드 `torch.distributed` DDP 작업 | `ml.t3.medium` (CPU) + 작업 노드 |

권장 경로: **M0 → M1 → M2 → M3**, 이후 합성 데이터(M5/M6), 정책 + 시뮬레이션
(M9/M10), 검색(M4), 프로덕션 패턴(M12/M11)으로 분기합니다. 표시된 인스턴스는
대시보드 기본값이며, 각 GPU 모듈은 대안도 제공합니다(예: `ml.g5.12xlarge` 용량이
대시보드는 배포 리전이 판매하는 타입만 제시하며, 쿼터가 0인 타입은 거부합니다).

위 AWS 블로그 글에서 설명하는 **8단계 파이프라인**에 각 모듈이 어떻게 매핑되는지는
[참가자 사전 학습 가이드 § 2 "8단계 파이프라인 (그리고 모듈이 어떻게 매핑되는가)"](PRE_LEARNING_GUIDE.md#the-8-stage-pipeline)를
참고하세요.

---

## 설치 전에 미리 보기

배포하기 전에 이 랩이 무엇을 만들어내는지 미리 보고 싶으신가요?

**실행된 노트북 결과.** [`examples/notebooks-with-outputs.tar.gz`](../../examples/notebooks-with-outputs.tar.gz)에는
12개 모듈 노트북이 실제 실행 후의 **출력 셀과 함께** 담겨 있습니다 — 그래프,
생성된 비디오의 메타데이터, 지표, 로그. 내려받아 아무 Jupyter 뷰어에서 열면 **설치하거나
실행하지 않고도** 각 모듈의 실제 결과를 볼 수 있습니다. (계정 관련 식별자는 자리표시자로
치환되어 있습니다.)

> **이 번들은 블로그 stage 순서로 재번호하기 전의 실행 기록입니다.** 따라서 파일명과
> 출력에 인쇄된 S3 경로는 **이전 번호**를 사용합니다. 인쇄된 경로를 고치면 실행 기록을
> 위조하는 것이 되므로, 캡처된 상태 그대로 두었습니다. 구 → 신: `M4`→M5, `M5`→M6,
> `M6`→M9, `M7`→M10, `M8`→M4, `M9`→M12, `M10`→M7이며 M0–M3과 M11은 그대로입니다.
> 신규 **M8**(Cosmos Reason LoRA SFT)은 아직 실행 기록이 없어 번들에 없습니다.

**관리자 대시보드.** 관리자는 여기서 참가자를 추가하거나 삭제합니다. 각 행의
**Dashboard Link → Copy link**를 누르면 해당 참가자의 개인 대시보드 링크가 복사되어
나눠줄 수 있고, 읽기 전용 **Region** 열에는 그 프로필이 프로비저닝된 리전이 적힙니다 —
Studio 도메인은 리전별로 존재하므로, 이 열이 없으면 리전을 잘못 받은 참가자도 정상으로
보입니다. **Sessions** 탭은 30초마다 갱신되고, **Costs** 탭은 최근 14일간의 일별 비용을
보여줍니다.

![관리자 대시보드](../images/admin-dashboard.png)

**참가자 대시보드.** 각 참가자는 자신의 대시보드를 열어 SageMaker 워크스페이스를 시작하고
노트북을 실행합니다. 파이프라인 맵은 12개 모듈을 INGEST → CURATE → AUGMENT → TRAIN →
VALIDATE 다섯 개 단계 열로 배치하고, 각 모듈을 Completed / In Progress / Locked 로
표시하며, 한 모듈의 출력이 다른 모듈로 들어가는 지점마다 화살표를 그립니다. JupyterLab
워크스페이스 하나가 모든 모듈을 담당하므로, 참가자는 다음 노트북에 필요한
인스턴스(CPU 또는 GPU)로 워크스페이스를 바꿔 시작한 뒤, 워크스페이스를 열어 노트북을
실행합니다.

![참가자 대시보드](../images/participant-dashboard.png)

---

## 어떤 문서를 읽어야 하나

전체 가이드는 **English / 한국어 / 日本語**로 **`docs/<lang>/`** 아래에 있습니다
(아래 링크는 이 언어 디렉터리의 문서입니다. 언어 선택은 페이지 상단의 스위처를
사용하세요):

| 당신은… | 읽을 문서(순서대로) |
|---|---|
| **관리자 — 랩 설정 담당** | [PREREQUISITES](PREREQUISITES.md) → [ADMIN_GUIDE](ADMIN_GUIDE.md) → [DATA_CONTRACT](DATA_CONTRACT.md) |
| **참가자** | [PRE_LEARNING_GUIDE](PRE_LEARNING_GUIDE.md) → [PARTICIPANT_GUIDE](PARTICIPANT_GUIDE.md) |
| **모듈별 심화** | [COSMOS_M5_M6](COSMOS_M5_M6.md) · [ALPAMAYO_M9](ALPAMAYO_M9.md) · [ALPASIM_M10](ALPASIM_M10.md) · [HYPERPOD_M12](HYPERPOD_M12.md) · [PIPELINE_M11](PIPELINE_M11.md) |
| **M10 GPU / SSM(고급)** | [M10_MANUAL_TEST_RUNBOOK](M10_MANUAL_TEST_RUNBOOK.md)(관리자) · [M10_PARTICIPANT_SSM_RUNBOOK](M10_PARTICIPANT_SSM_RUNBOOK.md)(참가자) |

---

## 사전 요구 사항

| 요구 사항 | 버전 | 비고 |
|---|---|---|
| AWS 계정 | — | SageMaker, S3, DynamoDB, Cognito, CloudFront 접근 권한 필요 |
| AWS CLI | v2.x | 구성 완료(`aws sts get-caller-identity`) |
| Node.js | 18+ | CDK CLI + 프런트엔드 빌드 |
| Python | 3.12+ | CDK 인프라 코드 |
| AWS CDK | 2.x | `npm install -g aws-cdk` |
| jq | — | 배포 스크립트의 JSON 파싱 |
| Hugging Face 토큰 | — | **관리자 전용** — 게이트된 모델(M2/M5/M6/M9)을 사전 캐싱하고 M10 레퍼런스 평가를 실행합니다. **참가자에게는 HF 토큰이 필요 없습니다.** [docs/ko/PREREQUISITES.md](PREREQUISITES.md)를 참고하세요. |
| NGC API 키 | — | **관리자 전용, M10 전용** — AlpaSim NuRec 렌더러 이미지용. |

### 서비스 할당량(조기 요청 — 24–48시간 리드 타임)

GPU **Studio JupyterLab App** 할당량은 새 계정에서 기본적으로 낮거나 **0**입니다 —
워크숍 전에 증설을 요청하세요. 또한 M12/M11에는 놓치기 쉬운 별도의 **작업(job)**
할당량이 있습니다. 전체 표 + CLI 명령: **[docs/ko/ADMIN_GUIDE.md](ADMIN_GUIDE.md)**
및 **[docs/ko/PREREQUISITES.md](PREREQUISITES.md)**.

현재 값 확인:
```bash
aws service-quotas list-service-quotas \
  --service-code sagemaker --region "${AWS_REGION:-us-west-2}" \
  --query 'Quotas[?contains(QuotaName, `Studio JupyterLab Apps`) || contains(QuotaName, `for training job`) || contains(QuotaName, `for processing job`)].{Name:QuotaName,Value:Value,Code:QuotaCode}' \
  --output table
```

---

## 빠른 시작

모든 명령은 계정과 리전을 환경에서 가져옵니다 — 하드코딩된 값은 없습니다.

```bash
# 1. 클론
git clone <repository-url> av3.0-blueprint-lab
cd av3.0-blueprint-lab

# 2. 필수 환경 변수
export ADMIN_EMAIL="<admin-email>"           # 예: you@example.com
export REGION="us-west-2"                     # 배포할 단 하나의 리전
export AWS_REGION="$REGION"                   # 아래 시딩 스크립트가 사용
export HF_TOKEN="hf_..."                      # 관리자 Hugging Face 읽기 토큰
# 선택 사항이지만 권장: 관리자 대시보드 접근을 특정 IP/CIDR로 제한
export ADMIN_IP_ALLOWLIST="203.0.113.0/24"    # 기본값 0.0.0.0/0 = WAF 개방

# 2b. Hugging Face에서 게이트된 모델/데이터셋 라이선스에 동의(6단계 전에).
#     huggingface.co에 로그인하여 각 게이트된 리포지토리에서 "Agree and access repository"를
#     클릭하세요 — 전체 목록은 docs/ko/PREREQUISITES.md 참고.

# 3. CDK 부트스트랩(계정 + 리전당 1회)
cd infra && python3 -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt
npx cdk bootstrap "aws://$(aws sts get-caller-identity --query Account --output text)/$REGION"
cd ..

# 3b. 이 리전의 인스턴스 요금표 생성(필수).
#     없으면 Lambda 가 다른 리전 가격을 인용하는 대신 import 시점에 예외를 던지므로,
#     누락 시 인스턴스 관련 엔드포인트가 500 으로 나타납니다.
./scripts/refresh_instance_rates.py --region "$REGION" --merge

# 4. 인프라 + 대시보드 배포(~25분). 리전은 명시적입니다 — 배포 경로 어디에도
#    리터럴 기본값이 없습니다.
./scripts/deploy.sh --region "$REGION"

# 5. 첫 번째 Cognito 관리자 사용자 생성
#    (deploy.sh가 풀 id가 포함된 정확한 명령을 출력합니다; username은 반드시 이메일이어야 함)
aws cognito-idp admin-create-user \
    --user-pool-id <cognito-pool-id> \
    --username "$ADMIN_EMAIL" \
    --user-attributes Name=email,Value="$ADMIN_EMAIL" Name=email_verified,Value=true \
    --temporary-password 'TempPass1!' \
    --region "$REGION"

# 6. NVIDIA 모델을 S3에 사전 캐싱(백그라운드, 30–60분)
AWS_REGION="$REGION" ./scripts/cache_models.sh
#    M5/M6/M9은 추가로 오프라인 HF 캐시가 필요하고, M9은 데모 클립이, M10은
#    일회성 GPU-EC2 레퍼런스 평가가 필요합니다 — docs/ko/ADMIN_GUIDE.md §6 및
#    모듈별 심화 문서(COSMOS_M5_M6, ALPAMAYO_M9, ALPASIM_M10)를 참고하세요.

# 7. nuScenes-mini 데이터셋을 S3에 스테이징(M1 / M3 / M7에서 필요)
AWS_REGION="$REGION" ./scripts/stage_nuscenes.sh
#    공개 AWS Open Data 미러에서 가져옵니다(로그인 불필요; nuScenes 약관 적용).

# 8. 노트북 템플릿 + 헬퍼 스크립트를 공유 버킷에 업로드
ACCOUNT=$(aws sts get-caller-identity --query Account --output text)
aws s3 sync notebooks/ "s3://av30lab-shared-data-$ACCOUNT-$REGION/notebook-templates/" --region "$REGION"
aws s3 sync scripts/   "s3://av30lab-shared-data-$ACCOUNT-$REGION/notebook-templates/scripts/" --region "$REGION"
```

그런 다음 `deploy.sh`가 출력한 **Admin Dashboard URL**을 열어 5단계의 이메일 +
임시 비밀번호로 로그인하고, 테스트 사용자를 프로비저닝한 뒤 **Participant
Dashboard Link**를 열어 파이프라인 맵을 확인하세요. 스모크 테스트, 대량
프로비저닝, 모니터링, 정리(teardown)까지 포함한 일자별 전체 런북은
**[docs/ko/ADMIN_GUIDE.md](ADMIN_GUIDE.md)**에 있습니다.

---

## 아키텍처

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
                                         notebook-templates / m10-reference)
```

- **네트워크:** NAT 없는 VPC — 격리 프라이빗 서브넷 + 무료 S3 *게이트웨이* 엔드포인트.
  **NAT Gateway는 없습니다.** Studio 도메인이 `PublicInternetOnly`이므로 노트북 트래픽은
  SageMaker 관리형 VPC로 나가고, 이 VPC는 EFS/홈 디렉터리 트래픽만 담당합니다. 유료 *인터페이스*
  엔드포인트 6종은 기본 꺼짐입니다(VPC 안에 사용 주체가 없음 — Lambda는 VPC에 붙어 있지 않음).
  도메인을 `VpcOnly`로 바꿀 때 `-c vpc_interface_endpoints=true`로 켜세요.
- **스토리지:** KMS 암호화 S3(공유 데이터 + 사용자별 워크스페이스); 사전 캐싱된 모델.
- **컴퓨트:** 자동 설정을 위한 라이프사이클 구성이 있는 SageMaker Studio Domain.
- **인증:** 관리자 플레인용 선택적 **WAF IP 허용 목록**이 있는 Cognito 사용자 풀.
- **API:** 사용자 관리, 세션, 진행 상황을 위한 Lambda 기반 REST API.
- **모니터링:** CloudWatch 알람, SNS 알림, 일일 예산 경고.
- **프런트엔드:** CloudFront 상의 React SPA(관리자 대시보드 + 사용자 파이프라인 맵).

---

## 프로젝트 구조

```
av3.0-blueprint-lab/
├── infra/                  # AWS CDK app (Python): stack, constructs, Lambdas
│   ├── app.py  cdk.json  requirements.txt
│   ├── stacks/av30_stack.py
│   ├── av30_constructs/    # network, storage, database, sagemaker, auth, api, dashboards, monitoring
│   └── lambda/             # create_user, delete_user, bulk_provision, change_instance, get_costs, update_progress, …
├── notebooks/              # 13 workshop notebooks M0–M12
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

## 비용 & 정리

| 시나리오 | 비용 | 비고 |
|---|---|---|
| 유휴(인프라만) | **리전당 ~$1/월** | KMS 키. S3 게이트웨이 엔드포인트는 무료이고 NAT Gateway는 없습니다. DynamoDB(온디맨드)·CloudFront·Cognito는 유휴 시 ~$0. VPC 인터페이스 엔드포인트 6종을 켤 때만 **리전당 ~$87.60/월**이 추가됩니다(ENI 12개 × $0.01/AZ·시간). 모델 캐시 S3 저장료는 별도(리전당 ~$2/월). |
| GPU 모듈 | 시간당 | `ml.g5.xlarge` ~$1.41/hr (M7), `ml.g5.12xlarge` ~$7.09/hr (M2/M3), `ml.g5.12xlarge`는 M5/M6/M8/M9의 기본값이기도 합니다. 최대 해상도 출력은 GPU당 ≥38 GB가 필요합니다: `ml.g7e.2xlarge` ~$4.20/hr이 가장 저렴한 경로(96 GB 1장 — 기본값보다 저렴하지만 쿼터 기본값 0이며 이 랩에서 미검증), 그 외에는 `ml.p4d.24xlarge` ~$25.25/hr |
| EC2의 M10 AlpaSim | ~$30 일회성(관리자) | `g6e.12xlarge`에서 레퍼런스 평가; 선택적 참가자 자체 실행 시 ~$10.5/hr/호스트 |
| 전체 1주(혼합) | ~$400–600+ | p4d 모듈과 사용자 수가 비용의 대부분을 차지 |

**비용 제어:** 일일 예산 알람(SNS → `<admin-email>`), Sessions 탭에서 관리자
강제 종료, JupyterLab 앱 유휴 자동 중지(기본 90분;
`-c idle_timeout_minutes=<60..180>`). **정리:**
`scripts/teardown.sh`(기본은 드라이런; `--yes`, `--user <id>`, `--destroy`)는
사용자별 앱/스페이스/프로필을 제거하고, 고아 상태의 OpenSearch Serverless
컬렉션을 정리하며, 태그된 GPU EC2 호스트를 종료합니다. 이벤트 후에는 **관리자
HF 토큰을 폐기하고 NGC 키를 교체**하세요. 자세한 내용은
[docs/ko/ADMIN_GUIDE.md](ADMIN_GUIDE.md)에 있습니다.

---

## 리전 선택

리전은 배포마다 `./scripts/deploy.sh --region <region>` 으로 선택합니다 — **한 번에 한 리전**.
나중에 다른 리전을 추가하려면 [docs/en/ADDING_A_REGION.md](../en/ADDING_A_REGION.md) 를 보세요.

GPU 타입을 쓸 수 있는지는 **서로 다른 두 사실**이 결정하는데, 이전 표는 둘을 섞었습니다 —
이 계정은 us-east-1 에서 `ml.p5.48xlarge` 쿼터가 0인데 사용 가능으로 표시했고, 가능한 리전이
3개뿐인 것처럼 보이게 했습니다(실제로 p5 쿼터는 10개 리전에 존재).

1. **그 리전이 Studio-JupyterLab 용으로 판매하는가?** 리전별 실측 생성값 (`$/hr`, `—` = 미판매):

   | 리전 | g5.12xlarge | g5.24xlarge | g6.24xlarge | g7e.2xlarge | p4d.24xlarge | p5.48xlarge |
   |---|---|---|---|---|---|---|
   | us-west-2 | $7.09 | $10.18 | $8.34 | $4.20 | $25.25 | $63.30 |
   | us-east-1 | $7.09 | $10.18 | $8.34 | $4.20 | $25.25 | $63.30 |
   | ap-northeast-1 | $10.28 | $14.76 | $12.10 | — | $34.61 | $79.12 |
   | ap-northeast-2 | $8.72 | $12.52 | $10.26 | — | $34.97 | — |
   | eu-west-1 | $7.92 | $11.36 | — | — | $27.27 | — |

   재생성/리전 추가: `./scripts/refresh_instance_rates.py --region <region> --merge`
   생성되지 않은 리전은 Lambda 가 import 시점에 예외를 던집니다(다른 리전 가격을 조용히
   인용하지 않기 위해).

2. **내 계정이 그 리전에서, 참가자 수만큼 쿼터를 갖고 있는가?** 쿼터 스코프는 `(계정 × 리전)`
   이라 한 리전의 증설이 다른 리전에 적용되지 않고, 큰 GPU 타입은 기본값이 0인 경우가 많습니다:

   ```bash
   ./scripts/check_quotas.py --region <region> --participants 10
   ```

   요금표·라이브 쿼터·모듈 권장 인스턴스를 교차 확인합니다. 이 계정 실측: us-west-2 와
   ap-northeast-2 모두 권장 타입 전체를 **동시 5명**까지 실행할 수 있고, 10명에서는 양쪽 다
   통과하지 못합니다 — 두 리전의 한계가 똑같이 `ml.g5.12xlarge`/`ml.g5.xlarge`의 쿼터 5입니다.
   ap-northeast-2 는 `ml.g6` 패밀리 전체가 쿼터 **0** 이고 `ml.g7e.*`/`ml.p5.*` 는 아예 판매하지
   않습니다 — 그래서 대시보드 권장값에 `g6` 타입이 하나도 없습니다.

S3 모델 캐시 경로는 리전 로컬입니다 — 배포한 리전에 데이터를 적재하세요
(`AWS_REGION=<region> ./scripts/cache_models.sh`; 스크립트는 리전을 추측하지 않습니다).
다시 실행하세요.

---

## 라이선스

이 저장소의 **워크숍 코드**(CDK 인프라, Lambda, 노트북, 대시보드, 스크립트)는
**MIT-0** 라이선스를 따릅니다 — [LICENSE](../../LICENSE)를 참고하세요.

노트북이 다운로드하는 **모델과 데이터셋**은 그 라이선스의 대상이 **아니며**
여기서 **재배포되지 않습니다**. 각각은 고유한 약관을 유지합니다 — 특히
**Alpamayo-1.5-10B (M9/M10)는 비상업용(연구/평가 전용)**이며 **nuScenes**는
비상업용입니다. 적용되는 모든 라이선스를 검토하고 준수하세요; 전체 목록은
[NOTICE](../../NOTICE)를 참고하세요.
