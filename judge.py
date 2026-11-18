import subprocess
import sys
import os
import tempfile

def run_python_code(code: str, input_data: str, timeout: int = 2) -> tuple[str, str]:
    """
    Chạy code Python với input_data.
    Trả về (stdout, stderr).
    """
    # Tạo file tạm để chứa code và input
    with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False, encoding='utf-8') as f:
        f.write(code)
        code_file = f.name

    try:
        # Chạy code
        result = subprocess.run(
            [sys.executable, code_file],
            input=input_data,
            text=True,
            capture_output=True,
            timeout=timeout
        )
        return result.stdout, result.stderr
    except subprocess.TimeoutExpired:
        return "", "Time Limit Exceeded"
    except Exception as e:
        return "", str(e)
    finally:
        # Dọn dẹp file tạm
        if os.path.exists(code_file):
            os.remove(code_file)

def evaluate_submission(
    student_code: str,
    generator_code: str,
    solution_code: str,
    num_tests: int,
    max_score: float = 10.0,
) -> dict:
    """
    Chấm điểm bài làm của sinh viên.
    Trả về dict: { status: 'correct'|'partial'|'wrong', score: float, max_score: float }
    """
    if not student_code or not student_code.strip():
        return {
            "status": "wrong",
            "score": 0.0,
            "max_score": round(max_score, 6),
            "passed": 0,
            "total": num_tests,
        }

    if not generator_code or not solution_code:
        return {
            "status": "wrong",
            "score": 0.0,
            "max_score": max_score,
            "message": "Giáo viên chưa cấu hình Code Generator/Solution.",
        }

    passed_tests = 0
    
    for i in range(num_tests):
        # 1. Sinh Input
        gen_out, gen_err = run_python_code(generator_code, "")
        if gen_err:
            print(f"Lỗi Generator (Test {i+1}): {gen_err}")
            continue # Bỏ qua test này nếu generator lỗi

        test_input = gen_out.strip()

        # 2. Chạy Solution để lấy Output chuẩn
        sol_out, sol_err = run_python_code(solution_code, test_input)
        if sol_err:
            print(f"Lỗi Solution (Test {i+1}): {sol_err}")
            continue
        
        expected_output = sol_out.strip()

        # 3. Chạy code của Sinh viên
        stu_out, stu_err = run_python_code(student_code, test_input)
        
        if stu_err:
            # Sinh viên bị lỗi (Runtime Error, Time Limit...) -> Test này sai
            continue
            
        # So sánh kết quả (bỏ qua khoảng trắng thừa ở cuối)
        if stu_out.strip() == expected_output:
            passed_tests += 1

    # Tính điểm
    if passed_tests == num_tests:
        status = "correct"
        score = max_score
    elif passed_tests > 0:
        status = "partial"
        score = (passed_tests / num_tests) * max_score
    else:
        status = "wrong"
        score = 0.0

    return {
        "status": status,
        "score": round(score, 6),
        "max_score": round(max_score, 6),
        "passed": passed_tests,
        "total": num_tests
    }