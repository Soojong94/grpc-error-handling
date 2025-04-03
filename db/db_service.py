import time
import grpc
from concurrent import futures
import sys
import os

# 프로젝트 루트 경로 추가
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from generated import db_pb2, db_pb2_grpc
from common.logging_config import setup_logging

class DbServicer(db_pb2_grpc.DbServiceServicer):
    def __init__(self):
        self.logger = setup_logging("db_service")
        self.query_delay = 1  # 슬로우 쿼리 지연 시간 (초)
    
    def Query(self, request, context):
        query_type = request.query_type
        self.logger.info(f"[DB] 쿼리 요청 받음: {query_type}")
        
        if query_type == "slow":
            self.logger.info(f"[DB] 슬로우 쿼리 실행 중... ({self.query_delay}초 지연)")
            time.sleep(self.query_delay)
            self.logger.info("[DB] 슬로우 쿼리 완료")
        else:
            self.logger.info("[DB] 일반 쿼리 실행")
        
        return db_pb2.DbResponse(
            result="쿼리 결과 데이터",
            success=True
        )

def serve():
    logger = setup_logging("db_server")
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
    db_pb2_grpc.add_DbServiceServicer_to_server(DbServicer(), server)
    
    port = 50053
    server.add_insecure_port(f'[::]:{port}')
    server.start()
    logger.info(f"DB 서비스 시작됨: 포트 {port}")
    
    try:
        server.wait_for_termination()
    except KeyboardInterrupt:
        logger.info("DB 서비스 종료 중...")
        server.stop(0)

if __name__ == '__main__':
    serve()