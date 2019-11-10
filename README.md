# Pyplet

Pyplet is a library for creating web applications from single Python files. Its name (although short for *Python Applet*) was heavily inspired by the french word *pipelette*, because of the unusual amount of communication between the client and the server involved in the execution of our apps.

This name was an amazing source of inspiration for not proposing any premature optimisation to solve this *not-so-much-of-a-problem*, preferring to keep the library simple and letting it grow freely of those constraints.

One can try it using the command from the root folder of this repository. 

```bash
python -m pyplet.server --apps "*/app_*.py" --port 8888
```

## Philosophy

There are already very fancy libraries to achieve small python webapps (Dash and Bokeh to name a few), but we found them quite rigid to extend or to program with. This library wants to keep components very simple, so that there is almost no barrier before writing a new one. (Example coming soon)

And at the same time, writing an app should just feel like writing a research Python script. Printing, plotting. An exception arising should not prevent an app from working at all, and everything should be easy to debug. The counterpart is that you should not expect the apps to look better than a research Python script, at least for now.

It is clear that this library is not ready to produce apps for end users, and won't probably be soon, as this is not even our goal. There are a lot of open questions to answer before.
