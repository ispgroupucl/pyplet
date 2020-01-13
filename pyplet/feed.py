from .primitives import Component
from .transpiler import js_code
from .js_lib import jQ

from matplotlib import pyplot as plt

import numpy as np
import scipy.misc

import collections
import contextlib
import base64
import sys
import io

import matplotlib
matplotlib.use("Agg")


def arrays_to_rgba(r=None, g=None, b=None, alpha=None, scale=1):
    f = [x for x in (r, g, b) if x is not None][0]
    if r is None: r = np.zeros_like(f)
    if g is None: g = np.zeros_like(f)
    if b is None: b = np.zeros_like(f)
    if alpha is None:
        alpha = 255
    if isinstance(alpha, (float, int)):
        alpha = np.ones_like(f) * alpha
    else:
        alpha = alpha * scale
    return np.stack((r*scale, g*scale, b*scale, alpha), axis=-1).astype(np.uint8)


def img_to_rgba(image, scale=1, CHW=False):
    if len(image.shape) == 2:
        image = image[...,None]
    elif CHW:
        image = np.moveaxis(image, 0, 2)
    if scale != 1:
        image = image*scale
    if image.dtype != np.uint8:
        image = image.astype(np.uint8)
    assert len(image.shape) == 3
    if image.shape[-1] == 1:
        image = np.tile(image, [1, 1, 3])
    if image.shape[-1] == 2:
        image = np.concatenate((image,
                                np.zeros([*image.shape[:2], 1], dtype=np.uint8)),
                               axis=-1)
    if image.shape[-1] == 3:
        image = np.concatenate((image, 255*np.ones(image.shape[:-1], dtype=np.uint8)[...,None]), axis=-1)
    assert image.shape[-1] == 4

    return image


class Block(Component):
    def init(self, classes="", style="", ms=1000):
        self.classes = classes
        self.style = style
        self.ms = int(ms)
        self.content = []

    @contextlib.contextmanager
    def enter(self):
        _stdout = sys.stdout
        _stderr = sys.stderr
        _show = plt.show
        try:
            sys.stdout = Block._StreamCapture(self, stream="stdout")
            sys.stderr = Block._StreamCapture(self, stream="stderr")
            plt.show = self._show
            yield self
        except Exception as e:
            import traceback
            traceback.print_exc()
        finally:
            plt.show = _show
            sys.stdout = _stdout
            sys.stderr = _stderr

    def clear(self):
        self.content = []

    def append(self, widget):
        if isinstance(widget, Component):
            self.content__append = widget
        elif isinstance(widget, str):
            self.content__append = {"html": widget}

    def image(self, image, scale=1, CHW=False, style="", end="", img=None):
        file = io.BytesIO()
        scipy.misc.toimage(img_to_rgba(image, scale=scale, CHW=CHW)).save(file, format="jpg", quality=100)
        src = "data:image/jpg;base64,{}".format(
            base64.b64encode(file.getvalue()).decode("utf-8"))

        if img is not None:
            assert not end and not style
            img.src = src
        else:
            self.append('<img src={!r} style={!r} />{}'.format(src, style, end))

    def _show(self, style="", end="", img=None):
        file = io.BytesIO()
        plt.tight_layout()
        plt.savefig(file, dpi="figure", format="jpg", quality=100)
        plt.close()
        src = "data:image/jpg;base64,{}".format(
            base64.b64encode(file.getvalue()).decode("utf-8"))

        if img is not None:
            assert not end and not style
            img.src = src
        else:
            self.append('<img src={!r} style={!r} />{}'.format(src, style, end))

    def remove(self, widget):
        self.content__remove = widget

    class _StreamCapture:
        def __init__(self, block, stream):
            self.block = block
            self.stream = stream

        def write(self, text):
            self.block.content__append = dict(content=text, stream=self.stream)

    @js_code
    class BlockView:
        def constructor():
            this.domNode = document.createElement("div")
            this.jq = jQ(this.domNode)

        def append(content):
            if content.stream:
                block = this.domNode
                last = block.lastChild
                if (not last or not last.classList.contains(content.stream)):
                    last = document.createElement("pre")
                    last.classList.add(content.stream)
                    last.style.color = content.color
                    block.appendChild(last)
                newContent = content.content
                lastCharet = newContent.lastIndexOf("\r")
                if lastCharet >= 0:
                    whole = last.innerText + content.content.slice(0, lastCharet)
                    lastLine = last.innerText.lastIndexOf("\n")
                    last.innerText = whole.slice(0,lastLine+1) + newContent.slice(lastCharet+1)
                else:
                    last.innerText += content.content
            if content.html:
                this.jq.append(content.html)
            if content.comp_id:
                comp = g.session.components[content.comp_id]
                this.domNode.appendChild(comp.domNode)

        def handle_height():
            height = this.jq.height()
            this.domNode.innerHTML = ""
            if this._clearPending:
                clearTimeout(this._clearPending[1])
                height = Math.max(height, this._clearPending[0])
                this._clearPending = None

            this.jq.css("minHeight", height+"px")
            def clearHeight():
                this.jq.animate({"minHeight": ''}, {"queue":False})
                this._clearPending = None
            this._clearPending = [height, setTimeout(clearHeight.bind(this), this.ms)]


        def handle(state_change):
            if state_change.content != undefined:
                this.handle_height()
                for c in state_change.content:
                    this.append(c)
            if state_change.content__append != undefined:
                this.append(state_change.content__append)
            if state_change.content__remove != undefined:
                this.domNode.removeChild(g.session.components[state_change.content__remove.comp_id].domNode)
                this.handle_height()
            if state_change.classes != undefined:
                this.domNode.setAttribute("class", state_change.classes)
            if state_change.style != undefined:
                this.domNode.setAttribute("style", state_change.style)

    __view__ = BlockView


def _trim(strings):
    return [string.strip() for string in strings]


class Feed(Component):
    def init(self, layout=[["body"]], classes="", rowClasses=""):
        self.__current = []
        _layout = []
        for row in layout:
            _layout.append([])
            for comp in row:
                name, *opts = _trim(comp.split(";"))
                options = dict(_trim(opt.split("=")) for opt in opts)
                _layout[-1].append({"name":name, "options":options})
        self.layout = _layout
        self.classes = classes
        self.rowClasses = rowClasses
        self.blocks = {
            blk["name"]: Block(**blk["options"])
            for row in self.layout
            for blk in row
        }

        if len(self.layout) == 1 and len(self.layout[0]) == 1:
            self.__current.append(self.blocks[self.layout[0][0]["name"]])

    def enter(self, name=None, **kwargs):
        if name is ...:
            blk = Block(**kwargs)
            self.append(blk)
            return self._enter(blk)
        assert not kwargs
        return self._enter(self._getblk(name))

    @contextlib.contextmanager
    def _enter(self, blk):
        try:
            self.__current.append(blk)
            with blk.enter():
                yield blk
        finally:
            self.__current.pop()

    def clear(self, name=None):
        blk = self._getblk(name)
        blk.clear()

    def append(self, widget, name=None):
        blk = self._getblk(name)
        blk.append(widget)

    def image(self, image, scale=1, CHW=False, style="", end=""):
        blk = self._getblk(None)
        blk.image(image, scale, CHW, style, end)

    def remove(self, widget, name=None):
        blk = self._getblk(name)
        blk.remove(widget)

    @js_code
    class FeedView:
        def constructor():
            this.domNode = document.createElement("div")
            this._rows = []

        def handle(state_change):
            if state_change.classes != undefined:
                if state_change.classes != "":
                    this.domNode.classList.add(*state_change.classes.split(" "))
            if state_change.layout != undefined:
                this._rows = []
                this.domNode.innerHTML = ""
                for row in state_change.layout:
                    domRow = document.createElement("div")
                    if this.rowClasses != "":
                        domRow.classList.add(*this.rowClasses.split(" "))
                    this._rows.push(domRow)
                    for block in row:
                        blk_comp_id = this.blocks[block.name].comp_id
                        domRow.appendChild(g.session.components[blk_comp_id].domNode)
                    this.domNode.appendChild(domRow)

    __view__ = FeedView

    def _getblk(self, name):
        if name is None:
            return self.__current[-1]
        if isinstance(name, Block):
            return name
        return self.blocks[name]
