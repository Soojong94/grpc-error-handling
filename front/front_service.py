import sys
import os
sys.path.insert(0, os.path.abspath(os.path.dirname(os.path.dirname(__file__))))

from flask import Flask, render_template, request, jsonify
import grpc
import threading
import time
import json
import logging
from flask_socketio import SocketIO, emit
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
import glob
import re

from generated import bff_pb2, bff_pb2_grpc
from common.logging_config import setup_logging

# gRPC 디버그 로깅 활성화
os.environ['GRPC_VERBOSITY'] = 'DEBUG'
os.environ['GRPC_TRACE'] = 'all'

app = Flask(__name__)
app.config['SECRET_KEY'] = 'grpc-error-handling-secret-key'
socketio = SocketIO(app, cors_allowed_origins="*")

logger = setup_logging("front_service")

# BFF 서비스 주소 (환경 변수에서 읽기)
BFF_ADDRESS = os.environ.get("BFF_SERVICE_ADDRESS", "localhost:50051")
logger.info(f"BFF 서비스 주소: {BFF_ADDRESS}")

# 로그 패턴 상수
LOG_PATTERN_HTTP = re.compile(r'(http|HTTP)', re.IGNORECASE)
LOG_PATTERN_GRPC = re.compile(r'(grpc|GRPC|RPC|rpc|transport)', re.IGNORECASE)
LOG_PATTERN_ALL = re.compile(r'(DEBUG|INFO|WARNING|ERROR|CRITICAL|grpc|GRPC|http|HTTP|RPC|rpc|Request|Response|transport)', re.IGNORECASE)

# 로그 파일 모니터링 클래스
class LogWatcher(FileSystemEventHandler):
    def __init__(self, log_dir, socketio):
        self.log_dir = log_dir
        self.socketio = socketio
        self.file_positions = {}
        self.log_pattern = LOG_PATTERN_ALL

    def scan_for_logs(self):
        """초기 로그 파일 스캔"""
        log_files = glob.glob(os.path.join(self.log_dir, "*.log"))
        for log_file in log_files:
            self.file_positions[log_file] = os.path.getsize(log_file)

    def on_modified(self, event):
        """파일 변경 이벤트 핸들러"""
        if not event.is_directory and event.src_path.endswith('.log'):
            self.process_log_file(event.src_path)

    def process_log_file(self, file_path):
        """로그 파일 처리"""
        if file_path not in self.file_positions:
            self.file_positions[file_path] = 0

        file_size = os.path.getsize(file_path)
        if file_size > self.file_positions[file_path]:
            try:
                # UTF-8로 시도
                with open(file_path, 'r', encoding='utf-8', errors='replace') as f:
                    f.seek(self.file_positions[file_path])
                    new_lines = f.read()
                    self.file_positions[file_path] = file_size

                    if new_lines:
                        service_name = os.path.basename(file_path).split('_')[0]
                        
                        # 모든 로그 라인 처리
                        all_lines = []
                        grpc_lines = []
                        http_lines = []
                        
                        for line in new_lines.splitlines():
                            # 모든 패턴 로그
                            if LOG_PATTERN_ALL.search(line):
                                all_lines.append({
                                    'service': service_name,
                                    'content': line,
                                    'type': 'all'
                                })
                            
                            # gRPC 패턴 로그
                            if LOG_PATTERN_GRPC.search(line):
                                grpc_lines.append({
                                    'service': service_name,
                                    'content': line,
                                    'type': 'grpc'
                                })
                            
                            # HTTP 패턴 로그
                            if LOG_PATTERN_HTTP.search(line):
                                http_lines.append({
                                    'service': service_name,
                                    'content': line,
                                    'type': 'http'
                                })
                        
                        # 모든 로그 타입 전송
                        if all_lines:
                            self.socketio.emit('raw_log', {'logs': all_lines, 'type': 'all'})
                        if grpc_lines:
                            self.socketio.emit('raw_log', {'logs': grpc_lines, 'type': 'grpc'})
                        if http_lines:
                            self.socketio.emit('raw_log', {'logs': http_lines, 'type': 'http'})
                        
            except Exception as e:
                logger.error(f"로그 파일 처리 중 오류: {str(e)}")

def start_log_watcher():
    """로그 모니터링 시작"""
    log_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'logs'))
    log_watcher = LogWatcher(log_dir, socketio)
    log_watcher.scan_for_logs()
    
    observer = Observer()
    observer.schedule(log_watcher, log_dir, recursive=False)
    observer.start()
    
    logger.info(f"로그 모니터링 시작: {log_dir}")
    return observer

# gRPC 인터셉터 - 요청과 응답을 로깅하기 위한
class GrpcLoggingInterceptor(grpc.UnaryUnaryClientInterceptor):
    def __init__(self, logger):
        self.logger = logger

    def intercept_unary_unary(self, continuation, client_call_details, request):
        self.logger.info(f"[GRPC 요청] 메서드: {client_call_details.method}, 요청: {request}")
        response = continuation(client_call_details, request)
        response.add_done_callback(lambda r: self.log_response(r, client_call_details.method))
        return response
    
    def log_response(self, future, method):
        try:
            response = future.result()
            self.logger.info(f"[GRPC 응답] 메서드: {method}, 응답: {response}")
        except grpc.RpcError as e:
            self.logger.error(f"[GRPC 에러] 메서드: {method}, 코드: {e.code()}, 상세: {e.details()}")

def create_channel(address):
    """gRPC 채널 생성 - 로깅 인터셉터 추가"""
    interceptor = GrpcLoggingInterceptor(logger)
    return grpc.intercept_channel(grpc.insecure_channel(address), interceptor)

def call_bff(request_type, use_deadline, use_circuit_breaker, use_backpressure, backend_type):
    """BFF 서비스 호출"""
    logger.info(f"[Front] BFF 서비스 호출 시작 (백엔드: {backend_type})")
    logger.info(f"[Front] 패턴 설정 - 서킷브레이커: {use_circuit_breaker}, " +
                f"데드라인: {use_deadline}, 백프레셔: {use_backpressure}")
    
    start_time = time.time()
    
    try:
        # 로깅 인터셉터가 포함된 채널 사용
        channel = create_channel(BFF_ADDRESS)
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
        # 로깅 인터셉터가 포함된 채널 사용
        channel = create_channel(BFF_ADDRESS)
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
        # 로깅 인터셉터가 포함된 채널 사용
        channel = create_channel(BFF_ADDRESS)
        stub = bff_pb2_grpc.BffServiceStub(channel)
        
        status_request = bff_pb2.StatusRequest(
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

@socketio.on('connect')
def handle_connect():
    """클라이언트 연결 이벤트"""
    logger.info('클라이언트 연결됨')
    
@socketio.on('disconnect')
def handle_disconnect():
    """클라이언트 연결 해제 이벤트"""
    logger.info('클라이언트 연결 해제됨')

def run_flask(host="0.0.0.0", port=5000):
    port = int(os.environ.get("PORT", port))  # 환경 변수에서 포트 읽기
    observer = start_log_watcher()
    
    try:
        socketio.run(app, host=host, port=port, debug=True, use_reloader=False, allow_unsafe_werkzeug=True)
    except KeyboardInterrupt:
        observer.stop()
    observer.join()

if __name__ == "__main__":
    run_flask()