import time
import logging
import threading
from collections import deque
from datetime import datetime, timedelta

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
        
        # 서킷 브레이커 상태 변화 콜백
        self._state_change_callbacks = []
        
        # 최근 쿼리 실행 시간 기록 (최근 1시간)
        self.execution_times = deque(maxlen=1000)  # 최대 1000개 실행 시간 저장
        self.last_execution_time_cleanup = time.time()
    
    def allow_request(self):
        """요청 허용 여부 결정"""
        with self.lock:
            if self.state == self.STATE_CLOSED:
                return True
                
            if self.state == self.STATE_OPEN:
                # 초기화 시간이 지났는지 확인
                if time.time() > self.last_failure_time + self.reset_timeout:
                    self._change_state(self.STATE_HALF_OPEN)
                    return True
                return False
                
            if self.state == self.STATE_HALF_OPEN:
                return True
        
        return True
    
    def report_success(self):
        """성공 보고"""
        with self.lock:
            if self.state == self.STATE_HALF_OPEN:
                self._change_state(self.STATE_CLOSED)
                self.failure_count = 0
    
    def report_failure(self):
        """실패 보고"""
        with self.lock:
            self.failure_count += 1
            self.last_failure_time = time.time()
            
            if self.state == self.STATE_CLOSED and self.failure_count >= self.fail_threshold:
                self._change_state(self.STATE_OPEN)
                
            elif self.state == self.STATE_HALF_OPEN:
                self._change_state(self.STATE_OPEN)
                
            else:
                self.logger.info(f"[서킷브레이커-{self.name}] 실패 카운트 증가: {self.failure_count}/{self.fail_threshold}")
    
    def reset(self):
        """서킷브레이커 상태 강제 초기화"""
        with self.lock:
            old_state = self.state
            self.state = self.STATE_CLOSED
            self.failure_count = 0
            self.last_failure_time = 0
            self.logger.info(f"[서킷브레이커-{self.name}] 상태 수동 초기화: CLOSED")
            
            # 상태 변경 콜백 실행
            if old_state != self.STATE_CLOSED:
                self._notify_state_change(old_state, self.STATE_CLOSED)
    
    def record_execution_time(self, execution_time):
        """실행 시간 기록"""
        with self.lock:
            current_time = time.time()
            self.execution_times.append((current_time, execution_time))
            
            # 1시간에 한 번 정도 오래된 기록 정리 (매번 하면 성능에 영향)
            if current_time - self.last_execution_time_cleanup > 3600:
                self._cleanup_old_execution_times()
                self.last_execution_time_cleanup = current_time
    
    def _cleanup_old_execution_times(self):
        """1시간 이상 지난 실행 시간 기록 제거"""
        one_hour_ago = time.time() - 3600
        self.execution_times = deque(
            [(t, e) for t, e in self.execution_times if t >= one_hour_ago],
            maxlen=self.execution_times.maxlen
        )
    
    def get_recent_execution_times(self, window_seconds=3600):
        """최근 지정 시간 (기본 1시간) 내 실행 시간 목록 반환"""
        with self.lock:
            current_time = time.time()
            cutoff_time = current_time - window_seconds
            return [e for t, e in self.execution_times if t >= cutoff_time]
    
    def calculate_percentile_execution_time(self, percentile=95, window_seconds=3600):
        """최근 실행 시간의 지정된 백분위수 계산"""
        times = self.get_recent_execution_times(window_seconds)
        if not times:
            return None
            
        sorted_times = sorted(times)
        index = int(len(sorted_times) * percentile / 100)
        return sorted_times[index]
    
    def add_state_change_callback(self, callback):
        """상태 변화 콜백 함수 추가"""
        self._state_change_callbacks.append(callback)
    
    def _change_state(self, new_state):
        """서킷 브레이커 상태 변경 및 콜백 실행"""
        old_state = self.state
        self.state = new_state
        
        # 상태 변화 로깅
        if new_state == self.STATE_OPEN:
            self.logger.warning(f"[서킷브레이커-{self.name}] 실패 임계값 도달({self.failure_count}/{self.fail_threshold}), 상태 변경: {old_state} -> {new_state}")
        elif new_state == self.STATE_HALF_OPEN:
            self.logger.info(f"[서킷브레이커-{self.name}] 초기화 시간 경과, 상태 변경: {old_state} -> {new_state}")
        elif new_state == self.STATE_CLOSED:
            self.logger.info(f"[서킷브레이커-{self.name}] 요청 성공, 상태 변경: {old_state} -> {new_state}")
        
        # 상태 변경 콜백 실행
        self._notify_state_change(old_state, new_state)
    
    def _notify_state_change(self, old_state, new_state):
        """등록된 모든 콜백 함수 호출"""
        for callback in self._state_change_callbacks:
            try:
                callback(self, old_state, new_state)
            except Exception as e:
                self.logger.error(f"[서킷브레이커-{self.name}] 콜백 실행 중 오류: {str(e)}")