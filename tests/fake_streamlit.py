"""A tiny stand-in for the `streamlit` module so page scripts can be executed in tests.
It records what a page displays and returns scripted widget values. Not a browser test: it checks that page code
runs, uses the API contract correctly and shows the right messages."""
import sys
import types


class StopPage(Exception):
    pass


class RerunPage(Exception):
    pass


class Config:
    def reset(self):
        self.text, self.select, self.checks, self.clicks, self.file, self.numbers = {}, {}, {}, set(), None, {}
        self.log, self.downloads, self.pages = [], [], []


CFG = Config()
CFG.reset()


class Any:
    """Absorbs any call/attribute; usable as a context manager."""
    def __call__(self, *a, **k):
        return Any()

    WIDGETS = ("text_input", "text_area", "number_input", "selectbox", "radio", "multiselect", "checkbox", "button", "form_submit_button",
               "file_uploader", "download_button")

    def __getattr__(self, name):
        if name in Any.WIDGETS:  # widgets used on columns/containers behave like the top-level ones
            return getattr(sys.modules["streamlit"], name)
        return Any()

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def __iter__(self):
        return iter(())


class SessionState(dict):
    def __getattr__(self, k):
        try:
            return self[k]
        except KeyError:
            raise AttributeError(k) from None

    def __setattr__(self, k, v):
        self[k] = v


class Stub(types.ModuleType):
    def __init__(self):
        super().__init__("streamlit")
        self.session_state = SessionState()
        self.sidebar = Any()
        self.__dict__.update({k: self._recorder(k) for k in ("title", "caption", "write", "markdown", "code", "json", "subheader", "header", "divider", "image",
                                                             "plotly_chart", "dataframe", "metric", "toast", "set_page_config", "table", "text", "latex")})
        for kind in ("error", "success", "warning", "info"):
            self.__dict__[kind] = self._recorder(kind)

    @staticmethod
    def _recorder(kind):
        def rec(*a, **k):
            CFG.log.append((kind, str(a[0]) if a else ""))
            return Any()
        return rec

    def stop(self):
        raise StopPage()

    def rerun(self):
        raise RerunPage()

    def columns(self, spec, **k):
        return [Any() for _ in range(spec if isinstance(spec, int) else len(spec))]

    def tabs(self, labels):
        return [Any() for _ in labels]

    def form(self, *a, **k):
        return Any()

    def expander(self, *a, **k):
        return Any()

    def spinner(self, *a, **k):
        return Any()

    def empty(self):
        return Any()
    def container(self, *a, **k):
        return Any()
    def progress(self, *a, **k):
        return Any()

    def text_input(self, label, value="", **k):
        return CFG.text.get(label, value)

    text_area = text_input

    def number_input(self, label, min_value=None, max_value=None, value=None, **k):
        return CFG.numbers.get(label, value if value is not None else (min_value or 0))

    def selectbox(self, label, options, index=0, format_func=str, **k):
        opts = list(options)
        [format_func(o) for o in opts]  # exercise label lambdas
        return CFG.select.get(label, opts[index] if opts else None)

    radio = selectbox

    def multiselect(self, *a, **k):
        return []

    def checkbox(self, label, value=False, **k):
        return CFG.checks.get(label, value)

    def button(self, label, disabled=False, **k):
        return label in CFG.clicks and not disabled

    form_submit_button = button

    def file_uploader(self, *a, **k):
        return CFG.file

    def download_button(self, label, data=None, **k):
        CFG.downloads.append((label, k.get("file_name"), len(data or b"")))
        return False

    def Page(self, path, **k):
        return types.SimpleNamespace(path=path, **k)

    def navigation(self, pages, **k):
        CFG.pages = pages
        return types.SimpleNamespace(run=lambda: CFG.log.append(("nav.run", "")))


def install() -> Stub:
    if not isinstance(sys.modules.get("streamlit"), Stub):
        sys.modules["streamlit"] = Stub()
    return sys.modules["streamlit"]
