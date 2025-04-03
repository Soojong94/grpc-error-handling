import grpc
import sys
import os

# 프로젝트 루트 경로 추가
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from generated import db_pb2, db_pb2_grpc
from common.logging_config import setup_logging

class DbClient:
    def __init__(self, address='localhost:50053'):
        self.logger = setup_logging("db_client")
        self.address = address
        self.channel = grpc.insecure_channel(address)
        self.stub = db_pb2_grpc.DbServiceStub(self.channel)
    
    def query(self, query_type="normal", timeout=None):
        """DB 쿼리 요청"""
        self.logger.info(f"[DB 클라이언트] DB 서비스 쿼리 요청: {query_type}")
        try:
            request = db_pb2.DbRequest(query_type=query_type)
            if timeout:
                self.logger.info(f"[DB 클라이언트] 타임아웃 설정: {timeout}초")
                response = self.stub.Query(request, timeout=timeout)
            else:
                response = self.stub.Query(request)
            
            self.logger.info(f"[DB 클라이언트] 쿼리 응답: {response.result}")
            return response
        
        except grpc.RpcError as e:
            self.logger.error(f"[DB 클라이언트] gRPC 오류: {e.code()} - {e.details()}")
            raise