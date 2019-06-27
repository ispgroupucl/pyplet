from pyplet.widgets import Div, Root, Slider, TextArea, Select, throttle
from pyplet.feed import Feed
from matplotlib import pyplot as plt
import numpy as np
import sys

feed = Feed(
    layout=[["left   ;classes=cell large-6",
             "right  ;classes=cell large-6",
             "test   ;classes=cell large-6",
             "test2  ;classes=cell large-6"]],
    classes="", rowClasses="grid-x")


Root(html="""
<div class="grid-container fluid">
    <div class="grid-x">
        <div class="cell" class="root"></div>
    </div>
</div>
""", children=[feed])


with feed.enter("left"):
    file_selector = Select(options=["a", "b"])
    feed.append(file_selector)


with feed.enter("right"):
    feed.append(TextArea(value="ok"))
    feed.clear()
    slider = Slider(value=50)
    # feed.append(slider)


with feed.enter("test2"):
    print("hqhq")


@throttle(ms=1)
@feed.enter("test")
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
    file_selector.flat = state_change["value"] == "a"
file_selector.on_change(switch, "value")


with feed.enter("test2"):
    print("Ceci est un slider ajouté dynamiquement après un print()")
    feed.append(slider)
    raise Exception("shit")
    print("lol", file=sys.stderr)
