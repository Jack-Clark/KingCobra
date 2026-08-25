# Third-party components

King Cobra is MIT licensed (see [LICENSE](LICENSE)). It bundles or vendors the following, each under its
own terms.

| Component | Where | Origin | Licence |
| --- | --- | --- | --- |
| Cobra verifier | everything under `src/`, `include/`, `bsl/` not listed below | [DBCobra/CobraVerifier](https://github.com/DBCobra/CobraVerifier) | MIT (Copyright 2020 DBCobra; reproduced in `LICENSE`) |
| MonoSAT 1.4.0 | `monosat/monosat.jar`, `include/libmonosat.so` (Linux x86-64 build) | [MonoSAT](http://www.cs.ubc.ca/labs/isd/Projects/monosat/), Sam Bayless et al. | MIT |
| dbcop (the BE19 baseline) | `bsl/BE19/dbcop-master.zip` | [gitlab.math.univ-paris-diderot.fr/ranadeep/dbcop](https://gitlab.math.univ-paris-diderot.fr/ranadeep/dbcop), Ranadeep Biswas; artifact of Biswas & Enea, OOPSLA 2019 ([Zenodo 3370437](https://zenodo.org/record/3370437)) | No licence file in the archive; included unchanged, as upstream Cobra ships it, for reproducing the paper's baselines only |
| Cobra histories | `CobraLogs/` (git submodule) | [DBCobra/CobraLogs](https://github.com/DBCobra/CobraLogs) | MIT |

Maven and Cargo dependencies are declared in `pom.xml` and `bsl/BE19/BE19_translator/Cargo.toml`
respectively and are fetched at build time under their own licences.
