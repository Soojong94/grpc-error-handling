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
import queue
import subprocess
import datetime

from generated import bff_pb2, bff_pb2_grpc
from common.logging_config import setup_logging

# gRPC 디버그 로깅 활성화
os.environ['GRPC_VERBOSITY'] = 'DEBUG'
os.environ['GRPC_TRACE'] = 'all'

# 기본 로깅 설정
logging.basicConfig(level=logging.INFO)

# 로그 저장 디렉토리
LOG_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'logs'))

# 터미널 로그 파일 경로
timestamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
TERMINAL_LOG_FILE = os.path.join(LOG_DIR, f"terminal_output_{timestamp}.log")

app = Flask(__name__)
app.config['SECRET_KEY'] = 'grpc-error-handling-secret-key'
socketio = SocketIO(app, cors_allowed_origins="*")

logger = setup_logging("front_service")

# BFF 서비스 주소 (환경 변수에서 읽기)
BFF_ADDRESS = os.environ.get("BFF_SERVICE_ADDRESS", "localhost:50051")
logger.info(f"BFF 서비스 주소: {BFF_ADDRESS}")

# 로그 패턴 상수
LOG_PATTERN_HTTP = re.compile(r'(http|HTTP|127\.0\.0\.1.*HTTP|POST|GET|PUT|DELETE|werkzeug)', re.IGNORECASE)
LOG_PATTERN_GRPC = re.compile(r'(grpc|GRPC|RPC|rpc|transport|chttp2|tcp|core/ext|EXECUTOR|completion_queue|executor|surface)', re.IGNORECASE)

# 로그 메시지 큐
log_queue = queue.Queue()

# 터미널 출력을 캡처하기 위한 설정
class TerminalCapture:
    def __init__(self, log_file):
        self.log_file = log_file
        self.file = open(log_file, 'a', encoding='utf-8')
        self.original_stdout = sys.stdout
        self.original_stderr = sys.stderr
        self.setup()
        
    def setup(self):
        """표준 출력 및 에러를 파일로 리다이렉트"""
        sys.stdout = self
        sys.stderr = self
        
    def write(self, message):
        """메시지 작성 시 원본 스트림과 파일 모두에 출력"""
        self.original_stdout.write(message)
        self.file.write(message)
        self.file.flush()
        
    def flush(self):
        """버퍼 비우기"""
        self.original_stdout.flush()
        self.file.flush()
        
    def close(self):
        """리소스 정리"""
        sys.stdout = self.original_stdout
        sys.stderr = self.original_stderr
        self.file.close()

# 로그 파일 모니터링 클래스
class LogWatcher(FileSystemEventHandler):
    def __init__(self, log_dir):
        self.log_dir = log_dir
        self.file_positions = {}
        
    def scan_for_logs(self):
        """초기 로그 파일 스캔"""
        log_files = glob.glob(os.path.join(self.log_dir, "*.log"))
        for log_file in log_files:
            self.file_positions[log_file] = os.path.getsize(log_file)
            logger.info(f"로그 파일 발견: {os.path.basename(log_file)}")

    def on_modified(self, event):
        """파일 변경 이벤트 핸들러"""
        if not event.is_directory and event.src_path.endswith('.log'):
            self.process_log_file(event.src_path)

    def process_log_file(self, file_path):
        """로그 파일 처리"""
        try:
            if file_path not in self.file_positions:
                self.file_positions[file_path] = 0
                
            current_size = os.path.getsize(file_path)
            if current_size <= self.file_positions[file_path]:
                return  # 파일 크기가 변하지 않았거나 줄어들었다면 처리하지 않음
                
            with open(file_path, 'r', encoding='utf-8', errors='replace') as f:
                f.seek(self.file_positions[file_path])
                new_content = f.read()
                self.file_positions[file_path] = f.tell()
                
                if not new_content.strip():
                    return
                    
                # 서비스 이름 확인 - 파일 이름에서 추출
                service_name = os.path.basename(file_path).split('_')[0]
                
                # 로그 내용을 줄로 분리하여 처리
                for line in new_content.strip().split('\n'):
                    if not line.strip():
                        continue
                        
                    # 원시 로그 항상 추가
                    log_queue.put({
                        'type': 'all',
                        'logs': [{
                            'service': service_name,
                            'content': line.strip()
                        }]
                    })
                    
                    # gRPC 관련 로그 필터링
                    if LOG_PATTERN_GRPC.search(line):
                        log_queue.put({
                            'type': 'grpc',
                            'logs': [{
                                'service': service_name,
                                'content': line.strip()
                            }]
                        })
                    
                    # HTTP 관련 로그 필터링
                    elif LOG_PATTERN_HTTP.search(line):
                        log_queue.put({
                            'type': 'http',
                            'logs': [{
                                'service': service_name,
                                'content': line.strip()
                            }]
                        })
                        
        except Exception as e:
            logger.error(f"로그 파일 처리 중 오류: {str(e)}")

# 로그 처리 및 전송 스레드
def log_processor_thread():
    """로그 큐에서 메시지를 가져와 클라이언트에 전송"""
    while True:
        try:
            if not log_queue.empty():
                log_data = log_queue.get()
                socketio.emit('raw_log', log_data)
                log_queue.task_done()
            else:
                time.sleep(0.1)
        except Exception as e:
            logger.error(f"로그 처리 중 오류: {str(e)}")
            time.sleep(1)

# 외부 프로세스의 gRPC 로그 캡처
def capture_grpc_logs():
    """외부 프로세스에서 gRPC 로그 캡처"""
    try:
        # gRPC 내부 로그를 생성하는 테스트 명령
        if os.name == 'nt':  # Windows
            cmd = 'grpc_cli ls localhost:50051'
        else:  # Linux/Mac
            cmd = 'grpc_cli ls localhost:50051 2>&1'
            
        # 10초마다 명령 실행
        while True:
            try:
                # 명령 실행 및 출력 캡처
                output = subprocess.check_output(cmd, shell=True, stderr=subprocess.STDOUT, text=True)
                
                # 캡처된 출력을 로그 큐에 추가
                lines = output.strip().split('\n')
                for line in lines:
                    if not line.strip():
                        continue
                        
                    # gRPC 로그로 추가
                    log_queue.put({
                        'type': 'grpc',
                        'logs': [{
                            'service': 'grpc_cli',
                            'content': line.strip()
                        }]
                    })
                    
                    # 원시 로그에도 추가
                    log_queue.put({
                        'type': 'all',
                        'logs': [{
                            'service': 'grpc_cli',
                            'content': line.strip()
                        }]
                    })
            except subprocess.CalledProcessError:
                # 명령 실행 실패 - 무시하고 계속 진행
                pass
                
            # 지연
            time.sleep(10)
    except Exception as e:
        logger.error(f"gRPC 로그 캡처 오류: {str(e)}")

# 주기적으로 더미 gRPC 로그 생성
def generate_dummy_grpc_logs():
    """더미 gRPC 로그 생성"""
    while True:
        try:
            # 예제 gRPC 로그 형식
            current_time = time.strftime("%H:%M:%S", time.localtime())
            dummy_logs = [
                f"I0508 {current_time}.000000000 12345 src/core/lib/surface/completion_queue.cc:1405] grpc_completion_queue_shutdown(cq=00000DEADBEEF000)",
                f"I0508 {current_time}.000000000 12345 src/core/lib/surface/completion_queue.cc:1410] grpc_completion_queue_destroy(cq=00000DEADBEEF000)",
                f"I0508 {current_time}.000000000 12345 src/core/lib/surface/channel.cc:428] grpc_channel_destroy(channel=00000BEEFCAFE000)",
                f"127.0.0.1 - - [{current_time}] \"POST /api/test HTTP/1.1\" 200 -"
            ]
            
            # 로그 추가
            for log in dummy_logs:
                # 터미널 로그 파일에 직접 쓰기
                with open(TERMINAL_LOG_FILE, 'a', encoding='utf-8') as f:
                    f.write(log + '\n')
            
            # 지연
            time.sleep(5)
        except Exception as e:
            logger.error(f"더미 로그 생성 오류: {str(e)}")
            time.sleep(1)

# gRPC 인터셉터 - 최소화된 버전
class GrpcLoggingInterceptor(grpc.UnaryUnaryClientInterceptor):
    def intercept_unary_unary(self, continuation, client_call_details, request):
        return continuation(client_call_details, request)

def create_channel(address):
    """gRPC 채널 생성"""
    interceptor = GrpcLoggingInterceptor()
    return grpc.intercept_channel(grpc.insecure_channel(address), interceptor)

def call_bff(request_type, use_deadline, use_circuit_breaker, use_backpressure, backend_type):
    """BFF 서비스 호출"""
    logger.info(f"[Front] BFF 서비스 호출 시작 (백엔드: {backend_type})")
    
    start_time = time.time()
    
    try:
        # 채널 생성
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
    logger.info("[Front] 메인 페이지 접속")
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
        # 채널 생성
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
        # 채널 생성
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
    
    # 터미널 출력 캡처 설정
    terminal_capture = TerminalCapture(TERMINAL_LOG_FILE)
    
    # 로그 디렉토리가 존재하는지 확인
    os.makedirs(LOG_DIR, exist_ok=True)
    
    # 로그 모니터링 설정
    log_watcher = LogWatcher(LOG_DIR)
    log_watcher.scan_for_logs()
    
    observer = Observer()
    observer.schedule(log_watcher, LOG_DIR, recursive=False)
    observer.start()
    
    # 로그 처리 스레드 시작
    log_processor = threading.Thread(target=log_processor_thread)
    log_processor.daemon = True
    log_processor.start()
    
    # 더미 gRPC 로그 생성 스레드 시작
    dummy_grpc = threading.Thread(target=generate_dummy_grpc_logs)
    dummy_grpc.daemon = True
    dummy_grpc.start()
    
    logger.info(f"Flask 서버 시작: {host}:{port}")
    
    try:
        socketio.run(app, host=host, port=port, debug=False, use_reloader=False)
    except KeyboardInterrupt:
        logger.info("서버 종료 중...")
    finally:
        observer.stop()
        observer.join()
        terminal_capture.close()

if __name__ == "__main__":
    run_flask()