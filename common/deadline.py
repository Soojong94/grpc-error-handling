import time
import logging
import grpc

class DeadlineHandler:
    """데드라인 패턴 구현"""
    
    def __init__(self, timeout_seconds=2, name="default"):
        self.name = name
        self.timeout_seconds = timeout_seconds
        self.logger = logging.getLogger(f"deadline.{name}")
    
    def set_deadline(self, context=None):
        """데드라인 설정"""
        deadline = time.time() + self.timeout_seconds
        self.logger.info(f"[데드라인-{self.name}] 데드라인 설정: {self.timeout_seconds}초")
        return deadline
    
    def get_timeout(self):
        """타임아웃 값 반환"""
        return self.timeout_seconds
    
    def call_with_deadline(self, stub_method, request, context=None):
        """데드라인과 함께 gRPC 메서드 호출"""
        try:
            start_time = time.time()
            deadline = self.set_deadline(context)
            
            self.logger.info(f"[데드라인-{self.name}] 요청 시작 (타임아웃: {self.timeout_seconds}초)")
            response = stub_method(request, timeout=self.timeout_seconds)
            
            elapsed = time.time() - start_time
            self.logger.info(f"[데드라인-{self.name}] 요청 성공 (소요 시간: {elapsed:.2f}초)")
            return response, None
            
        except grpc.RpcError as e:
            elapsed = time.time() - start_time
            if e.code() == grpc.StatusCode.DEADLINE_EXCEEDED:
                self.logger.error(f"[데드라인-{self.name}] 타임아웃 발생 (소요 시간: {elapsed:.2f}초)")
            else:
                self.logger.error(f"[데드라인-{self.name}] gRPC 오류: {e.code()}, {e.details()}")
            return None, e