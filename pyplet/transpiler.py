import ast as _ast
import inspect
import sys
import re
from .js_lib import Replaceable


def js_code(f):
    frame = sys._getframe(1)
    env = {**frame.f_globals, **frame.f_locals}

    source = inspect.getsource(f)
    match = _whitespace_re.match(source)
    if match:
        source = "\n".join(line[match.end(0):] for line in source.split("\n"))

    ast = _ast.parse(source).body[0]
    for k, v in Translator.translate_root(ast, env):
        setattr(f, k, v)
    return f
_whitespace_re = re.compile(r"[ \t]+")


class _JSFunction:
    def __init__(self, name, args, body, defn):
        self._name = name
        self._args = args
        self._body = body
        self._defn = defn


class _JSClass:
    def __init__(self, name, defn):
        self._name = name
        self._defn = defn


class Phase1(_ast.NodeVisitor):
    def __init__(self, env):
        self.env = env
        self.declarations = set()
        self._variables = [set()]

    @property
    def variables(self):
        return self._variables[-1]

    def push(self):
        self._variables.append(self._variables[-1].copy())

    def pop(self):
        self._variables.pop()

    def visit_If(self, node):
        assert len(node.orelse) <= 1
        self.push()
        for b in node.body:
            self.visit(b)
        self.pop()
        if node.orelse:
            self.push()
            self.generic_visit(node.orelse[0])
            self.pop()

    def visit_FunctionDef(self, node):
        self.push()
        self.variables.update([arg.arg for arg in node.args.args])
        for b in node.body:
            self.visit(b)
        self.pop()

    def visit_Assign(self, node):
        assert len(node.targets) == 1
        target = node.targets[0]
        if isinstance(target, _ast.Name):
            name = target.id
            if name not in self.variables:
                self.variables.add(name)
                self.declarations.add(id(target))

    def visit_For(self, node):
        if isinstance(node.target, _ast.Name):
            name = node.target.id
            if name not in self.variables:
                self.variables.add(name)
                self.declarations.add(id(node.target))
        for b in node.body:
            self.visit(b)


class Translator:
    def __init__(self, env):
        self.env = env
        self.phase1 = Phase1(env)

    @staticmethod
    def translate_root(node, env):
        translator = Translator(env)
        translator.phase1.visit(node)
        if isinstance(node, _ast.FunctionDef):
            js_fun = translator.translate_FunctionDef(node, js_code=True)
            return js_fun.__dict__.items()
        elif isinstance(node, _ast.ClassDef):
            js_class = translator.translate_ClassDef(node, js_code=True)
            return js_class.__dict__.items()

    def translate(self, node):
        method = getattr(self, "translate_"+node.__class__.__name__, self.generic_translate)
        return method(node)

    def indent(self, str):
        return "\t"+"\n\t".join(str.split("\n"))

    def translate_Module(self, node:_ast.Module):
        return "\n".join([self.translate(n) for n in node.body])

    def translate_Expr(self, node:_ast.Expr):
        return self.translate(node.value)

    def translate_Lambda(self, node:_ast.Lambda):
        args = ",".join([arg.arg for arg in node.args.args])
        return "".join([args, " => ", self.translate(node.body)])

    def translate_ClassDef(self, node:_ast.ClassDef, js_code=False):
        assert not node.bases
        methods = []
        for method in node.body:
            method = self.translate_FunctionDef(method)[len("function "):]
            methods.append(method)
        
        cdef = "".join(["class ", node.name, "{\n",
                        self.indent("\n".join(methods)), "\n",
                        "}"])

        if js_code:
            return _JSClass(node.name, cdef)
        return cdef

    def translate_FunctionDef(self, node:_ast.FunctionDef, js_code=False):
        args = _args = [arg.arg for arg in node.args.args]
        args = ["(", ", ".join(args), ")"]

        body = "\n".join([self.translate(n) for n in node.body])

        fdef = "".join(["function ", node.name, *args, " {\n",
                        self.indent(body), "\n"
                        "}"])

        if js_code:
            return _JSFunction(node.name, _args, body, fdef)
        return fdef

    def translate_While(self, node:_ast.While):
        assert not node.orelse
        body = "\n".join([self.translate(n) for n in node.body])
        return "".join(["while (", self.translate(node.test), ") {\n",
                        self.indent(body), "\n"
                        "}"])

    def translate_For(self, node:_ast.For):
        assert not node.orelse
        body = "\n".join([self.translate(n) for n in node.body])
        left = self.translate(node.target)
        right = self.translate(node.iter)
        dic = right.endswith(".items()")
        middle = " in " if dic else " of "
        return "".join(["for (", left, middle, right, ") {\n",
                        self.indent(body), "\n"
                        "}"])

    def translate_If(self, node:_ast.If):
        body = "\n".join([self.translate(n) for n in node.body])
        return "".join(["if (", self.translate(node.test), ") {\n",
                        self.indent(body), "\n",
                        "}", self._orelse(node.orelse)])

    def _orelse(self, orelse:list):
        assert len(orelse) <= 1
        if not orelse:  return ""
        body = "".join([self.translate(n) for n in orelse])
        return "".join([" else {\n",
                        self.indent(body), "\n",
                        "}"])

    def translate_Call(self, node:_ast.Call):
        args = [self.translate(n) for n in node.args]
        if isinstance(node.func, _ast.Name) and node.func.id[0].isupper():
            _new = ["new "]
        else:
            _new = []

        return "".join([*_new, self.translate(node.func), "(",
                            ", ".join(args),
                        ")"])

    def translate_Starred(self, node:_ast.Starred):
        return "".join(["...", self.translate(node.value)])

    def translate_Attribute(self, node:_ast.Attribute):
        return "".join([self.translate(node.value), ".", node.attr])

    def translate_Subscript(self, node:_ast.Subscript):
        assert isinstance(node.slice, _ast.Index), "Slices are not handled, please use the .slice(...) javascript function"
        return "".join([self.translate(node.value), "[", self.translate(node.slice), "]"])

    def translate_Index(self, node:_ast.Index):
        return self.translate(node.value)

    def translate_Name(self, node:_ast.Name):
        env_val = self.env.get(node.id, None)
        if isinstance(env_val, Replaceable):
            return env_val.replacement
        elif id(node) in self.phase1.declarations:
            return "let "+node.id
        return node.id

    def translate_Str(self, node:_ast.Str):
        return repr(node.s)

    def translate_Num(self, node:_ast.Num):
        return str(node.n)

    def translate_List(self, node:_ast.List):
        return "".join(["[",
                        ", ".join([self.translate(elt) for elt in node.elts]),
                        "]"])

    def translate_Dict(self, node:_ast.Dict):
        assert all(isinstance(k, (_ast.Str, _ast.Num)) for k in node.keys)
        return "".join(["{",
                        ", ".join(["".join([self.translate(k), ": ", self.translate(v)])
                                   for k, v in zip(node.keys, node.values)
                                   ]),
                        "}"])

    def translate_Assign(self, node:_ast.Assign):
        assert len(node.targets) == 1
        return "".join([self.translate(node.targets[0]), " = ", self.translate(node.value)])

    def translate_Return(self, node:_ast.Return):
        if node.value is None:
            return "return"
        return "".join(["return ", self.translate(node.value)])

    def translate_Delete(self, node:_ast.Delete):
        assert len(node.targets) == 1
        return "".join(["delete ", self.translate(node.targets[0])])

    def translate_Pass(self, node:_ast.Pass):
        return "// pass"

    def translate_NameConstant(self, node:_ast.NameConstant):
        if node.value == True:
            return "true"
        if node.value == False:
            return "false"
        if node.value == None:
            return "null"
        raise NotImplementedError("Constant {!r} was not recognized for transpilation.".format(node.value))

    def translate_UnaryOp(self, node:_ast.UnaryOp):
        return "".join([self.translate(node.op), self.translate(node.operand)])

    def translate_Invert(self, node): return "~"
    def translate_Not(self, node):    return "!"
    def translate_UAdd(self, node):   return "+"
    def translate_USub(self, node):   return "-"

    def translate_BoolOp(self, node:_ast.BoolOp):
        assert len(node.values) == 2
        return "".join(["(", self.translate(node.values[0]), self.translate(node.op), self.translate(node.values[1]), ")"])

    def translate_And(self, node): return " && "
    def translate_Or(self, node):  return " || "

    def translate_Compare(self, node:_ast.Compare):
        assert len(node.ops) == 1 == len(node.comparators)
        return "".join(["(", self.translate(node.left), self.translate(node.ops[0]), self.translate(node.comparators[0]), ")"])

    def translate_Eq(self, node):    return " === "
    def translate_Gt(self, node):    return " > "
    def translate_Lt(self, node):    return " < "
    def translate_GtE(self, node):   return " >= "
    def translate_LtE(self, node):   return " <= "
    def translate_NotEq(self, node): return " !== "

    def translate_BinOp(self, node:_ast.BinOp):
        return "".join(["(", self.translate(node.left), self.translate(node.op), self.translate(node.right), ")"])

    def translate_Mult(self, node):   return " * "
    def translate_Add(self, node):    return " + "
    def translate_Sub(self, node):    return " - "
    def translate_Div(self, node):    return " / "
    def translate_Mod(self, node):    return " % "
    def translate_Pow(self, node):    return " ** "
    def translate_BitOr(self, node):  return " | "
    def translate_BitAnd(self, node): return " & "
    def translate_BitXor(self, node): return " ^ "

    def translate_AugAssign(self, node:_ast.AugAssign):
        return "".join([self.translate(node.target), " += ", self.translate(node.value)])

    def translate_IfExp(self, node:_ast.IfExp):
        return "".join(["(", self.translate(node.test), " ? ", self.translate(node.body), " : ", self.translate(node.orelse), ")"])

    def generic_translate(self, node):
        print(_ast.dump(node))
        raise NotImplementedError("{!r} nodes not supported for transpilation.".format(node.__class__.__name__))
