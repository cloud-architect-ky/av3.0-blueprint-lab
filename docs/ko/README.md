<!-- Language: [English](../en/README.md) · **한국어** · [日本語](../ja/README.md) -->

# AV 3.0 Blueprint Lab — 문서 (한국어)

**언어:** [English](../en/README.md) · **한국어** · [日本語](../ja/README.md)

이 디렉터리는 AV 3.0 Blueprint Lab의 한국어 문서 전체를 담고 있습니다. 프로젝트
개요와 가장 빠른 설치 경로는 [저장소 README](../../README.md)에서 시작하세요.

## 12개 모듈

이 랩은 NVIDIA + AWS **Physical AI 데이터 파이프라인**을 12개의 SageMaker Studio
노트북(M0–M11)으로 실습하는 과정입니다:

| 모듈 | 하는 일 | 인스턴스 |
|---|---|---|
| **M0** | 파이프라인 개요 — 전체 파이프라인을 각 모듈에 매핑 (컴퓨팅 없음) | CPU `t3.medium` |
| **M1** | 데이터 탐색 — 실제 **nuScenes-mini** 센서 데이터 수집·탐색, 씬 선택 | CPU `t3.medium` |
| **M2** | Cosmos Reason 캡셔닝 — 샘플 클립에 대한 VLM 캡션 | GPU `g5.12xlarge` |
| **M3** | Cosmos Curator — **NeMo Curator** 비디오 큐레이션(분할·트랜스코드·필터·중복제거) | GPU `g5.12xlarge` |
| **M4** | Cosmos Transfer — 실제 클립의 날씨/조건 증강 | GPU (`g6.24xlarge` 검증됨) |
| **M5** | Cosmos Predict — 합성 시나리오(video2world) 생성 | GPU |
| **M6** | Alpamayo VLA — **Alpamayo-1.5-10B** 비전-언어-행동 추론 + 궤적 예측 | GPU |
| **M7** | AlpaSim 폐루프 평가 — 진짜 폐루프 정책 평가 결과 시각화 | CPU `t3.medium` (+ GPU EC2) |
| **M8** | OpenSearch 시맨틱 검색 — 캡션 임베딩에 대한 k-NN 검색 | CPU `t3.medium` |
| **M9** | HyperPod 분산 학습 — 실제 2-노드 `torch.distributed` DDP 작업 | CPU `t3.medium` (+ 작업 노드) |
| **M10** | Nerfstudio 3D 재구성 — NeRF / 3D Gaussian Splatting (선택/데모) | GPU `g5.xlarge` |
| **M11** | 파이프라인 자동화 — 실제 SageMaker Pipeline(Caption→Curate→Augment) | CPU `t3.medium` (+ 처리 작업) |

권장 경로: **M0 → M1 → M2 → M3**, 이후 합성 데이터(M4/M5), 정책+시뮬레이션(M6/M7),
검색(M8), 프로덕션 패턴(M9/M11)으로 분기.

## 읽는 순서

**랩을 세팅하는 admin이라면:**
1. [PREREQUISITES.md](PREREQUISITES.md) — 계정, 토큰, 쿼터, 게이트 라이선스.
2. [ADMIN_GUIDE.md](ADMIN_GUIDE.md) — 날짜별 세팅 런북(배포, 데이터/모델 스테이징,
   참가자 프로비저닝, 모니터링, 정리).
3. [DATA_CONTRACT.md](DATA_CONTRACT.md) — 모듈 간 S3 데이터 계약(참고용).

**참가자라면:**
1. [PRE_LEARNING_GUIDE.md](PRE_LEARNING_GUIDE.md) — 행사 전에 읽을 개념 정리.
2. [PARTICIPANT_GUIDE.md](PARTICIPANT_GUIDE.md) — 당일 클릭 단위 실행 런북.

**모듈별 심화:**
- [COSMOS_M4_M5.md](COSMOS_M4_M5.md) — Cosmos Transfer(M4) & Predict(M5).
- [ALPAMAYO_M6.md](ALPAMAYO_M6.md) — Alpamayo VLA(M6).
- [ALPASIM_M7.md](ALPASIM_M7.md) — AlpaSim 폐루프 평가(M7).
- [HYPERPOD_M9.md](HYPERPOD_M9.md) — 분산 학습(M9).
- [PIPELINE_M11.md](PIPELINE_M11.md) — SageMaker Pipelines(M11).

**M7 GPU / SSM 런북 (고급):**
- [M7_MANUAL_TEST_RUNBOOK.md](M7_MANUAL_TEST_RUNBOOK.md) — admin: GPU EC2 호스트에서
  진짜 AlpaSim 레퍼런스 평가 실행.
- [M7_PARTICIPANT_SSM_RUNBOOK.md](M7_PARTICIPANT_SSM_RUNBOOK.md) — 참가자: SSM으로
  진짜 AlpaSim을 직접 실행하는 선택 경로.
