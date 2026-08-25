import threading
import time

import pytest

from eiraos.application.execution_budget import ExecutionBudget


def test_consumes_finite_execution_allowance():
    budget = ExecutionBudget(2, 10)
    assert budget.consume().allowed
    assert budget.consume().allowed
    result = budget.consume()
    assert not result.allowed
    assert result.reason_code == "EXECUTION_BUDGET_EXHAUSTED"


def test_invalid_budget_fails_closed():
    with pytest.raises(ValueError):
        ExecutionBudget(-1, 10)
    with pytest.raises(ValueError):
        ExecutionBudget(1, 0)


def test_timeout_denies_execution():
    budget = ExecutionBudget(1, 0.01)
    time.sleep(0.02)
    result = budget.consume()
    assert not result.allowed
    assert result.reason_code == "TIME_BUDGET_EXHAUSTED"


def test_concurrent_consumption_cannot_double_spend_last_allowance():
    budget = ExecutionBudget(1, 10)
    results = []
    lock = threading.Lock()

    def consume():
        result = budget.consume()
        with lock:
            results.append(result.allowed)

    threads = [threading.Thread(target=consume) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert sum(results) == 1
    assert budget.remaining_executions == 0
