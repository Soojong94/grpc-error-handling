import time
import threading
import logging

class BackpressureController:
    """백프레셔 패턴 구현"""
    
    def __init__(self, window_size=5, max_requests=30, max_concurrency=8, name="default"):
        self.name = name
        self.window_size = window_size
        self.max_requests = max_requests
        self.max_concurrency = max_concurrency
        
        self.request_times = []  # 요청 시간 기록
        self.active_requests = 0 # 현재 활성 요청 수
        self.lock = threading.RLock()
        self.logger = logging.getLogger(f"backpressure.{name}")
        
        self.logger.warning(f"[백프레셔-{self.name}] 초기화 - 설정: 창={window_size}초, 최대요청={max_requests}개, 최대동시={max_concurrency}개")
    
    def is_overloaded(self):
        """과부하 상태 확인"""
        with self.lock:
            current_time = time.time()
            
            # 측정 시간 창 외의 오래된 요청 제거
            self.request_times = [t for t in self.request_times if current_time - t < self.window_size]
            
            # 현재 초당 요청 수 계산
            request_rate = len(self.request_times) / self.window_size if self.window_size > 0 else 0
            
            # 과부하 상태 확인
            is_rate_exceeded = len(self.request_times) >= self.max_requests
            is_concurrency_exceeded = self.active_requests >= self.max_concurrency
            is_overloaded = is_rate_exceeded or is_concurrency_exceeded
            
            self.logger.warning(f"[백프레셔-{self.name}] 상태 확인: 요청수={len(self.request_times)}/{self.max_requests}, " +
                            f"동시처리={self.active_requests}/{self.max_concurrency}, 과부하={is_overloaded}")
            
            if is_rate_exceeded:
                self.logger.warning(f"[백프레셔-{self.name}] 초당 요청 수 초과: {request_rate:.1f}/초 (최대: {self.max_requests/self.window_size}/초)")
            
            if is_concurrency_exceeded:
                self.logger.warning(f"[백프레셔-{self.name}] 동시 요청 수 초과: {self.active_requests} (최대: {self.max_concurrency})")
            
            return is_overloaded
    
    def register_request(self):
        """요청 등록 및 처리 가능 여부 반환"""
        with self.lock:
            current_time = time.time()
            
            # 측정 시간 창 외의 오래된 요청 제거
            self.request_times = [t for t in self.request_times if current_time - t < self.window_size]
            
            # 현재 과부하 상태인지 확인 (새 요청 등록 전에 확인)
            is_rate_exceeded = len(self.request_times) >= self.max_requests
            is_concurrency_exceeded = self.active_requests >= self.max_concurrency
            is_overloaded = is_rate_exceeded or is_concurrency_exceeded
            
            # 상태 로깅 추가 - 더 자세한 정보
            self.logger.warning(f"[백프레셔-{self.name}] 요청 등록 전 상태: 요청수={len(self.request_times)}/{self.max_requests}, " +
                            f"동시처리={self.active_requests}/{self.max_concurrency}, 과부하={is_overloaded}")
            
            if is_overloaded:
                # 과부하 상태이면 요청 거부
                reject_reason = []
                if is_rate_exceeded:
                    reject_reason.append(f"시간당 요청 초과({len(self.request_times)}/{self.max_requests})")
                if is_concurrency_exceeded:
                    reject_reason.append(f"동시 요청 초과({self.active_requests}/{self.max_concurrency})")
                    
                self.logger.error(f"[백프레셔-{self.name}] 요청 거부! 과부하 상태! 이유: {', '.join(reject_reason)}")
                return False
            
            # 과부하 상태가 아니면 요청 등록
            self.request_times.append(current_time)
            self.active_requests += 1
            self.logger.warning(f"[백프레셔-{self.name}] 요청 등록 완료: 활성 요청 {self.active_requests}개")
            return True
    
    def complete_request(self):
        """요청 완료"""
        with self.lock:
            if self.active_requests > 0:
                self.active_requests -= 1
                self.logger.warning(f"[백프레셔-{self.name}] 요청 완료: 활성 요청 {self.active_requests}개")
    
    def reset(self):
        """백프레셔 상태 강제 초기화"""
        with self.lock:
            self.request_times = []
            self.active_requests = 0
            self.logger.warning(f"[백프레셔-{self.name}] 상태 수동 초기화")