import time
import random
import sys
import os

# 상위 디렉토리 경로 추가
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# 공통 모듈
from common.logging_config import setup_logger, log_event

# 로거 설정
logger = setup_logger("DB_CLIENT")

class DBClient:
    """데이터베이스 연결 및 쿼리 실행을 담당하는 클라이언트"""
    
    def __init__(self):
        try:
            log_event(logger, "INFO", "DB 클라이언트 초기화")
            self.connected = True
            log_event(logger, "INFO", "DB 클라이언트 초기화 완료")
        except Exception as e:
            log_event(logger, "ERROR", f"DB 클라이언트 초기화 실패: {str(e)}")
            self.connected = False
            raise
    
    def execute_query(self, query, params=None, delay=None):
        """쿼리 실행"""
        if not self.connected:
            log_event(logger, "ERROR", "DB 연결이 없습니다")
            raise Exception("DB 연결이 없습니다")
        
        # 쿼리 로깅
        param_str = str(params) if params else "없음"
        log_event(logger, "INFO", f"쿼리 실행: {query}, 파라미터: {param_str}")
        
        # 슬로우 쿼리 시뮬레이션을 위한 지연
        if delay:
            log_event(logger, "INFO", f"DB 지연 시작 ({delay}초)", "슬로우쿼리")
            time.sleep(delay)
            log_event(logger, "INFO", f"DB 지연 완료 ({delay}초)", "슬로우쿼리")
        else:
            # 기본 쿼리 지연
            base_delay = random.uniform(0.05, 0.2)
            time.sleep(base_delay)
        
        log_event(logger, "INFO", "DB 쿼리 실행 완료")
        return {"success": True}
    
    def get_user(self, user_id, delay=None):
        """사용자 정보 조회"""
        log_event(logger, "INFO", f"DB에서 사용자 조회 (ID: {user_id})")
        self.execute_query("SELECT * FROM users WHERE id = ?", [user_id], delay)
        
        # 테스트 데이터 반환
        user = {
            "user_id": user_id,
            "name": f"사용자{user_id}",
            "email": f"user{user_id}@example.com"
        }
        return user
    
    def list_users(self, page, page_size, delay=None):
        """사용자 목록 조회"""
        log_event(logger, "INFO", f"DB에서 사용자 목록 조회 (페이지: {page}, 페이지 크기: {page_size})")
        self.execute_query(
            "SELECT * FROM users LIMIT ? OFFSET ?", 
            [page_size, (page - 1) * page_size],
            delay
        )
        
        # 테스트 데이터 생성
        users = []
        total_count = 20  # 가상의 전체 사용자 수
        
        start_id = (page - 1) * page_size + 1
        end_id = start_id + page_size
        
        for i in range(start_id, min(end_id, total_count + 1)):
            users.append({
                "user_id": i,
                "name": f"사용자{i}",
                "email": f"user{i}@example.com"
            })
        
        return {
            "users": users,
            "total_count": total_count
        }
    
    def create_user(self, name, email):
        """사용자 생성"""
        log_event(logger, "INFO", f"DB에 사용자 생성 (이름: {name}, 이메일: {email})")
        self.execute_query(
            "INSERT INTO users (name, email) VALUES (?, ?)",
            [name, email]
        )
        
        # 임의의 ID 생성 (실제로는 DB가 생성)
        user_id = random.randint(100, 999)
        
        return {
            "user_id": user_id,
            "name": name,
            "email": email
        }