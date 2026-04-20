"""Failure injection helpers for integration and resilience tests."""

from __future__ import annotations


class FailureInjectionError(RuntimeError):
    """Raised when a configured failure point is triggered."""

    def __init__(self, failure_point: str) -> None:
        self.failure_point = failure_point
        super().__init__(f"Injected failure at {failure_point}")


class FailureInjector:
    """Deterministic failure injector used by the final integration push."""

    def __init__(self, fail_points: set[str] | None = None) -> None:
        self.fail_points = set(fail_points or set())

    def enable(self, failure_point: str) -> None:
        self.fail_points.add(failure_point)

    def disable(self, failure_point: str) -> None:
        self.fail_points.discard(failure_point)

    def clear(self) -> None:
        self.fail_points.clear()

    def check(self, failure_point: str) -> None:
        if failure_point in self.fail_points:
            raise FailureInjectionError(failure_point)
