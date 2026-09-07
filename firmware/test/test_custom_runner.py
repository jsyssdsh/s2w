"""``pio test -e native`` 용 커스텀 러너.

테스트 본체(``test_offline_control/``)는 프레임워크를 쓰지 않는 평범한
``main()`` 이다. 그래야 PlatformIO 없이도 컴파일러 하나로 돌릴 수 있다
(``firmware/run_host_tests.sh``). 이 러너는 그 출력을 PlatformIO 의 결과
표로 옮겨 주는 얇은 어댑터일 뿐이다.

- ``- <이름>``  → 테스트 케이스 시작
- ``  FAIL ...`` → 직전 케이스 실패
- 프로세스 종료코드가 0 이 아니면 전체 실패
"""

from platformio.public import TestCase, TestRunnerBase, TestStatus


class CustomTestRunner(TestRunnerBase):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._current = None
        self._failures = []

    def _flush(self):
        if self._current is None:
            return
        failed = bool(self._failures)
        self.test_suite.add_case(
            TestCase(
                name=self._current,
                status=TestStatus.FAILED if failed else TestStatus.PASSED,
                message="\n".join(self._failures) if failed else None,
            )
        )
        self._current = None
        self._failures = []

    def on_testing_line_output(self, line):
        text = line.rstrip()
        if text.startswith("- "):
            self._flush()
            self._current = text[2:].strip()
        elif text.lstrip().startswith("FAIL "):
            self._failures.append(text.strip())
        elif "failures" in text:
            # 마지막 요약 줄 ("N checks, M failures") 에서 마무리한다.
            self._flush()
        super().on_testing_line_output(line)
