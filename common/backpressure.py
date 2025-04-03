import time
import threading
import logging

class BackpressureController:
    """백프레셔 패턴 구현"""
    
    def __init__(self, window_size=5, max_requests=50, max_concurrency=10, name="default"):
        self.name = name
        self.window_size = window_size      # 측정 시간 창 (초)
        self.max_requests = max_requests    # 최대 요청 수
        self.max_concurrency = max_concurrency  # 최대 동시 처리 요청 수
        
        self.request_times = []  # 요청 시간 기록
        self.active_requests = 0 # 현재 활성 요청 수
        self.lock = threading.RLock()
        self.logger = logging.getLogger(f"backpressure.{name}")
    
    def is_overloaded(self):
        """과부하 상태 확인"""
        with self.lock:
            current_time = time.time()
            
            # 측정 시간 창 외의 오래된 요청 제거
            self.request_times = [t for t in self.request_times if current_time - t < self.window_size]
            
            # 현재 초당 요청 수 계산
            request_rate = len(self.request_times) / self.window_size
            
            # 과부하 상태 확인
            is_rate_exceeded = len(self.request_times) >= self.max_requests
            is_concurrency_exceeded = self.active_requests >= self.max_concurrency
            
            if is_rate_exceeded:
                self.logger.warning(f"[백프레셔-{self.name}] 초당 요청 수 초과: {request_rate:.1f}/초 (최대: {self.max_requests/self.window_size}/초)")
                
            if is_concurrency_exceeded:
                self.logger.warning(f"[백프레셔-{self.name}] 동시 요청 수 초과: {self.active_requests} (최대: {self.max_concurrency})")
                
            return is_rate_exceeded or is_concurrency_exceeded
    
    def register_request(self):
        """요청 등록"""
        with self.lock:
            self.request_times.append(time.time())
            self.active_requests += 1
            self.logger.debug(f"[백프레셔-{self.name}] 요청 등록: 활성 요청 {self.active_requests}개")
    
    def complete_request(self):
        """요청 완료"""
        with self.lock:
            if self.active_requests > 0:
                self.active_requests -= 1
                self.logger.debug(f"[백프레셔-{self.name}] 요청 완료: 활성 요청 {self.active_requests}개")
                
    def reset(self):
        """백프레셔 상태 강제 초기화"""
        with self.lock:
            self.request_times = []
            self.active_requests = 0
            self.logger.info(f"[백프레셔-{self.name}] 상태 수동 초기화")