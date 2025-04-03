import grpc
import logging
import time
from concurrent import futures
import threading

# gRPC 생성된 모듈들 import
import sys
sys.path.append('.')  # 현재 디렉토리에서 모듈 찾기
import service_pb2
import service_pb2_grpc

# 로깅 설정
from common.logging_config import setup_logger, log_event, add_event

# 로거 설정
logger = setup_logger("GRPC_CLIENT")

class UserServiceClient:
    """백엔드 서비스와 통신하는 gRPC 클라이언트"""
    
    def __init__(self, server_address):
        """
        매개변수:
            server_address: gRPC 서버 주소 (예: localhost:50051)
        """
        self.server_address = server_address
        self.service_status = {"available": False, "last_error": None}
        self._status_lock = threading.Lock()
        self._connect()
        
    def _connect(self):
        """gRPC 채널 생성 및 연결"""
        try:
            # 채널 생성
            self.channel = grpc.insecure_channel(
                self.server_address,
                options=[
                    ('grpc.max_send_message_length', 10 * 1024 * 1024),
                    ('grpc.max_receive_message_length', 10 * 1024 * 1024),
                    ('grpc.keepalive_time_ms', 20000),
                    ('grpc.keepalive_timeout_ms', 10000),
                    ('grpc.keepalive_permit_without_calls', 1),
                    ('grpc.http2.max_pings_without_data', 0),
                    ('grpc.http2.min_time_between_pings_ms', 10000),
                    ('grpc.http2.min_ping_interval_without_data_ms', 5000)
                ]
            )
            self.stub = service_pb2_grpc.UserServiceStub(self.channel)
            log_event(logger, "INFO", f"gRPC 클라이언트 초기화 완료: {self.server_address}")
            
            with self._status_lock:
                self.service_status["available"] = True
                self.service_status["last_error"] = None
                
        except Exception as e:
            log_event(logger, "ERROR", f"gRPC 클라이언트 초기화 실패: {str(e)}")
            
            with self._status_lock:
                self.service_status["available"] = False
                self.service_status["last_error"] = str(e)
                
            raise
    
    def check_health(self):
        """백엔드 서비스 상태 확인"""
        try:
            # 간단한 호출로 상태 확인 (타임아웃 감소)
            request = service_pb2.ListUsersRequest(page=1, page_size=1)
            response = self.stub.ListUsers(request, timeout=1)  # 1초로 감소
            
            with self._status_lock:
                self.service_status["available"] = True
                self.service_status["last_error"] = None
                
            log_event(logger, "INFO", "백엔드 상태 확인 성공")
            return True
        except Exception as e:
            log_event(logger, "ERROR", f"백엔드 상태 확인 실패: {str(e)}")
            
            with self._status_lock:
                self.service_status["available"] = False
                self.service_status["last_error"] = str(e)
                
            add_event("error", f"백엔드 연결 실패: {str(e)}")
            raise
    
    def get_status(self):
        """현재 서비스 상태 반환"""
        with self._status_lock:
            return self.service_status.copy()
    
    def get_user(self, user_id, timeout=5):
        """단일 사용자 정보 조회"""
        log_event(logger, "INFO", f"사용자 조회 요청 (ID: {user_id}, 타임아웃: {timeout if timeout else '없음'})")
        try:
            request = service_pb2.UserRequest(user_id=user_id)
            response = self.stub.GetUser(request, timeout=timeout)
            
            with self._status_lock:
                self.service_status["available"] = True
                self.service_status["last_error"] = None
                
            return {
                "user_id": response.user_id,
                "name": response.name,
                "email": response.email
            }
        except grpc.RpcError as e:
            log_event(logger, "ERROR", f"gRPC 오류 발생: {e.code()} - {e.details()}")
            
            with self._status_lock:
                # NOT_FOUND는 정상적인 상태 코드이므로 서비스를 사용할 수 없는 것으로 간주하지 않음
                if e.code() != grpc.StatusCode.NOT_FOUND:
                    self.service_status["available"] = False
                    self.service_status["last_error"] = f"{e.code()}: {e.details()}"
            
            raise
        except Exception as e:
            log_event(logger, "ERROR", f"사용자 조회 중 오류 발생: {str(e)}")
            
            with self._status_lock:
                self.service_status["available"] = False
                self.service_status["last_error"] = str(e)
                
            raise
    
    def get_user_with_delay(self, user_id, delay=0, timeout=5):
        """지연을 추가한 사용자 조회 (데드라인 테스트용)"""
        log_event(logger, "INFO", f"지연 있는 사용자 조회 요청 (ID: {user_id}, 지연: {delay}초, 타임아웃: {timeout if timeout else '없음'})")
        try:
            # 메타데이터에 지연 정보 추가
            metadata = (('delay', str(delay)),)
            request = service_pb2.UserRequest(user_id=user_id)
            response = self.stub.GetUser(request, timeout=timeout, metadata=metadata)
            
            with self._status_lock:
                self.service_status["available"] = True
                self.service_status["last_error"] = None
                
            return {
                "user_id": response.user_id,
                "name": response.name,
                "email": response.email
            }
        except grpc.RpcError as e:
            log_event(logger, "ERROR", f"gRPC 오류 발생: {e.code()} - {e.details()}")
            
            # 특정 에러 코드에 대한 이벤트 기록
            if e.code() == grpc.StatusCode.DEADLINE_EXCEEDED:
                add_event("deadline", f"데드라인 초과: 사용자 조회 (ID: {user_id}, 제한시간: {timeout}초)")
            elif e.code() == grpc.StatusCode.RESOURCE_EXHAUSTED:
                add_event("backpressure", f"백프레셔: 사용자 조회 거부 (ID: {user_id})")
            
            with self._status_lock:
                # NOT_FOUND는 정상적인 상태 코드이므로 서비스를 사용할 수 없는 것으로 간주하지 않음
                if e.code() != grpc.StatusCode.NOT_FOUND:
                    self.service_status["available"] = False
                    self.service_status["last_error"] = f"{e.code()}: {e.details()}"
            
            raise
        except Exception as e:
            log_event(logger, "ERROR", f"사용자 조회 중 오류 발생: {str(e)}")
            
            with self._status_lock:
                self.service_status["available"] = False
                self.service_status["last_error"] = str(e)
                
            raise
    
    def list_users(self, page=1, page_size=10, timeout=5):
        """사용자 목록 조회"""
        log_event(logger, "INFO", f"사용자 목록 조회 요청 (페이지: {page}, 페이지 크기: {page_size})")
        try:
            request = service_pb2.ListUsersRequest(page=page, page_size=page_size)
            response = self.stub.ListUsers(request, timeout=timeout)
            
            users = []
            for user in response.users:
                users.append({
                    "user_id": user.user_id,
                    "name": user.name,
                    "email": user.email
                })
            
            with self._status_lock:
                self.service_status["available"] = True
                self.service_status["last_error"] = None
                
            return users
        except Exception as e:
            log_event(logger, "ERROR", f"사용자 목록 조회 중 오류 발생: {str(e)}")
            
            with self._status_lock:
                self.service_status["available"] = False
                self.service_status["last_error"] = str(e)
                
            raise
    
    def create_user(self, name, email, timeout=5):
        """사용자 생성"""
        log_event(logger, "INFO", f"사용자 생성 요청 (이름: {name}, 이메일: {email})")
        try:
            request = service_pb2.CreateUserRequest(name=name, email=email)
            response = self.stub.CreateUser(request, timeout=timeout)
            
            with self._status_lock:
                self.service_status["available"] = True
                self.service_status["last_error"] = None
                
            return {
                "user_id": response.user_id,
                "name": response.name,
                "email": response.email
            }
        except Exception as e:
            log_event(logger, "ERROR", f"사용자 생성 중 오류 발생: {str(e)}")
            
            with self._status_lock:
                self.service_status["available"] = False
                self.service_status["last_error"] = str(e)
                
            raise
    
    def set_error_rate(self, error_rate):
        """백엔드의 에러 발생률 설정 (서킷 브레이커 테스트용)"""
        log_event(logger, "INFO", f"에러 발생률 설정 요청 ({error_rate}%)")
        try:
            # 메타데이터로 에러율 전달
            metadata = (('error_rate', str(error_rate)),)
            request = service_pb2.ListUsersRequest(page=1, page_size=1)
            response = self.stub.ListUsers(request, metadata=metadata, timeout=3)
            
            # 이벤트 기록
            add_event("settings", f"에러율 {error_rate}%로 설정")
            return True
        except Exception as e:
            log_event(logger, "ERROR", f"에러율 설정 중 오류 발생: {str(e)}")
            # 이 경우 에러를 전파하지 않고 무시함
            return False
    
    def set_backpressure_enabled(self, enabled):
        """백엔드의 백프레셔 상태 변경"""
        status_str = "활성화" if enabled else "비활성화"
        log_event(logger, "INFO", f"백프레셔 상태 변경 요청: {status_str}")
        try:
            # 메타데이터를 통해 백프레셔 상태 전달
            metadata = (('backpressure_enabled', str(enabled).lower()),)
            request = service_pb2.ListUsersRequest(page=1, page_size=1)
            self.stub.ListUsers(request, metadata=metadata, timeout=3)
            
            # 이벤트 기록
            add_event("settings", f"백프레셔 {status_str}")
            return True
        except Exception as e:
            log_event(logger, "ERROR", f"백프레셔 상태 변경 중 오류 발생: {str(e)}")
            return False
        
    def reset_backpressure(self):
        """백프레셔 메커니즘 초기화"""
        log_event(logger, "INFO", "백프레셔 초기화 요청", "백프레셔")
        try:
            # 메타데이터를 통해 백프레셔 초기화 신호 전달
            metadata = (('reset_backpressure', 'true'),)
            request = service_pb2.ListUsersRequest(page=1, page_size=1)
            self.stub.ListUsers(request, metadata=metadata, timeout=3)
            
            # 이벤트 기록
            add_event("backpressure", "백프레셔 메커니즘 초기화")
            return True
        except Exception as e:
            log_event(logger, "ERROR", f"백프레셔 초기화 중 오류 발생: {str(e)}", "백프레셔")
            return False
    
    def close(self):
        """gRPC 채널 종료"""
        if hasattr(self, 'channel'):
            self.channel.close()
            log_event(logger, "INFO", "gRPC 채널 종료됨")