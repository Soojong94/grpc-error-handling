import grpc
import time
import random
import logging
import threading
import concurrent.futures
from concurrent import futures
import queue

# gRPC 생성된 모듈들 import
import sys
sys.path.append('.')  # proto 컴파일된 파일 위치
import service_pb2
import service_pb2_grpc

# DB 클라이언트 import
from db_client import DBClient

# 로깅 설정
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] [BACKEND] [Thread-%(thread)d] %(message)s',
)
logger = logging.getLogger(__name__)

# 전역 설정
ERROR_RATE = 0
MAX_CONCURRENT_REQUESTS = 10

# 백프레셔 구현을 위한 요청 큐 및 세마포어
request_queue = queue.Queue()
request_semaphore = threading.Semaphore(MAX_CONCURRENT_REQUESTS)

# 테스트용 사용자 데이터
SAMPLE_USERS = [
    {"user_id": 1, "name": "홍길동", "email": "hong@example.com"},
    {"user_id": 2, "name": "김철수", "email": "kim@example.com"},
    {"user_id": 3, "name": "이영희", "email": "lee@example.com"},
    {"user_id": 4, "name": "박지성", "email": "park@example.com"},
    {"user_id": 5, "name": "최민수", "email": "choi@example.com"},
]

class UserServiceServicer(service_pb2_grpc.UserServiceServicer):
    """gRPC 서비스 구현"""
    
    def __init__(self):
        self.db = DBClient()
        
        # 백프레셔 워커 스레드 시작
        self.start_worker_thread()
    
    def start_worker_thread(self):
        """백프레셔 처리를 위한 워커 스레드 시작"""
        def worker():
            while True:
                try:
                    # 큐에서 작업 가져오기
                    task, callback = request_queue.get()
                    logger.info(f"워커 스레드가 작업 처리 시작: {task}")
                    
                    # 요청 처리
                    try:
                        result = task()
                        callback(result, None)
                    except Exception as e:
                        logger.error(f"작업 처리 중 오류 발생: {str(e)}")
                        callback(None, e)
                    
                    # 작업 완료 표시
                    request_queue.task_done()
                    # 세마포어 반환
                    request_semaphore.release()
                    logger.info("세마포어 반환, 다음 요청 처리 가능")
                except Exception as e:
                    logger.error(f"워커 스레드 오류: {str(e)}")
        
        # 워커 스레드 시작
        for i in range(MAX_CONCURRENT_REQUESTS):
            t = threading.Thread(target=worker, daemon=True)
            t.start()
            logger.info(f"워커 스레드 {i+1} 시작됨")
    
    def should_generate_error(self):
        """현재 에러율에 따라 에러를 발생시켜야 하는지 결정"""
        global ERROR_RATE
        return random.randint(1, 100) <= ERROR_RATE
    
    def GetUser(self, request, context):
        """단일 사용자 정보 조회"""
        user_id = request.user_id
        logger.info(f"사용자 조회 요청 받음 (ID: {user_id})")
        
        # 메타데이터에서 지연 정보 확인
        delay = 0
        for key, value in context.invocation_metadata():
            if key == 'delay':
                delay = int(value)
                logger.info(f"요청에 지연 {delay}초 추가")
        
        # 에러 발생 여부 확인
        if self.should_generate_error():
            logger.error(f"의도적 에러 발생 (사용자 ID: {user_id})")
            context.set_code(grpc.StatusCode.INTERNAL)
            context.set_details(f"의도적으로 발생시킨 에러 (사용자 ID: {user_id})")
            return service_pb2.UserResponse()
        
        # 지연 시뮬레이션
        if delay > 0:
            logger.info(f"요청 처리 지연 중... ({delay}초)")
            time.sleep(delay)
            logger.info("지연 완료, 요청 처리 계속")
        
        # 요청 처리
        try:
            # 실제로는 DB에서 조회하지만, 여기서는 샘플 데이터 사용
            user = next((u for u in SAMPLE_USERS if u["user_id"] == user_id), None)
            
            if user:
                logger.info(f"사용자 조회 성공 (ID: {user_id})")
                return service_pb2.UserResponse(
                    user_id=user["user_id"],
                    name=user["name"],
                    email=user["email"]
                )
            else:
                logger.warning(f"사용자를 찾을 수 없음 (ID: {user_id})")
                context.set_code(grpc.StatusCode.NOT_FOUND)
                context.set_details(f"ID가 {user_id}인 사용자를 찾을 수 없습니다")
                return service_pb2.UserResponse()
        except Exception as e:
            logger.error(f"사용자 조회 중 오류 발생: {str(e)}")
            context.set_code(grpc.StatusCode.INTERNAL)
            context.set_details(f"서버 오류: {str(e)}")
            return service_pb2.UserResponse()
    
    def ListUsers(self, request, context):
        """사용자 목록 조회"""
        page = request.page
        page_size = request.page_size
        logger.info(f"사용자 목록 조회 요청 받음 (페이지: {page}, 페이지 크기: {page_size})")
        
        # 메타데이터에서 에러율 설정 확인
        for key, value in context.invocation_metadata():
            if key == 'error_rate':
                global ERROR_RATE
                ERROR_RATE = int(value)
                logger.info(f"에러율 {ERROR_RATE}%로 설정됨")
        
        # 백프레셔 구현을 위한 세마포어 획득 시도
        if not request_semaphore.acquire(blocking=False):
            logger.warning("최대 동시 요청 수 초과, 요청 거부")
            context.set_code(grpc.StatusCode.RESOURCE_EXHAUSTED)
            context.set_details("서버가 과부하 상태입니다. 나중에 다시 시도해주세요.")
            return service_pb2.ListUsersResponse()
        
        # 세마포어 획득 성공, 요청 처리
        try:
            # 에러 발생 여부 확인
            if self.should_generate_error():
                logger.error("의도적 에러 발생 (사용자 목록 조회)")
                context.set_code(grpc.StatusCode.INTERNAL)
                context.set_details("의도적으로 발생시킨 에러 (사용자 목록 조회)")
                return service_pb2.ListUsersResponse()
            
            # 페이지네이션 계산
            start_idx = (page - 1) * page_size
            end_idx = start_idx + page_size
            
            # 결과 생성
            response = service_pb2.ListUsersResponse()
            response.total_count = len(SAMPLE_USERS)
            
            # 페이지에 해당하는 사용자만 추가
            for user in SAMPLE_USERS[start_idx:end_idx]:
                user_response = service_pb2.UserResponse(
                    user_id=user["user_id"],
                    name=user["name"],
                    email=user["email"]
                )
                response.users.append(user_response)
            
            logger.info(f"사용자 목록 조회 성공 ({len(response.users)}명)")
            return response
        except Exception as e:
            logger.error(f"사용자 목록 조회 중 오류 발생: {str(e)}")
            context.set_code(grpc.StatusCode.INTERNAL)
            context.set_details(f"서버 오류: {str(e)}")
            return service_pb2.ListUsersResponse()
        finally:
            # 에러 발생 시 세마포어 반환
            if self.should_generate_error():
                request_semaphore.release()
    
    def CreateUser(self, request, context):
        """사용자 생성"""
        name = request.name
        email = request.email
        logger.info(f"사용자 생성 요청 받음 (이름: {name}, 이메일: {email})")
        
        # 에러 발생 여부 확인
        if self.should_generate_error():
            logger.error("의도적 에러 발생 (사용자 생성)")
            context.set_code(grpc.StatusCode.INTERNAL)
            context.set_details("의도적으로 발생시킨 에러 (사용자 생성)")
            return service_pb2.UserResponse()
        
        # 요청 처리
        try:
            # 실제로는 DB에 저장하지만, 여기서는 간단히 처리
            new_user_id = len(SAMPLE_USERS) + 1
            
            # 결과 반환
            logger.info(f"사용자 생성 성공 (ID: {new_user_id})")
            return service_pb2.UserResponse(
                user_id=new_user_id,
                name=name,
                email=email
            )
        except Exception as e:
            logger.error(f"사용자 생성 중 오류 발생: {str(e)}")
            context.set_code(grpc.StatusCode.INTERNAL)
            context.set_details(f"서버 오류: {str(e)}")
            return service_pb2.UserResponse()

def serve():
    """gRPC 서버 실행"""
    # 서버 생성
    server = grpc.server(
        futures.ThreadPoolExecutor(max_workers=MAX_CONCURRENT_REQUESTS),
        options=[
            ('grpc.max_send_message_length', 50 * 1024 * 1024),
            ('grpc.max_receive_message_length', 50 * 1024 * 1024),
        ]
    )
    
    # 서비스 등록
    service_pb2_grpc.add_UserServiceServicer_to_server(
        UserServiceServicer(), server
    )
    
    # 서버 시작
    server.add_insecure_port('0.0.0.0:50051')
    server.start()
    logger.info("백엔드 서버 시작됨. 포트: 50051")
    
    try:
        server.wait_for_termination()
    except KeyboardInterrupt:
        logger.info("서버 종료 중...")
        server.stop(0)
        logger.info("서버 종료됨")

if __name__ == '__main__':
    serve()