from example_interactive_web import add, native_version


def test_native_boundary() -> None:
    assert native_version() == "0.1.0"
    assert add(20, 22) == 42


def test_native_operation_matches_python_integer_addition() -> None:
    for left in range(-32, 33):
        for right in (-32, -1, 0, 1, 32):
            assert add(left, right) == left + right
