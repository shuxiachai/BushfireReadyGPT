from src.file_lock import _windows_wait_result_is_running


def test_windows_process_wait_results_are_interpreted_conservatively():
    assert _windows_wait_result_is_running(0) is False
    assert _windows_wait_result_is_running(258) is True
    assert _windows_wait_result_is_running(0xFFFFFFFF) is True
    assert _windows_wait_result_is_running(12345) is True
