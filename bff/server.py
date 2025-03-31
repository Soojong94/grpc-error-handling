from flask import Flask, jsonify, request
import grpc
import time
import threading
import pybreaker
import concurrent.futures
import functools
import sys
import os

# 상위 디렉토리 경로 추가
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# 서비스 프로토버프 모듈 임포트
import service_pb2
import service_pb2_grpc

# 공통 모듈
from common.logging_config import setup_logger, log_event, get_logs
from common.utils import track_metrics, get_metrics, pattern_status, update_pattern_status, add_event, get_events

# 로거 설정
logger = setup_logger("BFF")

app = Flask(__name__)

# CORS 설정 (프론트엔드와의 통신을 위함)
@app.after_request
def add_cors_headers(response):
    response.headers.add('Access-Control-Allow-Origin', '*')
    response.headers.add('Access-Control-Allow-Headers', 'Content-Type,Authorization')
    response.headers.add('Access-Control-Allow-Methods', 'GET,POST,PUT,DELETE,OPTIONS')
    return response

# 로그 필터링을 위한 추가
@app.before_request
def before_request():
    # 상태 확인 요청은 로깅하지 않음
    if request.path in ['/logs', '/patterns/status', '/metrics', '/events', '/health']:
        return None
    
    # API 요청 로깅
    log_event(logger, "INFO", f"API 요청: {request.method} {request.path}")

# 서킷 브레이커 설정
cb = pybreaker.CircuitBreaker(
    fail_max=3,  # 3번 실패하면 서킷 오픈
    reset_timeout=10,  # 10초 후 다시 시도
    exclude=[lambda e: isinstance(e, grpc.RpcError) and e.code() == grpc.StatusCode.NOT_FOUND]
)

# 서킷 브레이커 이벤트 리스너
class CircuitBreakerListener(pybreaker.CircuitBreakerListener):
    """서킷 브레이커 상태 변화 감지 리스너"""
    
    def state_change(self, cb, old_state, new_state):
        """상태 변경 이벤트 핸들러"""
        state_name = lambda state: "오픈" if state == "open" else "클로즈" if state == "closed" else "하프-오픈"
        old_name = state_name(old_state)
        new_name = state_name(new_state)
        
        log_event(logger, "WARNING" if new_state == "open" else "INFO", 
                 f"서킷 브레이커 상태 변경: {old_name} → {new_name}", "서킷브레이커")
        
        # 이벤트 기록
        add_event("circuit_breaker", f"서킷 브레이커: {old_name} → {new_name}", new_state)

# 리스너 등록
cb.add_listener(CircuitBreakerListener())

class GrpcClient:
    """백엔드 gRPC 서비스 클라이언트"""
    
    def __init__(self, server_address):
        try:
            self.server_address = server_address
            # 채널 옵션 추가
            self.channel = grpc.insecure_channel(
                server_address,
                options=[
                    ('grpc.max_send_message_length', 10 * 1024 * 1024),
                    ('grpc.max_receive_message_length', 10 * 1024 * 1024),
                    ('grpc.keepalive_time_ms', 20000),  # 20초마다 keepalive 핑
                    ('grpc.keepalive_timeout_ms', 10000),  # 10초 타임아웃
                    ('grpc.keepalive_permit_without_calls', 1),  # 호출이 없어도 핑 허용
                    ('grpc.http2.max_pings_without_data', 0),  # 데이터 없이 핑 제한 없음
                    ('grpc.http2.min_time_between_pings_ms', 10000),  # 핑 간 최소 간격
                    ('grpc.http2.min_ping_interval_without_data_ms', 5000)  # 데이터 없을 때 핑 간격
                ]
            )
            self.stub = service_pb2_grpc.UserServiceStub(self.channel)
            log_event(logger, "INFO", f"gRPC 클라이언트 초기화: {server_address}", "초기화")
        except Exception as e:
            log_event(logger, "ERROR", f"gRPC 클라이언트 초기화 실패: {str(e)}", "초기화")
            raise
    
    def get_user(self, user_id, timeout=None, delay=None):
        """사용자 정보 조회"""
        log_event(logger, "INFO", f"사용자 조회 요청 (ID: {user_id}, 타임아웃: {timeout if timeout else '없음'}초)")
        
        metadata = []
        if delay:
            metadata.append(('delay', str(delay)))
            log_event(logger, "INFO", f"지연 설정: {delay}초 (ID: {user_id})", "슬로우쿼리")
        
        request = service_pb2.UserRequest(user_id=user_id)
        
        try:
            start_time = time.time()
            response = self.stub.GetUser(
                request, 
                timeout=timeout,
                metadata=metadata
            )
            elapsed = time.time() - start_time
            log_event(logger, "INFO", f"사용자 조회 성공 (ID: {user_id}, 소요시간: {elapsed:.2f}초)")
            
            return {
                "user_id": response.user_id,
                "name": response.name,
                "email": response.email
            }
        except grpc.RpcError as e:
            elapsed = time.time() - start_time
            if e.code() == grpc.StatusCode.DEADLINE_EXCEEDED:
                log_event(logger, "ERROR", f"타임아웃 발생 (ID: {user_id}, 제한시간: {timeout}초, 경과시간: {elapsed:.2f}초)", "데드라인")
                
                # 이벤트 기록
                add_event("deadline", f"데드라인 초과: 사용자 조회 (ID: {user_id}, {elapsed:.2f}초)")
                
            elif e.code() == grpc.StatusCode.RESOURCE_EXHAUSTED:
                log_event(logger, "ERROR", f"요청 거부됨 (ID: {user_id}, 경과시간: {elapsed:.2f}초)", "백프레셔")
                
                # 이벤트 기록
                add_event("backpressure", f"백프레셔: 사용자 조회 거부 (ID: {user_id})")
                
            else:
                log_event(logger, "ERROR", f"gRPC 에러 발생: {e.code()} - {e.details()} (ID: {user_id}, 경과시간: {elapsed:.2f}초)")
            raise
        except Exception as e:
            elapsed = time.time() - start_time
            log_event(logger, "ERROR", f"예상치 못한 에러: {str(e)} (ID: {user_id}, 경과시간: {elapsed:.2f}초)")
            raise
    
    def list_users(self, page=1, page_size=10, timeout=None, delay=None):
        """사용자 목록 조회"""
        log_event(logger, "INFO", f"사용자 목록 조회 요청 (페이지: {page}, 페이지 크기: {page_size})")
        
        metadata = []
        if delay:
            metadata.append(('delay', str(delay)))
            log_event(logger, "INFO", f"지연 설정: {delay}초 (목록 조회)", "슬로우쿼리")
        
        request = service_pb2.ListUsersRequest(page=page, page_size=page_size)
        
        try:
            start_time = time.time()
            response = self.stub.ListUsers(
                request, 
                timeout=timeout,
                metadata=metadata
            )
            elapsed = time.time() - start_time
            
            users = []
            for user in response.users:
                users.append({
                    "user_id": user.user_id,
                    "name": user.name,
                    "email": user.email
                })
            
            log_event(logger, "INFO", f"사용자 목록 조회 성공 ({len(users)}명, 소요시간: {elapsed:.2f}초)")
            return {
                "users": users,
                "total_count": response.total_count
            }
        except grpc.RpcError as e:
            elapsed = time.time() - start_time
            if e.code() == grpc.StatusCode.DEADLINE_EXCEEDED:
                log_event(logger, "ERROR", f"타임아웃 발생 (목록 조회, 제한시간: {timeout}초, 경과시간: {elapsed:.2f}초)", "데드라인")
                
                # 이벤트 기록
                add_event("deadline", f"데드라인 초과: 사용자 목록 조회 ({elapsed:.2f}초)")
                
            elif e.code() == grpc.StatusCode.RESOURCE_EXHAUSTED:
                log_event(logger, "ERROR", f"요청 거부됨 (목록 조회, 경과시간: {elapsed:.2f}초)", "백프레셔")
                
                # 이벤트 기록
                add_event("backpressure", "백프레셔: 사용자 목록 조회 거부")
                
            else:
                log_event(logger, "ERROR", f"gRPC 에러 발생: {e.code()} - {e.details()} (목록 조회, 경과시간: {elapsed:.2f}초)")
            raise
        except Exception as e:
            elapsed = time.time() - start_time
            log_event(logger, "ERROR", f"예상치 못한 에러: {str(e)} (목록 조회, 경과시간: {elapsed:.2f}초)")
            raise
    
    def set_error_rate(self, error_rate):
        """에러 발생률 설정"""
        log_event(logger, "INFO", f"에러 발생률 설정: {error_rate}%", "설정")
        try:
            metadata = [('error_rate', str(error_rate))]
            request = service_pb2.ListUsersRequest(page=1, page_size=1)
            self.stub.ListUsers(request, metadata=metadata, timeout=3)  # 타임아웃 추가
            
            # 이벤트 기록
            add_event("settings", f"에러율 설정: {error_rate}%")
            
            return True
        except Exception as e:
            log_event(logger, "ERROR", f"에러율 설정 중 오류: {str(e)}")
            return False
    
    def set_backpressure_enabled(self, enabled):
        """백프레셔 활성화/비활성화"""
        status = "활성화" if enabled else "비활성화"
        log_event(logger, "INFO", f"백프레셔 {status} 설정", "설정")
        try:
            metadata = [('backpressure_enabled', str(enabled).lower())]
            request = service_pb2.ListUsersRequest(page=1, page_size=1)
            self.stub.ListUsers(request, metadata=metadata, timeout=3)  # 타임아웃 추가
            
            # 이벤트 기록
            add_event("settings", f"백프레셔 {status}")
            
            return True
        except Exception as e:
            log_event(logger, "ERROR", f"백프레셔 상태 변경 중 오류: {str(e)}")
            return False
    
    def reset_backpressure(self):
        """백프레셔 초기화"""
        log_event(logger, "INFO", "백프레셔 초기화 요청", "백프레셔")
        try:
            metadata = [('reset_backpressure', 'true')]
            request = service_pb2.ListUsersRequest(page=1, page_size=1)
            self.stub.ListUsers(request, metadata=metadata, timeout=3)  # 타임아웃 추가
            
            # 이벤트 기록
            add_event("backpressure", "백프레셔 수동 초기화")
            
            return True
        except Exception as e:
            log_event(logger, "ERROR", f"백프레셔 초기화 중 오류: {str(e)}")
            return False
    
    def create_user(self, name, email, timeout=None):
        """사용자 생성"""
        log_event(logger, "INFO", f"사용자 생성 (이름: {name}, 이메일: {email})")
        
        request = service_pb2.CreateUserRequest(name=name, email=email)
        
        try:
            start_time = time.time()
            response = self.stub.CreateUser(request, timeout=timeout)
            elapsed = time.time() - start_time
            
            log_event(logger, "INFO", f"사용자 생성 성공 (ID: {response.user_id}, 소요시간: {elapsed:.2f}초)")
            
            return {
                "user_id": response.user_id,
                "name": response.name,
                "email": response.email
            }
        except grpc.RpcError as e:
            elapsed = time.time() - start_time
            log_event(logger, "ERROR", f"gRPC 에러 발생: {e.code()} - {e.details()} (사용자 생성, 경과시간: {elapsed:.2f}초)")
            raise
        except Exception as e:
            elapsed = time.time() - start_time
            log_event(logger, "ERROR", f"예상치 못한 에러: {str(e)} (사용자 생성, 경과시간: {elapsed:.2f}초)")
            raise

# gRPC 클라이언트 초기화
try:
    client = GrpcClient('localhost:50051')
    log_event(logger, "INFO", "gRPC 클라이언트 생성 성공", "초기화")
    
    # 서버 시작 이벤트 기록
    add_event("system", "BFF 서버 시작됨")
    
except Exception as e:
    log_event(logger, "ERROR", f"gRPC 클라이언트 생성 실패: {str(e)}", "초기화")
    client = None

# API 엔드포인트

@app.route('/health')
def health_check():
    """BFF 상태 확인"""
    return jsonify({"status": "ok", "service": "bff"})

@app.route('/users')
@track_metrics
def get_users():
    """사용자 목록 조회"""
    try:
        # 클라이언트가 초기화되지 않았을 경우 처리
        if client is None:
            log_event(logger, "ERROR", "gRPC 클라이언트가 초기화되지 않았습니다", "초기화")
            return jsonify({"error": "서비스를 사용할 수 없습니다"}), 503
            
        page = int(request.args.get('page', 1))
        page_size = int(request.args.get('page_size', 10))
        
        # 서킷 브레이커 적용
        if pattern_status["circuit_breaker"]:
            log_event(logger, "INFO", "서킷 브레이커 패턴 적용", "서킷브레이커")
            
            @cb
            def get_users_with_cb():
                timeout = 5 if pattern_status["deadline"] else None
                return client.list_users(page, page_size, timeout=timeout)
            
            result = get_users_with_cb()
        else:
            log_event(logger, "INFO", "서킷 브레이커 패턴 비활성화 - 직접 호출", "서킷브레이커")
            timeout = 5 if pattern_status["deadline"] else None
            result = client.list_users(page, page_size, timeout=timeout)
        
        return jsonify(result)
    except pybreaker.CircuitBreakerError:
        log_event(logger, "ERROR", "서킷 브레이커 오픈 상태 - 요청 거부", "서킷브레이커")
        return jsonify({"error": "서비스 일시적으로 사용 불가능 (서킷 브레이커 개방)"}), 503
    except grpc.RpcError as e:
        if e.code() == grpc.StatusCode.DEADLINE_EXCEEDED:
            log_event(logger, "ERROR", "요청 타임아웃", "데드라인")
            return jsonify({"error": "요청 시간 초과 (데드라인 초과)"}), 504
        elif e.code() == grpc.StatusCode.RESOURCE_EXHAUSTED:
            log_event(logger, "ERROR", "요청 거부", "백프레셔")
            return jsonify({"error": "서버 과부하로 요청 거부 (백프레셔)"}), 503
        log_event(logger, "ERROR", f"gRPC 오류: {e.code()} - {e.details()}")
        return jsonify({"error": f"서비스 오류: {e.code()} - {e.details()}"}), 500
    except Exception as e:
        log_event(logger, "ERROR", f"사용자 목록 조회 실패: {str(e)}")
        return jsonify({"error": str(e)}), 500

@app.route('/users/<int:user_id>')
@track_metrics
def get_user(user_id):
    """단일 사용자 조회"""
    try:
        # 클라이언트가 초기화되지 않았을 경우 처리
        if client is None:
            log_event(logger, "ERROR", "gRPC 클라이언트가 초기화되지 않았습니다", "초기화")
            return jsonify({"error": "서비스를 사용할 수 없습니다"}), 503
            
        # 데드라인 패턴 적용 여부
        if pattern_status["deadline"]:
            timeout = int(request.args.get('timeout', 5))
            log_event(logger, "INFO", f"데드라인 패턴 적용 - 타임아웃: {timeout}초", "데드라인")
        else:
            timeout = None
            log_event(logger, "INFO", "데드라인 패턴 비활성화 - 타임아웃 없음", "데드라인")
        
        # 서킷 브레이커 패턴 적용 여부
        if pattern_status["circuit_breaker"]:
            log_event(logger, "INFO", "서킷 브레이커 패턴 적용", "서킷브레이커")
            
            @cb
            def get_user_with_cb():
                return client.get_user(user_id, timeout=timeout)
            
            user = get_user_with_cb()
        else:
            log_event(logger, "INFO", "서킷 브레이커 패턴 비활성화 - 직접 호출", "서킷브레이커")
            user = client.get_user(user_id, timeout=timeout)
        
        return jsonify(user)
    except pybreaker.CircuitBreakerError:
        log_event(logger, "ERROR", "서킷 브레이커 오픈 상태 - 요청 거부", "서킷브레이커")
        return jsonify({"error": "서비스 일시적으로 사용 불가능 (서킷 브레이커 개방)"}), 503
    except grpc.RpcError as e:
        if e.code() == grpc.StatusCode.DEADLINE_EXCEEDED:
            log_event(logger, "ERROR", f"요청 타임아웃 (ID: {user_id})", "데드라인")
            return jsonify({"error": "요청 시간 초과 (데드라인 초과)"}), 504
        elif e.code() == grpc.StatusCode.RESOURCE_EXHAUSTED:
            log_event(logger, "ERROR", f"요청 거부 (ID: {user_id})", "백프레셔")
            return jsonify({"error": "서버 과부하로 요청 거부 (백프레셔)"}), 503
        elif e.code() == grpc.StatusCode.NOT_FOUND:
            log_event(logger, "WARNING", f"사용자를 찾을 수 없음 (ID: {user_id})")
            return jsonify({"error": f"ID가 {user_id}인 사용자를 찾을 수 없습니다"}), 404
        log_event(logger, "ERROR", f"gRPC 오류: {e.code()} - {e.details()}")
        return jsonify({"error": f"서비스 오류: {e.code()} - {e.details()}"}), 500
    except Exception as e:
        log_event(logger, "ERROR", f"사용자 조회 실패: {str(e)}")
        return jsonify({"error": str(e)}), 500

@app.route('/test/slow-query')
@track_metrics
def test_slow_query():
    """슬로우 쿼리 테스트"""
    # 클라이언트가 초기화되지 않았을 경우 처리
    if client is None:
        log_event(logger, "ERROR", "gRPC 클라이언트가 초기화되지 않았습니다", "초기화")
        return jsonify({"error": "서비스를 사용할 수 없습니다"}), 503
        
    # 테스트 파라미터
    try:
        query_delay = int(request.args.get('delay', 5))  # 쿼리 지연 시간(초)
        concurrent_requests = int(request.args.get('requests', 10))  # 동시 요청 수
        timeout = int(request.args.get('timeout', 3))  # 타임아웃 설정(초)
    except ValueError as e:
        log_event(logger, "ERROR", f"잘못된 파라미터: {str(e)}")
        return jsonify({"error": "잘못된 파라미터 형식"}), 400
    
    log_event(logger, "INFO", f"슬로우 쿼리 테스트 시작 (지연: {query_delay}초, 동시 요청: {concurrent_requests}개, 타임아웃: {timeout}초)", "테스트")
    
    # 이벤트 기록
    add_event("test", f"슬로우 쿼리 테스트 시작 (지연: {query_delay}초, 요청: {concurrent_requests}개)")
    
    # 서킷 브레이커 초기화
    if pattern_status["circuit_breaker"]:
        cb.close()
        log_event(logger, "INFO", "서킷 브레이커 초기화 (닫힌 상태)", "서킷브레이커")
        
        # 이벤트 기록
        add_event("circuit_breaker", "서킷 브레이커 수동 초기화 (CLOSED)")
    
    # 테스트 결과 저장
    results = {
        "total_requests": concurrent_requests,
        "success_count": 0,
        "deadline_exceeded": 0,
        "circuit_broken": 0,
        "backpressure_rejected": 0,
        "other_errors": 0,
        "details": []
    }
    
    # 동시에 여러 요청 실행
    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
        futures = []
        
        for i in range(concurrent_requests):
            def execute_slow_query(request_id):
                start_time = time.time()
                try:
                    log_event(logger, "INFO", f"요청 {request_id}: 슬로우 쿼리 실행 (지연: {query_delay}초)", "테스트")
                    
                    # 데드라인 패턴 적용 여부
                    actual_timeout = timeout if pattern_status["deadline"] else None
                    if pattern_status["deadline"]:
                        log_event(logger, "INFO", f"요청 {request_id}: 데드라인 패턴 적용 (타임아웃: {actual_timeout}초)", "데드라인")
                    
                    # 서킷 브레이커 패턴 적용 여부
                    if pattern_status["circuit_breaker"]:
                        log_event(logger, "INFO", f"요청 {request_id}: 서킷 브레이커 패턴 적용", "서킷브레이커")
                        
                        @cb
                        def call_with_cb():
                            return client.get_user(1, timeout=actual_timeout, delay=query_delay)
                        
                        result = call_with_cb()
                    else:
                        log_event(logger, "INFO", f"요청 {request_id}: 서킷 브레이커 패턴 비활성화", "서킷브레이커")
                        result = client.get_user(1, timeout=actual_timeout, delay=query_delay)
                    
                    elapsed = time.time() - start_time
                    log_event(logger, "INFO", f"요청 {request_id}: 성공 (소요시간: {elapsed:.2f}초)", "테스트")
                    return {
                        "request_id": request_id,
                        "status": "success",
                        "elapsed": elapsed
                    }
                except pybreaker.CircuitBreakerError:
                    elapsed = time.time() - start_time
                    log_event(logger, "ERROR", f"요청 {request_id}: 서킷 브레이커 오픈 (소요시간: {elapsed:.2f}초)", "서킷브레이커")
                    return {
                        "request_id": request_id,
                        "status": "circuit_broken",
                        "elapsed": elapsed
                    }
                except grpc.RpcError as e:
                    elapsed = time.time() - start_time
                    if e.code() == grpc.StatusCode.DEADLINE_EXCEEDED:
                        log_event(logger, "ERROR", f"요청 {request_id}: 데드라인 초과 (소요시간: {elapsed:.2f}초)", "데드라인")
                        return {
                            "request_id": request_id,
                            "status": "deadline_exceeded",
                            "elapsed": elapsed
                        }
                    elif e.code() == grpc.StatusCode.RESOURCE_EXHAUSTED:
                        log_event(logger, "ERROR", f"요청 {request_id}: 백프레셔에 의한 거부 (소요시간: {elapsed:.2f}초)", "백프레셔")
                        return {
                            "request_id": request_id,
                            "status": "backpressure_rejected",
                            "elapsed": elapsed
                        }
                    else:
                        log_event(logger, "ERROR", f"요청 {request_id}: gRPC 오류 - {e.code()} - {e.details()} (소요시간: {elapsed:.2f}초)")
                        return {
                            "request_id": request_id,
                            "status": "error",
                            "error_code": str(e.code()),
                            "error_details": e.details(),
                            "elapsed": elapsed
                        }
                except Exception as e:
                    elapsed = time.time() - start_time
                    log_event(logger, "ERROR", f"요청 {request_id}: 오류 발생 - {str(e)} (소요시간: {elapsed:.2f}초)")
                    return {
                        "request_id": request_id,
                        "status": "error",
                        "error": str(e),
                        "elapsed": elapsed
                    }
            
            futures.append(executor.submit(execute_slow_query, i+1))
        
        # 결과 수집
        for future in concurrent.futures.as_completed(futures):
            try:
                result = future.result()
                results["details"].append(result)
                
                # 상태별 카운트 업데이트
                if result["status"] == "success":
                    results["success_count"] += 1
                elif result["status"] == "deadline_exceeded":
                    results["deadline_exceeded"] += 1
                elif result["status"] == "circuit_broken":
                    results["circuit_broken"] += 1
                elif result["status"] == "backpressure_rejected":
                    results["backpressure_rejected"] += 1
                else:
                    results["other_errors"] += 1
            except Exception as e:
                log_event(logger, "ERROR", f"결과 처리 중 오류: {str(e)}")
    
    # 활성화된 패턴 목록
    active_patterns = []
    if pattern_status["deadline"]:
        active_patterns.append("데드라인")
    if pattern_status["circuit_breaker"]:
        active_patterns.append("서킷 브레이커")
    if pattern_status["backpressure"]:
        active_patterns.append("백프레셔")
    
    # 패턴별 효과 분석
    pattern_effects = {}
    
    if pattern_status["deadline"]:
        effectiveness = min(results["deadline_exceeded"] / max(concurrent_requests, 1), 1.0)
        pattern_effects["deadline"] = {
            "name": "데드라인 패턴",
            "effectiveness": effectiveness,
            "comment": f"데드라인 패턴이 {results['deadline_exceeded']}개의 느린 요청을 차단했습니다."
        }
    
    if pattern_status["circuit_breaker"]:
        effectiveness = min(results["circuit_broken"] / max(concurrent_requests, 1), 1.0)
        pattern_effects["circuit_breaker"] = {
            "name": "서킷 브레이커 패턴",
            "effectiveness": effectiveness,
            "comment": f"서킷 브레이커 패턴이 {results['circuit_broken']}개의 요청을 차단했습니다."
        }
    
    if pattern_status["backpressure"]:
        effectiveness = min(results["backpressure_rejected"] / max(concurrent_requests, 1), 1.0)
        pattern_effects["backpressure"] = {
            "name": "백프레셔 패턴",
            "effectiveness": effectiveness,
            "comment": f"백프레셔 패턴이 {results['backpressure_rejected']}개의 요청을 거부했습니다."
        }
    
    # 요약 메시지
    summary = f"슬로우 쿼리 테스트 완료 - 활성화된 패턴: {', '.join(active_patterns) if active_patterns else '없음'}\n"
    summary += f"총 {concurrent_requests}개 요청 중:\n"
    summary += f"- 성공: {results['success_count']}개\n"
    summary += f"- 데드라인 초과: {results['deadline_exceeded']}개\n"
    summary += f"- 서킷 브레이커 차단: {results['circuit_broken']}개\n"
    summary += f"- 백프레셔 거부: {results['backpressure_rejected']}개\n"
    summary += f"- 기타 오류: {results['other_errors']}개"
    
    log_event(logger, "INFO", summary, "테스트")
    
    # 테스트 완료 이벤트 기록
    add_event("test", f"슬로우 쿼리 테스트 완료 (성공: {results['success_count']}, 실패: {concurrent_requests - results['success_count']})")
    
    return jsonify({
        "summary": summary,
        "active_patterns": active_patterns,
        "results": results,
        "pattern_effects": pattern_effects
    })

# 패턴 상태 조회 API
@app.route('/patterns/status')
def get_pattern_status():
    """에러 처리 패턴 상태 조회"""
    # 로깅 없이 바로 응답
    return jsonify(pattern_status)

# 패턴 활성화/비활성화 API
@app.route('/patterns/<pattern>', methods=['POST'])
def toggle_pattern(pattern):
    """에러 처리 패턴 활성화/비활성화"""
    if pattern not in pattern_status:
        log_event(logger, "ERROR", f"알 수 없는 패턴: {pattern}")
        return jsonify({"error": f"알 수 없는 패턴: {pattern}"}), 400
    
    try:
        data = request.json
        if data is None:
            log_event(logger, "ERROR", "요청 본문이 JSON 형식이 아닙니다")
            return jsonify({"error": "요청 본문이 JSON 형식이 아닙니다"}), 400
            
        status = data.get('status', None)
        if status is None:
            log_event(logger, "ERROR", "status 필드가 필요합니다")
            return jsonify({"error": "status 필드가 필요합니다"}), 400
        
        # 이전 상태
        old_status = pattern_status[pattern]
        
        # 상태 변경
        update_pattern_status(pattern, bool(status))
        
        # 상태 문자열 변환
        status_str = "활성화" if status else "비활성화"
        log_event(logger, "INFO", f"패턴 {pattern} {status_str} 됨", "설정")
        
        # 백프레셔 패턴 설정 변경 시 백엔드에도 알림
        if pattern == "backpressure" and client is not None:
            try:
                result = client.set_backpressure_enabled(status)
                if not result:
                    log_event(logger, "WARNING", "백엔드 백프레셔 상태 변경 요청은 실패했지만, BFF의 설정은 변경되었습니다", "백프레셔")
            except Exception as e:
                log_event(logger, "ERROR", f"백엔드 백프레셔 상태 변경 실패: {str(e)}", "백프레셔")
        
        return jsonify({
            "pattern": pattern,
            "status": pattern_status[pattern],
            "previousStatus": old_status
        })
    except Exception as e:
        log_event(logger, "ERROR", f"패턴 설정 변경 중 오류: {str(e)}")
        return jsonify({"error": f"패턴 설정 변경 중 오류: {str(e)}"}), 500

# 서킷 브레이커 상태 조회 API
@app.route('/circuit-breaker/status')
def circuit_breaker_status():
    """서킷 브레이커 상태 조회"""
    state = "OPEN" if cb.current_state == "open" else "CLOSED" if cb.current_state == "closed" else "HALF-OPEN"
    
    return jsonify({
        "state": state,
        "failure_count": cb.fail_counter,
        "reset_timeout": cb.reset_timeout,
        "remaining_recovery_time": max(0, (cb._last_attempt + cb.reset_timeout) - time.time()) if state == "OPEN" else 0
    })

# 서킷 브레이커 초기화 API
@app.route('/circuit-breaker/reset', methods=['POST'])
def reset_circuit_breaker():
    """서킷 브레이커 초기화"""
    log_event(logger, "INFO", "서킷 브레이커 초기화 요청", "서킷브레이커")
    try:
        # 서킷 브레이커 상태 기록
        old_state = "OPEN" if cb.current_state == "open" else "CLOSED" if cb.current_state == "closed" else "HALF-OPEN"
        
        cb.close()
        log_event(logger, "INFO", "서킷 브레이커 초기화 완료 (상태: CLOSED)", "서킷브레이커")
        
        # 이벤트 기록
        add_event("circuit_breaker", f"서킷 브레이커 초기화: {old_state} → CLOSED")
        
        return jsonify({
            "status": "success",
            "message": "서킷 브레이커가 초기화되었습니다",
            "previous_state": old_state,
            "current_state": "CLOSED"
        })
    except Exception as e:
        log_event(logger, "ERROR", f"서킷 브레이커 초기화 실패: {str(e)}", "서킷브레이커")
        return jsonify({
            "status": "error",
            "message": f"초기화 실패: {str(e)}"
        }), 500

# 백엔드 에러율 설정 API
@app.route('/backend/error-rate', methods=['POST'])
def set_error_rate():
    """백엔드 에러율 설정"""
    try:
        # 클라이언트가 초기화되지 않았을 경우 처리
        if client is None:
            log_event(logger, "ERROR", "gRPC 클라이언트가 초기화되지 않았습니다", "초기화")
            return jsonify({"error": "서비스를 사용할 수 없습니다"}), 503
            
        data = request.json
        if data is None:
            log_event(logger, "ERROR", "요청 본문이 JSON 형식이 아닙니다")
            return jsonify({"error": "요청 본문이 JSON 형식이 아닙니다"}), 400
            
        error_rate = data.get('error_rate', 0)
        log_event(logger, "INFO", f"백엔드 에러율 설정 요청: {error_rate}%", "설정")
        
        result = client.set_error_rate(error_rate)
        if result:
            return jsonify({
                "status": "success",
                "message": f"에러율이 {error_rate}%로 설정되었습니다"
            })
        else:
            return jsonify({
                "status": "warning",
                "message": "에러율 설정 요청은 실패했을 수 있습니다"
            }), 500
    except Exception as e:
        log_event(logger, "ERROR", f"에러율 설정 실패: {str(e)}")
        return jsonify({
            "status": "error",
            "message": f"설정 실패: {str(e)}"
        }), 500

# 백프레셔 초기화 API
@app.route('/backend/reset-backpressure', methods=['POST'])
def reset_backpressure():
    """백엔드 백프레셔 초기화"""
    try:
        # 클라이언트가 초기화되지 않았을 경우 처리
        if client is None:
            log_event(logger, "ERROR", "gRPC 클라이언트가 초기화되지 않았습니다", "초기화")
            return jsonify({"error": "서비스를 사용할 수 없습니다"}), 503
            
        log_event(logger, "INFO", "백프레셔 초기화 요청", "백프레셔")
        result = client.reset_backpressure()
        if result:
            log_event(logger, "INFO", "백프레셔 초기화 완료", "백프레셔")
            return jsonify({
                "status": "success",
                "message": "백프레셔가 초기화되었습니다"
            })
        else:
            return jsonify({
                "status": "warning",
                "message": "백프레셔 초기화 요청은 실패했을 수 있습니다"
            }), 500
    except Exception as e:
        log_event(logger, "ERROR", f"백프레셔 초기화 실패: {str(e)}", "백프레셔")
        return jsonify({
            "status": "error",
            "message": f"초기화 실패: {str(e)}"
        }), 500

# 로그 조회 API
@app.route('/logs')
def get_all_logs():
    """로그 조회 API"""
    pattern = request.args.get('pattern', None)
    level = request.args.get('level', None)
    limit = int(request.args.get('limit', 100))
    
    # 로깅하지 않고 바로 응답
    return jsonify(get_logs(pattern, level, limit))

# 이벤트 조회 API
@app.route('/events')
def get_all_events():
    """이벤트 조회 API"""
    limit = int(request.args.get('limit', 50))
    return jsonify(get_events(limit))

# 메트릭 조회 API
@app.route('/metrics')
def get_all_metrics():
    """메트릭 조회 API"""
    # 로깅하지 않고 바로 응답
    return jsonify(get_metrics())

if __name__ == '__main__':
    # 디버그 모드 활성화
    app.run(host='0.0.0.0', port=8000, threaded=True)