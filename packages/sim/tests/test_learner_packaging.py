"""The learner imports with numpy and scipy only; the controller imports without them."""

import subprocess
import sys
import textwrap

BLOCKED = ("pyarrow", "aiomqtt", "climate_manager_capture")


def _run(code: str) -> subprocess.CompletedProcess[str]:
    """Run ``code`` in a fresh interpreter and return the finished process."""
    return subprocess.run(  # noqa: S603
        [sys.executable, "-c", textwrap.dedent(code)],
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
    )


def test_learner_imports_without_tool_dependencies() -> None:
    result = _run(f"""
        import importlib.abc
        import sys

        BLOCKED = {BLOCKED!r}

        class Blocker(importlib.abc.MetaPathFinder):
            def find_spec(self, name, path, target=None):
                if name.split(".")[0] in BLOCKED:
                    raise ImportError("blocked " + name)
                return None

        sys.meta_path.insert(0, Blocker())
        import ovenbird_sim.learn.__main__
        import ovenbird_sim.learn.run
        assert not any(m.split(".")[0] in BLOCKED for m in sys.modules)
        """)
    assert result.returncode == 0, result.stderr


def test_controller_imports_stay_free_of_numpy_and_scipy() -> None:
    result = _run("""
        import sys
        import ovenbird_core
        import ovenbird.control.loop
        loaded = [m for m in ("numpy", "scipy") if m in sys.modules]
        assert not loaded, loaded
        """)
    assert result.returncode == 0, result.stderr
