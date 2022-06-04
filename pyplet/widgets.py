import tornado.ioloop

from .transpiler import js_code
from .primitives import Component, Session, JSClass

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

    __view__ = JSClass('''
    class PeriodicSchedulerView {
        constructor() {
        }

        onclose() {
            if (this.reload) {
                setTimeout(location.reload.bind(location), 1000)
            }
        }

        state_change(state_change) {
            if (state_change.reload) {
                g.session.ws.onclose = this.onclose.bind(this)
            }
        }
    }
    ''')


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


class MultiSelect(Component):
    def init(self, options=None, value=None):
        self.options = options
        self.value = value

    def user_event(self, user_event):
        assert len(user_event) == 1 and "value" in user_event
        self.update(value=user_event['value'], _send_frontend=False)

    __view__ = JSClass('''
    class MultiSelectView {
        constructor() {
            this.domNode = document.createElement("select")
            this.domNode.setAttribute("multiple","") 

            function _onchange(evt) {
                selected = this.domNode.selectedOptions
                values = []
                for (opt in selected) {
                    values.push(opt.value)
                }
                g.session.user_event(this, {"value":values})
            }
            this.domNode.onchange = _onchange.bind(this)

        state_change(state_change) {
            if (state_change.options !== undefined) {
                let selection = (d3.select(this.domNode)
                    .selectAll("option")
                    .data(state_change.options)
                    .text((d) => d)
                );
                (selection.enter()
                    .append("option")
                    .text((d) => d)
                )
                selection.exit().remove()
            }
            if (state_change.value !== undefined) {
                this.domNode.value = "" if state_change.value == None else state_change.value
            }
        }
    }
    ''')


class Select(Component):
    def init(self, options=None, value=None, flat=False):
        self.options = options
        self.value = value
        self.flat = flat

    def user_event(self, user_event):
        assert len(user_event) == 1 and "value" in user_event
        self.update(value=user_event['value'], _send_frontend=False)

    __view__ = JSClass('''
    class SelectView {
        constructor() {
            this.domNode = document.createElement("select")

            function _onchange(evt) {
                let value = this.domNode.value
                g.session.user_event(this, {"value":(value === "") ? null : value})
                this.domNode.value = this.domNode.value
            }
            this.domNode.onchange = _onchange.bind(this)
        }

        state_change(state_change, old_state) {
            if (state_change.options !== undefined) {
                let selection = (d3.select(this.domNode)
                    .selectAll("option")
                    .data(state_change.options)
                    .text((d) => d)
                );
                (selection.enter()
                    .append("option")
                    .text((d) => d)
                )
                selection.exit().remove()
            }
            if (state_change.value !== undefined) {
                this.domNode.value = (state_change.value === null) ? "" : state_change.value
            }
            if (state_change.flat !== undefined) {
                if (state_change.flat) {
                    this.domNode.setAttribute("multiple","")
                } else {
                    this.domNode.removeAttribute("multiple")
                }
            }
        }
    }
    ''')


class Button(Component):
    def init(self, label, style=""):
        self.label = label
        self.value = 0
        self.style = style

    def user_event(self, user_event):
        assert len(user_event) == 1 and "click" in user_event
        self.value += 1

    __view__ = JSClass('''
    class ButtonView {
        constructor() {
            this.domNode = document.createElement("button")
            this.jq = $(this.domNode)
            this.jq.button()
            function _onclick(evt) {
                g.session.user_event(this, {"click":None})
            }
            this.jq.click(_onclick.bind(this))
        }

        state_change(state_change) {
            if (state_change.label !== undefined) {
                this.domNode.innerText = state_change.label
            }
            if (state_change.style !== undefined) {
                this.domNode.setAttribute("style", state_change.style)
            }
        }
    }
    ''')


class Root(Component):
    def init(self, html=None, selector=".root", children=None):
        self.html = html if html is not None else """
            <div class="root"></div>
        """
        self.children = children if children is not None else []
        self.selector = selector

    __view__ = JSClass('''
    class RootView {
        constructor() {
        }

        state_change(state_change) {
            if (state_change.html !== undefined) {
                let rootRoot = $(state_change.html).get()[0]
                this.domNode = $(rootRoot, this.selector).get()[0]
                document.getElementsByTagName("body")[0].appendChild(rootRoot)
                for (let child of this.children) {
                    let comp = g.session.components[child.comp_id]
                    this.domNode.appendChild(comp.domNode)
                }
            } else if (state_change.children !== undefined) {
                for (let child of state_change.children) {
                    let comp = g.session.components[child.comp_id]
                    this.domNode.appendChild(comp.domNode)
                }
            }
        }
    }
    ''')


class Image(Component):
    def init(self, src="", style=""):
        self.src = src
        self.style = style

    __view__ = JSClass('''
    class ImageView {
        constructor() {
            this.domNode = document.createElement("img")
        }

        state_change(state_change, old_state) {
            if (state_change.src !== undefined) {
                this.domNode.setAttribute("src", state_change.src)
            }
            if (state_change.style !== undefined) {
                this.domNode.setAttribute("style", state_change.style)
            }
        }
    }
    ''')


class TextArea(Component):
    def init(self, value="", placeholder="", classes="", style=""):
        self.value = value
        self.placeholder = placeholder
        self.classes = classes
        self.style = style

    def user_event(self, user_event):
        assert len(user_event) == 1 and "value" in user_event
        self.update(value=user_event["value"], _send_frontend=False)

    __view__ = JSClass('''
    class TextAreaView {
        constructor() {
            this.domNode = document.createElement("textarea")
            function _onchange(evt) {
                g.session.user_event(this, {"value": this.domNode.value})
            }
            this.domNode.onchange = _onchange.bind(this)
        }

        state_change(state_change) {
            if (state_change.value !== undefined) {
                this.domNode.value = state_change.value
            }
            if (state_change.placeholder !== undefined) {
                this.domNode.setAttribute("placeholder", state_change.placeholder)
            }
            if (state_change.classes !== undefined) {
                this.domNode.setAttribute("class", state_change.classes)
            }
            if (state_change.style !== undefined) {
                this.domNode.setAttribute("style", state_change.style)
            }
        }
    }
    ''')


class Slider(Component):
    def init(self, value=0, min=0, max=100):
        self.min = min
        self.max = max
        self.value = value

    def user_event(self, user_event):
        assert len(user_event) == 1 and "value" in user_event
        self.update(value=user_event['value'],
            _send_frontend=user_event['value'] not in range(self.min, self.max+1))

    __view__ = JSClass('''
    class SliderView {
        constructor() {
            this.jq = $(`
            <div style="margin:1ex 0ex 1ex 0ex">
                <div class="ui-slider-handle"
                style="width:initial;padding:0em 0.4em 0em 0.4em;height:1.6em">
                </div>
            </div>
            `)
            this.domNode = this.jq.get()[0]
            this._handle = $(".ui-slider-handle", this.jq)

            function _ondblclick() {
                let _value = prompt("", this.value)
                if (_value !== null) {
                    _value = parseInt(_value)
                    this.slider.slider("value", _value)
                    _onslide.bind(this)(null, {"value": _value})
                }
            }

            this._handle.dblclick(_ondblclick.bind(this))

            function _onslide(evt, ui) {
                let _value = ui.value
                this._handle.text(_value)
                g.session.user_event(this, {"value": _value})
            }

            this.slider = this.jq.slider({
                "slide": _onslide.bind(this),
            })
        }

        state_change(state_change) {
            if (state_change.min !== undefined) {
                this.jq.slider("option", "min", state_change.min)
            }
            if (state_change.max !== undefined) {
                this.jq.slider("option", "max", state_change.max)
            }
            if (state_change.value !== undefined) {
                this.jq.slider("value", state_change.value)
                this._handle.text(state_change.value)
            }
        }
    }''')
