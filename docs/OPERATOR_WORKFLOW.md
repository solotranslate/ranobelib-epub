# Operator workflow

This document describes the current manual workflow for the `ranobelib-epub` web service.

## Current UI workflow

1. Open the web UI.
2. Paste a public RanobeLib title URL.
3. Load the title page.
4. Check the title metadata, cover, branches, and available chapter count.
5. Pick a branch card.
6. Use quick actions for normal EPUB batches.
7. Use custom range only when quick actions are not enough.
8. Use manual chapter selection only for advanced one-off selections.
9. Start the build and watch progress.
10. Download the generated EPUB.

## Quick range actions

For a branch under the current build limit, the UI shows:

```text
Собрать всю ветку
```

For larger branches, the UI shows practical chunks, for example:

```text
Собрать главы 1–100
Собрать главы 101–200
```

This is the preferred way to split a large title into multiple EPUB files.

## Custom range

For single-volume branches, the primary custom range UI should be simple:

```text
Свой диапазон
С главы [1] по главу [100]
```

The UI should not show `Том от` / `Том до` for ordinary single-volume branches. Volume fields are only useful for multi-volume cases or when chapter numbers repeat across volumes.

The page shows a live count for the custom range:

```text
Будет собрано: 100 глав
```

If the range is empty or too large, the UI should show a Russian warning and disable the custom range build button.

## Manual chapter selection

Manual chapter checkboxes are kept as an advanced mode under:

```text
Ручной выбор глав
```

Use this only when the quick actions and custom range are not enough.

## Stop active build

During an active build, the UI shows:

```text
Остановить
```

Use it if the selected range is wrong or the build should not continue.

Expected behavior:

- the button asks the backend to cancel the active build;
- the page shows `Останавливаю сборку…` and then `Сборка остановлена.`;
- the cancelled job does not expose a downloadable EPUB;
- normal build controls become usable again after the cancellation lifecycle finishes;
- if a request is already in progress, cancellation may take effect after that request returns or times out.

Cancellation is cooperative. It does not forcibly kill a Python thread.

## EPUB table of contents

For chapters without real source names, the EPUB table of contents uses generated fallback titles.

Default RanobeLib secondary numbering like `number_secondary=1` should not appear as `.1` in fallback titles. For ordinary chapters, expected TOC entries are like:

```text
Volume 1 Chapter 3
Volume 1 Chapter 4
```

not:

```text
Volume 1 Chapter 3.1
Volume 1 Chapter 4.1
```

Meaningful non-default secondary numbers should still be preserved.

## Post-update smoke checklist

After updating the VPS and restarting the service, check:

- `/health` responds on port `8080`;
- the web UI opens;
- a title URL loads the Russian build page;
- a single-volume branch shows quick actions instead of confusing volume filters;
- a large branch can build chunk 1, for example chapters `1–100`;
- the next chunk, for example `101–200`, can also build;
- the `Остановить` button cancels an active build and the page recovers;
- a newly built EPUB table of contents does not add `.1` to unnamed ordinary chapters;
- generated EPUBs, temporary files, logs, screenshots, and local debugging artifacts are not left in the repository checkout.

## Runtime hygiene

The repository should contain source code, tests, and documentation only.

Do not keep generated EPUBs, temporary build files, logs, screenshots, copied API responses, or local debugging artifacts in the repository checkout.
