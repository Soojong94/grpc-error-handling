# server.py에서 수정이 필요한 부분

# UserServiceServicer 클래스 내 GetUser 메서드 수정
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
    if backend_settings["backpressure_enabled"]:
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
        
        # 슬로우 쿼리 시뮬레이션 - 테스트에서만 지연 발생
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
        if backend_settings["backpressure_enabled"] and acquired:
            request_semaphore.release()
            log_event(logger, "INFO", f"세마포어 반환 완료 (ID: {user_id})", "백프레셔")