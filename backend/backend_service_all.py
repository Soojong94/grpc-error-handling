import sys
import os
# 프로젝트 루트 디렉토리를 sys.path에 명시적으로 추가
sys.path.insert(0, os.path.abspath(os.path.dirname(os.path.dirname(__file__))))

# 상대 경로 임포트를 절대 경로로 변경
# from .backend_service_base import run_server
from backend.backend_service_base import run_server

if __name__ == '__main__':
    # 모든 패턴 적용
    run_server(
        service_name="backend_all_patterns",
        port=50056,
        use_circuit_breaker=True,
        use_deadline=True,
        use_backpressure=True
    )