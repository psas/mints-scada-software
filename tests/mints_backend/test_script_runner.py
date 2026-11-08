import logging

from PySide6.QtCore import QProcess

from mints_backend.script_runner import DSL_MARKER, ScriptRunner


def test_script_runner_run_starts_process_for_valid_script(
    script_runner: ScriptRunner, qtbot
):
    """
    When run is called with a script starting with the DSL marker, the underlying
    QProcess should be started
    """
    script = f"{DSL_MARKER}\nprint('hello')"
    script_runner.run(script)

    assert script_runner.process.state() != QProcess.NotRunning
    qtbot.waitUntil(
        lambda: script_runner.process.state() == QProcess.NotRunning, timeout=5000
    )


def test_script_runner_run_does_not_start_process_for_invalid_script(
    script_runner: ScriptRunner, caplog
):
    """
    When run is called with a script missing the DSL marker, the process should not
    be started and an error should be logged
    """
    script = "print('hello')"
    with caplog.at_level(logging.ERROR):
        script_runner.run(script)

    assert script_runner.process.state() == QProcess.NotRunning
    assert "Missing mints script marker" in caplog.text


def test_script_runner_stop_logs_error_when_nothing_running(
    script_runner: ScriptRunner, caplog
):
    """
    When stop is called and no process is running, it should log an error rather than
    attempting to kill anything
    """
    with caplog.at_level(logging.ERROR):
        script_runner.stop()

    assert "No process running to stop" in caplog.text


def test_script_runner_stop_kills_running_process(script_runner: ScriptRunner, qtbot):
    """
    When stop is called while a process is running, the process should be killed
    """
    script = f"{DSL_MARKER}\nimport time\ntime.sleep(5)"
    script_runner.run(script)
    qtbot.waitUntil(
        lambda: script_runner.process.state() == QProcess.Running, timeout=2000
    )

    script_runner.stop()

    qtbot.waitUntil(
        lambda: script_runner.process.state() == QProcess.NotRunning, timeout=2000
    )
