import tornado.web
import tornado.autoreload
import tornado.websocket
import tornado.ioloop

from .primitives import JSSession, Session
from .widgets import Root
from .feed import Feed

import collections
import contextlib
import functools
import glob
import sys
import os


index_html = """
<!doctype html>
<html class="no-js" lang="en">
    <head>
        <meta charset="utf-8" />
        <title><<APP>></title>

        <link rel="stylesheet" href="http://code.jquery.com/ui/1.12.1/themes/base/jquery-ui.min.css">
        <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/foundation-sites@6.5.3/dist/css/foundation.min.css" integrity="sha256-xpOKVlYXzQ3P03j397+jWFZLMBXLES3IiryeClgU5og= sha384-gP4DhqyoT9b1vaikoHi9XQ8If7UNLO73JFOOlQV1RATrA7D0O7TjJZifac6NwPps sha512-AKwIib1E+xDeXe0tCgbc9uSvPwVYl6Awj7xl0FoaPFostZHOuDQ1abnDNCYtxL/HWEnVOMrFyf91TDgLPi9pNg==" crossorigin="anonymous">
        <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/codemirror/5.44.0/codemirror.min.css">

        <script src="https://cdn.jsdelivr.net/npm/jquery@3.3.1/dist/jquery.min.js"></script>
        <script src="http://code.jquery.com/ui/1.12.1/jquery-ui.js"></script>
        <script src="https://d3js.org/d3.v5.min.js"></script>
        <script src="https://cdn.jsdelivr.net/npm/foundation-sites@6.5.3/dist/js/foundation.min.js" integrity="sha256-/PFxCnsMh+nTuM0k3VJCRch1gwnCfKjaP8rJNq5SoBg= sha384-9ksAFjQjZnpqt6VtpjMjlp2S0qrGbcwF/rvrLUg2vciMhwc1UJJeAAOLuJ96w+Nj sha512-UMSn6RHqqJeJcIfV1eS2tPKCjzaHkU/KqgAnQ7Nzn0mLicFxaVhm9vq7zG5+0LALt15j1ljlg8Fp9PT1VGNmDw==" crossorigin="anonymous"></script>
        <script src="https://cdnjs.cloudflare.com/ajax/libs/underscore.js/1.9.1/underscore-min.js"></script>
        <script src="https://cdnjs.cloudflare.com/ajax/libs/codemirror/5.44.0/codemirror.min.js"></script>
        <script src="https://cdnjs.cloudflare.com/ajax/libs/codemirror/5.44.0/mode/python/python.min.js"></script>
        <style type="text/css">
            .stderr {{
                color: red;
            }}
            .stdout {{
                white-space: pre-wrap;
            }}
        </style>
    </head>
    <body>
        <<TOP_BAR>>
        <script>
            {JSSession}
            g = {{session: new JSSession("ws://"+location.host+"/websocket/<<APP>>")}}
            $(document).foundation();
        </script>
    </body>
</html>
""".format(JSSession=JSSession._defn)


def files_bar(files):
    files.sort()
    dirs = collections.defaultdict(list)
    for file in files:
        dirs[os.path.dirname(file)].append(file)
    items = ["""<li><a href="#">{}</a><ul class="menu vertical">"""
             .format(d)+
             "".join(["""<li><a href="{}">{}</a></li>"""
                      .format("/"+file, os.path.relpath(file, d))
                      for file in files])+
             """</ul></li>"""
             for d, files in dirs.items()
             ]
    return """
    <div class="top-bar">
        <div class="top-bar-left">
            <ul class="dropdown menu" data-dropdown-menu>
                <<ITEMS>>
            </ul>
        </div>
    </div>
    """.replace("<<ITEMS>>", "".join(items))


@contextlib.contextmanager
def session_into_feed(feed):
    import pyplet
    _ = pyplet.root
    assert _ is None
    pyplet.root = feed
    with feed.enter():
        yield
    pyplet.root = _


def make_app(config):
    class SocketHandler(tornado.websocket.WebSocketHandler):
        instances = dict()

        def open(self):
            self.id = id(self)
            self.instances[self.id] = self
            self.session = Session(self.id, self)
            with self.session:
                app_path = self.request.uri[len("/websocket/"):]
                available_apps = glob.glob(config.apps)

                feed = Feed()
                Root(html="<div><h3>{}</h3><div class='root'></div></div>"
                          .format(app_path),
                     children=[feed])
                self.session.add_wrapper(functools.partial(session_into_feed, feed), "feed_wrapper")
                try:
                    if app_path not in available_apps:
                        raise FileNotFoundError()
                    with open(app_path, "r") as file:
                        src = file.read()
                except FileNotFoundError:
                    print("Application {!r} not found</p>".format(app_path),
                          file=sys.stderr)
                else:
                    try:
                        code = compile(src, app_path, "exec")
                        self.session.env = {"__file__": app_path, "__root__": feed}
                        exec(code, self.session.env)
                    except:
                        import traceback
                        traceback.print_exc()

        def on_message(self, message):
            with self.session:
                try:
                    self.session.on_message(message)
                except:
                    import traceback
                    Root(html="""<pre style="color:red">{}</pre>"""
                              .format(traceback.format_exc()))

        def on_close(self):
            self.session.closed = True
            self.instances.pop(self.id)

    class MainHandler(tornado.web.RequestHandler):
        def get(self):
            available_apps = glob.glob(config.apps)
            top_bar = files_bar(available_apps) if config.top_bar else ""
            self.write(index_html
                       .replace("<<TOP_BAR>>", top_bar)
                       .replace("<<APP>>", self.request.uri[1:])
                       )

    app = tornado.web.Application([
        (r"/websocket/.*", SocketHandler),
        (r"/.*", MainHandler),
    ], debug=True)
    return app


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", default=8888, type=int)
    parser.add_argument("--apps", default="*/app_*.py")
    parser.add_argument("--top-bar", default=1, type=int)
    parser.add_argument("--host", default="127.0.0.1")
    args = parser.parse_args()

    app = make_app(args)
    app.listen(args.port, address=args.host)

    from datetime import datetime
    print(f"\rServer (re)started on {datetime.now().ctime()} on http://{args.host}:{args.port}", end="")

    tornado.ioloop.IOLoop.current().start()