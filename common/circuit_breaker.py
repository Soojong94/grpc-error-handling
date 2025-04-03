import time
import logging
import threading

class CircuitBreaker:
    """서킷 브레이커 패턴 구현"""
    
    # 서킷 상태
    STATE_CLOSED = "CLOSED"       # 정상 작동
    STATE_OPEN = "OPEN"           # 차단됨
    STATE_HALF_OPEN = "HALF_OPEN" # 일부 허용
    
    def __init__(self, fail_threshold=5, reset_timeout=10, name="default"):
        self.name = name
        self.fail_threshold = fail_threshold  # 실패 임계값
        self.reset_timeout = reset_timeout    # 초기화 시간 (초)
        
        self.state = self.STATE_CLOSED
        self.failure_count = 0
        self.last_failure_time = 0
        self.lock = threading.RLock()
        self.logger = logging.getLogger(f"circuit_breaker.{name}")
    
    def allow_request(self):
        """요청 허용 여부 결정"""
        with self.lock:
            if self.state == self.STATE_CLOSED:
                return True
                
            if self.state == self.STATE_OPEN:
                # 초기화 시간이 지났는지 확인
                if time.time() > self.last_failure_time + self.reset_timeout:
                    self.logger.info(f"[서킷브레이커-{self.name}] 초기화 시간 경과, 상태 변경: OPEN -> HALF_OPEN")
                    self.state = self.STATE_HALF_OPEN
                    return True
                return False
                
            if self.state == self.STATE_HALF_OPEN:
                return True
        
        return True
    
    def report_success(self):
        """성공 보고"""
        with self.lock:
            if self.state == self.STATE_HALF_OPEN:
                self.logger.info(f"[서킷브레이커-{self.name}] 요청 성공, 상태 변경: HALF_OPEN -> CLOSED")
                self.state = self.STATE_CLOSED
                self.failure_count = 0
    
    def report_failure(self):
        """실패 보고"""
        with self.lock:
            self.failure_count += 1
            self.last_failure_time = time.time()
            
            if self.state == self.STATE_CLOSED and self.failure_count >= self.fail_threshold:
                self.logger.warning(f"[서킷브레이커-{self.name}] 실패 임계값 도달({self.failure_count}/{self.fail_threshold}), 상태 변경: CLOSED -> OPEN")
                self.state = self.STATE_OPEN
                
            elif self.state == self.STATE_HALF_OPEN:
                self.logger.warning(f"[서킷브레이커-{self.name}] HALF_OPEN 상태에서 실패, 상태 변경: HALF_OPEN -> OPEN")
                self.state = self.STATE_OPEN
                
            else:
                self.logger.info(f"[서킷브레이커-{self.name}] 실패 카운트 증가: {self.failure_count}/{self.fail_threshold}")
                
    def reset(self):
        """서킷브레이커 상태 강제 초기화"""
        with self.lock:
            self.state = self.STATE_CLOSED
            self.failure_count = 0
            self.last_failure_time = 0
            self.logger.info(f"[서킷브레이커-{self.name}] 상태 수동 초기화: CLOSED")