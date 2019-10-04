from pyplet import transpiler
import inspect
import ast


def test_class():
    @transpiler.js_code
    def a(y):
        w = 2
        x = "Ok"
        y = 3

        for z in [3]:
            w = z
    print(a._defn)
    assert "let x" in a._defn
    assert "let y" not in a._defn
    assert "let z" in a._defn
    assert "let w = z" not in a._defn
