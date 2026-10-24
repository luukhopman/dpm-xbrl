import gc

from dpmxbrl._util import gc_paused


def test_gc_paused_restores_the_collector_after_nested_pauses() -> None:
    assert gc.isenabled()
    with gc_paused():
        with gc_paused():
            assert not gc.isenabled()
        assert not gc.isenabled()
    assert gc.isenabled()


def test_gc_paused_keeps_a_disabled_collector_disabled() -> None:
    gc.disable()
    try:
        with gc_paused():
            pass
        assert not gc.isenabled()
    finally:
        gc.enable()
