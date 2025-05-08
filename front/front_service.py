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
import glob
import re
import queue
import subprocess
import datetime

from generated import bff_pb2, bff_pb2_grpc
from common.logging_config import setup_logging

# gRPC 환경 변수 설정 추가 - 디버그 로그 세부화
os.environ['GRPC_VERBOSITY'] = 'DEBUG'
os.environ['GRPC_TRACE'] = 'connectivity_state,channel,client_channel,transport_flow_control,http,call_error,subchannel,api'
# 핵심 서브시스템 로깅으로 집중
os.environ['GRPC_GO_LOG_SEVERITY_LEVEL'] = 'INFO'
os.environ['GRPC_GO_LOG_VERBOSITY_LEVEL'] = '2'

# 기본 로깅 설정
logging.basicConfig(level=logging.DEBUG)

# 로그 저장 디렉토리
LOG_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'logs'))

# 터미널 로그 파일 경로
timestamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
TERMINAL_LOG_FILE = os.path.join(LOG_DIR, f"terminal_output_{timestamp}.log")

app = Flask(__name__)
app.config['SECRET_KEY'] = 'grpc-error-handling-secret-key'
socketio = SocketIO(app, cors_allowed_origins="*")

logger = setup_logging("front_service")

# Werkzeug 로거 설정 (HTTP 로그용)
werkzeug_logger = logging.getLogger('werkzeug')
werkzeug_logger.setLevel(logging.INFO)
werkzeug_handler = logging.FileHandler(os.path.join(LOG_DIR, f"werkzeug_{timestamp}.log"))
werkzeug_handler.setFormatter(logging.Formatter('%(asctime)s - %(message)s'))
werkzeug_logger.addHandler(werkzeug_handler)

# BFF 서비스 주소 (환경 변수에서 읽기)
BFF_ADDRESS = os.environ.get("BFF_SERVICE_ADDRESS", "localhost:50051")
logger.info(f"BFF 서비스 주소: {BFF_ADDRESS}")

# 로그 메시지 큐
log_queue = queue.Queue()

# 카스텀 로그 처리 시스템 - 로그 종류를 식별하는 패턴
WERKZEUG_PATTERN = re.compile(r'^\[werkzeug\]', re.IGNORECASE)
GRPC_CORE_PATTERN = re.compile(r'(src/core/|I\d{4}|D\d{4}|completion_queue|channel|client_channel|connectivity)', re.IGNORECASE)
SYSTEM_LOG_PATTERN = re.compile(r'^\[시스템\]', re.IGNORECASE)

# 로그 메시지 ID를 추적하여 중복 방지
processed_log_ids = set()

# Protobuf 메시지를 포맷팅하는 함수 개선
def format_protobuf_message(message):
    """Protobuf 메시지를 가독성 있는 형식으로 변환"""
    if not message:
        return "빈 메시지"
    
    try:
        # Protobuf 메시지를 사전으로 변환
        message_dict = {}
        for field, value in message.ListFields():
            message_dict[field.name] = value
        
        # 사전을 JSON 형식의 문자열로 변환
        formatted_json = json.dumps(message_dict, ensure_ascii=False, indent=2)
        return formatted_json
    except Exception as e:
        return f"{str(message)} (포맷 오류: {str(e)})"

# gRPC 인터셉터를 위한 클래스 개선
class DetailedGrpcInterceptor(grpc.UnaryUnaryClientInterceptor):
    def __init__(self, log_queue, service_name="grpc_client"):
        self.service_name = service_name
        self.logger = logging.getLogger(f"grpc_interceptor.{service_name}")
        self.log_queue = log_queue
        
    def _log_to_queue(self, log_type, content, is_debug=False):
        """로그 큐에 로그 추가"""
        # 로그 중복 방지를 위한 ID 생성
        log_id = hash(f"{log_type}:{content}")
        
        if log_id in processed_log_ids:
            return  # 이미 처리된 로그는 무시
            
        processed_log_ids.add(log_id)
        
        # 최대 1000개 ID만 유지 (메모리 누수 방지)
        if len(processed_log_ids) > 1000:
            processed_log_ids.clear()
        
        self.log_queue.put({
            'type': log_type,
            'logs': [{
                'service': self.service_name,
                'content': content,
                'is_debug': is_debug
            }]
        })
        
    def _extract_metadata(self, metadata):
        """메타데이터 추출 및 문자열 변환"""
        if metadata is None:
            return "없음"
        return ", ".join([f"{k}={v}" for k, v in dict(metadata).items()])
    
    def _format_message(self, message):
        """메시지 내용 포맷팅 - 개선된 방법"""
        if hasattr(message, "ListFields"):
            # Protobuf 메시지 객체인 경우 향상된 포맷팅
            return format_protobuf_message(message)
        return str(message)
    
    def intercept_unary_unary(self, continuation, client_call_details, request):
        # 요청 정보 추출
        method = client_call_details.method.decode('utf-8') if isinstance(client_call_details.method, bytes) else client_call_details.method
        method_name = method.split('/')[-1] if '/' in method else method
        service_name = method.split('/')[-2].split('.')[-1] if '/' in method else "unknown"
        
        # 타임아웃 정보 추출
        timeout = client_call_details.timeout
        timeout_str = f"{timeout}초" if timeout is not None else "무제한"
        
        # 메타데이터 추출
        metadata_str = self._extract_metadata(client_call_details.metadata)
        
        # 요청 메시지 포맷팅
        request_str = self._format_message(request)
        
        # 요청 로그
        request_log = f"[gRPC 요청] 서비스: {service_name}, 메서드: {method_name}\n" + \
                      f"타임아웃: {timeout_str}, 메타데이터: {metadata_str}\n" + \
                      f"메시지: {request_str}"
        
        self.logger.info(f"요청 발송: {method_name}")
        
        # 로그 큐에 추가 - gRPC 로그에 추가
        self._log_to_queue('grpc', request_log)
        
        try:
            # 실제 gRPC 호출
            start_call_time = time.time()
            response_future = continuation(client_call_details, request)
            
            # 응답 대기 및 로깅
            response = response_future
            
            elapsed = time.time() - start_call_time
            
            # 응답 메시지 포맷팅
            try:
                response_str = self._format_message(response)
            except Exception as e:
                response_str = f"<응답 포맷팅 실패: {str(e)}>"
            
            # 응답 로그
            response_log = f"[gRPC 응답] 서비스: {service_name}, 메서드: {method_name}\n" + \
                           f"소요시간: {elapsed:.3f}초, 상태: 성공\n" + \
                           f"응답: {response_str}"
            
            self.logger.info(f"응답 수신: {method_name} ({elapsed:.3f}초)")
            
            # 로그 큐에 추가 - gRPC 로그에 추가
            self._log_to_queue('grpc', response_log)
            
            return response
            
        except grpc.RpcError as e:
            # 응답 시간 측정
            elapsed = time.time() - start_call_time
            
            # 오류 로그
            error_log = f"[gRPC 오류] 서비스: {service_name}, 메서드: {method_name}\n" + \
                        f"소요시간: {elapsed:.3f}초, 코드: {e.code()}\n" + \
                        f"상세: {e.details()}"
            
            self.logger.error(f"오류 발생: {method_name} - {e.code()} ({elapsed:.3f}초)")
            
            # 로그 큐에 추가 - gRPC 로그에 추가
            self._log_to_queue('grpc', error_log)
            
            raise
        except Exception as e:
            # 응답 시간 측정
            elapsed = time.time() - start_call_time
            
            # 오류 로그
            error_log = f"[gRPC 예외] 서비스: {service_name}, 메서드: {method_name}\n" + \
                        f"소요시간: {elapsed:.3f}초\n" + \
                        f"예외: {str(e)}"
            
            self.logger.error(f"예외 발생: {method_name} - {str(e)} ({elapsed:.3f}초)")
            
            # 로그 큐에 추가 - gRPC 로그에 추가
            self._log_to_queue('grpc', error_log)
            
            raise

# gRPC 디버그 로그 캡처를 위한 TerminalCapture 클래스 수정
class TerminalCapture:
    def __init__(self, log_queue, log_file):
        self.log_queue = log_queue
        self.log_file = log_file
        self.file = open(log_file, 'a', encoding='utf-8')
        self.original_stdout = sys.stdout
        self.original_stderr = sys.stderr
        self.last_log_line = ""
        self.debug_buffer = []
        self.setup()
        
        # gRPC 디버그 로그 패턴 - 더 넓게 확장
        self.grpc_debug_pattern = re.compile(
            r'(I\d{5}|D\d{5}|E\d{5}|W\d{5}|src/core/|connectivity_state|' +
            r'chttp2_transport|client_channel|transport_|ConnectivityStateChange|' +
            r'completion_queue|grpc_|subchannel|resolver|000001[A-F0-9]{8,}|' +
            r'handshaker|fd_|call_|ssl_|polling_|dns_|tcp_|client_|timer_|connected_|' +
            r'api.cc|channel.cc|endpoint.cc|alarm.cc)',
            re.IGNORECASE
        )
        
        # Werkzeug 로그 패턴
        self.werkzeug_pattern = re.compile(r'^\[werkzeug\]', re.IGNORECASE)
        
    def setup(self):
        """표준 출력 및 에러를 파일로 리다이렉트"""
        sys.stdout = self
        sys.stderr = self
        
    def write(self, message):
        """메시지 작성 시 원본 스트림과 파일 모두에 출력"""
        self.original_stdout.write(message)
        self.file.write(message)
        self.file.flush()
        
        # 디버깅 메시지 수집
        if message.strip():
            # 중복 로그 방지
            if message.strip() == self.last_log_line:
                return
                
            self.last_log_line = message.strip()
            
            # Werkzeug 로그는 무시
            if self.werkzeug_pattern.search(message):
                return
            
            # 실제 gRPC 저수준 로그인지 확인
            if self.grpc_debug_pattern.search(message):
                # 로그 중복 방지를 위한 ID 생성
                log_id = hash(message.strip())
                
                if log_id in processed_log_ids:
                    return  # 이미 처리된 로그는 무시
                    
                processed_log_ids.add(log_id)
                
                # 디버그 정보 분석
                is_debug = "D" in message[:10]  # D로 시작하는 것은 디버그 로그
                
                # 로그 큐에 추가
                self.log_queue.put({
                    'type': 'grpc',
                    'logs': [{
                        'service': 'gRPC 코어',
                        'content': message.rstrip(),
                        'is_debug': is_debug
                    }]
                })
        
    def flush(self):
        """버퍼 비우기"""
        self.original_stdout.flush()
        self.file.flush()
        
    def close(self):
        """리소스 정리"""
        sys.stdout = self.original_stdout
        sys.stderr = self.original_stderr
        self.file.close()

# 향상된 로그 파일 모니터링 클래스
class EnhancedLogWatcher:
    def __init__(self, log_dir, log_queue):
        self.log_dir = log_dir
        self.log_queue = log_queue
        self.file_positions = {}
        self.processed_lines = set()  # 중복 방지용
        self.max_processed_lines = 1000  # 메모리 사용 제한
        
    def scan_for_logs(self):
        """초기 로그 파일 스캔"""
        log_files = [f for f in os.listdir(self.log_dir) if f.endswith('.log')]
        for log_file in log_files:
            file_path = os.path.join(self.log_dir, log_file)
            self.file_positions[file_path] = os.path.getsize(file_path)
            logging.info(f"로그 파일 발견: {log_file}")
    
    def check_files(self):
        """모든 로그 파일 확인"""
        log_files = [f for f in os.listdir(self.log_dir) if f.endswith('.log')]
        for log_file in log_files:
            file_path = os.path.join(self.log_dir, log_file)
            if file_path not in self.file_positions:
                self.file_positions[file_path] = 0
            self.process_log_file(file_path)
    
    def process_log_file(self, file_path):
        """로그 파일 처리"""
        try:
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
                
                # 라인별로 처리하여 중복 방지
                for line in new_content.splitlines():
                    if line.strip():
                        # 중복 확인
                        line_hash = hash(line)
                        if line_hash in self.processed_lines:
                            continue
                            
                        self.processed_lines.add(line_hash)
                        
                        # 최대 처리 라인 수 제한
                        if len(self.processed_lines) > self.max_processed_lines:
                            self.processed_lines.clear()
                        
                        # 로그 타입 결정
                        log_type = 'processed'
                        if 'grpc' in line.lower() or 'rpc' in line.lower():
                            log_type = 'grpc'
                        
                        # 로그 큐에 추가
                        self.log_queue.put({
                            'type': log_type,
                            'logs': [{
                                'service': service_name,
                                'content': line.strip(),
                                'is_from_file': True  # 파일에서 읽은 로그 표시
                            }]
                        })
                    
        except Exception as e:
            logging.error(f"로그 파일 처리 중 오류: {str(e)}")
            
    def get_terminal_log(self):
        """터미널 로그 파일을 읽어서 로그 큐에 추가"""
        if os.path.exists(TERMINAL_LOG_FILE):
            self.process_log_file(TERMINAL_LOG_FILE)

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

# 로그 파일 모니터링 스레드 함수
def log_monitor_thread(log_watcher):
    """로그 파일 모니터링 스레드"""
    while True:
        try:
            log_watcher.check_files()
            # 터미널 로그 파일도 모니터링
            log_watcher.get_terminal_log()
            time.sleep(0.1)  # 짧은 간격으로 확인
        except Exception as e:
            logger.error(f"로그 모니터링 중 오류: {str(e)}")
            time.sleep(1)

# gRPC 채널 생성 함수
def create_channel(address, log_queue=None, service_name="bff_client"):
    """인터셉터가 포함된 gRPC 채널 생성"""
    # 향상된 채널 옵션 설정
    options = [
        ('grpc.enable_http_proxy', 0),
        ('grpc.max_receive_message_length', 1024 * 1024 * 10),  # 10MB
        ('grpc.enable_retries', 1),
        ('grpc.keepalive_time_ms', 30000),  # 30 seconds
        ('grpc.keepalive_timeout_ms', 10000),  # 10 seconds
        ('grpc.http2.max_pings_without_data', 0),
        ('grpc.http2.min_time_between_pings_ms', 10000),  # 10 seconds
        ('grpc.http2.min_ping_interval_without_data_ms', 5000)  # 5 seconds
    ]
    
    if log_queue:
        interceptor = DetailedGrpcInterceptor(log_queue, service_name=service_name)
        return grpc.intercept_channel(
            grpc.insecure_channel(address, options=options), 
            interceptor
        )
    else:
        return grpc.insecure_channel(address, options=options)

# BFF 서비스 호출 함수
def call_bff(request_type, use_deadline, use_circuit_breaker, use_backpressure, backend_type):
    """BFF 서비스 호출"""
    logger.info(f"[Front] BFF 서비스 호출 시작 (백엔드: {backend_type})")
    
    start_time = time.time()
    
    try:
        # 인터셉터가 포함된 채널 생성
        channel = create_channel(BFF_ADDRESS, log_queue, "bff_client")
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

# test_api 함수 수정 - 직접 로그 큐에 추가하고 로거는 사용하지 않음
@app.route('/api/test', methods=['POST'])
def test_api():
    """테스트 API 엔드포인트"""
    data = request.json
    request_type = data.get('request_type', 'normal')
    use_deadline = data.get('use_deadline', False)
    use_circuit_breaker = data.get('use_circuit_breaker', False)
    use_backpressure = data.get('use_backpressure', False)
    backend_type = data.get('backend_type', 'no_pattern')
    
    # 로거 사용 안 함 (로그 중복 방지)
    # logger.info(f"[Front] 테스트 API 호출 - 요청 유형: {request_type}, 백엔드: {backend_type}")
    
    result = call_bff(request_type, use_deadline, use_circuit_breaker, use_backpressure, backend_type)
    
    # 테스트 결과 로그 직접 추가 - 가공된 로그 탭에 표시
    log_content = f"====== 테스트 실행 ({datetime.datetime.now().strftime('%H:%M:%S')}) ======\n"
    log_content += f"백엔드: {backend_type}\n"
    log_content += f"요청 유형: {request_type}\n"
    log_content += f"패턴 설정: 데드라인={use_deadline}, 서킷브레이커={use_circuit_breaker}, 백프레셔={use_backpressure}\n"
    log_content += f"요청 시간: {result['elapsed_time']:.2f}초\n"
    
    if result['success']:
        log_content += f"성공: {result['result']}"
    else:
        log_content += f"실패: {result['error_message']}"
    
    # 로그 중복 체크를 위한 ID 생성
    log_id = hash(log_content)
    
    # 중복되지 않은 경우에만 로그 추가
    if log_id not in processed_log_ids:
        processed_log_ids.add(log_id)
        
        # 로그 큐에 직접 추가
        log_queue.put({
            'type': 'processed',
            'logs': [{
                'service': '시스템',
                'content': log_content,
                'timestamp': datetime.datetime.now().strftime('%H:%M:%S')
            }]
        })
    
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
        channel = create_channel(BFF_ADDRESS, log_queue, "bff_client")
        stub = bff_pb2_grpc.BffServiceStub(channel)
        
        reset_request = bff_pb2.ResetRequest(
            pattern=pattern,
            backend_type=backend_type
        )
        
        response = stub.ResetPattern(reset_request)
        
        # 가공된 로그에 결과 추가
        log_content = f"====== 패턴 리셋 ({datetime.datetime.now().strftime('%H:%M:%S')}) ======\n"
        log_content += f"백엔드: {backend_type}\n"
        log_content += f"패턴: {pattern}\n"
        
        if response.success:
            log_content += f"성공: {response.message}"
        else:
            log_content += f"실패: {response.message}"
        
        # 로그 중복 체크를 위한 ID 생성
        log_id = hash(log_content)
        
        # 중복되지 않은 경우에만 로그 추가
        if log_id not in processed_log_ids:
            processed_log_ids.add(log_id)
            
            log_queue.put({
                'type': 'processed',
                'logs': [{
                    'service': '시스템',
                    'content': log_content,
                    'timestamp': datetime.datetime.now().strftime('%H:%M:%S')
                }]
            })
        
        return jsonify({
            "success": response.success,
            "message": response.message
        })
    except Exception as e:
        logger.exception("[Front] 패턴 리셋 중 오류")
        
        # 오류 로그 추가
        log_content = f"====== 패턴 리셋 오류 ({datetime.datetime.now().strftime('%H:%M:%S')}) ======\n"
        log_content += f"백엔드: {backend_type}\n"
        log_content += f"패턴: {pattern}\n"
        log_content += f"오류: {str(e)}"
        
        # 로그 중복 체크를 위한 ID 생성
        log_id = hash(log_content)
        
        # 중복되지 않은 경우에만 로그 추가
        if log_id not in processed_log_ids:
            processed_log_ids.add(log_id)
            
            log_queue.put({
                'type': 'processed',
                'logs': [{
                    'service': '시스템',
                    'content': log_content,
                    'timestamp': datetime.datetime.now().strftime('%H:%M:%S')
                }]
            })
        
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
        channel = create_channel(BFF_ADDRESS, log_queue, "bff_client")
        stub = bff_pb2_grpc.BffServiceStub(channel)
        
        status_request = bff_pb2.StatusRequest(
            backend_type=backend_type
        )
        
        response = stub.GetStatus(status_request)
        
        # 가공된 로그에 결과 추가
        log_content = f"====== 패턴 상태 조회 ({datetime.datetime.now().strftime('%H:%M:%S')}) ======\n"
        log_content += f"백엔드: {backend_type}\n"
        
        if response.success:
            log_content += f"서킷브레이커: {response.circuit_breaker_state} ({response.circuit_breaker_failures})\n"
            log_content += f"백프레셔: 활성 요청 {response.backpressure_active_requests}개, 과부하={response.backpressure_overloaded}"
            
            # 로그 중복 체크를 위한 ID 생성
            log_id = hash(log_content)
            
            # 중복되지 않은 경우에만 로그 추가
            if log_id not in processed_log_ids:
                processed_log_ids.add(log_id)
                
                log_queue.put({
                    'type': 'processed',
                    'logs': [{
                        'service': '시스템',
                        'content': log_content,
                        'timestamp': datetime.datetime.now().strftime('%H:%M:%S')
                    }]
                })
            
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
            log_content += f"상태 조회 실패: {response.error_message}"
            
            # 로그 중복 체크를 위한 ID 생성
            log_id = hash(log_content)
            
            # 중복되지 않은 경우에만 로그 추가
            if log_id not in processed_log_ids:
                processed_log_ids.add(log_id)
                
                log_queue.put({
                    'type': 'processed',
                    'logs': [{
                        'service': '시스템',
                        'content': log_content,
                        'timestamp': datetime.datetime.now().strftime('%H:%M:%S')
                    }]
                })
            
            return jsonify({
                "success": False,
                "message": response.error_message
            })
    except Exception as e:
        logger.exception("[Front] 패턴 상태 조회 중 오류")
        
        # 오류 로그 추가
        log_content = f"====== 패턴 상태 조회 오류 ({datetime.datetime.now().strftime('%H:%M:%S')}) ======\n"
        log_content += f"백엔드: {backend_type}\n"
        log_content += f"오류: {str(e)}"
        
        # 로그 중복 체크를 위한 ID 생성
        log_id = hash(log_content)
        
        # 중복되지 않은 경우에만 로그 추가
        if log_id not in processed_log_ids:
            processed_log_ids.add(log_id)
            
            log_queue.put({
                'type': 'processed',
                'logs': [{
                    'service': '시스템',
                    'content': log_content,
                    'timestamp': datetime.datetime.now().strftime('%H:%M:%S')
                }]
            })
        
        return jsonify({
            "success": False,
            "message": f"상태 조회 실패: {str(e)}"
        })