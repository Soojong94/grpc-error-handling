import grpc
import time
import random
import threading
from concurrent import futures
import sys
import os

# 상위 디렉토리 경로 추가
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# gRPC 생성된 모듈
import service_pb2
import service_pb2_grpc

# 공통 모듈
from common.logging_config import setup_logger, log_event
from common.utils import add_event
from db_client import DBClient

# 로거 설정
logger = setup_logger("BACKEND")

# 글로벌 설정
MAX_CONCURRENT_REQUESTS = 10  # 백프레셔 제한값

# 백프레셔 구현을 위한 세마포어
request_semaphore = threading.Semaphore(MAX_CONCURRENT_REQUESTS)

# 세마포어 상태 조회 함수
def get_semaphore_status():
    """현재 세마포어 상태 반환"""
    # 현재 가용 슬롯 수 추정 - 비표준 방식이나 상태 표시용
    try:
        # 이 방식은 세마포어 내부 상태에 의존하므로 변경될 수 있음
        available = request_semaphore._value
        return {
            "max_requests": MAX_CONCURRENT_REQUESTS,
            "available_slots": available,
            "active_requests": MAX_CONCURRENT_REQUESTS - available
        }
    except:
        # 세마포어 내부 상태 접근 실패시 기본값
        return {
            "max_requests": MAX_CONCURRENT_REQUESTS,
            "available_slots": "알 수 없음",
            "active_requests": "알 수 없음"
        }

class UserServiceServicer(service_pb2_grpc.UserServiceServicer):
    """gRPC 서비스 구현"""
    
    def __init__(self):
        try:
            self.db = DBClient()
            self.error_rate = 0  # 에러 발생률
            self.backpressure_enabled = True  # 백프레셔 활성화 상태
            log_event(logger, "INFO", "UserServiceServicer 초기화 완료")
        except Exception as e:
            log_event(logger, "ERROR", f"UserServiceServicer 초기화 실패: {str(e)}")
            raise
    
    def should_generate_error(self):
        """현재 에러율에 따라 에러를 발생시켜야 하는지 결정"""
        return random.randint(1, 100) <= self.error_rate
    
    def GetUser(self, request, context):
        """단일 사용자 정보 조회"""
        user_id = request.user_id
        log_event(logger, "INFO", f"사용자 조회 요청 (ID: {user_id})")
        
        # 메타데이터에서 지연 정보 확인
        delay = 0
        for key, value in context.invocation_metadata():
            if key == 'delay':
                try:
                    delay = int(value)
                    log_event(logger, "INFO", f"{delay}초 지연 추가 (ID: {user_id})", "슬로우쿼리")
                except ValueError:
                    log_event(logger, "WARNING", f"잘못된 지연 값: {value}")
        
        # 백프레셔 처리
        acquired = False
        if self.backpressure_enabled:
            acquired = request_semaphore.acquire(blocking=False)
            if not acquired:
                log_event(logger, "WARNING", f"최대 동시 요청 수 초과, 요청 거부 (ID: {user_id})", "백프레셔")
                context.set_code(grpc.StatusCode.RESOURCE_EXHAUSTED)
                context.set_details("서버가 과부하 상태입니다. 나중에 다시 시도해주세요.")
                
                # 이벤트 기록
                add_event("backpressure", f"백프레셔: 사용자 조회 요청 거부 (ID: {user_id})")
                
                return service_pb2.UserResponse()
            log_event(logger, "INFO", f"세마포어 획득 성공, 요청 처리 시작 (ID: {user_id})", "백프레셔")
        
        try:
            # 에러 발생 여부 확인
            if self.should_generate_error():
                log_event(logger, "ERROR", f"의도적 에러 발생 (사용자 ID: {user_id})")
                context.set_code(grpc.StatusCode.INTERNAL)
                context.set_details(f"의도적으로 발생시킨 에러 (사용자 ID: {user_id})")
                
                # 이벤트 기록
                add_event("error", f"의도적 에러: 사용자 조회 (ID: {user_id})")
                
                return service_pb2.UserResponse()
            
            # 슬로우 쿼리 시뮬레이션
            start_time = time.time()
            user = None
            
            if delay > 0:
                log_event(logger, "INFO", f"{delay}초 지연 시작 (ID: {user_id})", "슬로우쿼리")
                user = self.db.get_user(user_id, delay)
                elapsed = time.time() - start_time
                log_event(logger, "INFO", f"{delay}초 지연 완료 (ID: {user_id}, 실제 소요시간: {elapsed:.2f}초)", "슬로우쿼리")
            else:
                user = self.db.get_user(user_id)
            
            # 결과 반환
            if user:
                log_event(logger, "INFO", f"사용자 조회 성공 (ID: {user_id})")
                return service_pb2.UserResponse(
                    user_id=user["user_id"],
                    name=user["name"],
                    email=user["email"]
                )
            else:
                log_event(logger, "WARNING", f"사용자를 찾을 수 없음 (ID: {user_id})")
                context.set_code(grpc.StatusCode.NOT_FOUND)
                context.set_details(f"ID가 {user_id}인 사용자를 찾을 수 없습니다")
                return service_pb2.UserResponse()
                
        except Exception as e:
            log_event(logger, "ERROR", f"사용자 조회 중 오류 발생: {str(e)} (ID: {user_id})")
            context.set_code(grpc.StatusCode.INTERNAL)
            context.set_details(f"서버 오류: {str(e)}")
            return service_pb2.UserResponse()
        finally:
            # 백프레셔 세마포어 반환
            if self.backpressure_enabled and acquired:
                request_semaphore.release()
                log_event(logger, "INFO", f"세마포어 반환 완료 (ID: {user_id})", "백프레셔")
    
    def ListUsers(self, request, context):
        """사용자 목록 조회"""
        page = request.page
        page_size = request.page_size
        log_event(logger, "INFO", f"사용자 목록 조회 요청 (페이지: {page}, 페이지 크기: {page_size})")
        
        # 메타데이터에서 설정 확인
        delay = 0
        for key, value in context.invocation_metadata():
            if key == 'error_rate':
                try:
                    old_rate = self.error_rate
                    self.error_rate = int(value)
                    log_event(logger, "INFO", f"에러율 {self.error_rate}%로 설정됨", "설정")
                    
                    # 에러율 변경 이벤트 기록
                    add_event("settings", f"에러율 변경: {old_rate}% → {self.error_rate}%")
                    
                except ValueError:
                    log_event(logger, "WARNING", f"잘못된 에러율 값: {value}")
            elif key == 'reset_backpressure' and value.lower() == 'true':
                # 세마포어 재설정
                global request_semaphore
                request_semaphore = threading.Semaphore(MAX_CONCURRENT_REQUESTS)
                log_event(logger, "INFO", f"백프레셔 메커니즘 수동 초기화 완료", "백프레셔")
                
                # 백프레셔 초기화 이벤트 기록
                add_event("backpressure", "백프레셔 메커니즘 초기화")
                
                return service_pb2.ListUsersResponse()
            elif key == 'backpressure_enabled':
                old_status = self.backpressure_enabled
                self.backpressure_enabled = value.lower() == 'true'
                status_str = "활성화" if self.backpressure_enabled else "비활성화"
                log_event(logger, "INFO", f"백프레셔 상태 변경: {status_str}", "설정")
                
                # 백프레셔 상태 변경 이벤트 기록
                if old_status != self.backpressure_enabled:
                    add_event("settings", f"백프레셔 {status_str}")
                
            elif key == 'delay':
                try:
                    delay = int(value)
                    log_event(logger, "INFO", f"{delay}초 지연 추가 (목록 조회)", "슬로우쿼리")
                except ValueError:
                    log_event(logger, "WARNING", f"잘못된 지연 값: {value}")
        
        # 백프레셔 처리
        acquired = False
        if self.backpressure_enabled:
            acquired = request_semaphore.acquire(blocking=False)
            if not acquired:
                log_event(logger, "WARNING", "최대 동시 요청 수 초과, 요청 거부 (목록 조회)", "백프레셔")
                context.set_code(grpc.StatusCode.RESOURCE_EXHAUSTED)
                context.set_details("서버가 과부하 상태입니다. 나중에 다시 시도해주세요.")
                
                # 이벤트 기록
                add_event("backpressure", "백프레셔: 사용자 목록 조회 거부")
                
                return service_pb2.ListUsersResponse()
            log_event(logger, "INFO", "세마포어 획득 성공, 요청 처리 시작 (목록 조회)", "백프레셔")
        
        try:
            # 에러 발생 여부 확인
            if self.should_generate_error():
                log_event(logger, "ERROR", "의도적 에러 발생 (사용자 목록 조회)")
                context.set_code(grpc.StatusCode.INTERNAL)
                context.set_details("의도적으로 발생시킨 에러 (사용자 목록 조회)")
                
                # 이벤트 기록
                add_event("error", "의도적 에러: 사용자 목록 조회")
                
                return service_pb2.ListUsersResponse()
            
            # 슬로우 쿼리 시뮬레이션
            start_time = time.time()
            result = None
            
            if delay > 0:
                log_event(logger, "INFO", f"{delay}초 지연 시작 (목록 조회)", "슬로우쿼리")
                result = self.db.list_users(page, page_size, delay)
                elapsed = time.time() - start_time
                log_event(logger, "INFO", f"{delay}초 지연 완료 (목록 조회, 실제 소요시간: {elapsed:.2f}초)", "슬로우쿼리")
            else:
                result = self.db.list_users(page, page_size)
            
            # 결과 생성
            response = service_pb2.ListUsersResponse()
            
            if result:
                response.total_count = result["total_count"]
                
                # 사용자 목록 추가
                for user in result["users"]:
                    user_response = service_pb2.UserResponse(
                        user_id=user["user_id"],
                        name=user["name"],
                        email=user["email"]
                    )
                    response.users.append(user_response)
            
            log_event(logger, "INFO", f"사용자 목록 조회 성공 ({len(response.users)}명)")
            return response
        except Exception as e:
            log_event(logger, "ERROR", f"사용자 목록 조회 중 오류 발생: {str(e)}")
            context.set_code(grpc.StatusCode.INTERNAL)
            context.set_details(f"서버 오류: {str(e)}")
            return service_pb2.ListUsersResponse()
        finally:
            # 백프레셔 세마포어 반환
            if self.backpressure_enabled and acquired:
                request_semaphore.release()
                log_event(logger, "INFO", "세마포어 반환 완료 (목록 조회)", "백프레셔")
    
    def CreateUser(self, request, context):
        """사용자 생성"""
        log_event(logger, "INFO", f"사용자 생성 요청 (이름: {request.name}, 이메일: {request.email})")
        
        # 백프레셔 처리 (쓰기 작업도 제한)
        acquired = False
        if self.backpressure_enabled:
            acquired = request_semaphore.acquire(blocking=False)
            if not acquired:
                log_event(logger, "WARNING", "최대 동시 요청 수 초과, 요청 거부 (사용자 생성)", "백프레셔")
                context.set_code(grpc.StatusCode.RESOURCE_EXHAUSTED)
                context.set_details("서버가 과부하 상태입니다. 나중에 다시 시도해주세요.")
                
                # 이벤트 기록
                add_event("backpressure", "백프레셔: 사용자 생성 요청 거부")
                
                return service_pb2.UserResponse()
            log_event(logger, "INFO", "세마포어 획득 성공, 요청 처리 시작 (사용자 생성)", "백프레셔")
        
        try:
            # 에러 발생 여부 확인
            if self.should_generate_error():
                log_event(logger, "ERROR", "의도적 에러 발생 (사용자 생성)")
                context.set_code(grpc.StatusCode.INTERNAL)
                context.set_details("의도적으로 발생시킨 에러 (사용자 생성)")
                
                # 이벤트 기록
                add_event("error", "의도적 에러: 사용자 생성")
                
                return service_pb2.UserResponse()
            
            # 사용자 생성
            user = self.db.create_user(request.name, request.email)
            
            if user:
                log_event(logger, "INFO", f"사용자 생성 성공 (ID: {user['user_id']})")
                return service_pb2.UserResponse(
                    user_id=user["user_id"],
                    name=user["name"],
                    email=user["email"]
                )
            else:
                log_event(logger, "ERROR", "사용자 생성 실패")
                context.set_code(grpc.StatusCode.INTERNAL)
                context.set_details("사용자 생성 중 오류가 발생했습니다")
                return service_pb2.UserResponse()
                
        except Exception as e:
            log_event(logger, "ERROR", f"사용자 생성 중 오류 발생: {str(e)}")
            context.set_code(grpc.StatusCode.INTERNAL)
            context.set_details(f"서버 오류: {str(e)}")
            return service_pb2.UserResponse()
        finally:
            # 백프레셔 세마포어 반환
            if self.backpressure_enabled and acquired:
                request_semaphore.release()
                log_event(logger, "INFO", "세마포어 반환 완료 (사용자 생성)", "백프레셔")

def serve():
    """gRPC 서버 실행"""
    try:
        # 서버 생성
        server = grpc.server(
            futures.ThreadPoolExecutor(max_workers=MAX_CONCURRENT_REQUESTS * 2),
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
        
        # 서비스 등록
        service_pb2_grpc.add_UserServiceServicer_to_server(
            UserServiceServicer(), server
        )
        
        # 서버 시작
        server.add_insecure_port('[::]:50051')
        server.start()
        log_event(logger, "INFO", "백엔드 서버 시작됨. 포트: 50051", "서버")
        
        # 시작 이벤트 기록
        add_event("system", "백엔드 서버 시작됨")
        
        # 서버 종료 처리를 위한 이벤트
        stop_event = threading.Event()
        
        def handle_sigterm(*args):
            """SIGTERM 시그널 처리기"""
            log_event(logger, "INFO", "종료 시그널 받음, 서버 종료 중...", "서버")
            stop_event.set()
        
        # 신호 처리기 등록
        try:
            import signal
            signal.signal(signal.SIGTERM, handle_sigterm)
            signal.signal(signal.SIGINT, handle_sigterm)
        except (ImportError, AttributeError):
            pass  # 신호 모듈을 사용할 수 없는 환경
        
        try:
            stop_event.wait()  # 종료 이벤트 대기
        except KeyboardInterrupt:
            log_event(logger, "INFO", "키보드 인터럽트 받음, 서버 종료 중...", "서버")
        
        log_event(logger, "INFO", "서버 종료 중...", "서버")
        server.stop(5)  # 5초 이내에 정상 종료
        log_event(logger, "INFO", "서버 종료됨", "서버")
        
        # 종료 이벤트 기록
        add_event("system", "백엔드 서버 종료됨")
        
    except Exception as e:
        log_event(logger, "ERROR", f"서버 시작 중 오류 발생: {str(e)}")
        sys.exit(1)

if __name__ == '__main__':
    serve()