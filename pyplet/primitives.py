import tornado.websocket

from .transpiler import js_code
from .js_lib import undefined

import collections
import contextlib
import functools
import threading
import textwrap
import weakref
import json
import re


def update_state(local_state, compact_state_change):
    for k, v in compact_state_change.items():
        if '__' in k:
            full_k = k
            k, action = full_k.split('__')
            assert k not in compact_state_change
            if action == 'append':
                local_state[k].append(v)
            if action == 'remove':
                local_state[k].remove(v)
        else:
            local_state[k] = compact_state_change[k]


def compute_events(compact_state_change):
    events = set()
    for k, v in compact_state_change.items():
        events.add(k)
        if '__' in k:
            k, action = k.split('__')
            events.add(k)
    return events


class Component:
    """Components are objects whose state are pseudo-synchronized between the
    frontend and the backend.

    Their state is meant to characterize them fully, but nothing constraints to it.
    """

    def __init__(self, **kwargs):
        self._state = {}                               # Internal state
        self._id = id(self)                            # Unique ID
        self._session = Session._current               # Session
        self._session._components[self._id] = self
        self._listeners = []
        self._batch = None
        # Whether the widget is initialized (to skip validation on init)
        # Update Frontend
        view_ref = self.__view__.ref
        if view_ref not in self._session._views:
            self._session._views[view_ref] = self.__view__
            msg = {
                "type": "class",
                "clss": view_ref,
                "defn": self.__view__.defn
            }
            self._session.write_message(json.dumps(msg))
        msg = {
            "type": "new",
            "comp_id": self._id,
            "clss": view_ref
        }
        self._session.write_message(json.dumps(msg))
        with self.batch():
            self.init(**kwargs)

    def init(self):
        pass

    def user_event(self, user_event):
        raise NotImplementedError()
    
    def _set_locally(self, state_change):
        self._state.update(state_change)

    def _send_frontend(self, state_change):
        if not state_change: return
        msg = {
            "type": "state_change",
            "comp_id": self._id,
            "state_change": state_change,
        }
        # state_change may contain components => special encoder
        self._session.write_message(JSONEncoder().encode(msg))

    def _trigger_listeners(self, state_change):
        for listener in self._listeners:
            listener(state_change)

    def on_change(self, callback, events=None, trigger=True):
        if events is not None:
            if isinstance(events, str):
                events = [events]
            _callback = callback
            def callback(state_change):
                if any(e in state_change for e in events):
                    _callback(state_change)
        self._listeners.append(callback)
        if trigger:
            callback(set(self._state))

    def update(self, *args, _send_frontend=True, _trigger_listeners=True, **kwargs):
        """State is always updated directly.
        What can wait are notifications to listeners and frontend"""
        compact_state_change = dict(args, **kwargs) if args and kwargs else kwargs or dict(args)
        if not compact_state_change:
            return
        if self._batch is not None:
            assert not any('__' in k for k in compact_state_change), """
                Actions are currently not supported in batched updates
            """
            update_state(self._state, compact_state_change)
            self._batch.update(compact_state_change)
        else:
            update_state(self._state, compact_state_change)
            self._notify(compact_state_change, _send_frontend, _trigger_listeners)

    def _notify(self, compact_state_change, _send_frontend, _trigger_listeners):
        # Update Frontend
        if _send_frontend:      self._send_frontend(compact_state_change)
        # Trigger listeners
        if _trigger_listeners:  self._trigger_listeners(compute_events(compact_state_change))

    @contextlib.contextmanager
    def batch(self, _send_frontend=True, _trigger_listeners=True):
        """Content should have very simple flow"""
        assert self._batch is None, """Recursive batching not supported"""
        try:
            self._batch = {}
            self._session._batching = True
            yield
            self._session._batching = False
            self._notify(self._batch, _send_frontend, _trigger_listeners)
        finally:
            self._batch = None

    def __setattr__(self, name, value):
        if name.startswith("_"):
            self.__dict__[name] = value
        else:
            self.update((name,value))
    
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
        assert message["type"] == "user_event"
        component = self._components[message["comp_id"]]
        component.user_event(message["user_event"])

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


_js_cls_parser = re.compile(r'^class (?P<name>[a-zA-Z_]+) *(?:\((?P<base>[^\)]*)\))?')


class JSClass:
    _encountered = {}

    def __init__(self, code):
        code = textwrap.dedent(code).strip()
        match = _js_cls_parser.match(code)
        assert match is not None
        import sys

        self.name = match.group('name')
        self.base = match.group('base')
        self.defn = code
        
        frame = sys._getframe(1)
        glob = frame.f_globals
        loc = frame.f_locals

        self.__module__ = glob['__name__']
        self.__qualname__ = f'{loc["__qualname__"]}.{self.name}' if '__qualname__' in loc else self.name
        self.ref = "{}.{}".format(self.__module__,
                                  self.__qualname__)
        assert self.ref not in self._encountered
        self._encountered[self.ref] = self


JSSession = JSClass('''
class JSSession {
    constructor(url) {
        this.ws = new WebSocket(url)
        this.ws.onmessage = (evt) => this.on_message(JSON.parse(evt.data))            
        this.ws.onclose = (evt) => document.getElementsByTagName("title")[0].innerText += "*"
        this.classes = {}
        this.components = {}
        this.i = 0
    }

    user_event(comp, event) {
        this.ws.send(JSON.stringify({
            type: "user_event",
            comp_id: comp._comp_id,
            user_event: event,
        }))
    }

    on_message(message) {
        this.i = this.i+1
        // console.log(this.i, message)
        if (message.type === "state_change") {
            Object.assign(this.components[message.comp_id], message.state_change)
            this.components[message.comp_id].state_change(message.state_change)
        } else if (message.type === "new") {
            let comp_id = message.comp_id
            let Cls = this.classes[message.clss]
            let component = new Cls(comp_id)
            component._comp_id = comp_id
            this.components[comp_id] = component
            // component.handle(message.state)
        } else if (message.type === "class") {
            let script = document.createElement('script')
            //script.src = '/classes/'+message.clss
            script.innerHTML = `g.session.classes["${message.clss}"] = ${message.defn}\\n//# sourceURL=/classes/${message.clss}`
            document.body.appendChild(script)
            //this.classes[message.clss] = (new Function("return "+message.defn))()
        } else if (message.type === "delete") {
            delete this.components[message.comp_id]
        }
    }
}
''')


class JSONEncoder(json.JSONEncoder):
    def default(self, o):
        if isinstance(o, Component):
            return {"comp_id": o._id}
        return super().default(o)
