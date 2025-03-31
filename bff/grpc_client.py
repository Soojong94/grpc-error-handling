import grpc
import logging
import time
from concurrent import futures

# gRPC 생성된 모듈들 import
import sys
sys.path.append('.')  # 현재 디렉토리에서 모듈 찾기
import service_pb2
import service_pb2_grpc

# 로깅 설정
logger = logging.getLogger(__name__)

class UserServiceClient:
    """백엔드 서비스와 통신하는 gRPC 클라이언트"""
    
    def __init__(self, server_address):
        """
        매개변수:
            server_address: gRPC 서버 주소 (예: localhost:50051)
        """
        self.server_address = server_address
        # 채널 생성
        self.channel = grpc.insecure_channel(server_address)
        self.stub = service_pb2_grpc.UserServiceStub(self.channel)
        logger.info(f"gRPC 클라이언트 초기화 완료: {server_address}")
    
    def check_health(self):
        """백엔드 서비스 상태 확인"""
        try:
            # 간단한 호출로 상태 확인
            request = service_pb2.ListUsersRequest(page=1, page_size=1)
            response = self.stub.ListUsers(request, timeout=2)
            return True
        except Exception as e:
            logger.error(f"백엔드 상태 확인 실패: {str(e)}")
            raise
    
    def check_db_health(self):
        """DB 상태 확인 (백엔드를 통해)"""
        try:
            # 실제로는 백엔드에 DB 상태 확인
            request = service_pb2.ListUsersRequest(page=1, page_size=1)
            response = self.stub.ListUsers(request, timeout=2)
            return True
        except Exception as e:
            logger.error(f"DB 상태 확인 실패: {str(e)}")
            raise
    
    def get_user(self, user_id, timeout=5):
        """단일 사용자 정보 조회"""
        logger.info(f"사용자 조회 요청 (ID: {user_id}, 타임아웃: {timeout if timeout else '없음'})")
        try:
            request = service_pb2.UserRequest(user_id=user_id)
            response = self.stub.GetUser(request, timeout=timeout)
            return {
                "user_id": response.user_id,
                "name": response.name,
                "email": response.email
            }
        except grpc.RpcError as e:
            logger.error(f"gRPC 오류 발생: {e.code()} - {e.details()}")
            raise
        except Exception as e:
            logger.error(f"사용자 조회 중 오류 발생: {str(e)}")
            raise
    
    def get_user_with_delay(self, user_id, delay=0, timeout=5):
        """지연을 추가한 사용자 조회 (데드라인 테스트용)"""
        logger.info(f"지연 있는 사용자 조회 요청 (ID: {user_id}, 지연: {delay}초, 타임아웃: {timeout if timeout else '없음'})")
        try:
            # 메타데이터에 지연 정보 추가
            metadata = (('delay', str(delay)),)
            request = service_pb2.UserRequest(user_id=user_id)
            response = self.stub.GetUser(request, timeout=timeout, metadata=metadata)
            return {
                "user_id": response.user_id,
                "name": response.name,
                "email": response.email
            }
        except grpc.RpcError as e:
            logger.error(f"gRPC 오류 발생: {e.code()} - {e.details()}")
            raise
        except Exception as e:
            logger.error(f"사용자 조회 중 오류 발생: {str(e)}")
            raise
    
    def list_users(self, page=1, page_size=10):
        """사용자 목록 조회"""
        logger.info(f"사용자 목록 조회 요청 (페이지: {page}, 페이지 크기: {page_size})")
        try:
            request = service_pb2.ListUsersRequest(page=page, page_size=page_size)
            response = self.stub.ListUsers(request)
            
            users = []
            for user in response.users:
                users.append({
                    "user_id": user.user_id,
                    "name": user.name,
                    "email": user.email
                })
            
            return users
        except Exception as e:
            logger.error(f"사용자 목록 조회 중 오류 발생: {str(e)}")
            raise
    
    def create_user(self, name, email):
        """사용자 생성"""
        logger.info(f"사용자 생성 요청 (이름: {name}, 이메일: {email})")
        try:
            request = service_pb2.CreateUserRequest(name=name, email=email)
            response = self.stub.CreateUser(request)
            
            return {
                "user_id": response.user_id,
                "name": response.name,
                "email": response.email
            }
        except Exception as e:
            logger.error(f"사용자 생성 중 오류 발생: {str(e)}")
            raise
    
    def set_error_rate(self, error_rate):
        """백엔드의 에러 발생률 설정 (서킷 브레이커 테스트용)"""
        logger.info(f"에러 발생률 설정 요청 ({error_rate}%)")
        try:
            # 메타데이터로 에러율 전달
            metadata = (('error_rate', str(error_rate)),)
            request = service_pb2.ListUsersRequest(page=1, page_size=1)
            response = self.stub.ListUsers(request, metadata=metadata)
            return True
        except Exception as e:
            logger.error(f"에러율 설정 중 오류 발생: {str(e)}")
            # 이 경우 에러를 전파하지 않고 무시함
            return False
    
    def set_backpressure_enabled(self, enabled):
        """백엔드의 백프레셔 상태 변경"""
        logger.info(f"백프레셔 상태 변경 요청: {'활성화' if enabled else '비활성화'}")
        try:
            # 메타데이터를 통해 백프레셔 상태 전달
            metadata = (('backpressure_enabled', str(enabled).lower()),)
            request = service_pb2.ListUsersRequest(page=1, page_size=1)
            self.stub.ListUsers(request, metadata=metadata)
            return True
        except Exception as e:
            logger.error(f"백프레셔 상태 변경 중 오류 발생: {str(e)}")
            return False
        
    def reset_backpressure(self):
        """백프레셔 메커니즘 초기화"""
        logger.info("백프레셔 초기화 요청")
        try:
            # 메타데이터를 통해 백프레셔 초기화 신호 전달
            metadata = (('reset_backpressure', 'true'),)
            request = service_pb2.ListUsersRequest(page=1, page_size=1)
            self.stub.ListUsers(request, metadata=metadata)
            return True
        except Exception as e:
            logger.error(f"백프레셔 초기화 중 오류 발생: {str(e)}")
            return False