# __init__.py
print("Initializing multivarious")

from .ode4u import *
#from .lsym  import *
#from .abcd_dim import *


from importlib import metadata

__version__ = metadata.version("multivarious") if metadata.packages_distributions().get("multivarious") else "0.0.1"

# Optional: make submodules importable directly
from . import optimization
from . import utils
from . import distributions

__all__ = ["optimization", "utils", "distributions"]

