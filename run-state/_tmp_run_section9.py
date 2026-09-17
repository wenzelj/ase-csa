import datetime
if not hasattr(datetime, "UTC"):
    datetime.UTC = datetime.timezone.utc

import runpy
import sys
import os

workspace = os.environ["CSA_WORKSPACE"]
sys.argv = [
    "cli_apply_section.py",
    "--engine", "docxengine",
    "--section", "9",
    "--change-file", os.path.join(workspace, "01 Current State AS Built/7 IAMPS/01 Final Version/reviews/ChangesCSA_IAMPS_Section9_E146_E160.md"),
    "--docx", os.path.join(workspace, "01 Current State AS Built/7 IAMPS/01 Final Version/Current State Assessment - IAMPS - v1.docx"),
    "--workspace", workspace,
    "--limit", "10",
    "--comment-author", "Wenzel Joubert",
    "--comment-initials", "WJ",
]

runpy.run_path(os.path.join(workspace, ".agents/framework/csa_docx/cli_apply_section.py"), run_name="__main__")
