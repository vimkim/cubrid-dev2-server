# 자원 정책 작업 재개 안내

2026-10-26 사용자가 다음 세션에서 재개하기로 했다. 이번 세션에서는 재개 기록만 작성한다.

## 재개 위치와 상태

| 항목 | 기록 시점의 상태 |
| --- | --- |
| 작업 추적 | `work-tracker` 항목 `501` |
| 기본 저장소 | `/home/vimkim/temp/cubrid-dev2-server` |
| 작업 트리 | `/home/vimkim/temp/cubrid-dev2-server-resource-policy` |
| 작업 브랜치 | `feat/resource-policy` |
| 기능 구현 커밋 | `a6da87a` |
| 기존 작업 브랜치 끝 | `c22d517` — 디스크 기반 `/tmp` 선호 기록 |
| 문서화가 끝난 `main` | `be6e960` — 설계 질의응답 반영 및 원격 푸시 완료 |
| 관련 정책 문서 | [자원 정책과 적용 절차](resource-policy.md) |

이 표는 재개 기록 시점의 상태다. 재개할 때 브랜치, 커밋, 작업 트리와 추적 항목의 최신 상태를 확인한다.
항목 `501`에는 별도 장애 진단 저장소의 작업도 포함되어 있다. 이번 재개의 첫 범위는 자원 정책 브랜치 검토다.

## 먼저 확인할 확정 요구사항

`main`의 `docs/design-context.md`를 읽는다. 현재 작업 브랜치의 같은 문서는 이전 부분 답변만 포함한다.

- 컨테이너는 SSH로 접속하는 VM 같은 개발 환경이다. 독립적인 LAN IP가 필요하다.
  개발자마다 33000번 등 같은 포트 번호를 충돌 없이 사용해야 하며, 호스트 IP 하나에서 포트를 재할당하는 방식은 맞지 않는다.
- CPU와 메모리 사용량을 제한할 수 있어야 하며, 제한 단위는 컨테이너다.
- 기본 `/tmp`는 디스크 기반으로 사용한다. 사용자가 의도적으로 tmpfs를 만드는 것은 허용한다.
  이 결정은 작업 브랜치의 기존 답변과 항목 `501`의 이력에 있다.
- 재생성 시 `/home`만 보존하면 충분하다. `/home`의 별도 백업은 요구하지 않는다.
- 호스트 재부팅 후 재시작 여부는 상황에 따라 사용자가 선택한다.
  사용자는 별도 스크립트로 처리할 수 있을 것으로 보았다.
- sudo 명령 실수의 영향이 다른 개발자나 호스트에 미치는 것까지 막는 것은 필수 요구사항이 아니다.
- `--privileged`는 기존 인프라와 디버깅 호환성을 위해 선택했다. 필요한 최소 권한 조합은 미검토다.
  ipvlan과 macvlan의 적합성 비교도 미검증이다.

## 다음 작업 순서

1. 개인 CUBRID 지침과 각 저장소의 `AGENTS.md`를 읽고, 아래 명령으로 재개 상태를 확인한다.
2. 작업 브랜치의 `docs/design-context.md`에 최신 `main`의 답변을 반영한다.
   작업 브랜치에만 있는 디스크 기반 `/tmp` 결정과 원문도 보존한다.
   두 브랜치가 이 문서를 각각 추가했으므로 최종 리베이스에서 충돌할 수 있다.
3. `AGENTS.md`에서 최신 설계 문서 참조와 자원 정책 참조를 함께 유지한다.
   `main`에서 삭제한 "systemd 때문에 privileged가 필수"라는 단정을 복원하지 않는다.
4. `resource_policy.py`, `run_dev_containers.py`, 예제 정책과 테스트를 확정 요구사항에 대조한다.
   기록 시점의 정책 스키마와 실행 옵션에는 메모리·스왑 제한이 있으며 CPU 제한 항목은 없다.
   컨테이너별 CPU 제한을 지원하려면 필요한 변경과 검증을 준비한다.
5. 정책 문서의 제한 수치는 제안으로 유지한다. 예제의 `approved: false`를 유지하고,
   구체적인 CPU·RAM·스왑 한도와 적용 일정은 별도로 정한다.
6. 변경에 맞는 격리 테스트와 dry-run을 실행하고 전체 diff를 검토한다. 작업 파일만 커밋한다.
7. 결과가 검토 가능한 상태가 되면 현재 로컬 `main`으로 리베이스하고 병합할 승인을 한 번 요청한다.
   승인 후 충돌을 해결하고 검사한 뒤 fast-forward 병합한다. `main` 병합 승인에는 설정된 원격 푸시가 포함된다.

## 재개 명령

```bash
cd /home/vimkim/temp/cubrid-dev2-server
work-tracker show 501
work-tracker history 501
git status --short --branch
git worktree list
git show main:docs/design-context.md

cd /home/vimkim/temp/cubrid-dev2-server-resource-policy
git status --short --branch
git log -3 --oneline
git diff main...HEAD --stat
/usr/bin/python3 -B -m unittest discover -s tests -v
/usr/bin/python3 -B run_dev_containers.py --resource-policy resource-policy.example.json --only vimkim1 --dry-run
git diff --check
```

재개 시점에 실행한 검사 결과를 보고한다.

## 재개 기록과 별도로 진행할 작업

이번 요청은 재개 기록 작성이다. 호스트 적용, 컨테이너 재생성·재시작은 수행하지 않는다.
실제 호스트에서의 systemd·SSH·빌드·테스트·제한값·마운트·재부팅 검증과
기존 컨테이너 이관은 [적용 절차](resource-policy.md)에 따라 별도로 진행한다.
항목 `501`에 기록된 장애 진단 쪽의 작업과 미병합 커밋도 보존한다.
