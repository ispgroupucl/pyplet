class document:
    pass

class console:
    pass


class Replaceable:
    def __init__(self, replacement):
        self.replacement = replacement

jQ = Replaceable("$")

this = object()

undefined = object()

d3 = object()