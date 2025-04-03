import time
import grpc
from concurrent import futures
import sys
import os

# 프로젝트 루트 경로 추가
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from generated import backend_pb2, backend_pb2_grpc, db_pb2, db_pb2_grpc
from common.logging_config import setup_logging
from common.circuit_breaker import CircuitBreaker
from common.backpressure import BackpressureController
from common.deadline import DeadlineHandler

class BackendServicer(backend_pb2_grpc.BackendServiceServicer):
    def __init__(self):
        self.logger = setup_logging("backend_service")
        
        # 에러 처리 패턴 초기화
        self.circuit_breaker = CircuitBreaker(
            fail_threshold=3,
            reset_timeout=10,
            name="backend_to_db"
        )
        self.backpressure = BackpressureController(
            window_size=5,
            max_requests=20,
            max_concurrency=5,
            name="backend"
        )
        self.deadline_handler = DeadlineHandler(
            timeout_seconds=3,
            name="backend_to_db"
        )
        
        # DB 서비스 주소
        self.db_address = 'localhost:50053'
    
    def Process(self, request, context):
        self.logger.info(f"[Backend] 요청 받음: {request.request_type}")
        self.logger.info(f"[Backend] 패턴 설정 - 서킷브레이커: {request.use_circuit_breaker}, " +
                         f"데드라인: {request.use_deadline}, 백프레셔: {request.use_backpressure}")
        
        # 백프레셔 패턴 적용
        if request.use_backpressure:
            self.backpressure.register_request()
            if self.backpressure.is_overloaded():
                self.logger.warning("[Backend] 백프레셔 패턴 발동 - 과부하 상태")
                context.set_code(grpc.StatusCode.RESOURCE_EXHAUSTED)
                context.set_details("서버 과부하 상태입니다. 잠시 후 다시 시도해주세요.")
                self.backpressure.complete_request()
                return backend_pb2.BackendResponse(
                    success=False,
                    error_message="서버 과부하 상태"
                )
        
        try:
            db_channel = grpc.insecure_channel(self.db_address)
            db_stub = db_pb2_grpc.DbServiceStub(db_channel)
            
            # 서킷 브레이커 패턴 적용
            if request.use_circuit_breaker:
                self.logger.info("[Backend] 서킷브레이커 상태 확인 중...")
                if not self.circuit_breaker.allow_request():
                    self.logger.warning("[Backend] 서킷브레이커 오픈 상태 - 요청 차단됨")
                    context.set_code(grpc.StatusCode.UNAVAILABLE)
                    context.set_details("서비스 일시적으로 사용 불가")
                    if request.use_backpressure:
                        self.backpressure.complete_request()
                    return backend_pb2.BackendResponse(
                        success=False,
                        error_message="서킷브레이커가 오픈 상태입니다"
                    )
            
            # DB 서비스 호출
            try:
                # 데드라인 패턴 적용
                if request.use_deadline:
                    self.logger.info(f"[Backend] 데드라인 패턴 사용 ({self.deadline_handler.get_timeout()}초)")
                    response, error = self.deadline_handler.call_with_deadline(
                        db_stub.Query,
                        db_pb2.DbRequest(query_type="slow")
                    )
                    
                    if error:
                        if request.use_circuit_breaker:
                            self.circuit_breaker.report_failure()
                        raise error
                else:
                    self.logger.info("[Backend] DB 서비스 호출 (데드라인 없음)")
                    response = db_stub.Query(db_pb2.DbRequest(query_type="slow"))
                
                # 성공 처리
                if request.use_circuit_breaker:
                    self.circuit_breaker.report_success()
                
                self.logger.info(f"[Backend] DB 응답 수신: {response.result}")
                if request.use_backpressure:
                    self.backpressure.complete_request()
                
                return backend_pb2.BackendResponse(
                    result="처리 완료: " + response.result,
                    success=True
                )
            
            except grpc.RpcError as e:
                if request.use_circuit_breaker:
                    self.circuit_breaker.report_failure()
                
                status_code = e.code()
                details = e.details()
                
                self.logger.error(f"[Backend] DB 호출 중 오류: {status_code} - {details}")
                
                if status_code == grpc.StatusCode.DEADLINE_EXCEEDED:
                    context.set_code(grpc.StatusCode.DEADLINE_EXCEEDED)
                    context.set_details("DB 서비스 응답 시간 초과")
                else:
                    context.set_code(status_code)
                    context.set_details(f"DB 서비스 오류: {details}")
                
                if request.use_backpressure:
                    self.backpressure.complete_request()
                    
                return backend_pb2.BackendResponse(
                    success=False,
                    error_message=f"DB 호출 오류: {details}"
                )
        
        except Exception as e:
            self.logger.exception("[Backend] 예기치 않은 오류")
            context.set_code(grpc.StatusCode.INTERNAL)
            context.set_details(f"내부 서버 오류: {str(e)}")
            
            if request.use_backpressure:
                self.backpressure.complete_request()
                
            return backend_pb2.BackendResponse(
                success=False,
                error_message=f"내부 서버 오류: {str(e)}"
            )

def serve():
    logger = setup_logging("backend_server")
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
    backend_pb2_grpc.add_BackendServiceServicer_to_server(BackendServicer(), server)
    
    port = 50052
    server.add_insecure_port(f'[::]:{port}')
    server.start()
    logger.info(f"Backend 서비스 시작됨: 포트 {port}")
    
    try:
        server.wait_for_termination()
    except KeyboardInterrupt:
        logger.info("Backend 서비스 종료 중...")
        server.stop(0)

if __name__ == '__main__':
    serve()