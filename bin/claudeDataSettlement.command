#!/bin/zsh
# Double-click to settle the open evidence leads of REVELOC TETRA with Claude.
#
# Runs `csa settle --cli claude` interactively in this Terminal window: Claude reads each lead's original
# source and asks before it runs a command. When it asks to run `csa ev ...` or `python3.14 -m csa_docx.*`,
# choose "allow" (or "always allow for this session") so it can write the settled evidence to the matrix.

BIN="${0:A:h}"                       # the folder this file is in: .agents/bin
cd "${BIN:h:h}" || exit 1            # the CurrentStateAssessments folder

echo "REVELOC TETRA: settling evidence leads with Claude"
echo "Folder: $PWD"
echo

"$BIN/csa" -p tetra-reveloc settle --cli claude
status=$?

echo
echo "Finished (exit $status). Press Return to close this window."
read -r _
