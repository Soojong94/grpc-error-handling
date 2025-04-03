import sys
import os
sys.path.insert(0, os.path.abspath(os.path.dirname(os.path.dirname(__file__))))

from flask import Flask, render_template, request, jsonify
import grpc
import threading
import time

from generated import bff_pb2, bff_pb2_grpc
from common.logging_config import setup_logging

app = Flask(__name__)
logger = setup_logging("front_service")

# BFF 서비스 주소 (환경 변수에서 읽기)
BFF_ADDRESS = os.environ.get("BFF_SERVICE_ADDRESS", "localhost:50051")
logger.info(f"BFF 서비스 주소: {BFF_ADDRESS}")

def call_bff(request_type, use_deadline, use_circuit_breaker, use_backpressure, backend_type):
    """BFF 서비스 호출"""
    logger.info(f"[Front] BFF 서비스 호출 시작 (백엔드: {backend_type})")
    logger.info(f"[Front] 패턴 설정 - 서킷브레이커: {use_circuit_breaker}, " +
                f"데드라인: {use_deadline}, 백프레셔: {use_backpressure}")
    
    start_time = time.time()  # 여기로 이동: 함수 시작 부분에 선언하여 항상 정의되도록 함
    
    try:
        channel = grpc.insecure_channel(BFF_ADDRESS)
        stub = bff_pb2_grpc.BffServiceStub(channel)
        
        request = bff_pb2.BffRequest(
            request_type=request_type,
            use_deadline=use_deadline,
            use_circuit_breaker=use_circuit_breaker,
            use_backpressure=use_backpressure,
            backend_type=backend_type
        )
        
        response = stub.Process(request)
        elapsed_time = time.time() - start_time
        
        logger.info(f"[Front] BFF 응답 수신 (소요 시간: {elapsed_time:.2f}초)")
        logger.info(f"[Front] 응답 결과: 성공={response.success}, 메시지={response.result}")
        
        return {
            "success": response.success,
            "result": response.result,
            "error_message": response.error_message,
            "elapsed_time": elapsed_time
        }
        
    except grpc.RpcError as e:
        elapsed_time = time.time() - start_time
        status_code = e.code()
        details = e.details()
        
        logger.error(f"[Front] BFF 호출 중 오류: {status_code} - {details} (소요 시간: {elapsed_time:.2f}초)")
        
        return {
            "success": False,
            "error_message": f"BFF 서비스 오류: {details}",
            "status_code": str(status_code),
            "elapsed_time": elapsed_time
        }
        
    except Exception as e:
        elapsed_time = time.time() - start_time
        logger.exception("[Front] 예기치 않은 오류")
        
        return {
            "success": False,
            "error_message": f"내부 오류: {str(e)}",
            "elapsed_time": elapsed_time
        }

@app.route('/')
def index():
    """메인 페이지"""
    return render_template('index.html')

@app.route('/api/test', methods=['POST'])
def test_api():
    """테스트 API 엔드포인트"""
    data = request.json
    request_type = data.get('request_type', 'normal')
    use_deadline = data.get('use_deadline', False)
    use_circuit_breaker = data.get('use_circuit_breaker', False)
    use_backpressure = data.get('use_backpressure', False)
    backend_type = data.get('backend_type', 'no_pattern')
    
    logger.info(f"[Front] 테스트 API 호출 - 요청 유형: {request_type}, 백엔드: {backend_type}")
    logger.info(f"[Front] 패턴 설정 - 서킷브레이커: {use_circuit_breaker}, " +
                f"데드라인: {use_deadline}, 백프레셔: {use_backpressure}")
    
    result = call_bff(request_type, use_deadline, use_circuit_breaker, use_backpressure, backend_type)
    return jsonify(result)

@app.route('/api/reset', methods=['POST'])
def reset_api():
    """패턴 리셋 API 엔드포인트"""
    data = request.json
    pattern = data.get('pattern', 'all')
    backend_type = data.get('backend_type', 'no_pattern')
    
    logger.info(f"[Front] 패턴 리셋 API 호출 - 패턴: {pattern}, 백엔드: {backend_type}")
    
    try:
        channel = grpc.insecure_channel(BFF_ADDRESS)
        stub = bff_pb2_grpc.BffServiceStub(channel)
        
        reset_request = bff_pb2.ResetRequest(
            pattern=pattern,
            backend_type=backend_type
        )
        
        response = stub.ResetPattern(reset_request)
        
        return jsonify({
            "success": response.success,
            "message": response.message
        })
    except Exception as e:
        logger.exception("[Front] 패턴 리셋 중 오류")
        return jsonify({
            "success": False,
            "message": f"리셋 실패: {str(e)}"
        })

@app.route('/api/status', methods=['GET'])
def status_api():
    """패턴 상태 조회 API 엔드포인트"""
    backend_type = request.args.get('backend_type', 'no_pattern')
    
    logger.info(f"[Front] 패턴 상태 조회 API 호출 - 백엔드: {backend_type}")
    
    try:
        channel = grpc.insecure_channel(BFF_ADDRESS)
        stub = bff_pb2_grpc.BffServiceStub(channel)
        
        # 변수명 변경
        status_request = bff_pb2.StatusRequest(  # 'request'에서 'status_request'로 변경
            backend_type=backend_type
        )
        
        response = stub.GetStatus(status_request)
        
        if response.success:
            return jsonify({
                "success": True,
                "circuit_breaker": {
                    "state": response.circuit_breaker_state,
                    "failure_count": response.circuit_breaker_failures
                },
                "backpressure": {
                    "active_requests": response.backpressure_active_requests,
                    "is_overloaded": response.backpressure_overloaded
                }
            })
        else:
            return jsonify({
                "success": False,
                "message": response.error_message
            })
    except Exception as e:
        logger.exception("[Front] 패턴 상태 조회 중 오류")
        return jsonify({
            "success": False,
            "message": f"상태 조회 실패: {str(e)}"
        })

def run_flask(host="0.0.0.0", port=5000):
    port = int(os.environ.get("PORT", port))  # 환경 변수에서 포트 읽기
    app.run(host=host, port=port, debug=True, use_reloader=False)

if __name__ == "__main__":
    run_flask()