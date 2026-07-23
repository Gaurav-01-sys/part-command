from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, Iterable

import gradio as gr


@dataclass
class UIElement:
    component: Any


def _unwrap(items: Iterable[UIElement | Any] | None) -> list[Any]:
    if not items:
        return []
    result: list[Any] = []
    for item in items:
        result.append(item.component if isinstance(item, UIElement) else item)
    return result


class App:
    def __init__(self, title: str = "Mini Anvil", description: str = "") -> None:
        self.title = title
        self.description = description
        self._blocks = gr.Blocks(title=title)

    def __enter__(self) -> "App":
        self._blocks.__enter__()
        if self.description:
            gr.Markdown(f"# {self.title}\n\n{self.description}")
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self._blocks.__exit__(exc_type, exc, tb)

    def run(self, **kwargs: Any) -> Any:
        return self._blocks.launch(**kwargs)

    @contextmanager
    def row(self):
        with gr.Row():
            yield

    @contextmanager
    def column(self, **kwargs: Any):
        with gr.Column(**kwargs):
            yield

    @contextmanager
    def accordion(self, label: str, open: bool = True):
        with gr.Accordion(label, open=open):
            yield

    @contextmanager
    def tabs(self):
        with gr.Tabs():
            yield

    @contextmanager
    def tab(self, label: str):
        with gr.Tab(label):
            yield

    def markdown(self, value: str) -> UIElement:
        return UIElement(gr.Markdown(value))

    def textbox(self, label: str = "", value: str = "", placeholder: str = "", lines: int = 1) -> UIElement:
        return UIElement(gr.Textbox(label=label, value=value, placeholder=placeholder, lines=lines))

    def dropdown(self, choices: list[str], *, value: str | None = None, label: str = "", multiselect: bool = False) -> UIElement:
        return UIElement(gr.Dropdown(choices=choices, value=value, label=label, multiselect=multiselect))

    def button(self, value: str) -> UIElement:
        return UIElement(gr.Button(value))

    def dataframe(self, label: str = "", value: Any | None = None) -> UIElement:
        return UIElement(gr.Dataframe(value=value, label=label, interactive=False))

    def plot(self, label: str = "") -> UIElement:
        return UIElement(gr.Plot(label=label))

    def state(self, value: Any = None) -> UIElement:
        return UIElement(gr.State(value=value))

    def html(self, value: str) -> UIElement:
        return UIElement(gr.HTML(value))

    def on_click(
        self,
        button: UIElement,
        *,
        inputs: list[UIElement | Any] | None = None,
        outputs: list[UIElement | Any] | None = None,
        **kwargs: Any,
    ):
        def decorator(fn):
            button.component.click(fn, inputs=_unwrap(inputs), outputs=_unwrap(outputs), **kwargs)
            return fn

        return decorator

    def on_submit(
        self,
        textbox: UIElement,
        *,
        inputs: list[UIElement | Any] | None = None,
        outputs: list[UIElement | Any] | None = None,
        **kwargs: Any,
    ):
        def decorator(fn):
            textbox.component.submit(fn, inputs=_unwrap(inputs), outputs=_unwrap(outputs), **kwargs)
            return fn

        return decorator

