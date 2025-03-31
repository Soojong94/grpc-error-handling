from flask import Flask, jsonify, request
import logging
import grpc
import time
import threading
import pybreaker
import concurrent.futures
import json
import sys
sys.path.append('.')  # 현재 디렉토리에서 모듈 찾기

# grpc_client.py 파일 임포트 방식 수정
from bff.grpc_client import UserServiceClient

# 로그 저장용 리스트
logs = []  # 로그 저장용 리스트
metrics = {
    "deadlines_exceeded": 0,
    "circuit_breaker_trips": 0,
    "backpressure_rejections": 0,
    "total_requests": 0,
    "successful_requests": 0,
    "failed_requests": 0,
    "avg_response_time": 0,
    "response_times": []
}

# 로깅 설정
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] [BFF] [Thread-%(thread)d] %(message)s',
)
logger = logging.getLogger(__name__)

# 로그 핸들러 추가
class UILogHandler(logging.Handler):
    def emit(self, record):
        log_entry = self.format(record)
        logs.append({
            "timestamp": time.strftime("%H:%M:%S"),
            "level": record.levelname,
            "message": record.getMessage(),
            "service": "BFF",
            "thread": record.thread
        })
        # 최대 100개 로그만 유지
        if len(logs) > 100:
            logs.pop(0)

# 로그 핸들러 등록
ui_handler = UILogHandler()
ui_handler.setFormatter(logging.Formatter('%(message)s'))
logger.addHandler(ui_handler)

app = Flask(__name__)

# 백엔드 gRPC 클라이언트 초기화
client = UserServiceClient('localhost:50051')

# 서킷 브레이커 설정
cb = pybreaker.CircuitBreaker(
    fail_max=5,
    reset_timeout=10,
    exclude=[grpc.RpcError]
)

# 처리 시간 측정 및 메트릭 업데이트 데코레이터
def track_request_metrics(func):
    def wrapper(*args, **kwargs):
        metrics["total_requests"] += 1
        start_time = time.time()
        try:
            result = func(*args, **kwargs)
            metrics["successful_requests"] += 1
            elapsed = time.time() - start_time
            metrics["response_times"].append(elapsed)
            # 평균 응답 시간 계산 (최대 100개까지만 유지)
            metrics["avg_response_time"] = sum(metrics["response_times"][-100:]) / len(metrics["response_times"][-100:])
            return result
        except Exception as e:
            metrics["failed_requests"] += 1
            if "deadline exceeded" in str(e).lower():
                metrics["deadlines_exceeded"] += 1
            if isinstance(e, pybreaker.CircuitBreakerError):
                metrics["circuit_breaker_trips"] += 1
            raise
        finally:
            # 최대 1000개 응답 시간만 저장
            if len(metrics["response_times"]) > 1000:
                metrics["response_times"] = metrics["response_times"][-1000:]
    return wrapper

@app.route('/health')
@track_request_metrics
def health_check():
    """BFF 상태 확인"""
    logger.info("BFF 상태 확인 요청 처리")
    return jsonify({"status": "ok", "service": "bff"})

@app.route('/backend/health')
@track_request_metrics
def backend_health():
    """백엔드 상태 확인"""
    logger.info("백엔드 상태 확인 요청 처리")
    try:
        status = client.check_health()
        return jsonify({"status": "ok", "service": "backend"})
    except Exception as e:
        logger.error(f"백엔드 상태 확인 실패: {str(e)}")
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/db/health')
@track_request_metrics
def db_health():
    """DB 상태 확인"""
    logger.info("DB 상태 확인 요청 처리")
    try:
        status = client.check_db_health()
        return jsonify({"status": "ok", "service": "db"})
    except Exception as e:
        logger.error(f"DB 상태 확인 실패: {str(e)}")
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/users')
@track_request_metrics
def get_users():
    """사용자 목록 조회"""
    logger.info("사용자 목록 조회 요청 처리")
    try:
        page = int(request.args.get('page', 1))
        page_size = int(request.args.get('page_size', 10))
        
        # 서킷 브레이커로 gRPC 호출 보호
        @cb
        def get_users_with_cb():
            return client.list_users(page, page_size)
        
        users = get_users_with_cb()
        return jsonify(users)
    except pybreaker.CircuitBreakerError:
        logger.error("서킷 브레이커 오픈 상태 - 요청 거부")
        metrics["circuit_breaker_trips"] += 1
        return jsonify({"error": "서비스 일시적으로 사용 불가능"}), 503
    except Exception as e:
        logger.error(f"사용자 목록 조회 실패: {str(e)}")
        return jsonify({"error": str(e)}), 500

@app.route('/users/<int:user_id>')
@track_request_metrics
def get_user(user_id):
    """단일 사용자 조회"""
    logger.info(f"사용자 조회 요청 처리 (ID: {user_id})")
    try:
        timeout = int(request.args.get('timeout', 5))
        
        # 데드라인 적용
        user = client.get_user(user_id, timeout=timeout)
        return jsonify(user)
    except grpc.RpcError as e:
        if e.code() == grpc.StatusCode.DEADLINE_EXCEEDED:
            logger.error(f"요청 타임아웃: {str(e)}")
            metrics["deadlines_exceeded"] += 1
            return jsonify({"error": "요청 시간 초과"}), 504
        logger.error(f"gRPC 오류: {str(e)}")
        return jsonify({"error": str(e)}), 500
    except Exception as e:
        logger.error(f"사용자 조회 실패: {str(e)}")
        return jsonify({"error": str(e)}), 500

@app.route('/users', methods=['POST'])
@track_request_metrics
def create_user():
    """사용자 생성"""
    logger.info("사용자 생성 요청 처리")
    try:
        data = request.json
        name = data.get('name')
        email = data.get('email')
        
        if not name or not email:
            return jsonify({"error": "이름과 이메일은 필수입니다"}), 400
        
        user = client.create_user(name, email)
        return jsonify(user), 201
    except Exception as e:
        logger.error(f"사용자 생성 실패: {str(e)}")
        return jsonify({"error": str(e)}), 500

# 테스트 API 엔드포인트

@app.route('/test/deadline')
@track_request_metrics
def test_deadline():
    """데드라인 테스트"""
    timeout = int(request.args.get('timeout', 5))
    logger.info(f"데드라인 테스트 시작 (타임아웃: {timeout}초)")
    
    results = []
    
    try:
        # 지연 있는 요청 실행
        start_time = time.time()
        client.get_user_with_delay(1, delay=timeout+2, timeout=timeout)
        elapsed = time.time() - start_time
        results.append(f"성공 (소요시간: {elapsed:.2f}초)")
    except grpc.RpcError as e:
        elapsed = time.time() - start_time
        if e.code() == grpc.StatusCode.DEADLINE_EXCEEDED:
            metrics["deadlines_exceeded"] += 1
            results.append(f"타임아웃 발생 (소요시간: {elapsed:.2f}초)")
        else:
            results.append(f"gRPC 오류: {e.code()} - {e.details()} (소요시간: {elapsed:.2f}초)")
    except Exception as e:
        elapsed = time.time() - start_time
        results.append(f"예외 발생: {str(e)} (소요시간: {elapsed:.2f}초)")
    
    success = "타임아웃 발생" in results[0]
    
    logger.info(f"데드라인 테스트 완료: {'성공' if success else '실패'}")
    return jsonify({
        "status": "성공" if success else "실패",
        "message": results[0],
        "timeout_value": timeout
    })

@app.route('/test/circuit-breaker')
@track_request_metrics
def test_circuit_breaker():
    """서킷 브레이커 테스트"""
    error_rate = int(request.args.get('error_rate', 50))
    logger.info(f"서킷 브레이커 테스트 시작 (에러율: {error_rate}%)")
    
    results = []
    
    # 백엔드에 에러율 설정
    try:
        client.set_error_rate(error_rate)
    except Exception as e:
        logger.error(f"에러율 설정 실패: {str(e)}")
        return jsonify({"status": "실패", "message": f"에러율 설정 실패: {str(e)}"}), 500
    
    # 여러 번 요청을 보내서 서킷 브레이커 동작 확인
    success_count = 0
    error_count = 0
    circuit_open = False
    
    for i in range(10):
        try:
            # 서킷 브레이커로 보호된 호출
            @cb
            def call_with_cb():
                return client.list_users(1, 10)
            
            result = call_with_cb()
            success_count += 1
            results.append(f"요청 {i+1}: 성공")
            logger.info(f"요청 {i+1} 성공")
        except pybreaker.CircuitBreakerError:
            error_count += 1
            circuit_open = True
            metrics["circuit_breaker_trips"] += 1
            results.append(f"요청 {i+1}: 서킷 오픈")
            logger.info(f"요청 {i+1}: 서킷 브레이커 오픈")
        except Exception as e:
            error_count += 1
            results.append(f"요청 {i+1}: 오류 - {str(e)}")
            logger.info(f"요청 {i+1}: 오류 발생 - {str(e)}")
    
    logger.info(f"서킷 브레이커 테스트 완료: 성공 {success_count}, 오류 {error_count}")
    return jsonify({
        "status": "성공" if circuit_open and error_rate > 30 else "실패",
        "message": "서킷 브레이커 동작 확인 완료" if circuit_open else "서킷 브레이커가 열리지 않음",
        "results": results,
        "success_count": success_count,
        "error_count": error_count,
        "circuit_open": circuit_open
    })

@app.route('/test/backpressure')
@track_request_metrics
def test_backpressure():
    """백프레셔 테스트"""
    request_count = int(request.args.get('requests', 20))
    logger.info(f"백프레셔 테스트 시작 (동시 요청: {request_count}개)")
    
    # 작업 완료 추적
    success_count = 0
    failed_count = 0
    results = []
    
    # 쓰레드 풀 생성 (백프레셔 효과를 위해 제한된 수의 워커 사용)
    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
        # 여러 요청 동시 실행
        futures = []
        for i in range(request_count):
            future = executor.submit(client.get_user, i % 5 + 1)  # ID 1~5 사용
            futures.append(future)
        
        # 결과 수집
        for i, future in enumerate(concurrent.futures.as_completed(futures)):
            try:
                result = future.result()
                success_count += 1
                results.append(f"요청 {i+1}: 성공")
                logger.info(f"요청 {i+1}: 성공")
            except Exception as e:
                failed_count += 1
                results.append(f"요청 {i+1}: 실패 - {str(e)}")
                logger.error(f"요청 {i+1}: 실패 - {str(e)}")
                if "RESOURCE_EXHAUSTED" in str(e):
                    metrics["backpressure_rejections"] += 1
    
    logger.info(f"백프레셔 테스트 완료: 성공 {success_count}, 실패 {failed_count}")
    return jsonify({
        "status": "완료",
        "message": f"백프레셔 테스트 완료: 총 {request_count}개 요청 중 {success_count}개 성공, {failed_count}개 실패",
        "success_count": success_count,
        "failed_count": failed_count,
        "results": results[:10]  # 처음 10개 결과만 반환
    })

# 로그 조회 API 추가
@app.route('/logs')
def get_logs():
    """로그 조회 API"""
    return jsonify(logs)

# 메트릭 조회 API 추가
@app.route('/metrics')
def get_metrics():
    """메트릭 조회 API"""
    return jsonify(metrics)

# 서킷브레이커 상태 확인 API
@app.route('/circuit-breaker/status')
def circuit_breaker_status():
    """서킷브레이커 상태 조회"""
    logger.info("서킷브레이커 상태 조회 요청")
    state = "OPEN" if cb.current_state == "open" else "CLOSED"
    
    try:
        return jsonify({
            "state": state,
            "failure_count": cb.fail_counter,
            "reset_timeout": cb.reset_timeout
        })
    except Exception as e:
        logger.error(f"서킷브레이커 상태 조회 실패: {str(e)}")
        return jsonify({
            "state": state,
            "error": str(e)
        })

# 서킷브레이커 초기화 API
@app.route('/circuit-breaker/reset', methods=['POST'])
def reset_circuit_breaker():
    """서킷브레이커 초기화"""
    logger.info("서킷브레이커 초기화 요청")
    try:
        # 서킷브레이커 초기화
        cb.close()
        logger.info("서킷브레이커가 초기화되었습니다")
        return jsonify({
            "status": "success",
            "message": "서킷브레이커가 초기화되었습니다"
        })
    except Exception as e:
        logger.error(f"서킷브레이커 초기화 실패: {str(e)}")
        return jsonify({
            "status": "error",
            "message": f"초기화 실패: {str(e)}"
        }), 500

# 백엔드 초기화 API (에러율 초기화)
@app.route('/backend/reset', methods=['POST'])
def reset_backend():
    """백엔드 에러율 초기화"""
    logger.info("백엔드 에러율 초기화 요청")
    try:
        # 에러율 0으로 설정
        client.set_error_rate(0)
        logger.info("백엔드 에러율이 초기화되었습니다")
        return jsonify({
            "status": "success",
            "message": "백엔드 에러율이 초기화되었습니다"
        })
    except Exception as e:
        logger.error(f"백엔드 초기화 실패: {str(e)}")
        return jsonify({
            "status": "error",
            "message": f"초기화 실패: {str(e)}"
        }), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8000, threaded=True)