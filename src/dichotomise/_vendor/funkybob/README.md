# Vendored: funkybob

Source: <https://github.com/andreacorbellini/funkybob>
Author: Andrea Corbellini
Licence: MIT (see `LICENSE` in this folder — the upstream repository does
not ship a separate licence file, so this is the standard MIT text with the
author as copyright holder, per the licence declared in the upstream
`setup.py`)
Vendored from commit: `151298100b68d482203829a33d8b4b95a8d5ef92` (2022-07-19)

`__init__.py` and `data.py` are copied unmodified from upstream.

## Why vendored rather than a normal dependency

`funkybob` is used by `pydcm/relabel.py`'s `minimal` sanitisation policy to
generate readable replacement patient names (e.g. `hungry_pike`). It is a
small, single-maintainer package with no dependencies of its own — vendoring
its source here means dichotomise keeps working even if the PyPI package or
the GitHub repository ever becomes unavailable.

Do not edit these files. If an upstream fix or feature is needed, pull a
fresh copy from the source above and replace both files, updating the
commit hash recorded here.
