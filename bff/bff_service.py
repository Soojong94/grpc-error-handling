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
            name="bff_to_backend"
        )
        self.backpressure = BackpressureController(
            window_size=backpressure_window,
            max_requests=backpressure_max_requests,
            max_concurrency=backpressure_max_concurrency,
            name="bff"
        )
        self.deadline_handler = DeadlineHandler(
            timeout_seconds=deadline_timeout,
            name="bff_to_backend"
        )
        
        # Backend 서비스 주소 매핑 (환경 변수에서 읽기)
        self.backend_addresses = {
            'no_pattern': os.environ.get('BACKEND_NO_PATTERN_ADDRESS', 'localhost:50052'),
            'circuit_breaker': os.environ.get('BACKEND_CIRCUIT_BREAKER_ADDRESS', 'localhost:50053'),
            'deadline': os.environ.get('BACKEND_DEADLINE_ADDRESS', 'localhost:50054'),
            'backpressure': os.environ.get('BACKEND_BACKPRESSURE_ADDRESS', 'localhost:50055'),
            'all': os.environ.get('BACKEND_ALL_PATTERNS_ADDRESS', 'localhost:50056')
        }
        
        self.logger.info(f"BFF 서비스 초기화 - 백엔드 주소: {self.backend_addresses}")
    
    def Process(self, request, context):
        backend_type = request.backend_type if request.backend_type else 'no_pattern'
        
        self.logger.info(f"[BFF] 요청 받음: {request.request_type}, 백엔드 타입: {backend_type}")
        self.logger.info(f"[BFF] 패턴 설정 - 서킷브레이커: {request.use_circuit_breaker}, " +
                        f"데드라인: {request.use_deadline}, 백프레셔: {request.use_backpressure}")
        
        # 백프레셔 패턴 적용
        if request.use_backpressure:
            if not self.backpressure.register_request():
                # 과부하 상태로 요청 거부
                self.logger.warning(f"[BFF] 백프레셔 패턴 발동 - 과부하 상태")
                context.set_code(grpc.StatusCode.RESOURCE_EXHAUSTED)
                context.set_details("서버 과부하 상태입니다. 잠시 후 다시 시도해주세요.")
                return bff_pb2.BffResponse(
                    success=False,
                    error_message="서버 과부하 상태"
                )
        
        try:
            # 백엔드 주소 선택
            backend_address = self.backend_addresses.get(backend_type, self.backend_addresses['no_pattern'])
            self.logger.info(f"[BFF] 연결할 백엔드 서비스: {backend_address}")
            
            backend_channel = grpc.insecure_channel(backend_address)
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
    
    def ResetPattern(self, request, context):
        pattern = request.pattern
        backend_type = request.backend_type if request.backend_type else 'no_pattern'
        
        self.logger.info(f"[BFF] 패턴 리셋 요청: {pattern}, 백엔드: {backend_type}")
        
        try:
            # 로컬 BFF 패턴 리셋
            if pattern == "circuit_breaker" or pattern == "all":
                self.circuit_breaker.reset()
                self.logger.info("[BFF] 서킷브레이커 리셋 완료")
                
            if pattern == "backpressure" or pattern == "all":
                self.backpressure.reset()
                self.logger.info("[BFF] 백프레셔 리셋 완료")
            
            # 백엔드 서비스 패턴 리셋 (선택적)
            if backend_type != 'none':
                try:
                    backend_address = self.backend_addresses.get(backend_type, self.backend_addresses['no_pattern'])
                    backend_channel = grpc.insecure_channel(backend_address)
                    backend_stub = backend_pb2_grpc.BackendServiceStub(backend_channel)
                    
                    reset_request = backend_pb2.ResetRequest(pattern=pattern)
                    backend_stub.ResetPattern(reset_request)
                    self.logger.info(f"[BFF] 백엔드({backend_type}) 패턴 리셋 요청 완료")
                except Exception as e:
                    self.logger.error(f"[BFF] 백엔드 패턴 리셋 중 오류: {str(e)}")
            
            return bff_pb2.ResetResponse(
                success=True,
                message=f"{pattern} 패턴 리셋 완료"
            )
        except Exception as e:
            self.logger.exception("[BFF] 패턴 리셋 중 오류")
            context.set_code(grpc.StatusCode.INTERNAL)
            context.set_details(f"패턴 리셋 실패: {str(e)}")
            return bff_pb2.ResetResponse(
                success=False,
                message=f"리셋 실패: {str(e)}"
            )
    
    def GetStatus(self, request, context):
        backend_type = request.backend_type if request.backend_type else 'no_pattern'
        self.logger.info(f"[BFF] 상태 확인 요청: 백엔드={backend_type}")
        
        try:
            # BFF 자체 상태 정보
            circuit_breaker_state = self.circuit_breaker.state
            circuit_breaker_failures = self.circuit_breaker.failure_count
            backpressure_active = self.backpressure.active_requests
            backpressure_overloaded = self.backpressure.is_overloaded()
            
            # 백엔드 상태 확인 (선택적)
            backend_status = {
                "circuit_breaker_state": "UNKNOWN",
                "circuit_breaker_failures": 0,
                "backpressure_active_requests": 0,
                "backpressure_overloaded": False
            }
            
            if backend_type != 'none':
                try:
                    backend_address = self.backend_addresses.get(backend_type, self.backend_addresses['no_pattern'])
                    backend_channel = grpc.insecure_channel(backend_address)
                    backend_stub = backend_pb2_grpc.BackendServiceStub(backend_channel)
                    
                    status_request = backend_pb2.StatusRequest()
                    response = backend_stub.GetStatus(status_request)
                    
                    backend_status = {
                        "circuit_breaker_state": response.circuit_breaker_state,
                        "circuit_breaker_failures": response.circuit_breaker_failures,
                        "backpressure_active_requests": response.backpressure_active_requests,
                        "backpressure_overloaded": response.backpressure_overloaded
                    }
                    
                    self.logger.info(f"[BFF] 백엔드({backend_type}) 상태 조회 완료")
                except Exception as e:
                    self.logger.error(f"[BFF] 백엔드 상태 조회 중 오류: {str(e)}")
            
            return bff_pb2.StatusResponse(
                circuit_breaker_state=circuit_breaker_state,
                circuit_breaker_failures=circuit_breaker_failures,
                backpressure_active_requests=backpressure_active,
                backpressure_overloaded=backpressure_overloaded,
                success=True,
                error_message=""
            )
        except Exception as e:
            self.logger.exception("[BFF] 상태 조회 중 오류")
            return bff_pb2.StatusResponse(
                success=False,
                error_message=f"상태 조회 실패: {str(e)}"
            )

def serve():
    logger = setup_logging("bff_server")
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
    bff_pb2_grpc.add_BffServiceServicer_to_server(BffServicer(), server)
    
    port = int(os.environ.get("PORT", "50051"))  # 환경 변수에서 포트 읽기
    server.add_insecure_port(f"[::]:{port}")
    server.start()
    logger.info(f"BFF 서비스 시작됨: 포트 {port}")
    
    try:
        server.wait_for_termination()
    except KeyboardInterrupt:
        logger.info("BFF 서비스 종료 중...")
        server.stop(0)

if __name__ == "__main__":
    serve()