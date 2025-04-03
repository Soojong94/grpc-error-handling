import os
import subprocess
import time
import threading
import signal
import sys
from concurrent import futures

def generate_protos():
    """Proto 파일 컴파일"""
    proto_dir = os.path.join(os.path.dirname(__file__), 'proto')
    output_dir = os.path.join(os.path.dirname(__file__), 'generated')
    
    # 출력 디렉토리 생성
    os.makedirs(output_dir, exist_ok=True)
    
    # __init__.py 파일 생성
    with open(os.path.join(output_dir, '__init__.py'), 'w') as f:
        pass
    
    # proto 파일 목록
    proto_files = [
        'front.proto',
        'bff.proto',
        'backend.proto',
        'db.proto'
    ]
    
    print("Proto 파일 컴파일 중...")
    for proto_file in proto_files:
        proto_path = os.path.join(proto_dir, proto_file)
        if os.path.exists(proto_path):
            cmd = [
                'python', '-m', 'grpc_tools.protoc',
                f'--proto_path={proto_dir}',
                f'--python_out={output_dir}',
                f'--grpc_python_out={output_dir}',
                proto_path
            ]
            
            try:
                subprocess.run(cmd, check=True)
                print(f"  ✓ {proto_file} 컴파일 완료")
            except subprocess.CalledProcessError as e:
                print(f"  ✗ {proto_file} 컴파일 실패: {e}")
                return False
    
    # 생성된 파일에서 import 경로 수정
    fix_imports(output_dir)
    
    print("모든 Proto 파일 컴파일 완료")
    return True

def fix_imports(output_dir):
    """생성된 *_pb2_grpc.py 파일의 import 경로 수정"""
    print("생성된 파일의 import 경로 수정 중...")
    
    for filename in os.listdir(output_dir):
        if filename.endswith('_pb2_grpc.py'):
            file_path = os.path.join(output_dir, filename)
            
            with open(file_path, 'r') as file:
                content = file.read()
            
            # import 문 수정 - 여기가 문제입니다
            # 'import grpc'를 유지하고 다른 import만 수정
            # from . import grpc로 변경된 부분을 다시 원래대로
            content = content.replace('from . import grpc', 'import grpc')
            
            # pb2 파일 import 수정
            base_name = filename.replace('_pb2_grpc.py', '')
            content = content.replace(f'import {base_name}_pb2', f'from . import {base_name}_pb2')
            
            with open(file_path, 'w') as file:
                file.write(content)
            
            print(f"  ✓ {filename} 수정 완료")

def start_service(service_name, command):
    """서비스 시작"""
    print(f"{service_name} 서비스 시작 중...")
    try:
        # 환경 변수 설정
        env = os.environ.copy()
        # 절대 경로로 PYTHONPATH 설정
        project_root = os.path.dirname(os.path.abspath(__file__))
        env["PYTHONPATH"] = project_root
        
        process = subprocess.Popen(command, env=env)
        print(f"{service_name} 서비스 시작됨 (PID: {process.pid})")
        return process
    except Exception as e:
        print(f"{service_name} 서비스 시작 실패: {e}")
        return None

def run_services():
    """모든 서비스 실행"""
    processes = []
    
    # DB 서비스
    db_process = start_service("DB", [sys.executable, "db/db_service.py"])
    if db_process:
        processes.append(db_process)
    
    # 약간의 지연
    time.sleep(1)
    
    # Backend 서비스
    backend_process = start_service("Backend", [sys.executable, "backend/backend_service.py"])
    if backend_process:
        processes.append(backend_process)
    
    # 약간의 지연
    time.sleep(1)
    
    # BFF 서비스
    bff_process = start_service("BFF", [sys.executable, "bff/bff_service.py"])
    if bff_process:
        processes.append(bff_process)
    
    # 약간의 지연
    time.sleep(1)
    
    # Front 서비스
    front_process = start_service("Front", [sys.executable, "front/front_service.py"])
    if front_process:
        processes.append(front_process)
    
    return processes

def stop_services(processes):
    """모든 서비스 중지"""
    for process in processes:
        if process and process.poll() is None:  # 프로세스가 아직 실행 중인지 확인
            process.terminate()
            print(f"프로세스 종료: PID {process.pid}")
    
    # 모든 프로세스가 제대로 종료될 때까지 잠시 대기
    time.sleep(2)
    
    # 여전히 실행 중인 프로세스가 있다면 강제 종료
    for process in processes:
        if process and process.poll() is None:
            process.kill()
            print(f"프로세스 강제 종료: PID {process.pid}")

def signal_handler(signal, frame):
    """시그널 핸들러"""
    print("\n종료 신호를 받았습니다. 모든 서비스를 종료합니다...")
    if 'processes' in globals():
        stop_services(processes)
    sys.exit(0)

if __name__ == "__main__":
    # SIGINT (Ctrl+C) 핸들러 등록
    signal.signal(signal.SIGINT, signal_handler)
    
    # proto 파일 컴파일
    if not generate_protos():
        sys.exit(1)
    
    # 서비스 실행
    processes = run_services()
    
    # 종료될 때까지 대기
    print("\n모든 서비스가 실행 중입니다.")
    print("종료하려면 Ctrl+C를 누르세요.")
    
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n종료 신호를 받았습니다. 모든 서비스를 종료합니다...")
        stop_services(processes)