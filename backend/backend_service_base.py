import time
import grpc
from concurrent import futures
import threading
import sys
import os

# 프로젝트 루트 디렉토리를 sys.path에 추가
sys.path.insert(0, os.path.abspath(os.path.dirname(os.path.dirname(__file__))))

from generated import backend_pb2, backend_pb2_grpc, db_pb2, db_pb2_grpc
from common.logging_config import setup_logging
from common.circuit_breaker import CircuitBreaker
from common.backpressure import BackpressureController
from common.deadline import DeadlineHandler

class BaseBackendServicer(backend_pb2_grpc.BackendServiceServicer):
    def __init__(self, service_name, port=50052, use_circuit_breaker=False, use_deadline=False, use_backpressure=False):
        self.service_name = service_name
        self.port = port
        self.logger = setup_logging(service_name)
        
        # 기본 패턴 활성화 설정
        self.default_use_circuit_breaker = use_circuit_breaker
        self.default_use_deadline = use_deadline
        self.default_use_backpressure = use_backpressure
        
        # 환경 변수에서 설정 가져오기
        fail_threshold = int(os.environ.get("CIRCUIT_BREAKER_FAIL_THRESHOLD", "3"))
        reset_timeout = int(os.environ.get("CIRCUIT_BREAKER_RESET_TIMEOUT", "10"))
        backpressure_window = int(os.environ.get("BACKPRESSURE_WINDOW", "5"))
        backpressure_max_requests = int(os.environ.get("BACKPRESSURE_MAX_REQUESTS", "30"))
        backpressure_max_concurrency = int(os.environ.get("BACKPRESSURE_MAX_CONCURRENCY", "8"))
        deadline_timeout = float(os.environ.get("DEADLINE_TIMEOUT", "0.5"))
        
        # 에러 처리 패턴 초기화
        self.circuit_breaker = CircuitBreaker(
            fail_threshold=fail_threshold,
            reset_timeout=reset_timeout,
            name=f"{service_name}_to_db"
        )
        self.backpressure = BackpressureController(
            window_size=backpressure_window,
            max_requests=backpressure_max_requests,
            max_concurrency=backpressure_max_concurrency,
            name=service_name
        )
        self.deadline_handler = DeadlineHandler(
            timeout_seconds=deadline_timeout,
            name=f"{service_name}_to_db"
        )
        
        # DB 서비스 주소 (환경 변수에서 읽기)
        self.db_address = os.environ.get("DB_SERVICE_ADDRESS", "localhost:50057")
        self.logger.info(f"[{service_name}] 초기화 - DB 주소: {self.db_address}")
        self.logger.info(f"[{service_name}] 초기화 - 패턴 설정: 서킷브레이커={use_circuit_breaker}, 데드라인={use_deadline}, 백프레셔={use_backpressure}")
    
    def Process(self, request, context):
        # 요청별 패턴 설정 (요청에서 지정되지 않으면 기본값 사용)
        use_circuit_breaker = request.use_circuit_breaker if request.use_circuit_breaker else self.default_use_circuit_breaker
        use_deadline = request.use_deadline if request.use_deadline else self.default_use_deadline
        use_backpressure = request.use_backpressure if request.use_backpressure else self.default_use_backpressure
        
        self.logger.info(f"[{self.service_name}] 요청 받음: {request.request_type}")
        self.logger.info(f"[{self.service_name}] 패턴 설정 - 서킷브레이커: {use_circuit_breaker}, " +
                         f"데드라인: {use_deadline}, 백프레셔: {use_backpressure}")
        
        # 백프레셔 패턴 적용
        if use_backpressure:
            self.backpressure.register_request()
            if self.backpressure.is_overloaded():
                self.logger.warning(f"[{self.service_name}] 백프레셔 패턴 발동 - 과부하 상태")
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
            if use_circuit_breaker:
                self.logger.info(f"[{self.service_name}] 서킷브레이커 상태 확인 중...")
                if not self.circuit_breaker.allow_request():
                    self.logger.warning(f"[{self.service_name}] 서킷브레이커 오픈 상태 - 요청 차단됨")
                    context.set_code(grpc.StatusCode.UNAVAILABLE)
                    context.set_details("서비스 일시적으로 사용 불가")
                    if use_backpressure:
                        self.backpressure.complete_request()
                    return backend_pb2.BackendResponse(
                        success=False,
                        error_message="서킷브레이커가 오픈 상태입니다"
                    )
            
            # DB 서비스 호출
            try:
                # 데드라인 패턴 적용
                query_type = "slow" if request.request_type == "slow" else "normal"
                
                if use_deadline:
                    self.logger.info(f"[{self.service_name}] 데드라인 패턴 사용 ({self.deadline_handler.get_timeout()}초)")
                    response, error = self.deadline_handler.call_with_deadline(
                        db_stub.Query,
                        db_pb2.DbRequest(query_type=query_type)
                    )
                    
                    if error:
                        if use_circuit_breaker:
                            self.circuit_breaker.report_failure()
                        raise error
                else:
                    self.logger.info(f"[{self.service_name}] DB 서비스 호출 (데드라인 없음)")
                    response = db_stub.Query(db_pb2.DbRequest(query_type=query_type))
                
                # 성공 처리
                if use_circuit_breaker:
                    self.circuit_breaker.report_success()
                
                self.logger.info(f"[{self.service_name}] DB 응답 수신: {response.result}")
                if use_backpressure:
                    self.backpressure.complete_request()
                
                # 응답 반환
                return backend_pb2.BackendResponse(
                    result=f"{self.service_name} 처리 결과: {response.result}",
                    success=response.success,
                    error_message=response.error_message
                )
            
            except grpc.RpcError as e:
                if use_circuit_breaker:
                    self.circuit_breaker.report_failure()
                
                status_code = e.code()
                details = e.details()
                
                self.logger.error(f"[{self.service_name}] DB 호출 중 오류: {status_code} - {details}")
                
                if status_code == grpc.StatusCode.DEADLINE_EXCEEDED:
                    context.set_code(grpc.StatusCode.DEADLINE_EXCEEDED)
                    context.set_details("DB 서비스 응답 시간 초과")
                else:
                    context.set_code(status_code)
                    context.set_details(f"DB 서비스 오류: {details}")
                
                if use_backpressure:
                    self.backpressure.complete_request()
                    
                return backend_pb2.BackendResponse(
                    success=False,
                    error_message=f"DB 호출 오류: {details}"
                )
        
        except Exception as e:
            self.logger.exception(f"[{self.service_name}] 예기치 않은 오류")
            context.set_code(grpc.StatusCode.INTERNAL)
            context.set_details(f"내부 서버 오류: {str(e)}")
            
            if use_backpressure:
                self.backpressure.complete_request()
                
            return backend_pb2.BackendResponse(
                success=False,
                error_message=f"내부 서버 오류: {str(e)}"
            )
    
    def ResetPattern(self, request, context):
        pattern = request.pattern
        self.logger.info(f"[{self.service_name}] 패턴 리셋 요청: {pattern}")
        
        try:
            if pattern == "circuit_breaker" or pattern == "all":
                self.circuit_breaker.reset()
                self.logger.info(f"[{self.service_name}] 서킷브레이커 리셋 완료")
                
            if pattern == "backpressure" or pattern == "all":
                self.backpressure.reset()
                self.logger.info(f"[{self.service_name}] 백프레셔 리셋 완료")
            
            return backend_pb2.ResetResponse(
                success=True,
                message=f"{pattern} 패턴 리셋 완료"
            )
        except Exception as e:
            self.logger.exception(f"[{self.service_name}] 패턴 리셋 중 오류")
            context.set_code(grpc.StatusCode.INTERNAL)
            context.set_details(f"패턴 리셋 실패: {str(e)}")
            return backend_pb2.ResetResponse(
                success=False,
                message=f"리셋 실패: {str(e)}"
            )
    
    def GetStatus(self, request, context):
        self.logger.info(f"[{self.service_name}] 상태 확인 요청")
        
        try:
            return backend_pb2.StatusResponse(
                circuit_breaker_state=self.circuit_breaker.state,
                circuit_breaker_failures=self.circuit_breaker.failure_count,
                backpressure_active_requests=self.backpressure.active_requests,
                backpressure_overloaded=self.backpressure.is_overloaded()
            )
        except Exception as e:
            self.logger.exception(f"[{self.service_name}] 상태 조회 중 오류")
            context.set_code(grpc.StatusCode.INTERNAL)
            context.set_details(f"상태 조회 실패: {str(e)}")
            return backend_pb2.StatusResponse(
                circuit_breaker_state="ERROR",
                circuit_breaker_failures=0,
                backpressure_active_requests=0,
                backpressure_overloaded=False
            )

def run_server(service_name, port, use_circuit_breaker=False, use_deadline=False, use_backpressure=False):
    logger = setup_logging(f"{service_name}_server")
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
    
    # 환경 변수에서 포트 설정 가져오기 (지정된 값이 있으면 우선 사용)
    port = int(os.environ.get("PORT", port))
    
    backend_pb2_grpc.add_BackendServiceServicer_to_server(
        BaseBackendServicer(
            service_name=service_name,
            port=port,
            use_circuit_breaker=use_circuit_breaker,
            use_deadline=use_deadline,
            use_backpressure=use_backpressure
        ), 
        server
    )
    
    server.add_insecure_port(f"[::]:{port}")
    server.start()
    logger.info(f"{service_name} 서비스 시작됨: 포트 {port}")
    
    try:
        server.wait_for_termination()
    except KeyboardInterrupt:
        logger.info(f"{service_name} 서비스 종료 중...")
        server.stop(0)