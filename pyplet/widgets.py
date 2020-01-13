import tornado.ioloop

from .transpiler import js_code
from .js_lib import jQ, undefined
from .primitives import Component, Session, AbortUpdateException

import contextlib
import functools
import datetime
import sys


class _Throttler:
    def __init__(self, f, ms=10):
        self.f  = f
        self.ms = ms
        self.todo = []
        self.session = Session._current
        assert self.session is not None

    def _do(self):
        doing = self.todo[-1]
        self.todo.clear()
        with self.session:
            doing()

    def __call__(self, *args, **kwargs):
        self.todo.append(functools.partial(self.f, *args, **kwargs))
        if len(self.todo) == 1:
            dt = datetime.timedelta(milliseconds=self.ms)
            tornado.ioloop.IOLoop.current().add_timeout(dt, self._do)


def throttle(**kwargs):
    return functools.partial(_Throttler, **kwargs)


class PeriodicScheduler(Component):
    def init(self, f, ms, reload=False):
        self._f = f
        self._dt = datetime.timedelta(milliseconds=ms)
        self._handle = None
        self._cleared = False
        self.reload = reload

    def do(self):
        if self._cleared or self._session.closed: return
        with self._session:
            self._f()
        self._handle = tornado.ioloop.IOLoop.current().add_timeout(self._dt, self.do)

    def start(self):
        self._cleared = False
        self._handle = tornado.ioloop.IOLoop.current().add_timeout(self._dt, self.do)
        return self

    def clear(self):
        self._cleared = True
        if self._handle is not None:
            tornado.ioloop.IOLoop.current().remove_timeout(self._handle)

    def reset(self):
        if self._handle is not None:
            tornado.ioloop.IOLoop.current().remove_timeout(self._handle)
        self.start()

    @js_code
    class PeriodicSchedulerView:
        def constructor():
            pass
        def onclose():
            if this.reload:
                setTimeout(location.reload.bind(location), 1000)

        def handle(state_change):
            if state_change.reload:
                g.session.ws.onclose = this.onclose.bind(this)

    __view__ = PeriodicSchedulerView


def on_change(*events, within=[], auto=True):
    if not isinstance(within, list):
        within = [within]
    def _decorator(f):
        for decorator in within[::-1]:
            f = decorator(f)
        frame = sys._getframe(1)
        for event in events:
            if isinstance(event, Component):
                comp = event
                field = "value"
            elif isinstance(event, str):
                comp = event.split(".")
                comp, field = ".".join(comp[:-1]), comp[-1]
                comp = eval(comp, frame.f_globals, frame.f_locals)
            else:
                raise Exception("{!r} event is not recognized")
            comp.on_change(lambda state_change: f(), field, auto=auto)
        return f
    return _decorator


class Select(Component):
    def init(self, options=None, value=None, flat=False):
        self.options = options
        self.value = value
        self.flat = flat

    def adjust(self, state_change):
        if state_change.options != undefined:
            value = (state_change.value
                     if state_change.value != undefined
                     else self.value)
            if value is not None and value not in state_change.options:
                state_change.value = None

    def handle(self, state_change):
        assert len(state_change) == 1 and "value" in state_change
        self.update(value=state_change.value, _send=False)

    @js_code
    class SelectView:
        def constructor():
            this.domNode = document.createElement("select")

            def _onchange(evt):
                value = this.domNode.value
                g.session.ask_update(this, {"value":None if value == "" else value})
                this.domNode.value = this.domNode.value
            this.domNode.onchange = _onchange.bind(this)

        def handle(state_change, old_state):
            if state_change.options != undefined:
                (d3.select(this.domNode)
                    .selectAll("option")
                    .data(state_change.options)
                        .text(lambda d: d)
                    .enter()
                        .append("option")
                        .text(lambda d: d)
                    .exit()
                        .remove()
                )
            if state_change.value != undefined:
                this.domNode.value = "" if state_change.value == None else state_change.value
            if state_change.flat != undefined:
                if state_change.flat:
                    this.domNode.setAttribute("multiple","")
                else:
                    this.domNode.removeAttribute("multiple")

    __view__ = SelectView


class Button(Component):
    def init(self, label, style=""):
        self.label = label
        self.value = 0
        self.style = style

    def handle(self, state_change):
        assert len(state_change) == 1 and "click" in state_change
        self.value += 1

    @js_code
    class ButtonView:
        def constructor():
            this.domNode = document.createElement("button")
            this.jq = jQ(this.domNode)
            this.jq.button()
            def _onclick(evt):
                g.session.ask_update(this, {"click":None})
            this.jq.click(_onclick.bind(this))

        def handle(state_change):
            if state_change.label != undefined:
                this.domNode.innerText = state_change.label
            if state_change.style != undefined:
                this.domNode.setAttribute("style", state_change.style)

    __view__ = ButtonView


class Root(Component):
    def init(self, html=None, selector=".root", children=None):
        self.html = html if html is not None else """
            <div class="root"></div>
        """
        self.children = children if children is not None else []
        self.selector = selector

    @js_code
    class RootView:
        def constructor():
            pass

        def handle(state_change):
            if state_change.html != undefined:
                rootRoot = jQ(state_change.html).get()[0]
                this.domNode = jQ(rootRoot, this.selector).get()[0]
                document.getElementsByTagName("body")[0].appendChild(rootRoot)
                for child in this.children:
                    comp = g.session.components[child.comp_id]
                    this.domNode.appendChild(comp.domNode)
            elif state_change.children != undefined:
                for child in state_change.children:
                    comp = g.session.components[child.comp_id]
                    this.domNode.appendChild(comp.domNode)

    __view__ = RootView


class Image(Component):
    def init(self, src="", style=""):
        self.src = src
        self.style = style

    @js_code
    class ImageView:
        def constructor():
            this.domNode = document.createElement("img")

        def handle(state_change, old_state):
            if state_change.src != undefined:
                this.domNode.setAttribute("src", state_change.src)
            if state_change.style != undefined:
                this.domNode.setAttribute("style", state_change.style)

    __view__ = ImageView


class TextArea(Component):
    def init(self, value="", placeholder="", classes="", style=""):
        self.value = value
        self.placeholder = placeholder
        self.classes = classes
        self.style = style

    def handle(self, state_change):
        assert len(state_change) == 1 and "value" in state_change
        self.update(value=state_change["value"], _send=False)

    @js_code
    class TextAreaView:
        def constructor():
            this.domNode = document.createElement("textarea")
            def _onchange(evt):
                g.session.ask_update(this, {"value": this.domNode.value})
            this.domNode.onchange = _onchange.bind(this)

        def handle(state_change):
            if state_change.value != undefined:
                this.domNode.value = state_change.value
            if state_change.placeholder != undefined:
                this.domNode.setAttribute("placeholder", state_change.placeholder)
            if state_change.classes != undefined:
                this.domNode.setAttribute("class", state_change.classes)
            if state_change.style != undefined:
                this.domNode.setAttribute("style", state_change.style)

    __view__ = TextAreaView


class Slider(Component):
    def init(self, value=0, min=0, max=100):
        self.min = min
        self.max = max
        self.value = value

    def adjust(self, state_change):
        min = state_change.min if state_change.min != undefined else self.min
        max = state_change.max if state_change.max != undefined else self.max
        value = state_change.value if state_change.value != undefined else self.value
        if state_change.min != undefined or state_change.max != undefined:
            if max < min:
                raise AbortUpdateException("max ({}) < min ({})".format(max, min))
        if value < min:
            state_change.value = min
        if value > max:
            state_change.value = max


    def handle(self, state_change):
        assert len(state_change) == 1 and "value" in state_change
        self.update(state_change, _send=self.min > state_change.value or self.max < state_change.value)

    @js_code
    class SliderView:
        def constructor():
            this.jq = jQ("""
            <div style="margin:1ex 0ex 1ex 0ex">
                <div class="ui-slider-handle"
                style="width:initial;padding:0em 0.4em 0em 0.4em;height:1.6em">
                </div>
            </div>
            """)
            this.domNode = this.jq.get()[0]
            this._handle = jQ(".ui-slider-handle", this.jq)

            def _ondblclick():
                _value = prompt("", this.value)
                if _value != null:
                    _value = parseInt(_value)
                    this.slider.slider("value", _value)
                    _onslide.bind(this)(null, {"value": _value})

            this._handle.dblclick(_ondblclick.bind(this))

            def _onslide(evt, ui):
                _value = ui.value
                this._handle.text(_value)
                g.session.ask_update(this, {"value": _value})

            this.slider = this.jq.slider({
                "slide": _onslide.bind(this),
            })

        def handle(state_change):
            if state_change.min != undefined:
                this.jq.slider("option", "min", state_change.min)
            if state_change.max != undefined:
                this.jq.slider("option", "max", state_change.max)
            if state_change.value != undefined:
                this.jq.slider("value", state_change.value)
                this._handle.text(state_change.value)

    __view__ = SliderView
