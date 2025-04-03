import os
import subprocess
import sys
import time
import threading
import signal

# 프로세스 저장용 딕셔너리
processes = {}

def start_service(service_name, command):
    print(f"Starting {service_name}...")
    process = subprocess.Popen(command, shell=True)
    processes[service_name] = process
    print(f"{service_name} started with PID {process.pid}")
    return process

def stop_all_services():
    print("\nStopping all services...")
    for name, process in processes.items():
        print(f"Stopping {name}...")
        process.terminate()
    
    # 모든 프로세스가 종료될 때까지 기다림
    for name, process in processes.items():
        process.wait()
        print(f"{name} stopped")

def signal_handler(sig, frame):
    print("\nCaught interrupt signal")
    stop_all_services()
    sys.exit(0)

def monitor_process(name, process):
    process.wait()
    if process.returncode != 0:
        print(f"\n{name} crashed with return code {process.returncode}")

if __name__ == "__main__":
    # SIGINT 핸들러 등록 (Ctrl+C)
    signal.signal(signal.SIGINT, signal_handler)
    
    try:
        # 필요한 디렉토리가 존재하는지 확인
        os.makedirs("logs", exist_ok=True)
        
        # 서비스 시작
        db_process = start_service("DB", "python db/db_service.py")
        time.sleep(1)  # DB 서비스가 시작될 시간을 줌
        
        # 백엔드 서비스들 시작
        for backend_type, port in [
            ("no_pattern", 50052),
            ("circuit_breaker", 50053),
            ("deadline", 50054),
            ("backpressure", 50055),
            ("all_patterns", 50056)
        ]:
            if backend_type == "all_patterns":
                script_name = "backend/backend_service_all.py"
            else:
                script_name = f"backend/backend_service_{backend_type}.py"
            backend_process = start_service(f"Backend ({backend_type})", f"python {script_name}")
            
            # 모니터링 스레드 시작
            monitor_thread = threading.Thread(
                target=monitor_process, 
                args=(f"Backend ({backend_type})", backend_process)
            )
            monitor_thread.daemon = True
            monitor_thread.start()
            
            time.sleep(0.5)  # 각 백엔드 서비스 시작 사이에 약간의 지연
        
        # BFF 서비스 시작
        bff_process = start_service("BFF", "python bff/bff_service.py")
        time.sleep(1)  # BFF 서비스가 시작될 시간을 줌
        
        # Front 서비스 시작
        front_process = start_service("Front", "python front/front_service.py")
        
        print("\nAll services started successfully!")
        print("\nAccess the web interface at: http://localhost:5000")
        print("\nPress Ctrl+C to stop all services")
        
        # 메인 스레드가 종료되지 않도록 대기
        while True:
            time.sleep(1)
            
    except KeyboardInterrupt:
        stop_all_services()
        sys.exit(0)
    except Exception as e:
        print(f"Error: {str(e)}")
        stop_all_services()
        sys.exit(1)