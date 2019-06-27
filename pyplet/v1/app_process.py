from .primitives import Session
from multiprocessing import Process

class OfflineSession(Session):
    """Some session playing in a process that can be mirrored to actual real
    sessions
    """
    pass

def _process_main(target, *args, **kwargs):
    session = OfflineSession()
    with session:
        target(*args, **kwargs)

def OfflineProcess(group=None, target=None, name=None, args=(), kwargs={}):
    return Process(group=group,
                   target=_process_main,
                   name=name,
                   args=(target,*args),
                   kwargs=kwargs)
