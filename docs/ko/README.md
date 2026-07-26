<!-- Language: [English](../en/README.md) · **한국어** · [日本語](../ja/README.md) -->

# AV 3.0 Blueprint Lab

**문서 언어:** [English](../en/README.md) · **한국어** · [日本語](../ja/README.md)

**NVIDIA + AWS Physical AI 데이터 파이프라인**을 직접 실행해 볼 수 있는 셀프
서비스 AWS 플랫폼입니다. 참가자는 자율주행 데이터 파이프라인 전체를 다루는
**12개의 Jupyter 노트북 모듈(M0–M11)**을 차례로 진행합니다 — 데이터 탐색,
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

## 12개 모듈

| 모듈 | 하는 일 | 권장 인스턴스 |
|---|---|---|
| **M0** | 파이프라인 개요 — 엔드투엔드 파이프라인을 각 모듈에 매핑(컴퓨트 없음) | `ml.t3.medium` (CPU) |
| **M1** | 데이터 탐색 — 실제 **nuScenes-mini** 센서 데이터 수집 및 탐색, 씬 선택 | `ml.t3.medium` (CPU) |
| **M2** | Cosmos Reason 캡셔닝 — 샘플링된 클립의 VLM 캡션 생성 | `ml.g5.12xlarge` (GPU) |
| **M3** | Cosmos Curator — **NeMo Curator** 비디오 큐레이션(분할, 트랜스코딩, 필터링, 중복 제거) | `ml.g5.12xlarge` (GPU) |
| **M4** | Cosmos Transfer — 실제 클립에 날씨/조건 증강 | GPU (`ml.g6.24xlarge` 검증됨) |
| **M5** | Cosmos Predict — 합성 시나리오(video2world) 생성 | GPU |
| **M6** | Alpamayo VLA — **Alpamayo-1.5-10B** 비전-언어-행동 추론 + 궤적 | GPU |
| **M7** | AlpaSim 폐루프 평가 — 진정한 폐루프 정책 평가 시각화 | `ml.t3.medium` (CPU) + GPU EC2 |
| **M8** | OpenSearch 시맨틱 검색 — 캡션 임베딩에 대한 k-NN 검색 | `ml.t3.medium` (CPU) |
| **M9** | HyperPod 분산 학습 — 실제 2노드 `torch.distributed` DDP 작업 | `ml.t3.medium` (CPU) + 작업 노드 |
| **M10** | Nerfstudio 3D 재구성 — NeRF / 3D Gaussian Splatting(선택/데모) | `ml.g5.xlarge` (GPU) |
| **M11** | 파이프라인 자동화 — 실제 SageMaker Pipeline(Caption→Curate→Augment) | `ml.t3.medium` (CPU) + 프로세싱 작업 |

권장 경로: **M0 → M1 → M2 → M3**, 이후 합성 데이터(M4/M5), 정책 + 시뮬레이션
(M6/M7), 검색(M8), 프로덕션 패턴(M9/M11)으로 분기합니다. 표시된 인스턴스는
대시보드 기본값이며, 각 GPU 모듈은 대안도 제공합니다(예: `ml.g5.12xlarge` 용량이
부족할 때 `ml.g6.12xlarge`).

---

## 어떤 문서를 읽어야 하나

전체 가이드는 **English / 한국어 / 日本語**로 **`docs/<lang>/`** 아래에 있습니다
(아래 링크는 이 언어 디렉터리의 문서입니다. 언어 선택은 페이지 상단의 스위처를
사용하세요):

| 당신은… | 읽을 문서(순서대로) |
|---|---|
| **관리자 — 랩 설정 담당** | [PREREQUISITES](PREREQUISITES.md) → [ADMIN_GUIDE](ADMIN_GUIDE.md) → [DATA_CONTRACT](DATA_CONTRACT.md) |
| **참가자** | [PRE_LEARNING_GUIDE](PRE_LEARNING_GUIDE.md) → [PARTICIPANT_GUIDE](PARTICIPANT_GUIDE.md) |
| **모듈별 심화** | [COSMOS_M4_M5](COSMOS_M4_M5.md) · [ALPAMAYO_M6](ALPAMAYO_M6.md) · [ALPASIM_M7](ALPASIM_M7.md) · [HYPERPOD_M9](HYPERPOD_M9.md) · [PIPELINE_M11](PIPELINE_M11.md) |
| **M7 GPU / SSM(고급)** | [M7_MANUAL_TEST_RUNBOOK](M7_MANUAL_TEST_RUNBOOK.md)(관리자) · [M7_PARTICIPANT_SSM_RUNBOOK](M7_PARTICIPANT_SSM_RUNBOOK.md)(참가자) |

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
| Hugging Face 토큰 | — | **관리자 전용** — 게이트된 모델(M2/M4/M5/M6)을 사전 캐싱하고 M7 레퍼런스 평가를 실행합니다. **참가자에게는 HF 토큰이 필요 없습니다.** [docs/ko/PREREQUISITES.md](PREREQUISITES.md)를 참고하세요. |
| NGC API 키 | — | **관리자 전용, M7 전용** — AlpaSim NuRec 렌더러 이미지용. |

### 서비스 할당량(조기 요청 — 24–48시간 리드 타임)

GPU **Studio JupyterLab App** 할당량은 새 계정에서 기본적으로 낮거나 **0**입니다 —
워크숍 전에 증설을 요청하세요. 또한 M9/M11에는 놓치기 쉬운 별도의 **작업(job)**
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
export AWS_REGION="us-west-2"                 # 기본값; "리전 선택" 참고
export HF_TOKEN="hf_..."                      # 관리자 Hugging Face 읽기 토큰
# 선택 사항이지만 권장: 관리자 대시보드 접근을 특정 IP/CIDR로 제한
export ADMIN_IP_ALLOWLIST="203.0.113.0/24"    # 기본값 0.0.0.0/0 = WAF 개방

# 2b. Hugging Face에서 게이트된 모델/데이터셋 라이선스에 동의(6단계 전에).
#     huggingface.co에 로그인하여 각 게이트된 리포지토리에서 "Agree and access repository"를
#     클릭하세요 — 전체 목록은 docs/ko/PREREQUISITES.md 참고.

# 3. CDK 부트스트랩(계정 + 리전당 1회)
cd infra && python3 -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt
npx cdk bootstrap "aws://$(aws sts get-caller-identity --query Account --output text)/$AWS_REGION"
cd ..

# 4. 인프라 + 대시보드 배포(~25분)
./scripts/deploy.sh

# 5. 첫 번째 Cognito 관리자 사용자 생성
#    (deploy.sh가 풀 id가 포함된 정확한 명령을 출력합니다; username은 반드시 이메일이어야 함)
aws cognito-idp admin-create-user \
    --user-pool-id <cognito-pool-id> \
    --username "$ADMIN_EMAIL" \
    --user-attributes Name=email,Value="$ADMIN_EMAIL" Name=email_verified,Value=true \
    --temporary-password 'TempPass1!' \
    --region "$AWS_REGION"

# 6. NVIDIA 모델을 S3에 사전 캐싱(백그라운드, 30–60분)
./scripts/cache_models.sh
#    M4/M5/M6은 추가로 오프라인 HF 캐시가 필요하고, M6은 데모 클립이, M7은
#    일회성 GPU-EC2 레퍼런스 평가가 필요합니다 — docs/ko/ADMIN_GUIDE.md §6 및
#    모듈별 심화 문서(COSMOS_M4_M5, ALPAMAYO_M6, ALPASIM_M7)를 참고하세요.

# 7. nuScenes-mini 데이터셋을 S3에 스테이징(M1 / M3 / M10에서 필요)
./scripts/stage_nuscenes.sh
#    공개 AWS Open Data 미러에서 가져옵니다(로그인 불필요; nuScenes 약관 적용).

# 8. 노트북 템플릿 + 헬퍼 스크립트를 공유 버킷에 업로드
ACCOUNT=$(aws sts get-caller-identity --query Account --output text)
aws s3 sync notebooks/ "s3://av30lab-shared-data-$ACCOUNT/notebook-templates/" --region "$AWS_REGION"
aws s3 sync scripts/   "s3://av30lab-shared-data-$ACCOUNT/notebook-templates/scripts/" --region "$AWS_REGION"
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
                                         notebook-templates / m7-reference)
```

- **네트워크:** 프라이빗 서브넷, NAT Gateway, S3/SageMaker용 VPC 엔드포인트를 갖춘 VPC.
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

## 비용 & 정리

| 시나리오 | 비용 | 비고 |
|---|---|---|
| 유휴(인프라만) | ~$80/월 | NAT Gateway, VPC 엔드포인트, DynamoDB, CloudFront |
| GPU 모듈 | 시간당 | `ml.g5.xlarge` ~$1.41/hr (M10), `ml.g5.12xlarge` ~$6.68/hr (M2/M3), `ml.p4d.24xlarge` ~$37.69/hr (M4/M5/M6) |
| EC2의 M7 AlpaSim | ~$30 일회성(관리자) | `g6e.12xlarge`에서 레퍼런스 평가; 선택적 참가자 자체 실행 시 ~$10.5/hr/호스트 |
| 전체 1주(혼합) | ~$400–600+ | p4d 모듈과 사용자 수가 비용의 대부분을 차지 |

**비용 제어:** 일일 예산 알람(SNS → `<admin-email>`), Sessions 탭에서 관리자
강제 종료, 유휴 앱의 라이프사이클 자동 중지(~180분). **정리:**
`scripts/teardown.sh`(기본은 드라이런; `--yes`, `--user <id>`, `--destroy`)는
사용자별 앱/스페이스/프로필을 제거하고, 고아 상태의 OpenSearch Serverless
컬렉션을 정리하며, 태그된 GPU EC2 호스트를 종료합니다. 이벤트 후에는 **관리자
HF 토큰을 폐기하고 NGC 키를 교체**하세요. 자세한 내용은
[docs/ko/ADMIN_GUIDE.md](ADMIN_GUIDE.md)에 있습니다.

---

## 리전 선택

기본값: **us-west-2 (Oregon)** — 가장 깊은 GPU 용량과 `ml.p5.48xlarge` 가용성.
배포 전에 `export AWS_REGION=...`으로 변경하세요.

| 리전 | p4d.24xlarge | p5.48xlarge | g5.12xlarge | 비고 |
|---|---|---|---|---|
| us-west-2 (Oregon) | ✅ | ✅ | ✅ | **기본값** |
| us-east-1 (Virginia) | ✅ | ✅ | ✅ | 대안 |
| ap-northeast-2 (Seoul) | ✅ | ❌ | ✅ | p5 폴백 없음 |

S3 모델 캐시 경로는 리전 로컬입니다 — 리전을 변경한 후에는 `cache_models.sh`를
다시 실행하세요.

---

## 라이선스

이 저장소의 **워크숍 코드**(CDK 인프라, Lambda, 노트북, 대시보드, 스크립트)는
**MIT-0** 라이선스를 따릅니다 — [LICENSE](../../LICENSE)를 참고하세요.

노트북이 다운로드하는 **모델과 데이터셋**은 그 라이선스의 대상이 **아니며**
여기서 **재배포되지 않습니다**. 각각은 고유한 약관을 유지합니다 — 특히
**Alpamayo-1.5-10B (M6/M7)는 비상업용(연구/평가 전용)**이며 **nuScenes**는
비상업용입니다. 적용되는 모든 라이선스를 검토하고 준수하세요; 전체 목록은
[NOTICE](../../NOTICE)를 참고하세요.
