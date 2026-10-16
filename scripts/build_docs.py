"""Build the API reference with pdoc and fail on any warning (CI, see #45).

Every module is passed explicitly: pdoc honours ``__all__``, which would
otherwise hide the submodules of each subpackage.

Usage: python scripts/build_docs.py [output_dir]   (default: site/)
"""

from __future__ import annotations

import pkgutil
import sys
import warnings
from pathlib import Path

import pdoc

import fixed_income

warnings.simplefilter("error")
# pdoc already pulls in some submodules on its own; listing them again is harmless.
warnings.filterwarnings("ignore", message=r"The module specification .* has already been added")

modules = ["fixed_income"] + [
    info.name for info in pkgutil.walk_packages(fixed_income.__path__, prefix="fixed_income.")
]
output_dir = Path(sys.argv[1] if len(sys.argv) > 1 else "site")
pdoc.render.configure(docformat="google")
pdoc.pdoc(*modules, output_directory=output_dir)
print(f"Rendered {len(modules)} modules to {output_dir}/")
