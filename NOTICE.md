# Attribution and scope

## Derived from `pynad`

`pnadc` is derived from **`pynad`**, created by **Rafael Guerreiro Osorio**
at the Instituto de Pesquisa Econômica Aplicada (Ipea).

- Package: <https://pypi.org/project/pynad/>
- Version referenced: 3.0.3
- License: GPL-3.0-or-later
- Copyright: Rafael Guerreiro Osorio / Ipea, 2023

`pynad` originated the workflow this package implements: mirroring and
synchronizing the IBGE PNAD Contínua archive, parsing the fixed-width
dictionaries, standardizing the microdata, and reconstructing the rotating
person panels. The field conventions and data organization used here follow
`pynad`'s.

This is a reimplementation, not a fork. No `pynad` source code was copied.
It exists to perform remote file discovery over HTTPS rather than FTP, so
that the workflow remains usable on networks that block FTP. It is
distributed under GPL-3.0-or-later to match `pynad` and to keep the lineage
explicit.

`pnadc` does not reproduce `pynad`'s seven-category historical panel
classifier; its person linkage is intentionally simpler and is documented in
`README.md`. Use `pynad` where faithful panel construction matters.

## Informed by `PNADcIBGE`

The column-selection workflow, and the documentation of income deflators and
complex survey design, are informed by IBGE's official R package
**`PNADcIBGE`** by Gabriel Assunção, Douglas Braga, and contributors
(GPL-3, <https://cran.r-project.org/package=PNADcIBGE>). No code was copied.

## No endorsement

No affiliation with or endorsement by IBGE, Ipea, the `pynad` author, or the
`PNADcIBGE` authors is implied. None of them has reviewed this package.

IBGE data and documentation retain their own terms and provenance. This
package downloads and reformats that material; it does not alter its
statistical content, and it redistributes none of it.
