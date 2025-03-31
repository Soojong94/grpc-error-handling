import psycopg2
import time
import random
import logging
from common.logging_config import setup_logger, log_event

# 로거 설정
logger = setup_logger("DB")

class Database:
    """데이터베이스 연결 및 쿼리 실행을 담당하는 클래스"""
    
    def __init__(self, host="localhost", port=5432, dbname="userdb", user="postgres", password="postgres"):
        """
        데이터베이스 연결 초기화
        """
        self.connection_params = {
            "host": host,
            "port": port,
            "dbname": dbname,
            "user": user,
            "password": password
        }
        self.conn = None
        self.connected = False
        self.connect()
    
    def connect(self):
        """데이터베이스에 연결"""
        try:
            log_event(logger, "INFO", "데이터베이스 연결 시도")
            self.conn = psycopg2.connect(**self.connection_params)
            self.connected = True
            log_event(logger, "INFO", "데이터베이스 연결 성공")
        except Exception as e:
            log_event(logger, "ERROR", f"데이터베이스 연결 실패: {str(e)}")
            self.connected = False
    
    def execute_query(self, query, params=None, delay=None):
        """
        쿼리 실행
        
        Args:
            query: SQL 쿼리 문자열
            params: 쿼리 파라미터
            delay: 인위적인 지연 시간(초)
        
        Returns:
            쿼리 결과
        """
        if not self.connected:
            self.connect()
            if not self.connected:
                log_event(logger, "ERROR", "DB 연결이 없습니다", "데이터베이스")
                raise Exception("DB 연결이 없습니다")
        
        # 쿼리 로깅
        param_str = str(params) if params else "없음"
        log_event(logger, "INFO", f"쿼리 실행: {query}, 파라미터: {param_str}", "데이터베이스")
        
        # 슬로우 쿼리 시뮬레이션을 위한 지연
        if delay:
            log_event(logger, "INFO", f"슬로우 쿼리 지연 시작 ({delay}초)", "백프레셔")
            time.sleep(delay)
            log_event(logger, "INFO", f"슬로우 쿼리 지연 완료 ({delay}초)", "백프레셔")
        else:
            # 기본 쿼리 지연 (50~200ms)
            base_delay = random.uniform(0.05, 0.2)
            time.sleep(base_delay)
        
        try:
            cursor = self.conn.cursor()
            cursor.execute(query, params)
            
            try:
                result = cursor.fetchall()
            except psycopg2.ProgrammingError:
                # INSERT, UPDATE 등 결과가 없는 쿼리
                result = []
            
            self.conn.commit()
            cursor.close()
            log_event(logger, "INFO", "쿼리 실행 완료", "데이터베이스")
            return result
        except Exception as e:
            self.conn.rollback()
            log_event(logger, "ERROR", f"쿼리 실행 오류: {str(e)}", "데이터베이스")
            raise
    
    def get_user(self, user_id, delay=None):
        """사용자 정보 조회"""
        log_event(logger, "INFO", f"사용자 조회 (ID: {user_id})", "데이터베이스")
        result = self.execute_query(
            "SELECT id, name, email FROM users WHERE id = %s",
            (user_id,),
            delay
        )
        
        if result:
            user = {
                "user_id": result[0][0],
                "name": result[0][1],
                "email": result[0][2]
            }
            return user
        return None
    
    def list_users(self, page, page_size, delay=None):
        """사용자 목록 조회"""
        offset = (page - 1) * page_size
        log_event(logger, "INFO", f"사용자 목록 조회 (페이지: {page}, 크기: {page_size})", "데이터베이스")
        
        # 총 사용자 수 조회
        count_result = self.execute_query("SELECT COUNT(*) FROM users")
        total_count = count_result[0][0] if count_result else 0
        
        # 페이지에 해당하는 사용자 조회
        users_result = self.execute_query(
            "SELECT id, name, email FROM users ORDER BY id LIMIT %s OFFSET %s",
            (page_size, offset),
            delay
        )
        
        users = []
        for row in users_result:
            users.append({
                "user_id": row[0],
                "name": row[1],
                "email": row[2]
            })
        
        return {
            "users": users,
            "total_count": total_count
        }
    
    def create_user(self, name, email):
        """사용자 생성"""
        log_event(logger, "INFO", f"사용자 생성 (이름: {name}, 이메일: {email})", "데이터베이스")
        result = self.execute_query(
            "INSERT INTO users (name, email) VALUES (%s, %s) RETURNING id",
            (name, email)
        )
        
        user_id = result[0][0] if result else None
        if user_id:
            return {
                "user_id": user_id,
                "name": name,
                "email": email
            }
        return None
    
    def close(self):
        """데이터베이스 연결 종료"""
        if self.conn:
            self.conn.close()
            self.connected = False
            log_event(logger, "INFO", "데이터베이스 연결 종료", "데이터베이스")