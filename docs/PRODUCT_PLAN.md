# OpenClaw Web Dashboard Product Plan (v2)

## 목표
대표님이 텔레그램에서 실제 작업을 지시하더라도, 웹에서 다음을 한눈에 파악한다.
1. 지금까지 자동화가 얼마나 구축됐는가
2. 어떤 에이전트(조직)가 어떤 책임으로 동작 중인가
3. 내가 AI를 얼마나 잘 활용하고 있고, 성장하고 있는가

## UX 원칙
- **Executive First:** 첫 화면은 KPI 6개와 리스크/기회만 보여준다.
- **Evidence Driven:** 모든 수치는 git snapshot(data/*.json, openclaw-data/*.md)에서 계산한다.
- **No Hardcoding:** 문서/에이전트/리포트는 인덱스 기반 렌더링.
- **Trust Layer:** 마지막 동기화 시각, 데이터 출처, 계산 방식 표시.

## IA (Information Architecture)
- Home (지표 요약, 성숙도 점수, 최근 변화)
- Agents (조직도, 역할, 상태)
- Automation (파이프라인/스케줄/커버리지)
- Documents (MD 인덱스, 원문 뷰)
- Calendar (운영 일정)
- Task Tracker (동기화/배포 이력)
- Playbook (OpenClaw 활용 가이드)

## 핵심 지표
- 활성 에이전트 수
- 자동화 잡 수(스케줄)
- 자동 생성 리포트 수
- 동기화 성공률
- Git 누적 커밋 수(성장 지표)
- AI 활용 성숙도 점수(0~100)

## 성숙도 계산(초안)
score =
  25 * (에이전트 구조 구축 여부)
+ 25 * (정기 자동화 잡 수/20, cap 1)
+ 20 * (문서/운영 데이터 추적 수준)
+ 15 * (리포트 파이프라인 가동 여부)
+ 15 * (최근 7일 활동성)

## 데이터 파이프라인
1. sync-openclaw-data.mjs: 로컬 workspace -> openclaw-data 동기화
2. build-site-data.mjs: md-index, agents, kpi, automation, sync-log 생성
3. sync-and-push.sh: 동기화 + 데이터 생성 + 커밋 + 푸시
4. cron(30분): 상기 스크립트 자동 실행

## 검증 체크리스트
- [ ] 하드코딩 없이 md-index로 문서 목록/뷰 동작
- [ ] mail_reports 기반 메일 에이전트 가시화
- [ ] 지표 수치가 data 파일과 일치
- [ ] 첫 화면에서 ‘성장/활용도’ 인사이트 제공
