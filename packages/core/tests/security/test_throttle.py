from voizy_core.security.throttle import Throttle


class Clock:
    def __init__(self) -> None:
        self.t = 1000.0

    def __call__(self) -> float:
        return self.t


def test_blocks_after_max_failures_then_recovers_when_the_window_passes() -> None:
    clock = Clock()
    th = Throttle(3, 60, clock=clock)
    for _ in range(3):
        assert th.retry_after("k") == 0
        th.record_failure("k")
    assert 0 < th.retry_after("k") <= 60
    clock.t += 61
    assert th.retry_after("k") == 0


def test_keys_are_independent_and_reset_clears() -> None:
    th = Throttle(1, 60, clock=Clock())
    th.record_failure("a")
    assert th.retry_after("a") > 0 and th.retry_after("b") == 0
    th.reset("a")
    assert th.retry_after("a") == 0


def test_retry_after_counts_down() -> None:
    clock = Clock()
    th = Throttle(1, 60, clock=clock)
    th.record_failure("k")
    clock.t += 20
    assert 39 < th.retry_after("k") <= 40


def test_memory_is_bounded_under_a_flood_of_distinct_keys() -> None:
    th = Throttle(5, 60, clock=Clock(), max_keys=100)
    for i in range(1000):
        th.record_failure(f"ip-{i}")
    assert len(th._events) <= 100  # noqa: SLF001
