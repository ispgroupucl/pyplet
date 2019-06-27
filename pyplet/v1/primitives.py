import tornado.websocket

from .transpiler import js_code
from .js_lib import let, undefined

import collections
import contextlib
import functools
import threading
import weakref
import json


class Component:
    """Components are objects whose state are pseudo-synchronized between the
    frontend and the backend.

    Their state is meant to characterize them fully, but nothing constraints to it.
    """

    def __init__(self, **kwargs):
        self.__state = {}
        self.__id = id(self)
        self.__session = Session._current
        self.__session.components[self.__id] = self
        self.__packed_state_changes = None
        self.__listeners = []
        self.__initialized = False
        # Update Frontend
        view_ref = "{}.{}".format(self.__view__.__module__,
                                  self.__view__.__qualname__)
        if view_ref not in self.__session._Session__views:
            self.__session._Session__views[view_ref] = self.__view__
            msg = {
                "type": "class",
                "clss": view_ref,
                "name": self.__view__._name,
                "defn": self.__view__._defn
            }
            self.__session.write_message(json.dumps(msg))
        msg = {
            "type": "new",
            "comp_id": self.__id,
            "clss": view_ref
        }
        self.__session.write_message(json.dumps(msg))
        # Initialize in one message
        with self.pack_updates():
            self.init(**kwargs)
        self.__initialized = True

    def on_change(self, callback, events=None, auto=True):
        if events is not None:
            if isinstance(events, str):
                events = [events]
            _callback = callback
            def callback(state_change):
                if any(e in state_change for e in events):
                    _callback(state_change)
        self.__listeners.append(callback)
        if auto:
            callback(self.__state)

    def init(self):
        pass

    def validate(self, state_change):
        pass

    def handle(self, state_change):
        raise NotImplementedError()

    def diff(self, state_change):
        real_change = {k: v for k, v in state_change.items()
                       if self.__state[k] != v}
        return real_change

    def update(self, *args, _broadcast=True, _trigger=True, **kwargs):
        assert _broadcast or _trigger, "Does updating without js or internal event make sense ?"
        state_change = JSLikeState(*args, **kwargs)
        # Validate changes first
        if self.__initialized:
            try:
                self.validate(state_change)
            except InvalidUpdateError:
                return
        # Reflect changes internally immediatly
        self.__state.update(state_change)
        # Trigger listeners
        if _trigger:
            for listener in self.__listeners:
                listener(state_change)
        # Update Frontend
        if _broadcast:
            if self.__packed_state_changes is None:
                self.__state_to_frontend(state_change)
            else:
                self.__packed_state_changes.update(state_change)

    @contextlib.contextmanager
    def pack_updates(self):
        _old = self.__packed_state_changes
        if _old is None:
            self.__packed_state_changes = {}
        yield
        if _old is None:
            self.__state_to_frontend(self.__packed_state_changes)
            self.__packed_state_changes = _old

    def __state_to_frontend(self, state_change):
        if not state_change: return
        msg = {
            "type": "update",
            "comp_id": self.__id,
            "state_change": state_change,
        }
        # state_change may contain backend components => special encoder
        self.__session.write_message(JSONEncoder().encode(msg))

    def __setattr__(self, name, value):
        if name.startswith("_"):
            self.__dict__[name] = value
        else:
            self.update({name:value})
    
    def __getattr__(self, name):
        return self.__state[name]

    def __del__(self):
        msg = {
            "type": "delete",
            "comp_id": self.__id,
        }
        self.__session.write_message(json.dumps(msg))


class Session:
    __lock = threading.RLock()
    _current = None

    def __init__(self, id, socket):
        self.id = id
        self.components = weakref.WeakValueDictionary()
        self.closed = False
        self.__views = weakref.WeakValueDictionary()
        self.__socket = socket
        self.__within = 0

        self.__wrappers = collections.OrderedDict()
        self.__entered = collections.OrderedDict()

    def on_message(self, message):
        message = json.loads(message)
        assert message["type"] == "update"
        component = self.components[message["comp_id"]]
        component.handle(JSLikeState(message["state_change"]))

    def write_message(self, string):
        if self.closed: return
        try:
            self.__socket.write_message(string)
        except tornado.websocket.WebSocketClosedError:
            self.closed = True

    def add_wrapper(self, ctx_manager, name):
        assert self.__wrappers.get(name, None) is None
        self.__wrappers[name] = ctx_manager
        if self.__within:
            if isinstance(ctx_manager, functools.partial):
                ctx_manager = ctx_manager()
            ctx_manager.__enter__()
            self.__entered[name] = ctx_manager

    def del_wrapper(self, name, exit_now=False):
        self.__wrappers.pop(name)
        if exit_now and self.__within:
            self.__entered.pop(name).__exit__(None, None, None)

    def __enter__(self):
        Session.__lock.acquire()
        if self.__within == 0:
            self.__old_session = Session._current
            Session._current = self
            for name, ctx_manager in self.__wrappers.items():
                if isinstance(ctx_manager, functools.partial):
                    ctx_manager = ctx_manager()
                ctx_manager.__enter__()
                self.__entered[name] = ctx_manager
        self.__within += 1

    def __exit__(self, exc_type, exc_value, traceback):
        self.__within -= 1
        if self.__within == 0:
            while self.__entered:
                _, ctx_manager = self.__entered.popitem()
                if ctx_manager.__exit__(exc_type, exc_value, traceback):
                    exc_type = exc_value = traceback = None
            Session._current = self.__old_session
        Session.__lock.release()


@js_code
class JSSession:
    def constructor(url):
        this.ws = WebSocket(url)
        def _on_message(evt):
            return this.on_message(JSON.parse(evt.data))
        this.ws.onmessage = _on_message.bind(this)
        this.classes = {}
        this.components = {}
        this.i = 0

    def ask_update(comp, state_change):
        this.ws.send(JSON.stringify({
            "type": "update",
            "comp_id": comp._comp_id,
            "state_change": state_change,
        }))

    def on_message(message):
        this.i = this.i+1
        # console.log(this.i, message)
        if message.type == "update":
            let.old_state = Object.assign({}, this.components[message.comp_id])
            Object.assign(this.components[message.comp_id], message.state_change)
            this.components[message.comp_id].handle(message.state_change, old_state)
        elif message.type == "new":
            let.comp_id = message.comp_id
            let.Cls = this.classes[message.clss]
            let.component = Cls(comp_id)
            component._comp_id = comp_id
            this.components[comp_id] = component
            # component.handle(message.state)
        elif message.type == "class":
            this.classes[message.clss] = Function("return "+message.defn)()
        elif message.type == "delete":
            del this.components[message.comp_id]


class JSONEncoder(json.JSONEncoder):
    def default(self, o):
        if not isinstance(o, Component):
            return super().default(o)
        return {"comp_id": o._Component__id}


class InvalidUpdateError(Exception):
    pass


class JSLikeState(dict):
    def __getattr__(self, key):
        return self.get(key, undefined)
    def __setattr__(self, key, value):
        self[key] = value


class Event(dict):
    def __new__(cls, *args, **kwargs):
        event = super().__new__(cls, *args, **kwargs)
        event.__dict__ = event
        return event
