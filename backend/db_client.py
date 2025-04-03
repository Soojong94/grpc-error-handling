import time
import random
import sys
import os
import threading

# 상위 디렉토리 경로 추가
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# 공통 모듈
from common.logging_config import setup_logger, log_event, add_event

# 로거 설정
logger = setup_logger("DB_CLIENT")

class DBClient:
    """데이터베이스 연결 및 쿼리 실행을 담당하는 클라이언트"""
    
    def __init__(self):
        try:
            log_event(logger, "INFO", "DB 클라이언트 초기화")
            self.connected = True
            self._query_stats = {
                "total_queries": 0,
                "slow_queries": 0,
                "error_queries": 0
            }
            self._stats_lock = threading.Lock()
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
        
        with self._stats_lock:
            self._query_stats["total_queries"] += 1
        
        # 슬로우 쿼리 시뮬레이션을 위한 지연
        if delay:
            log_event(logger, "INFO", f"DB 지연 시작 ({delay}초)", "슬로우쿼리")
            with self._stats_lock:
                self._query_stats["slow_queries"] += 1
            
            # 지연이 3초 이상이면 이벤트 로그에 기록
            if delay >= 3:
                add_event("database", f"슬로우 쿼리 감지: {delay}초 지연")
                
            time.sleep(delay)
            log_event(logger, "INFO", f"DB 지연 완료 ({delay}초)", "슬로우쿼리")
        else:
            # 테스트 모드가 아니면 기본 지연 없음
            pass
        
        log_event(logger, "INFO", "DB 쿼리 실행 완료")
        return {"success": True}
    
    def get_user(self, user_id, delay=None):
        """사용자 정보 조회"""
        log_event(logger, "INFO", f"DB에서 사용자 조회 (ID: {user_id})")
        try:
            self.execute_query("SELECT * FROM users WHERE id = ?", [user_id], delay)
            
            # 테스트 데이터 반환
            user = {
                "user_id": user_id,
                "name": f"사용자{user_id}",
                "email": f"user{user_id}@example.com"
            }
            return user
        except Exception as e:
            log_event(logger, "ERROR", f"사용자 조회 중 오류: {str(e)}")
            with self._stats_lock:
                self._query_stats["error_queries"] += 1
            raise
    
    def list_users(self, page, page_size, delay=None):
        """사용자 목록 조회"""
        log_event(logger, "INFO", f"DB에서 사용자 목록 조회 (페이지: {page}, 페이지 크기: {page_size})")
        try:
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
        except Exception as e:
            log_event(logger, "ERROR", f"사용자 목록 조회 중 오류: {str(e)}")
            with self._stats_lock:
                self._query_stats["error_queries"] += 1
            raise
    
    def create_user(self, name, email):
        """사용자 생성"""
        log_event(logger, "INFO", f"DB에 사용자 생성 (이름: {name}, 이메일: {email})")
        try:
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
        except Exception as e:
            log_event(logger, "ERROR", f"사용자 생성 중 오류: {str(e)}")
            with self._stats_lock:
                self._query_stats["error_queries"] += 1
            raise
    
    def get_stats(self):
        """DB 클라이언트 통계 조회"""
        with self._stats_lock:
            return self._query_stats.copy()
    
    def reset_stats(self):
        """통계 초기화"""
        with self._stats_lock:
            self._query_stats = {
                "total_queries": 0,
                "slow_queries": 0,
                "error_queries": 0
            }
        log_event(logger, "INFO", "DB 통계 초기화됨")
        return True