import time
import logging
import grpc

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
    def __init__(self, initial_timeout=2.0, name="adaptive", window_size=100):
        super().__init__(timeout_seconds=initial_timeout, name=name)
        self.execution_times = []  # 최근 실행 시간 기록
        self.window_size = window_size  # 분석할 최근 쿼리 수
        self.update_interval = 50  # 몇 개의 쿼리마다 타임아웃을 업데이트할지
        self.query_counter = 0
        self.percentile = 95  # p95 사용
        self.margin = 1.2  # 20% 여유
    
    def record_execution_time(self, execution_time):
        """SQL 실행 시간을 기록"""
        self.execution_times.append(execution_time)
        
        # 윈도우 크기를 초과하면 가장 오래된 데이터 제거
        if len(self.execution_times) > self.window_size:
            self.execution_times.pop(0)
        
        # 카운터 증가 및 필요시 타임아웃 업데이트
        self.query_counter += 1
        if self.query_counter >= self.update_interval:
            self.update_timeout()
            self.query_counter = 0
    
    def update_timeout(self):
        """측정된 실행 시간을 기반으로 타임아웃 값 업데이트"""
        if not self.execution_times:
            return
        
        # p95 계산 (간단한 구현)
        sorted_times = sorted(self.execution_times)
        p95_index = int(len(sorted_times) * self.percentile / 100)
        p95_value = sorted_times[p95_index]
        
        # 여유를 더한 새 타임아웃 계산
        new_timeout = p95_value * self.margin
        
        # 타임아웃 값이 크게 변했을 경우만 업데이트 (안정성 위해)
        if abs(new_timeout - self.timeout_seconds) / self.timeout_seconds > 0.1:  # 10% 이상 차이
            self.timeout_seconds = new_timeout
            self.logger.info(f"[데드라인-{self.name}] 타임아웃 값 업데이트: {self.timeout_seconds:.2f}초")

    def call_with_deadline_and_record(self, stub_method, request, context=None):
        """데드라인을 설정하고 실행 시간 기록"""
        start_time = time.time()
        
        try:
            response, error = self.call_with_deadline(stub_method, request, context)
            
            # 성공 시에만 실행 시간 기록
            if error is None:
                execution_time = time.time() - start_time
                self.record_execution_time(execution_time)
            
            return response, error
            
        except Exception as e:
            self.logger.error(f"[데드라인-{self.name}] 예외 발생: {str(e)}")
            raise