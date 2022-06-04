from pyplet.widgets import Root, Slider, TextArea, Select, throttle
from pyplet.feed import Feed
from matplotlib import pyplot as plt
import numpy as np
import sys

# Let's define some responsive layout
feed = Feed(
    layout=[["topleft   ;classes=cell large-6",
             "topright  ;classes=cell large-6",
             "botleft   ;classes=cell large-6",
             "botright  ;classes=cell large-6"]],
    classes="", rowClasses="grid-x")

# Let's put the layout in the web page using a Root
Root(html="""
<div class="grid-container fluid">
    <div class="grid-x">
        <div class="cell" class="root"></div>
    </div>
</div>
""", children=[feed])


with feed.enter("topleft"):
    file_selector = Select(value="flat", options=["flat", "not flat"])
    feed.append(file_selector)


with feed.enter("topright"):
    feed.append(TextArea(value="ok"))
    feed.clear()
    print("A textarea was here but got cleared")

    slider = Slider(value=50)
    feed.append(slider)
    print("A slider was here but got moved")


with feed.enter("botright"):
    print("Another block")


@throttle(ms=1)
@feed.enter("botleft")
def update(state_change):
    feed.clear()
    if slider.value == slider.min:
        return
    x = np.linspace(0, slider.value, 100)
    plt.plot(x, np.sin(x))
    print(slider.value)
    plt.show()
    plt.plot(x, x**2)
    plt.show()
slider.on_change(update, "value")


def switch(state_change):
    file_selector.flat = file_selector.value == "flat"
file_selector.on_change(switch, "value")


with feed.enter("botright"):
    print("Here after will be dynamically moved the slider")
    feed.append(slider)
    raise Exception("Some exception was thrown")
    print("Some output that won't show.", file=sys.stderr)
