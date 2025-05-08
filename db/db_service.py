import time
import grpc
from concurrent import futures
import sys
import os
sys.path.insert(0, os.path.abspath(os.path.dirname(os.path.dirname(__file__))))

from generated import db_pb2, db_pb2_grpc
from common.logging_config import setup_logging

class DbServicer(db_pb2_grpc.DbServiceServicer):
    def __init__(self):
        self.logger = setup_logging("db_service")
        self.slow_query_delay = float(os.environ.get("SLOW_QUERY_DELAY", "2.0"))  # 환경 변수에서 지연 시간 읽기
    
    def Query(self, request, context):
        query_type = request.query_type
        self.logger.info(f"[DB] 쿼리 요청 받음: {query_type}")
        
        if query_type == "slow":
            self.logger.info(f"[DB] 슬로우 쿼리 실행 중... ({self.slow_query_delay}초 지연)")
            time.sleep(self.slow_query_delay)
            self.logger.info("[DB] 슬로우 쿼리 완료")
        else:
            self.logger.info("[DB] 일반 쿼리 실행")
        
        return db_pb2.DbResponse(
            result="쿼리 결과 데이터",
            success=True
        )

def Query(self, request, context):
    query_type = request.query_type
    self.logger.info(f"[DB] 쿼리 요청 받음: {query_type}")
    
    start_time = time.time()
    
    try:
        if query_type == "slow":
            self.logger.info(f"[DB] 슬로우 쿼리 실행 중... ({self.slow_query_delay}초 지연)")
            time.sleep(self.slow_query_delay)
            self.logger.info("[DB] 슬로우 쿼리 완료")
        else:
            self.logger.info("[DB] 일반 쿼리 실행")
        
        execution_time = time.time() - start_time
        self.logger.info(f"[DB] 쿼리 실행 시간: {execution_time:.3f}초")
        
        # 히스토그램 메트릭에 기록 (추가 구현 필요)
        self.record_execution_time(query_type, execution_time)
        
        return db_pb2.DbResponse(
            result="쿼리 결과 데이터",
            success=True
        )
    except Exception as e:
        self.logger.exception(f"[DB] 쿼리 실행 중 오류: {str(e)}")
        context.set_code(grpc.StatusCode.INTERNAL)
        context.set_details(f"쿼리 실패: {str(e)}")
        return db_pb2.DbResponse(
            success=False,
            error_message=f"쿼리 오류: {str(e)}"
        )

def serve():
    logger = setup_logging("db_server")
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
    db_pb2_grpc.add_DbServiceServicer_to_server(DbServicer(), server)
    
    port = int(os.environ.get("PORT", "50057"))  # 환경 변수에서 포트 읽기
    server.add_insecure_port(f"[::]:{port}")
    server.start()
    logger.info(f"DB 서비스 시작됨: 포트 {port}")
    
    try:
        server.wait_for_termination()
    except KeyboardInterrupt:
        logger.info("DB 서비스 종료 중...")
        server.stop(0)

if __name__ == "__main__":
    serve()