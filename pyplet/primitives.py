import tornado.websocket

from .transpiler import js_code
from .js_lib import undefined

import collections
import contextlib
import functools
import threading
import weakref
import json


class ListSuffixes:
    @staticmethod
    def append(obj, value):
        return [*obj, value]
    @staticmethod
    def remove(obj, value):
        return [o for o in obj if o != value]


class Component:
    """Components are objects whose state are pseudo-synchronized between the
    frontend and the backend.

    Their state is meant to characterize them fully, but nothing constraints to it.
    """
    _suffixes = ListSuffixes

    def __init__(self, **kwargs):
        self._state = {}                               # Internal state
        self._id = id(self)                            # Unique ID
        self._session = Session._current               # Session
        self._session._components[self._id] = self
        self._listeners = []
        # Whether the widget is initialized (to skip validation on init)
        # Update Frontend
        view_ref = "{}.{}".format(self.__view__.__module__,
                                  self.__view__.__qualname__)
        if view_ref not in self._session._views:
            self._session._views[view_ref] = self.__view__
            msg = {
                "type": "class",
                "clss": view_ref,
                # "name": self.__view__._name,
                "defn": self.__view__._defn
            }
            self._session.write_message(json.dumps(msg))
        msg = {
            "type": "new",
            "comp_id": self._id,
            "clss": view_ref
        }
        self._session.write_message(json.dumps(msg))
        # Initialize in one message
        self.__packed_state_changes = {}
        self.init(**kwargs)
        self.__state_to_frontend(self.__packed_state_changes)
        self.__packed_state_changes = None

    def on_change(self, callback, events=None, auto=True):
        if events is not None:
            if isinstance(events, str):
                events = [events]
            _callback = callback
            def callback(state_change):
                if any(e in state_change for e in events):
                    _callback(state_change)
        self._listeners.append(callback)
        if auto:
            callback(self._state)

    def init(self):
        pass

    def handle(self, state_change):
        raise NotImplementedError()

    def adjust(self, state_change):
        pass
    
    def _set(self, state_change):
        self._state.update(state_change)

    def _send(self, state_change):
        if self.__packed_state_changes is None:
            self.__state_to_frontend(state_change)
        else:
            self.__packed_state_changes.update(state_change)

    def _trigger(self, state_change):
        for listener in self._listeners:
            listener(state_change)

    def update(self, *args, _set=True, _send=True, _trigger=True, **kwargs):
        assert _set
        state_change = JSLikeState(*args, **kwargs)
        # Validate changes first
        if self.__packed_state_changes is None:  # If initialized
            try:
                self.adjust(state_change)
            except AbortUpdateException:
                raise
        # Reflect changes internally
        if _set:        self._set(state_change)
        # Update Frontend
        if _send:       self._send(state_change)
        # Trigger listeners
        if _trigger:    self._trigger(state_change)

    def __state_to_frontend(self, state_change):
        if not state_change: return
        msg = {
            "type": "update",
            "comp_id": self._id,
            "state_change": state_change,
        }
        # state_change may contain components => special encoder
        self._session.write_message(JSONEncoder().encode(msg))

    def __setattr__(self, name, value):
        if name.startswith("_"):
            self.__dict__[name] = value
            return
        elif "__" in name:
            rname, action = name.split("__")
            whole = getattr(self._suffixes, action)(self._state[rname], value)
            state_change = JSLikeState({name:value, rname:whole})
            try:
                self.adjust(state_change)
                if name not in state_change or rname not in state_change:
                    raise AbortUpdateException()
                self._set({rname:state_change[rname]})
                self._send({name:state_change[name]})
                self._trigger(state_change)
            except AbortUpdateException:
                raise
        else:
            self.update({name: value})
    
    def __getattr__(self, name):
        return self._state[name]

    def __del__(self):
        msg = {
            "type": "delete",
            "comp_id": self._id,
        }
        self._session.write_message(json.dumps(msg))


class Session:
    __lock = threading.RLock()
    _current = None

    def __init__(self, id, socket):
        self.id = id
        self.closed = False
        self._socket = socket
        self._components = weakref.WeakValueDictionary()
        self._views = weakref.WeakValueDictionary()

        self.__within = 0
        self.__wrappers = collections.OrderedDict()
        self.__entered = collections.OrderedDict()

    def on_message(self, message):
        message = json.loads(message)
        assert message["type"] == "ask_update"
        component = self._components[message["comp_id"]]
        component.handle(JSLikeState(message["state_change"]))

    def write_message(self, string):
        if self.closed: return
        try:
            self._socket.write_message(string)
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


class ServerSession(Session):
    pass


class ExposerSession(Session):
    pass


@js_code
class JSSession:
    def constructor(url):
        this.ws = WebSocket(url)
        def _on_message(evt):
            return this.on_message(JSON.parse(evt.data))
        this.ws.onmessage = _on_message.bind(this)
        def _on_close(evt):
            document.getElementsByTagName("title")[0].innerText += "*"
        this.ws.onclose = _on_close.bind(this)
        this.classes = {}
        this.components = {}
        this.i = 0

    def ask_update(comp, state_change):
        this.ws.send(JSON.stringify({
            "type": "ask_update",
            "comp_id": comp._comp_id,
            "state_change": state_change,
        }))

    def on_message(message):
        this.i = this.i+1
        # console.log(this.i, message)
        if message.type == "update":
            old_state = Object.assign({}, this.components[message.comp_id])
            Object.assign(this.components[message.comp_id], message.state_change)
            this.components[message.comp_id].handle(message.state_change, old_state)
        elif message.type == "new":
            comp_id = message.comp_id
            Cls = this.classes[message.clss]
            component = Cls(comp_id)
            component._comp_id = comp_id
            this.components[comp_id] = component
            # component.handle(message.state)
        elif message.type == "class":
            this.classes[message.clss] = Function("return "+message.defn)()
        elif message.type == "delete":
            del this.components[message.comp_id]


class JSONEncoder(json.JSONEncoder):
    def default(self, o):
        if isinstance(o, Component):
            return {"comp_id": o._id}
        return super().default(o)


class AbortUpdateException(Exception):
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
