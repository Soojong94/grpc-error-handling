import time
import logging
import grpc
from collections import deque

class DeadlineHandler:
    """데드라인 패턴 구현"""
    
    def __init__(self, timeout_seconds=2, name="default"):
        self.name = name
        self.timeout_seconds = timeout_seconds
        self.logger = logging.getLogger(f"deadline.{name}")
    
    def set_deadline(self, context=None):
        """데드라인 설정"""
        deadline = time.time() + self.timeout_seconds
        self.logger.info(f"[데드라인-{self.name}] 데드라인 설정: {self.timeout_seconds}초")
        return deadline
    
    def get_timeout(self):
        """타임아웃 값 반환"""
        return self.timeout_seconds
    
    def set_timeout(self, timeout_seconds):
        """타임아웃 값 설정"""
        if timeout_seconds <= 0:
            self.logger.warning(f"[데드라인-{self.name}] 타임아웃 값이 0 이하입니다. 기본값 사용: {self.timeout_seconds}초")
            return
            
        self.timeout_seconds = timeout_seconds
        self.logger.info(f"[데드라인-{self.name}] 타임아웃 값 변경: {self.timeout_seconds}초")
    
    def call_with_deadline(self, stub_method, request, context=None):
        """데드라인과 함께 gRPC 메서드 호출"""
        try:
            start_time = time.time()
            deadline = self.set_deadline(context)
            
            self.logger.info(f"[데드라인-{self.name}] 요청 시작 (타임아웃: {self.timeout_seconds}초)")
            response = stub_method(request, timeout=self.timeout_seconds)
            
            elapsed = time.time() - start_time
            self.logger.info(f"[데드라인-{self.name}] 요청 성공 (소요 시간: {elapsed:.2f}초)")
            return response, None
            
        except grpc.RpcError as e:
            elapsed = time.time() - start_time
            if e.code() == grpc.StatusCode.DEADLINE_EXCEEDED:
                self.logger.error(f"[데드라인-{self.name}] 타임아웃 발생 (소요 시간: {elapsed:.2f}초)")
            else:
                self.logger.error(f"[데드라인-{self.name}] gRPC 오류: {e.code()}, {e.details()}")
            return None, e
        
class AdaptiveDeadlineHandler(DeadlineHandler):
    """적응형 데드라인 패턴 구현"""

    def __init__(self, initial_timeout=2.0, name="adaptive", window_size=100):
        super().__init__(timeout_seconds=initial_timeout, name=name)
        self.execution_times = deque(maxlen=window_size)  # 최근 실행 시간 기록
        self.window_size = window_size  # 분석할 최근 쿼리 수
        self.update_interval = 10  # 몇 개의 쿼리마다 타임아웃을 업데이트할지
        self.query_counter = 0
        self.percentile = 95  # p95 사용
        self.margin = 1.5  # 50% 여유
        self.min_timeout = 0.1  # 최소 타임아웃 값 (초)
        self.max_timeout = 10.0  # 최대 타임아웃 값 (초)
        
        # 서킷브레이커 연동을 위한 필드
        self.circuit_breaker = None
        self.circuit_breaker_triggered = False
        self.recovery_timeout = 1800  # 30분 (초) 후 기본값으로 복귀
        self.trigger_time = 0
    
    def record_execution_time(self, execution_time):
        """실행 시간을 기록하고 필요시 타임아웃 업데이트"""
        self.execution_times.append(execution_time)
        
        # 카운터 증가 및 필요시 타임아웃 업데이트
        self.query_counter += 1
        if self.query_counter >= self.update_interval:
            self.update_timeout()
            self.query_counter = 0
            
        # 서킷브레이커가 트리거된 후 복구 시간이 지났는지 확인
        if self.circuit_breaker_triggered:
            current_time = time.time()
            if current_time - self.trigger_time > self.recovery_timeout:
                self.circuit_breaker_triggered = False
                self.logger.info(f"[데드라인-{self.name}] 복구 시간 경과, 일반 적응형 타임아웃으로 복귀")
                self.update_timeout()  # 일반 모드로 타임아웃 업데이트
    
    def update_timeout(self):
        """측정된 실행 시간을 기반으로 타임아웃 값 업데이트"""
        if not self.execution_times:
            return
        
        # p95 계산
        sorted_times = sorted(self.execution_times)
        p95_index = min(int(len(sorted_times) * self.percentile / 100), len(sorted_times) - 1)
        p95_value = sorted_times[p95_index]
        
        # 여유를 더한 새 타임아웃 계산
        new_timeout = p95_value * self.margin
        
        # 타임아웃 값 범위 제한
        new_timeout = max(self.min_timeout, min(new_timeout, self.max_timeout))
        
        # 타임아웃 값이 크게 변했을 경우만 업데이트 (안정성 위해)
        if abs(new_timeout - self.timeout_seconds) / self.timeout_seconds > 0.1:  # 10% 이상 차이
            old_timeout = self.timeout_seconds
            self.timeout_seconds = new_timeout
            self.logger.info(f"[데드라인-{self.name}] 타임아웃 값 업데이트: {old_timeout:.2f}초 -> {self.timeout_seconds:.2f}초")
    
    def circuit_breaker_triggered_callback(self, circuit_breaker, old_state, new_state):
        """서킷브레이커 상태 변화 콜백 함수"""
        if new_state == "OPEN" and old_state != "OPEN":
            self.logger.warning(f"[데드라인-{self.name}] 서킷브레이커 OPEN 상태 감지, 1시간 데이터 기반 타임아웃 조정")
            self._adjust_timeout_based_on_circuit_breaker(circuit_breaker)
    
    def _adjust_timeout_based_on_circuit_breaker(self, circuit_breaker):
        """서킷브레이커 트리거 시 타임아웃 값 조정"""
        # 서킷브레이커에서 최근 1시간 내 실행 시간 데이터 가져오기
        execution_times = circuit_breaker.get_recent_execution_times(3600)  # 1시간
        
        if not execution_times or len(execution_times) < 5:  # 데이터가 충분하지 않으면 조정하지 않음
            self.logger.warning(f"[데드라인-{self.name}] 충분한 실행 시간 데이터가 없어 타임아웃 조정 불가")
            return
        
        # p99 계산 (더 보수적인 값)
        sorted_times = sorted(execution_times)
        p99_index = min(int(len(sorted_times) * 99 / 100), len(sorted_times) - 1)
        p99_value = sorted_times[p99_index]
        
        # 여유를 더한 새 타임아웃 계산 (더 큰 마진)
        new_timeout = p99_value * 2.0  # 100% 여유 (더 보수적)
        
        # 타임아웃 값 범위 제한
        new_timeout = max(self.min_timeout, min(new_timeout, self.max_timeout))
        
        # 현재 값보다 크면 적용
        if new_timeout > self.timeout_seconds:
            old_timeout = self.timeout_seconds
            self.timeout_seconds = new_timeout
            self.circuit_breaker_triggered = True
            self.trigger_time = time.time()
            self.logger.warning(f"[데드라인-{self.name}] 서킷브레이커 기반 타임아웃 조정: {old_timeout:.2f}초 -> {self.timeout_seconds:.2f}초")

    def set_circuit_breaker(self, circuit_breaker):
        """서킷브레이커 설정 및 콜백 등록"""
        self.circuit_breaker = circuit_breaker
        circuit_breaker.add_state_change_callback(self.circuit_breaker_triggered_callback)
        self.logger.info(f"[데드라인-{self.name}] 서킷브레이커({circuit_breaker.name}) 연동 완료")

    def call_with_deadline_and_record(self, stub_method, request, context=None):
        """데드라인을 설정하고 실행 시간 기록"""
        start_time = time.time()
        
        try:
            response, error = self.call_with_deadline(stub_method, request, context)
            
            # 성공 시에만 실행 시간 기록
            if error is None:
                execution_time = time.time() - start_time
                self.record_execution_time(execution_time)
                
                # 서킷브레이커가 설정되어 있으면 실행 시간 기록
                if self.circuit_breaker:
                    self.circuit_breaker.record_execution_time(execution_time)
            
            return response, error
            
        except Exception as e:
            self.logger.error(f"[데드라인-{self.name}] 예외 발생: {str(e)}")
            raise