# S09 - PRD Ingestion

Status: implemented (`prd_ingestion.py`). Verified against a real 2.7 MB Azure
DevOps user-story export (145 stories, 38 pages) in 3.9 s.

## The rule that matters: identity comes from the header, not the text

Every story's own work-item id is read from the **bold header link** in the PDF
(`<b>User Story: X</b>` → `/_workitems/edit/<id>`). Ids found in the story *body*
are cross-references to **other** work items and may only become `refers_to`.

Getting this wrong is not a parsing nit. An earlier revision scraped ids from the
body and folded "please refer to" placeholders into their target, which:

- deleted **32 of 145** tracked work items from the index (FW Signature, FW
  Encryption, FOTA, BLE Pairing, Readout Protection - core items, not noise), and
- gave 3 stories the id of the story they pointed at, so two requirements shared
  one work item id and their evidence merged silently.

Content deduplication is fine. **Identity loss is not.**

## Placeholder stories are kept

A story whose entire description is "please refer to User Story 2258143" is still a
work item the customer tracks and must close. It is kept with:

```
origin: "reference"          # this record asserts no content of its own
refers_to: "US-2258143"      # where the content lives
```

Coverage and reports may follow the pointer; they may not invent evidence for it.

## When there is no link layer

`.docx` and markdown sources have no header links. The fallback scrapes an id from
the text and says so on the record: `id_source: "story-text"`, `id_unmatched: true`.
A guessed identity that presents itself as fact is how two work items end up sharing
evidence - the same failure, quieter.

## Noise the ADO export generates

- a running header repeating the document title, and a `Page N of M` footer that
  echoes the page's story title - treated as a header, that fabricates a
  content-less duplicate, so it is dropped before header matching
- `Please refer to` and the typo `Pease refer to` both occur in the same export

## Not here

No LLM. `semantic_inference: forbidden` and `parser_mode: strict`: the parser
records what the document states, including its own references, and never decides
what a story "probably meant".
