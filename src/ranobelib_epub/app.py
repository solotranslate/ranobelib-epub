from __future__ import annotations

from fastapi import FastAPI
from fastapi.responses import HTMLResponse

app = FastAPI(title="RanobeLib EPUB Builder")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    return """
<!doctype html>
<html lang="ru">
<head>
  <meta charset="utf-8">
  <title>RanobeLib EPUB Builder</title>
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <style>
    body {
      max-width: 760px;
      margin: 40px auto;
      padding: 0 16px;
      font-family: system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      line-height: 1.5;
    }
    .card {
      border: 1px solid #ddd;
      border-radius: 16px;
      padding: 24px;
      box-shadow: 0 8px 24px rgba(0,0,0,.06);
    }
    input, button {
      font: inherit;
      padding: 10px 12px;
      border-radius: 10px;
      border: 1px solid #ccc;
    }
    input {
      width: 100%;
      box-sizing: border-box;
      margin: 8px 0 16px;
    }
    button {
      cursor: pointer;
    }
    .muted {
      color: #666;
      font-size: .95rem;
    }
  </style>
</head>
<body>
  <main class="card">
    <h1>RanobeLib EPUB Builder</h1>
    <p class="muted">
      Минимальный каркас сервиса запущен. Следующий этап — чтение ссылки RanobeLib,
      загрузка списка глав и сборка EPUB.
    </p>

    <form>
      <label for="url">Ссылка на тайтл RanobeLib</label>
      <input id="url" name="url" placeholder="https://ranobelib.me/ru/book/12345--title-slug">
      <button type="button">Пока не подключено</button>
    </form>
  </main>
</body>
</html>
"""
