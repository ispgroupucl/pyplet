import sys
print(sys.path)

from pyplet import transpiler
import inspect
import ast


def test_class():
    @transpiler.js_code
    class Test:
        def constructor():
            pass
