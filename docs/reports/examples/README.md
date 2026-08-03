# Five most complete crawler outputs

These examples were selected from job
`0633dcfa-9054-4d59-8262-07401ea45760`, generated on 2026-08-03.

All five items passed every coverage check and contain the complete artifact
set: raw HTML, captured tabs, cleaned HTML, Markdown, structured disease JSON,
normalization metadata, coverage result, manifest, and screenshot.

## Selection method

Items were ranked by:

1. number of populated structured disease fields;
2. availability of all four source tabs;
3. number of preserved Life/DD/TPD, IP, and Health classification rows;
4. amount of captured text.

Fields not present on the source page are not treated as extraction failures.

## Selected examples

| Rank | Example | Populated disease fields | Classification rows | Coverage |
| ---: | --- | ---: | ---: | --- |
| 1 | `hypertension--7a9eaa9c282e` | 9 | 69 | Complete |
| 2 | `hypertrophic-obstructive-cardiomyopathy--937da0c79405` | 9 | 55 | Complete |
| 3 | `pulmonary-hypertension--a3e9852eb505` | 9 | 18 | Complete |
| 4 | `aortic-dilatation--5f96bad61b3d` | 8 | 108 | Complete |
| 5 | `aortic-valve-stenosis--dc19676d4174` | 8 | 105 | Complete |

Open `disease.json` for the canonical structured output and `markdown.md` for
the human-readable content. The `tabs.json` file contains the four-tab output,
including hierarchy levels and parent classifications.
