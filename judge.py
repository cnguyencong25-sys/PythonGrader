import subprocess
import sys
import os
import tempfile


def _student_process_environment(working_dir: str) -> dict[str, str]:
    env = {
        "PYTHONIOENCODING": "utf-8",
        "PYTHONUTF8": "1",
    }

    if os.name == "nt":
        system_root = os.environ.get("SYSTEMROOT") or os.environ.get("WINDIR")
        if system_root:
            env["SystemRoot"] = system_root
            env["COMSPEC"] = os.path.join(system_root, "System32", "cmd.exe")
            system_paths = [
                system_root,
                os.path.join(system_root, "System32"),
            ]
        else:
            system_paths = []
        env["PATHEXT"] = ".COM;.EXE;.BAT;.CMD"
        env["TEMP"] = working_dir
        env["TMP"] = working_dir
        env["PATH"] = os.pathsep.join(dict.fromkeys([
            os.path.dirname(sys.executable),
            sys.prefix,
            sys.base_prefix,
            *system_paths,
        ]))
    else:
        env["PATH"] = os.pathsep.join(dict.fromkeys((
            os.path.dirname(sys.executable),
            os.defpath,
        )))
        env["TMPDIR"] = working_dir

    return env


def run_python_code(code: str, input_data: str, timeout: int = 2) -> tuple[str, str]:
    """
    Chạy code Python với input_data.
    Trả về (stdout, stderr).
    """
    try:
        with tempfile.TemporaryDirectory(prefix="python-grader-") as working_dir:
            code_file = os.path.join(working_dir, "submission.py")
            with open(code_file, "w", encoding="utf-8") as code_stream:
                code_stream.write(code)

            result = subprocess.run(
                [sys.executable, code_file],
                input=input_data,
                text=True,
                encoding="utf-8",
                errors="replace",
                capture_output=True,
                timeout=timeout,
                env=_student_process_environment(working_dir),
                cwd=working_dir,
            )
        return result.stdout, result.stderr
    except subprocess.TimeoutExpired:
        return "", "Time Limit Exceeded"
    except Exception as e:
        return "", str(e)

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