from flask import Flask, jsonify, request
import grpc
import time
import threading
import pybreaker
import concurrent.futures
import functools
import sys
import os
import json

# 프로젝트 루트 디렉토리를 명확하게 sys.path에 추가
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

# 서비스 프로토버프 모듈 임포트
import service_pb2
import service_pb2_grpc

# 공통 모듈
from common.logging_config import setup_logger, log_event, get_logs, get_events, add_event
from common.utils import track_metrics, get_metrics, reset_metrics, update_pattern_status, get_pattern_status, event_serializer
from grpc_client import UserServiceClient

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
    if request.path in ['/logs', '/patterns/status', '/metrics', '/events', '/health', '/circuit-breaker/status']:
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

# gRPC 클라이언트 초기화
try:
    client = UserServiceClient('localhost:50051')
    log_event(logger, "INFO", "gRPC 클라이언트 생성 성공", "초기화")
    
    # 서버 시작 이벤트 기록
    add_event("system", "BFF 서버 시작됨")
    
except Exception as e:
    log_event(logger, "ERROR", f"gRPC 클라이언트 생성 실패: {str(e)}", "초기화")
    client = None

# 클라이언트 상태 정기 확인 스레드
def health_check_thread():
    """주기적으로 백엔드 서비스 상태 확인"""
    while True:
        try:
            # 클라이언트 상태 확인
            if client:
                client.check_health()
                log_event(logger, "INFO", "백엔드 서비스 상태 확인 성공")
            else:
                log_event(logger, "WARNING", "gRPC 클라이언트가 초기화되지 않음")
        except Exception as e:
            log_event(logger, "ERROR", f"백엔드 서비스 상태 확인 실패: {str(e)}")
        
        # 30초 대기
        time.sleep(30)

# 상태 확인 스레드 시작
health_thread = threading.Thread(target=health_check_thread, daemon=True)
health_thread.start()

# API 엔드포인트

@app.route('/health')
def health_check():
    """BFF 상태 확인"""
    status = {
        "service": "bff",
        "status": "ok"
    }
    
    # 백엔드 상태 추가
    if client:
        try:
            backend_status = client.get_status()
            status["backend"] = {
                "available": backend_status.get("available", False),
                "last_error": backend_status.get("last_error", None)
            }
        except Exception as e:
            status["backend"] = {
                "available": False,
                "last_error": str(e)
            }
    else:
        status["backend"] = {
            "available": False,
            "last_error": "gRPC 클라이언트가 초기화되지 않음"
        }
    
    return jsonify(status)

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
        if get_pattern_status()["circuit_breaker"]:
            log_event(logger, "INFO", "서킷 브레이커 패턴 적용", "서킷브레이커")
            
            @cb
            def get_users_with_cb():
                pattern_status = get_pattern_status()
                timeout = 5 if pattern_status["deadline"] else None
                return client.list_users(page, page_size, timeout=timeout)
            
            result = get_users_with_cb()
        else:
            log_event(logger, "INFO", "서킷 브레이커 패턴 비활성화 - 직접 호출", "서킷브레이커")
            pattern_status = get_pattern_status()
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
        pattern_status = get_pattern_status()
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
    
    # 테스트 시작 이벤트 기록
    add_event("test", f"슬로우 쿼리 테스트 시작 (지연: {query_delay}초, 요청: {concurrent_requests}개)")
    
    # 서킷 브레이커 초기화
    pattern_status = get_pattern_status()
    if pattern_status["circuit_breaker"]:
        cb.close()
        log_event(logger, "INFO", "서킷 브레이커 초기화 (닫힌 상태)", "서킷브레이커")
        
        # 이벤트 기록
        add_event("circuit_breaker", "서킷 브레이커 수동 초기화 (CLOSED)")
    
    # 메트릭 초기화
    reset_metrics()
    log_event(logger, "INFO", "메트릭 초기화됨", "테스트")
    
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
    with concurrent.futures.ThreadPoolExecutor(max_workers=concurrent_requests) as executor:
        futures = []
        
        for i in range(concurrent_requests):
            def execute_slow_query(request_id):
                start_time = time.time()
                try:
                    log_event(logger, "INFO", f"요청 {request_id}: 슬로우 쿼리 실행 (지연: {query_delay}초)", "테스트")
                    
                    # 데드라인 패턴 적용 여부
                    pattern_status = get_pattern_status()
                    actual_timeout = timeout if pattern_status["deadline"] else None
                    if pattern_status["deadline"]:
                        log_event(logger, "INFO", f"요청 {request_id}: 데드라인 패턴 적용 (타임아웃: {actual_timeout}초)", "데드라인")
                    
                    # 서킷 브레이커 패턴 적용 여부
                    if pattern_status["circuit_breaker"]:
                        log_event(logger, "INFO", f"요청 {request_id}: 서킷 브레이커 패턴 적용", "서킷브레이커")
                        
                        @cb
                        def call_with_cb():
                            return client.get_user_with_delay(1, delay=query_delay, timeout=actual_timeout)
                        
                        result = call_with_cb()
                    else:
                        log_event(logger, "INFO", f"요청 {request_id}: 서킷 브레이커 패턴 비활성화", "서킷브레이커")
                        result = client.get_user_with_delay(1, delay=query_delay, timeout=actual_timeout)
                    
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
    pattern_status = get_pattern_status()
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

@app.route('/test/comparison', methods=['POST'])
def test_pattern_comparison():
    """에러 처리 패턴 비교 테스트"""
    if client is None:
        log_event(logger, "ERROR", "gRPC 클라이언트가 초기화되지 않았습니다", "초기화")
        return jsonify({"error": "서비스를 사용할 수 없습니다"}), 503
    
    try:
        data = request.json
        if not data:
            return jsonify({"error": "요청 데이터가 없습니다"}), 400
        
        # 테스트 파라미터
        delay = data.get('delay', 5)  # 쿼리 지연 시간(초)
        requests_per_test = data.get('requests_per_test', 10)  # 각 테스트당 요청 수
        timeout = data.get('timeout', 3)  # 타임아웃 설정(초)
        
        log_event(logger, "INFO", f"패턴 비교 테스트 시작 (지연: {delay}초, 요청: {requests_per_test}개/테스트)", "테스트")
        add_event("test", f"패턴 비교 테스트 시작")
        
        # 테스트 결과 저장
        comparison_results = {}
        
        # 1. 패턴 없이 테스트
        update_pattern_status("deadline", False)
        update_pattern_status("circuit_breaker", False)
        update_pattern_status("backpressure", False)
        reset_metrics()
        
        # 서킷 브레이커 초기화
        cb.close()
        
        # 백프레셔 초기화
        client.reset_backpressure()
        
        log_event(logger, "INFO", "패턴 없이 테스트 시작", "테스트")
        no_pattern_result = run_pattern_test(client, cb, delay, requests_per_test, timeout)
        comparison_results["no_pattern"] = no_pattern_result
        
        # 2. 데드라인 패턴만 테스트
        update_pattern_status("deadline", True)
        update_pattern_status("circuit_breaker", False)
        update_pattern_status("backpressure", False)
        reset_metrics()
        
        log_event(logger, "INFO", "데드라인 패턴만 테스트 시작", "테스트")
        deadline_result = run_pattern_test(client, cb, delay, requests_per_test, timeout)
        comparison_results["deadline_only"] = deadline_result
        
        # 3. 서킷 브레이커 패턴만 테스트
        update_pattern_status("deadline", False)
        update_pattern_status("circuit_breaker", True)
        update_pattern_status("backpressure", False)
        reset_metrics()
        
        # 서킷 브레이커 초기화
        cb.close()
        
        log_event(logger, "INFO", "서킷 브레이커 패턴만 테스트 시작", "테스트")
        circuit_result = run_pattern_test(client, cb, delay, requests_per_test, timeout)
        comparison_results["circuit_only"] = circuit_result
        
        # 4. 백프레셔 패턴만 테스트
        update_pattern_status("deadline", False)
        update_pattern_status("circuit_breaker", False)
        update_pattern_status("backpressure", True)
        reset_metrics()
        
        # 백프레셔 초기화
        client.reset_backpressure()
        
        log_event(logger, "INFO", "백프레셔 패턴만 테스트 시작", "테스트")
        backpressure_result = run_pattern_test(client, cb, delay, requests_per_test, timeout)
        comparison_results["backpressure_only"] = backpressure_result
        
        # 5. 모든 패턴 활성화 테스트
        update_pattern_status("deadline", True)
        update_pattern_status("circuit_breaker", True)
        update_pattern_status("backpressure", True)
        reset_metrics()
        
        # 서킷 브레이커 초기화
        cb.close()
        
        # 백프레셔 초기화
        client.reset_backpressure()
        
        log_event(logger, "INFO", "모든 패턴 활성화 테스트 시작", "테스트")
        all_patterns_result = run_pattern_test(client, cb, delay, requests_per_test, timeout)
        comparison_results["all_patterns"] = all_patterns_result
        
        # 분석 결과 생성
        analysis = {
            "success_rates": {
                "no_pattern": no_pattern_result["success_rate"],
                "deadline_only": deadline_result["success_rate"],
                "circuit_only": circuit_result["success_rate"],
                "backpressure_only": backpressure_result["success_rate"],
                "all_patterns": all_patterns_result["success_rate"]
            },
            "response_times": {
                "no_pattern": no_pattern_result["avg_response_time"],
                "deadline_only": deadline_result["avg_response_time"],
                "circuit_only": circuit_result["avg_response_time"],
                "backpressure_only": backpressure_result["avg_response_time"],
                "all_patterns": all_patterns_result["avg_response_time"]
            },
            "error_types": {
                "no_pattern": {
                    "deadline_exceeded": no_pattern_result["deadline_exceeded"],
                    "circuit_broken": no_pattern_result["circuit_broken"],
                    "backpressure_rejected": no_pattern_result["backpressure_rejected"],
                    "other_errors": no_pattern_result["other_errors"]
                },
                "deadline_only": {
                    "deadline_exceeded": deadline_result["deadline_exceeded"],
                    "circuit_broken": deadline_result["circuit_broken"],
                    "backpressure_rejected": deadline_result["backpressure_rejected"],
                    "other_errors": deadline_result["other_errors"]
                },
                "circuit_only": {
                    "deadline_exceeded": circuit_result["deadline_exceeded"],
                    "circuit_broken": circuit_result["circuit_broken"],
                    "backpressure_rejected": circuit_result["backpressure_rejected"],
                    "other_errors": circuit_result["other_errors"]
                },
                "backpressure_only": {
                    "deadline_exceeded": backpressure_result["deadline_exceeded"],
                    "circuit_broken": backpressure_result["circuit_broken"],
                    "backpressure_rejected": backpressure_result["backpressure_rejected"],
                    "other_errors": backpressure_result["other_errors"]
                },
                "all_patterns": {
                    "deadline_exceeded": all_patterns_result["deadline_exceeded"],
                    "circuit_broken": all_patterns_result["circuit_broken"],
                    "backpressure_rejected": all_patterns_result["backpressure_rejected"],
                    "other_errors": all_patterns_result["other_errors"]
                }
            }
        }
        
        # 최적의 패턴 추천
        best_pattern = determine_best_pattern(comparison_results)
        
        # 테스트 완료 이벤트 기록
        add_event("test", "패턴 비교 테스트 완료")
        
        # 결과 반환
        return jsonify({
            "comparison_results": comparison_results,
            "analysis": analysis,
            "best_pattern": best_pattern
        })
    
    except Exception as e:
        log_event(logger, "ERROR", f"패턴 비교 테스트 중 오류: {str(e)}", "테스트")
        return jsonify({"error": f"테스트 실패: {str(e)}"}), 500

def run_pattern_test(client, cb, delay, requests_count, timeout):
    """특정 패턴으로 테스트 실행"""
    results = {
        "total_requests": requests_count,
        "success_count": 0,
        "deadline_exceeded": 0,
        "circuit_broken": 0,
        "backpressure_rejected": 0,
        "other_errors": 0,
        "success_rate": 0,
        "avg_response_time": 0,
        "total_response_time": 0
    }
    
    # 동시에 여러 요청 실행
    with concurrent.futures.ThreadPoolExecutor(max_workers=requests_count) as executor:
        futures = []
        
        for i in range(requests_count):
            def execute_test_query(request_id):
                start_time = time.time()
                try:
                    # 현재 활성화된 패턴 가져오기
                    pattern_status = get_pattern_status()
                    
                    # 데드라인 패턴
                    actual_timeout = timeout if pattern_status["deadline"] else None
                    
                    # 서킷 브레이커 패턴
                    if pattern_status["circuit_breaker"]:
                        @cb
                        def call_with_cb():
                            return client.get_user_with_delay(1, delay=delay, timeout=actual_timeout)
                        
                        result = call_with_cb()
                    else:
                        result = client.get_user_with_delay(1, delay=delay, timeout=actual_timeout)
                    
                    elapsed = time.time() - start_time
                    return {
                        "status": "success",
                        "elapsed": elapsed
                    }
                except pybreaker.CircuitBreakerError:
                    elapsed = time.time() - start_time
                    return {
                        "status": "circuit_broken",
                        "elapsed": elapsed
                    }
                except grpc.RpcError as e:
                    elapsed = time.time() - start_time
                    if e.code() == grpc.StatusCode.DEADLINE_EXCEEDED:
                        return {
                            "status": "deadline_exceeded",
                            "elapsed": elapsed
                        }
                    elif e.code() == grpc.StatusCode.RESOURCE_EXHAUSTED:
                        return {
                            "status": "backpressure_rejected",
                            "elapsed": elapsed
                        }
                    else:
                        return {
                            "status": "error",
                            "elapsed": elapsed
                        }
                except Exception:
                    elapsed = time.time() - start_time
                    return {
                        "status": "error",
                        "elapsed": elapsed
                    }
            
            futures.append(executor.submit(execute_test_query, i+1))
        
        # 결과 수집
        response_times = []
        for future in concurrent.futures.as_completed(futures):
            try:
                result = future.result()
                
                # 상태별 카운트 업데이트
                if result["status"] == "success":
                    results["success_count"] += 1
                    response_times.append(result["elapsed"])
                elif result["status"] == "deadline_exceeded":
                    results["deadline_exceeded"] += 1
                elif result["status"] == "circuit_broken":
                    results["circuit_broken"] += 1
                elif result["status"] == "backpressure_rejected":
                    results["backpressure_rejected"] += 1
                else:
                    results["other_errors"] += 1
                
                results["total_response_time"] += result["elapsed"]
            except Exception as e:
                log_event(logger, "ERROR", f"결과 처리 중 오류: {str(e)}")
    
    # 결과 계산
    results["success_rate"] = results["success_count"] / results["total_requests"] if results["total_requests"] > 0 else 0
    results["avg_response_time"] = results["total_response_time"] / results["total_requests"] if results["total_requests"] > 0 else 0
    
    # 성공한 요청의 평균 응답 시간 계산
    if response_times:
        results["avg_success_response_time"] = sum(response_times) / len(response_times)
    else:
        results["avg_success_response_time"] = 0
    
    return results

def determine_best_pattern(results):
    """테스트 결과를 기반으로 최적의 패턴 조합 결정"""
    # 각 패턴 조합의 점수 계산
    scores = {}
    
    # 성공률 가중치
    success_weight = 0.6
    # 응답 시간 가중치
    response_time_weight = 0.4
    
    for pattern, result in results.items():
        # 성공률 점수 (0~1)
        success_score = result["success_rate"]
        
        # 응답 시간 점수 (0~1, 낮을수록 좋음)
        max_response_time = 10  # 10초를 최대 응답 시간으로 가정
        response_time = min(result["avg_response_time"], max_response_time)
        response_time_score = 1 - (response_time / max_response_time)
        
        # 종합 점수
        total_score = (success_score * success_weight) + (response_time_score * response_time_weight)
        scores[pattern] = total_score
    
    # 최고 점수 패턴 찾기
    best_pattern = max(scores.items(), key=lambda x: x[1])
    
    pattern_names = {
        "no_pattern": "패턴 없음",
        "deadline_only": "데드라인 패턴",
        "circuit_only": "서킷 브레이커 패턴",
        "backpressure_only": "백프레셔 패턴",
        "all_patterns": "모든 패턴"
    }
    
    # 추천 결과 생성
    recommendation = {
        "pattern": best_pattern[0],
        "name": pattern_names.get(best_pattern[0], best_pattern[0]),
        "score": best_pattern[1],
        "reason": get_recommendation_reason(best_pattern[0], results),
        "all_scores": scores
    }
    
    return recommendation

def get_recommendation_reason(pattern, results):
    """패턴 추천 이유 생성"""
    pattern_reasons = {
        "no_pattern": "모든 패턴을 비활성화하는 것이 가장 효과적입니다. 현재 시스템 부하가 낮거나 에러가 거의 발생하지 않는 상황일 수 있습니다.",
        "deadline_only": "데드라인 패턴만 활성화하는 것이 가장 효과적입니다. 이는 느린 응답을 차단하여 전체 시스템 성능을 개선합니다.",
        "circuit_only": "서킷 브레이커 패턴만 활성화하는 것이 가장 효과적입니다. 연속된 오류 발생 시 시스템을 보호하고 부분적 장애를 격리합니다.",
        "backpressure_only": "백프레셔 패턴만 활성화하는 것이 가장 효과적입니다. 과도한 동시 요청을 제한하여 시스템 안정성을 유지합니다.",
        "all_patterns": "모든 패턴을 함께 활성화하는 것이 가장 효과적입니다. 각 패턴이 서로 보완하여 다양한 유형의 장애에 대응합니다."
    }
    
    # 기본 이유
    reason = pattern_reasons.get(pattern, "")
    
    # 데이터 기반 추가 설명
    result = results.get(pattern, {})
    
    if result:
        success_rate = result.get("success_rate", 0) * 100
        avg_time = result.get("avg_response_time", 0)
        
        reason += f" 이 패턴은 {success_rate:.1f}%의 성공률과 평균 {avg_time:.2f}초의 응답 시간을 보여줍니다."
    
    return reason

# 패턴 상태 조회 API
@app.route('/patterns/status')
def get_patterns_status():
    """에러 처리 패턴 상태 조회"""
    # 로깅 없이 바로 응답
    return jsonify(get_pattern_status())

# 패턴 활성화/비활성화 API
@app.route('/patterns/<pattern>', methods=['POST'])
def toggle_pattern(pattern):
    """에러 처리 패턴 활성화/비활성화"""
    pattern_status = get_pattern_status()
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
            "status": get_pattern_status()[pattern],
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
    
    # 문제가 되는 부분을 수정
    remaining_time = 0
    if state == "OPEN":
        # pybreaker 버전에 따라 속성 이름이 다를 수 있음
        # 대안적인 방식으로 접근
        try:
            if hasattr(cb, '_last_attempt'):
                remaining_time = max(0, (cb._last_attempt + cb.reset_timeout) - time.time())
            elif hasattr(cb, 'opened_at'):
                remaining_time = max(0, (cb.opened_at + cb.reset_timeout) - time.time())
            else:
                remaining_time = 0
        except:
            remaining_time = 0
    
    return jsonify({
        "state": state,
        "failure_count": cb.fail_counter,
        "reset_timeout": cb.reset_timeout,
        "remaining_recovery_time": remaining_time
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

# 시스템 초기화 API
@app.route('/system/reset', methods=['POST'])
def reset_system():
    """전체 시스템 초기화"""
    try:
        log_event(logger, "INFO", "시스템 초기화 요청", "시스템")
        
        # 1. 메트릭 초기화
        reset_metrics()
        
        # 2. 서킷 브레이커 초기화
        cb.close()
        
        # 3. 백프레셔 초기화
        if client:
            client.reset_backpressure()
        
        # 4. 백엔드 에러율 초기화
        if client:
            client.set_error_rate(0)
        
        # 이벤트 기록
        add_event("system", "시스템 전체 초기화 완료")
        
        log_event(logger, "INFO", "시스템 초기화 완료", "시스템")
        return jsonify({
            "status": "success",
            "message": "시스템이 초기화되었습니다"
        })
    except Exception as e:
        log_event(logger, "ERROR", f"시스템 초기화 실패: {str(e)}", "시스템")
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
    events_data = get_events(limit)
    
    # 커스텀 JSON 인코더 사용
    from flask import Response
    import json
    
    return Response(
        json.dumps(events_data, default=event_serializer),
        mimetype='application/json'
    )

# 메트릭 조회 API
@app.route('/metrics')
def get_all_metrics():
    """메트릭 조회 API"""
    # 로깅하지 않고 바로 응답
    return jsonify(get_metrics())

if __name__ == '__main__':
    # 디버그 모드 활성화
    app.run(host='0.0.0.0', port=8000, threaded=True)