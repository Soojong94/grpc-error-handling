import logging
import time
import random

# 로깅 설정
logger = logging.getLogger(__name__)

class DBClient:
    """데이터베이스 연결 및 쿼리 실행을 담당하는 클라이언트"""
    
    def __init__(self):
        logger.info("DB 클라이언트 초기화")
        # 실제로는 DB 연결을 설정하지만, 이 예제에서는 단순화
        self.connected = True
    
    def execute_query(self, query, params=None):
        """쿼리 실행"""
        if not self.connected:
            logger.error("DB 연결이 없습니다")
            raise Exception("DB 연결이 없습니다")
        
        # 랜덤 지연 추가 (DB 지연 시뮬레이션)
        delay = random.uniform(0.05, 0.2)
        logger.info(f"DB 쿼리 실행 중 (지연: {delay:.2f}초)")
        time.sleep(delay)
        
        # 성공적으로 실행됐다고 가정
        logger.info("DB 쿼리 실행 완료")
        return {"success": True}
    
    def get_user(self, user_id):
        """사용자 정보 조회"""
        logger.info(f"DB에서 사용자 조회 (ID: {user_id})")
        return self.execute_query("SELECT * FROM users WHERE id = ?", [user_id])
    
    def list_users(self, page, page_size):
        """사용자 목록 조회"""
        logger.info(f"DB에서 사용자 목록 조회 (페이지: {page}, 페이지 크기: {page_size})")
        return self.execute_query(
            "SELECT * FROM users LIMIT ? OFFSET ?", 
            [page_size, (page - 1) * page_size]
        )
    
    def create_user(self, name, email):
        """사용자 생성"""
        logger.info(f"DB에 사용자 생성 (이름: {name}, 이메일: {email})")
        return self.execute_query(
            "INSERT INTO users (name, email) VALUES (?, ?)", 
            [name, email]
        )