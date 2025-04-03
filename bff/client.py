import grpc
import sys
import os

# 프로젝트 루트 경로 추가
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from generated import backend_pb2, backend_pb2_grpc
from common.logging_config import setup_logging

class BackendClient:
    def __init__(self, address='localhost:50052'):
        self.logger = setup_logging("backend_client")
        self.address = address
        self.channel = grpc.insecure_channel(address)
        self.stub = backend_pb2_grpc.BackendServiceStub(self.channel)
    
    def process(self, request_type="normal", use_deadline=False, 
                use_circuit_breaker=False, use_backpressure=False, timeout=None):
        """Backend 처리 요청"""
        self.logger.info(f"[Backend 클라이언트] Backend 서비스 요청: {request_type}")
        self.logger.info(f"[Backend 클라이언트] 패턴 설정 - 서킷브레이커: {use_circuit_breaker}, " +
                         f"데드라인: {use_deadline}, 백프레셔: {use_backpressure}")
        
        try:
            request = backend_pb2.BackendRequest(
                request_type=request_type,
                use_deadline=use_deadline,
                use_circuit_breaker=use_circuit_breaker,
                use_backpressure=use_backpressure
            )
            
            if timeout:
                self.logger.info(f"[Backend 클라이언트] 타임아웃 설정: {timeout}초")
                response = self.stub.Process(request, timeout=timeout)
            else:
                response = self.stub.Process(request)
            
            self.logger.info(f"[Backend 클라이언트] 응답: {response.result}")
            return response
        
        except grpc.RpcError as e:
            self.logger.error