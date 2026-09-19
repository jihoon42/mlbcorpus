"""mlbcorpus — MLB Stats API 기반 야구 텍스트 코퍼스 구축 도구.

모듈 구성
    config      경로·시즌·게임 타입·속도 제한 등 설정
    endpoints   Stats API URL 조립 (인증 없음)
    fetch       속도 제한 + 재시도가 붙은 비동기 HTTP 클라이언트
    storage     원본 응답의 gzip 캐시 (받은 바이트 그대로 저장)
    schedule    schedule 응답 → 경기 목록(종료 경기 판정, 순연 재등장 중복 제거)
    manifest    수집 상태 SQLite (resume의 근거)
    crawl       schedule → 경기별 4개 리소스 수집 루프
    normalize   원본 JSON → 정규화 테이블 (docs/02-schema.md, 추후 구현)
    cli         `mlbcorpus` 명령
"""

__version__ = "0.1.0"
