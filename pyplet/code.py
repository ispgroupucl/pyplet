from .primitives import Component
from .widgets import on_change
from .feed import Feed
from .transpiler import js_code
from .js_lib import this, undefined

import collections


def code_cell(code=None, layout=[["code","output"]], options=None, env=None):
    feed = Feed(layout=layout)
    code = CodeCell(code=code, options=options)
    feed.append(code, "code")
    cell_env = {"feed": feed}
    if env is not None:
        cell_env = {**env, **cell_env}
    code.on_change(lambda s:feed.clear("output"),
                   events=["clear_output"], auto=False)
    @on_change(code, dec=[feed.enter("output")], auto=False)
    def _():
        exec(code.value, cell_env)
    return feed


class CodeCell(Component):

    def init(self, code=None, options=None):
        self.code = "# feed.clear()\n" if code is None else code
        self.options = {
            "lineNumbers": True,
            "mode": "python",
        } if options is None else options

    def handle(self, state_change):
        if state_change.clear_output != undefined:
            self.update(clear_output=state_change.clear_output, _send=False)
        if state_change.value != undefined:
            self.update(value=state_change.value, _send=False)
        if state_change.instantiate != undefined:
            self.instantiate = state_change.instantiate

    @js_code
    class CodeCellView:
        def constructor(comp_id):
            this.domNode = document.createElement("div")
            this.domNode.style.border = "1px solid lightgray"
            this.textarea = document.createElement("textarea")
            this.domNode.appendChild(this.textarea)
            this._comp_id = comp_id
            g.session.ask_update(this, {"instantiate":None})

        def handle(state_change):
            if state_change.instantiate != undefined:
                if this.options.extraKeys == undefined:
                    this.options.extraKeys = {}
                def run():
                    g.session.ask_update(this, {"value": this.editor.getValue()})
                def clearThenRun():
                    g.session.ask_update(this, {"clear_output": None, "value": this.editor.getValue()})

                Object.assign(this.options.extraKeys, {
                    "Ctrl-Enter": run.bind(this),
                    "Shift-Ctrl-Enter": clearThenRun.bind(this),
                })
                this.editor = CodeMirror.fromTextArea(this.textarea, this.options)
            if state_change.code != undefined:
                if this.editor == undefined:
                    this.textarea.value = state_change.code
                else:
                    this.editor.setValue(state_change.code)

    __view__ = CodeCellView
