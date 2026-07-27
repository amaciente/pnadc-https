# Python, R, VS Code, and RStudio

The data repository is independent from the application used to read it.
Paths below use `C:\data\pnadc` as the repository location; substitute your
own. Note that R and DuckDB accept forward slashes on Windows, which avoids
escaping backslashes.

## Python

With pandas:

```python
import pandas as pd

path = r"C:\data\pnadc\parquet\trimestral\2025\PNADC_012025.parquet"
df = pd.read_parquet(path, columns=["uf", "v1028", "vd4002"])
```

With DuckDB, without loading the complete file:

```python
import duckdb

result = duckdb.sql("""
    SELECT uf, count(*) AS n
    FROM read_parquet('C:/data/pnadc/parquet/trimestral/2025/*.parquet')
    GROUP BY uf
""").df()
```

## R and RStudio

Install Arrow once:

```r
install.packages("arrow")
```

Read one quarter:

```r
library(arrow)

file <- "C:/data/pnadc/parquet/trimestral/2025/PNADC_012025.parquet"
pnadc_q1 <- read_parquet(
  file,
  col_select = c(ano, trimestre, uf, upa, estrato, v1028, vd4002)
)
```

Query multiple years lazily:

```r
library(arrow)
library(dplyr)

pnadc <- open_dataset("C:/data/pnadc/parquet/trimestral")

result <- pnadc |>
  select(ano, trimestre, uf, upa, estrato, v1028, vd4002) |>
  filter(ano >= 2024) |>
  collect()
```

The Parquet files keep weight, stratum, and PSU variables, but a weighted
average alone is not a complex-survey variance estimate. Use R's `survey` or
`srvyr` package (or the official `PNADcIBGE::pnadc_design()` workflow when
working with its returned objects) for design-aware estimates.

Do not compare nominal income across periods without applying the matching
official deflator. This package preserves source variables and documentation;
it does not silently alter income values.

