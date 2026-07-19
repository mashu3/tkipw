"""Built-in adapters for libraries that normally target Jupyter."""

from .altair import AltairExtension
from .bokeh import BokehExtension
from .folium import FoliumExtension
from .matplotlib import MatplotlibExtension, matplotlib_inline, matplotlib_window
from .pillow import PillowExtension
from .pyvista import PyVistaExtension

__all__ = [
    "AltairExtension",
    "BokehExtension",
    "FoliumExtension",
    "MatplotlibExtension",
    "matplotlib_inline",
    "matplotlib_window",
    "PillowExtension",
    "PyVistaExtension",
]
