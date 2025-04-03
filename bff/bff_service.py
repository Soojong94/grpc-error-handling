import time
import grpc
from concurrent import futures
import sys
import os
# 프로젝트 루트 디렉토리를 sys.path에 추가
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from generated import bff_pb2, bff_pb2_grpc, backend_pb2, backend_pb2_grpc
from common.logging_config import setup_logging
from common.circuit_breaker import CircuitBreaker
from common.backpressure import BackpressureController
from common.deadline import DeadlineHandler

class BffServicer(bff_pb2_grpc.BffServiceServicer):
    def __init__(self):
        self.logger = setup_logging("bff_service")
        
        # 에러 처리 패턴 초기화
        self.circuit_breaker = CircuitBreaker(
            fail_threshold=3,
            reset_timeout=10,
            name="bff_to_backend"
        )
        self.backpressure = BackpressureController(
            window_size=5,
            max_requests=30,
            max_concurrency=8,
            name="bff"
        )
        self.deadline_handler = DeadlineHandler(
            timeout_seconds=0.5,
            name="bff_to_backend"
        )
        
        # Backend 서비스 주소
        self.backend_address = 'localhost:50052'
    
    def Process(self, request, context):
        self.logger.info(f"[BFF] 요청 받음: {request.request_type}")
        self.logger.info(f"[BFF] 패턴 설정 - 서킷브레이커: {request.use_circuit_breaker}, " +
                         f"데드라인: {request.use_deadline}, 백프레셔: {request.use_backpressure}")
        
        # 백프레셔 패턴 적용
        if request.use_backpressure:
            self.backpressure.register_request()
            if self.backpressure.is_overloaded():
                self.logger.warning("[BFF] 백프레셔 패턴 발동 - 과부하 상태")
                context.set_code(grpc.StatusCode.RESOURCE_EXHAUSTED)
                context.set_details("서버 과부하 상태입니다. 잠시 후 다시 시도해주세요.")
                self.backpressure.complete_request()
                return bff_pb2.BffResponse(
                    success=False,
                    error_message="서버 과부하 상태"
                )
        
        try:
            backend_channel = grpc.insecure_channel(self.backend_address)
            backend_stub = backend_pb2_grpc.BackendServiceStub(backend_channel)
            
            # 서킷 브레이커 패턴 적용
            if request.use_circuit_breaker:
                self.logger.info("[BFF] 서킷브레이커 상태 확인 중...")
                if not self.circuit_breaker.allow_request():
                    self.logger.warning("[BFF] 서킷브레이커 오픈 상태 - 요청 차단됨")
                    context.set_code(grpc.StatusCode.UNAVAILABLE)
                    context.set_details("서비스 일시적으로 사용 불가")
                    if request.use_backpressure:
                        self.backpressure.complete_request()
                    return bff_pb2.BffResponse(
                        success=False,
                        error_message="서킷브레이커가 오픈 상태입니다"
                    )
            
            # Backend 서비스 호출
            try:
                # 데드라인 패턴 적용
                if request.use_deadline:
                    self.logger.info(f"[BFF] 데드라인 패턴 사용 ({self.deadline_handler.get_timeout()}초)")
                    response, error = self.deadline_handler.call_with_deadline(
                        backend_stub.Process,
                        backend_pb2.BackendRequest(
                            request_type=request.request_type,
                            use_deadline=request.use_deadline,
                            use_circuit_breaker=request.use_circuit_breaker,
                            use_backpressure=request.use_backpressure
                        )
                    )
                    
                    if error:
                        if request.use_circuit_breaker:
                            self.circuit_breaker.report_failure()
                        raise error
                else:
                    self.logger.info("[BFF] Backend 서비스 호출 (데드라인 없음)")
                    response = backend_stub.Process(
                        backend_pb2.BackendRequest(
                            request_type=request.request_type,
                            use_deadline=request.use_deadline,
                            use_circuit_breaker=request.use_circuit_breaker,
                            use_backpressure=request.use_backpressure
                        )
                    )
                
                # 성공 처리
                if request.use_circuit_breaker:
                    self.circuit_breaker.report_success()
                
                self.logger.info(f"[BFF] Backend 응답 수신: {response.result}")
                if request.use_backpressure:
                    self.backpressure.complete_request()
                
                return bff_pb2.BffResponse(
                    result="처리 완료: " + (response.result if response.result else ""),
                    success=response.success,
                    error_message=response.error_message
                )
            
            except grpc.RpcError as e:
                if request.use_circuit_breaker:
                    self.circuit_breaker.report_failure()
                
                status_code = e.code()
                details = e.details()
                
                self.logger.error(f"[BFF] Backend 호출 중 오류: {status_code} - {details}")
                
                if status_code == grpc.StatusCode.DEADLINE_EXCEEDED:
                    context.set_code(grpc.StatusCode.DEADLINE_EXCEEDED)
                    context.set_details("Backend 서비스 응답 시간 초과")
                else:
                    context.set_code(status_code)
                    context.set_details(f"Backend 서비스 오류: {details}")
                
                if request.use_backpressure:
                    self.backpressure.complete_request()
                    
                return bff_pb2.BffResponse(
                    success=False,
                    error_message=f"Backend 호출 오류: {details}"
                )
        
        except Exception as e:
            self.logger.exception("[BFF] 예기치 않은 오류")
            context.set_code(grpc.StatusCode.INTERNAL)
            context.set_details(f"내부 서버 오류: {str(e)}")
            
            if request.use_backpressure:
                self.backpressure.complete_request()
                
            return bff_pb2.BffResponse(
                success=False,
                error_message=f"내부 서버 오류: {str(e)}"
            )

def serve():
    logger = setup_logging("bff_server")
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
    bff_pb2_grpc.add_BffServiceServicer_to_server(BffServicer(), server)
    
    port = 50051
    server.add_insecure_port(f'[::]:{port}')
    server.start()
    logger.info(f"BFF 서비스 시작됨: 포트 {port}")
    
    try:
        server.wait_for_termination()
    except KeyboardInterrupt:
        logger.info("BFF 서비스 종료 중...")
        server.stop(0)

if __name__ == '__main__':
    serve()