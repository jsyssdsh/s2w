# 헬스체크 (SPEC 6)

라우터: `backend/app/routers/health.py`

| 메서드 | 경로 | 설명 | 응답 |
|---|---|---|---|
| GET | `/api/health` | 헬스체크 | `{"status":"ok"}` |

도커 `healthcheck` 와 `docker-compose` 가 이 경로에 의존한다. **경로도 응답 형태도
바꾸지 않는다** (ARCHITECTURE 3절).
