"""Publish the canonical install.sh into the docs site.

Serves the installer at ``https://open-jarvis.github.io/OpenJarvis/install.sh``
so users have an HTTPS-valid, project-controlled install URL that does not
depend on the externally-hosted ``openjarvis.ai`` domain — whose TLS config
broke and which the project does not control (issue #337).

Single source of truth: the script lives at ``scripts/install/install.sh``
(also bundled into the wheel as ``_install_scripts/``). This copies it
verbatim into the built site at ``install.sh`` on every ``mkdocs build``,
so the published copy can never drift from the canonical one.
"""

from pathlib import Path

import mkdocs_gen_files

_SRC = Path("scripts/install/install.sh")

with mkdocs_gen_files.open("install.sh", "wb") as dst:
    dst.write(_SRC.read_bytes())
